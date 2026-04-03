#!/usr/bin/env python3
"""Fetch official ScienceDirect PDFs through a live logged-in Edge DevTools session.

Workflow:
1. Reuse an existing Edge window launched with --remote-debugging-port.
2. Open one article tab at a time from DOI or candidate URL.
3. Read article HTML through DevTools Runtime.evaluate.
4. Extract ScienceDirect pdfDownload metadata or discover View PDF / full-text routes.
5. Open the PDF target in a new tab.
6. Extract the PDF bytes directly from the in-browser PDF.js viewer.
7. Save the PDF, close the temporary tabs, sleep a few seconds, then continue.

This stays inside the user's live browser session and avoids direct bulk HTTP bursts.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import websocket


PDF_RE = re.compile(
    r'"pdfDownload":\{"isPdfFullText":(?:true|false),"urlMetadata":\{"queryParams":\{"md5":"([^"]+)","pid":"([^"]+)"\},"pii":"([^"]+)","pdfExtension":"([^"]+)","path":"([^"]+)"\}\}'
)
URL_RE = re.compile(r"https?://[^\s;,\)]+", flags=re.I)
NO_SUBSCRIPTION_RE = re.compile(r"does not subscribe to this content", flags=re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch official ScienceDirect PDFs through a live Edge DevTools session.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-csv", required=True, help="Input CSV with ScienceDirect paper rows")
    parser.add_argument("--out-dir", required=True, help="Output directory for raw run artifacts")
    parser.add_argument("--debug-port", type=int, default=9222, help="Edge remote-debugging port")
    parser.add_argument("--page-wait-seconds", type=int, default=8, help="Seconds to wait after opening each tab")
    parser.add_argument("--inter-item-sleep-seconds", type=int, default=5, help="Seconds to sleep between rows")
    parser.add_argument(
        "--viewer-ws-timeout-seconds",
        type=int,
        default=420,
        help="Seconds to keep waiting for the in-browser PDF viewer",
    )
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N rows")
    return parser.parse_args()


def sanitize_name(text: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().replace(" ", "_")
    cleaned = cleaned[:140]
    return cleaned or fallback


def make_target_name(number: str, doi: str) -> str:
    return f"{int(number):03d}_{sanitize_name(doi, f'reference_{number}')}.pdf"


def extract_urls(note: str) -> list[str]:
    urls = []
    for match in URL_RE.findall(note or ""):
        url = match.rstrip(".,);")
        if url not in urls:
            urls.append(url)
    return urls


def choose_article_url(row: dict[str, str]) -> str:
    doi = (row.get("doi") or "").strip()
    urls = extract_urls(row.get("note", ""))
    for url in urls:
        lowered = url.lower()
        if "doi.org/" in lowered or "sciencedirect.com/" in lowered:
            return url
    if doi:
        return f"https://doi.org/{doi}"
    return urls[0] if urls else ""


def summarize_text(text: str, limit: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:limit]


def pdf_url_from_html(html: str) -> str:
    match = PDF_RE.search(html or "")
    if not match:
        return ""
    md5, pid, pii, pdf_ext, path = match.groups()
    return f"https://www.sciencedirect.com/{path}/{pii}{pdf_ext}?md5={md5}&pid={pid}"


def discover_pdf_target(devtools: "DevToolsClient", ws_url: str) -> dict[str, str]:
    value = devtools.evaluate(
        ws_url,
        r"""
new Promise(resolve => {
  let tries = 0;
  const snapshot = status => {
    const viewFull = Array.from(document.querySelectorAll('a[href]')).find(a => {
      const text = (a.innerText || '').trim().toLowerCase();
      return text.includes('view full text') && /\/science\/article\/pii\//i.test(a.href) && !/\/abs\//i.test(a.href);
    });
    const link = document.querySelector('li.ViewPDF a');
    resolve(JSON.stringify({
      status,
      current_url: location.href,
      title: document.title || '',
      pdf_url: link && link.href ? link.href : '',
      full_text_url: viewFull ? viewFull.href : '',
      note: document.body && document.body.innerText ? document.body.innerText.slice(0, 1000) : ''
    }));
  };

  const tick = () => {
    tries += 1;
    const link = document.querySelector('li.ViewPDF a');
    if (link && link.href) {
      snapshot('ok');
      return;
    }
    if (link) {
      link.click();
      setTimeout(() => {
        if (link.href) {
          snapshot('ok');
        } else if (tries >= 10) {
          snapshot('no_pdf_href');
        } else {
          tick();
        }
      }, 3000);
      return;
    }
    if (tries >= 6) {
      snapshot('no_view_pdf');
      return;
    }
    setTimeout(tick, 1500);
  };

  tick();
})
        """.strip(),
        await_promise=True,
        msg_id=12,
        ws_timeout_seconds=120,
    )
    return json.loads(value or "{}")


def classify_missing_pdf(article_html: str, page_state: dict[str, str]) -> tuple[str, str]:
    note = summarize_text(page_state.get("note", "")) or summarize_text(page_state.get("title", ""))
    combined = "\n".join(
        piece for piece in [page_state.get("title", ""), page_state.get("note", ""), article_html[:1200]] if piece
    )
    if NO_SUBSCRIPTION_RE.search(combined):
        return "institution_no_subscription", note or "ScienceDirect page says the current institution does not subscribe."

    page_status = page_state.get("status", "")
    if page_status in {"no_view_pdf", "no_pdf_href"}:
        return page_status, note or "View PDF was not exposed in the current ScienceDirect session."

    return "no_pdf_metadata", note or "ScienceDirect pdfDownload metadata was not exposed."


def write_utf8_no_bom(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        path.write_bytes(raw[3:])


class DevToolsClient:
    def __init__(self, debug_port: int, viewer_ws_timeout_seconds: int) -> None:
        self.base = f"http://127.0.0.1:{debug_port}"
        self.viewer_ws_timeout_seconds = viewer_ws_timeout_seconds

    def http_get(self, url: str, method: str = "GET") -> str:
        req = Request(url, method=method)
        with urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8")

    def open_page(self, url: str) -> dict:
        raw = self.http_get(f"{self.base}/json/new?{quote(url, safe=':/?&=%')}", method="PUT")
        return json.loads(raw)

    def close_page(self, page_id: str) -> None:
        try:
            self.http_get(f"{self.base}/json/close/{page_id}")
        except Exception:
            pass

    def call(
        self,
        ws_url: str,
        method: str,
        params: dict | None = None,
        msg_id: int = 1,
        ws_timeout_seconds: int | None = None,
    ) -> dict:
        ws = websocket.create_connection(
            ws_url,
            timeout=ws_timeout_seconds or self.viewer_ws_timeout_seconds,
            suppress_origin=True,
        )
        try:
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == msg_id:
                    return msg
        finally:
            ws.close()

    def evaluate(
        self,
        ws_url: str,
        expression: str,
        *,
        await_promise: bool = False,
        msg_id: int = 1,
        ws_timeout_seconds: int | None = None,
    ):
        msg = self.call(
            ws_url,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
            msg_id=msg_id,
            ws_timeout_seconds=ws_timeout_seconds,
        )
        return msg["result"]["result"].get("value")


def extract_pdf_bytes_from_page(devtools: DevToolsClient, ws_url: str) -> tuple[bytes | None, str]:
    value = devtools.evaluate(
        ws_url,
        """
new Promise(resolve => {
  const tick = async () => {
    try {
      const iframe = document.querySelector('iframe[src]');
      const embed = document.querySelector('embed[src]');
      const objectEl = document.querySelector('object[data]');
      const url =
        location.href ||
        (iframe && iframe.src) ||
        (embed && embed.src) ||
        (objectEl && objectEl.data) ||
        '';
      const resp = await fetch(url);
      const buf = await resp.arrayBuffer();
      const data = new Uint8Array(buf);
      const chunk = 0x8000;
      let binary = '';
      for (let i = 0; i < data.length; i += chunk) {
        binary += String.fromCharCode.apply(null, data.subarray(i, i + chunk));
      }
      if (resp.ok && binary.startsWith('%PDF-')) {
        resolve(JSON.stringify({ status: 'ok', source_url: url, b64: btoa(binary) }));
        return;
      }
    } catch (err) {
      // fall through to the PDF.js branch
    }

    try {
      const app = window.PDFViewerApplication;
      if (app && app.pdfDocument) {
        app.pdfDocument.getData().then(data => {
          const chunk = 0x8000;
          let binary = '';
          for (let i = 0; i < data.length; i += chunk) {
            binary += String.fromCharCode.apply(null, data.subarray(i, i + chunk));
          }
          if (binary.startsWith('%PDF-')) {
            resolve(JSON.stringify({ status: 'ok', source_url: location.href, b64: btoa(binary) }));
          } else {
            setTimeout(tick, 1000);
          }
        }).catch(() => setTimeout(tick, 1000));
        return;
      }
    } catch (err) {
      // keep polling until the WebSocket timeout expires
    }

    setTimeout(tick, 1000);
  };
  tick();
})
        """.strip(),
        await_promise=True,
        msg_id=21,
        ws_timeout_seconds=devtools.viewer_ws_timeout_seconds,
    )
    if not value:
        return None, ""
    payload = json.loads(value)
    if payload.get("status") != "ok":
        return None, payload.get("source_url", "")
    return base64.b64decode(payload["b64"]), payload.get("source_url", "")


def process_row(
    devtools: DevToolsClient,
    row: dict[str, str],
    pdf_dir: Path,
    page_wait_seconds: int,
) -> dict[str, str]:
    article_url = choose_article_url(row)
    target_name = make_target_name(row["number"], row.get("doi") or row.get("title") or row["number"])
    target_path = pdf_dir / target_name
    if target_path.exists() and target_path.stat().st_size > 0:
        return {
            **row,
            "status": "downloaded",
            "pdf_path": str(target_path),
            "source_url": article_url,
            "note": "existing_file",
        }

    if not article_url:
        return {**row, "status": "no_candidate_urls", "pdf_path": "", "source_url": "", "note": row.get("note", "")}

    article_page = None
    pdf_page = None
    try:
        article_page = devtools.open_page(article_url)
        time.sleep(page_wait_seconds)
        article_html = devtools.evaluate(
            article_page["webSocketDebuggerUrl"],
            "document.documentElement.outerHTML",
            msg_id=10,
            ws_timeout_seconds=120,
        ) or ""
        pdf_url = pdf_url_from_html(article_html)
        page_state: dict[str, str] = {}

        if not pdf_url:
            page_state = discover_pdf_target(devtools, article_page["webSocketDebuggerUrl"])
            pdf_url = page_state.get("pdf_url", "")
            full_text_url = page_state.get("full_text_url", "")
            current_url = page_state.get("current_url", article_url) or article_url

            if not pdf_url and full_text_url and full_text_url != current_url:
                devtools.close_page(article_page["id"])
                article_page = devtools.open_page(full_text_url)
                time.sleep(page_wait_seconds)
                article_html = devtools.evaluate(
                    article_page["webSocketDebuggerUrl"],
                    "document.documentElement.outerHTML",
                    msg_id=13,
                    ws_timeout_seconds=120,
                ) or ""
                pdf_url = pdf_url_from_html(article_html)
                if not pdf_url:
                    page_state = discover_pdf_target(devtools, article_page["webSocketDebuggerUrl"])
                    pdf_url = page_state.get("pdf_url", "")

        if not pdf_url:
            status, note = classify_missing_pdf(article_html, page_state)
            return {
                **row,
                "status": status,
                "pdf_path": "",
                "source_url": page_state.get("current_url", article_url) or article_url,
                "note": note,
            }

        pdf_page = devtools.open_page(pdf_url)
        time.sleep(page_wait_seconds)
        try:
            pdf_bytes, final_pdf_url = extract_pdf_bytes_from_page(devtools, pdf_page["webSocketDebuggerUrl"])
        except Exception as err:
            return {
                **row,
                "status": "viewer_extract_exception",
                "pdf_path": "",
                "source_url": pdf_url,
                "note": str(err)[:500],
            }
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF-"):
            return {
                **row,
                "status": "viewer_extract_failed",
                "pdf_path": "",
                "source_url": final_pdf_url or pdf_url,
                "note": "PDF.js extraction failed or returned non-PDF content",
            }

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(pdf_bytes)
        return {
            **row,
            "status": "downloaded",
            "pdf_path": str(target_path),
            "source_url": final_pdf_url or pdf_url,
            "note": "devtools_pdfjs_extract_with_viewpdf_fallback",
        }
    finally:
        if article_page:
            devtools.close_page(article_page["id"])
        if pdf_page:
            devtools.close_page(pdf_page["id"])


def main() -> int:
    args = parse_args()
    input_csv = Path(args.input_csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = out_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    devtools = DevToolsClient(args.debug_port, args.viewer_ws_timeout_seconds)
    results = []
    for index, row in enumerate(rows, start=1):
        doi = row.get("doi", "")
        print(f"[{index}/{len(rows)}] sciencedirect live fetch | {doi}")
        try:
            result = process_row(devtools, row, pdf_dir, args.page_wait_seconds)
        except Exception as err:
            result = {
                **row,
                "status": "row_exception",
                "pdf_path": "",
                "source_url": choose_article_url(row),
                "note": str(err)[:500],
            }
        results.append(result)
        print(f"    -> {result['status']}")
        if index < len(rows) and args.inter_item_sleep_seconds > 0:
            print(f"    -> sleeping {args.inter_item_sleep_seconds}s before next row")
            time.sleep(args.inter_item_sleep_seconds)

    fieldnames = ["number", "title", "doi", "year", "journal", "status", "pdf_path", "source_url", "note", "formatted"]
    results_csv = out_dir / "devtools_results.csv"
    missing_csv = out_dir / "devtools_missing.csv"
    downloaded_doi_txt = out_dir / "downloaded_doi.txt"
    missing_doi_txt = out_dir / "missing_doi.txt"
    summary_txt = out_dir / "summary.txt"

    with results_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    missing_rows = [row for row in results if row.get("status") != "downloaded"]
    with missing_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in missing_rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    downloaded_dois = [row.get("doi", "").strip() for row in results if row.get("status") == "downloaded" and row.get("doi", "").strip()]
    missing_dois = [row.get("doi", "").strip() for row in missing_rows if row.get("doi", "").strip()]
    write_utf8_no_bom(downloaded_doi_txt, "\n".join(downloaded_dois) + ("\n" if downloaded_dois else ""))
    write_utf8_no_bom(missing_doi_txt, "\n".join(missing_dois) + ("\n" if missing_dois else ""))

    summary_lines = [
        f"total_rows: {len(results)}",
        f"downloaded: {sum(1 for row in results if row.get('status') == 'downloaded')}",
        f"missing: {sum(1 for row in results if row.get('status') != 'downloaded')}",
        f"output_dir: {out_dir}",
        f"debug_port: {args.debug_port}",
        f"page_wait_seconds: {args.page_wait_seconds}",
        f"inter_item_sleep_seconds: {args.inter_item_sleep_seconds}",
        f"viewer_ws_timeout_seconds: {args.viewer_ws_timeout_seconds}",
    ]
    write_utf8_no_bom(summary_txt, "\n".join(summary_lines) + "\n")
    print("\n".join(summary_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
