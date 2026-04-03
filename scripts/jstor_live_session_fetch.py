#!/usr/bin/env python3
"""Fetch official JSTOR PDFs through a live logged-in Edge DevTools session."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, quote_plus
from urllib.request import Request, urlopen

import websocket


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch official JSTOR PDFs through a live Edge DevTools session.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-csv", required=True, help="Input CSV with JSTOR citation rows")
    parser.add_argument("--out-dir", required=True, help="Output directory for raw run artifacts")
    parser.add_argument("--debug-port", type=int, default=9222, help="Edge remote-debugging port")
    parser.add_argument("--page-wait-seconds", type=int, default=10, help="Seconds to wait after opening each search tab")
    parser.add_argument("--inter-item-sleep-seconds", type=int, default=3, help="Seconds to sleep between rows")
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N rows")
    return parser.parse_args()


def normalize_title(text: str) -> str:
    lowered = (text or "").lower()
    lowered = lowered.replace("-", " ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def sanitize_name(text: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().replace(" ", "_")
    cleaned = cleaned[:140]
    return cleaned or fallback


def row_number(row: dict[str, str], fallback_index: int) -> str:
    value = (row.get("ref_no") or row.get("number") or "").strip()
    if value:
        return value
    return str(fallback_index)


def make_target_name(number: str, title: str) -> str:
    return f"{int(number):03d}_{sanitize_name(title, f'reference_{number}')}.pdf"


def first_author_hint(authors: str) -> str:
    first_chunk = (authors or "").split(";")[0].strip()
    surname = first_chunk.split(",")[0].strip()
    return surname


def stable_id_from_row(row: dict[str, str]) -> str:
    stable_id = (row.get("stable_id") or "").strip()
    if stable_id:
        return stable_id

    for key in ("stable_url", "source_url", "article_url"):
        value = (row.get(key) or "").strip()
        if not value:
            continue
        match = re.search(r"/stable/([^/?#]+)", value)
        if match:
            return match.group(1)
    return ""


def write_utf8_no_bom(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        path.write_bytes(raw[3:])


class DevToolsClient:
    def __init__(self, debug_port: int) -> None:
        self.base = f"http://127.0.0.1:{debug_port}"

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

    def call(self, ws_url: str, method: str, params: dict | None = None, msg_id: int = 1) -> dict:
        ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
        try:
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == msg_id:
                    return msg
        finally:
            ws.close()

    def evaluate(self, ws_url: str, expression: str, *, await_promise: bool = False, msg_id: int = 1):
        msg = self.call(
            ws_url,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
            msg_id=msg_id,
        )
        return msg["result"]["result"].get("value")


def choose_search_hit(devtools: DevToolsClient, ws_url: str, title: str, author_hint: str) -> dict | None:
    escaped_title = json.dumps(title)
    escaped_author = json.dumps(author_hint)
    value = devtools.evaluate(
        ws_url,
        f"""
(() => {{
  const normalize = (s) => (s || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
  const targetTitle = normalize({escaped_title});
  const author = normalize({escaped_author});
  const links = Array.from(document.querySelectorAll('search-results-vue-pharos-link')).map(el => {{
    const wrapper = el.closest('div[data-v-85f7a40a], li, article, section, div');
    const nearby = wrapper ? (wrapper.innerText || '') : (el.innerText || '');
    return {{
      text: (el.innerText || '').trim(),
      href: el.href || '',
      nearby: nearby.slice(0, 1200)
    }};
  }});
  const exact = links.filter(item => normalize(item.text) === targetTitle);
  const withAuthor = exact.filter(item => !author || normalize(item.nearby).includes(author));
  const chosen = withAuthor[0] || exact[0] || null;
  return JSON.stringify({{ chosen }});
}})()
        """.strip(),
        msg_id=10,
    )
    payload = json.loads(value or "{}")
    chosen = payload.get("chosen")
    return chosen if isinstance(chosen, dict) else None


def fetch_pdf_bytes(devtools: DevToolsClient, ws_url: str, stable_id: str) -> bytes | None:
    escaped_id = json.dumps(stable_id)
    value = devtools.evaluate(
        ws_url,
        f"""
new Promise(async resolve => {{
  try {{
    const stableId = {escaped_id};
    const resp = await fetch(`/stable/pdf/${{stableId}}.pdf?acceptTC=1`);
    const buf = await resp.arrayBuffer();
    const data = new Uint8Array(buf);
    const head = Array.from(data.slice(0, 8)).map(x => String.fromCharCode(x)).join('');
    if (!resp.ok) {{
      resolve(JSON.stringify({{
        ok: false,
        status: resp.status,
        contentType: resp.headers.get('content-type') || '',
        head
      }}));
      return;
    }}
    const chunk = 0x8000;
    let binary = '';
    for (let i = 0; i < data.length; i += chunk) {{
      binary += String.fromCharCode.apply(null, data.subarray(i, i + chunk));
    }}
    resolve(JSON.stringify({{
      ok: true,
      status: resp.status,
      contentType: resp.headers.get('content-type') || '',
      head,
      b64: btoa(binary)
    }}));
  }} catch (err) {{
    resolve(JSON.stringify({{ ok: false, err: String(err) }}));
  }}
}})
        """.strip(),
        await_promise=True,
        msg_id=20,
    )
    payload = json.loads(value or "{}")
    if not payload.get("ok"):
        return None
    if payload.get("contentType") and "pdf" not in payload["contentType"].lower():
        return None
    if not str(payload.get("head", "")).startswith("%PDF"):
        return None
    return base64.b64decode(payload["b64"])


def process_row(
    devtools: DevToolsClient,
    row: dict[str, str],
    row_id: str,
    pdf_dir: Path,
    page_wait_seconds: int,
) -> dict[str, str]:
    target_name = make_target_name(row_id, row.get("title") or f"reference_{row_id}")
    target_path = pdf_dir / target_name
    if target_path.exists() and target_path.stat().st_size > 0:
        return {
            **row,
            "status": "downloaded",
            "pdf_path": str(target_path),
            "stable_id": stable_id_from_row(row),
            "source_url": row.get("stable_url") or row.get("source_url") or "",
            "note": "existing_file",
        }

    if "jstor_status" in row and (row.get("jstor_status") or "").strip() not in ("", "confirmed_on_jstor"):
        return {
            **row,
            "status": "skipped_input_not_confirmed",
            "pdf_path": "",
            "stable_id": stable_id_from_row(row),
            "source_url": row.get("jstor_search_url") or row.get("stable_url") or "",
            "note": row.get("jstor_status", ""),
        }

    title = (row.get("title") or "").strip()
    if not title:
        return {
            **row,
            "status": "missing_title",
            "pdf_path": "",
            "stable_id": stable_id_from_row(row),
            "source_url": "",
            "note": "",
        }

    stable_id = stable_id_from_row(row)
    if stable_id:
        search_url = f"https://www.jstor.org/stable/{stable_id}"
    else:
        query = f"\"{title}\" {first_author_hint(row.get('authors', ''))}".strip()
        search_url = f"https://www.jstor.org/action/doBasicSearch?Query={quote_plus(query)}"

    search_page = None
    try:
        search_page = devtools.open_page(search_url)
        time.sleep(page_wait_seconds)

        if not stable_id:
            hit = choose_search_hit(
                devtools,
                search_page["webSocketDebuggerUrl"],
                title,
                first_author_hint(row.get("authors", "")),
            )
            if not hit:
                return {
                    **row,
                    "status": "no_exact_search_hit",
                    "pdf_path": "",
                    "stable_id": "",
                    "source_url": search_url,
                    "note": title,
                }

            href = hit.get("href", "")
            match = re.search(r"/stable/([^/?#]+)", href)
            if not match:
                return {
                    **row,
                    "status": "no_stable_id",
                    "pdf_path": "",
                    "stable_id": "",
                    "source_url": href or search_url,
                    "note": hit.get("text", ""),
                }
            stable_id = match.group(1)

        pdf_bytes = fetch_pdf_bytes(devtools, search_page["webSocketDebuggerUrl"], stable_id)
        if not pdf_bytes:
            return {
                **row,
                "status": "pdf_fetch_failed",
                "pdf_path": "",
                "stable_id": stable_id,
                "source_url": f"https://www.jstor.org/stable/{stable_id}",
                "note": search_url,
            }

        target_path.write_bytes(pdf_bytes)
        return {
            **row,
            "status": "downloaded",
            "pdf_path": str(target_path),
            "stable_id": stable_id,
            "source_url": f"https://www.jstor.org/stable/{stable_id}",
            "note": "",
        }
    finally:
        if search_page:
            devtools.close_page(search_page["id"])


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    pdf_dir = out_dir / "pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    with open(args.input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        input_rows = [row for row in reader]

    rows: list[tuple[str, dict[str, str]]] = []
    for index, row in enumerate(input_rows, start=1):
        rows.append((row_number(row, index), row))

    if args.limit > 0:
        rows = rows[: args.limit]

    devtools = DevToolsClient(args.debug_port)
    results: list[dict[str, str]] = []
    for index, (row_id, row) in enumerate(rows, start=1):
        result = process_row(devtools, row, row_id, pdf_dir, args.page_wait_seconds)
        results.append(result)
        print(f"[{index}/{len(rows)}] {result['status']} - {row.get('title', row_id)}")
        if index != len(rows):
            time.sleep(args.inter_item_sleep_seconds)

    fieldnames: list[str] = []
    for item in results:
        for key in item.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    results_path = out_dir / "jstor_results.csv"
    with results_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    missing_rows = [item for item in results if item["status"] != "downloaded"]
    missing_path = out_dir / "jstor_missing.csv"
    with missing_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(missing_rows)

    downloaded_titles = [item.get("title", "") for item in results if item["status"] == "downloaded"]
    missing_titles = [item.get("title", "") for item in results if item["status"] != "downloaded"]
    write_utf8_no_bom(out_dir / "downloaded_titles.txt", "\n".join(downloaded_titles) + ("\n" if downloaded_titles else ""))
    write_utf8_no_bom(out_dir / "missing_titles.txt", "\n".join(missing_titles) + ("\n" if missing_titles else ""))

    downloaded = sum(1 for item in results if item["status"] == "downloaded")
    summary = "\n".join(
        [
            "JSTOR live session fetch summary",
            f"input_csv={Path(args.input_csv).resolve()}",
            f"out_dir={out_dir.resolve()}",
            f"rows_total={len(rows)}",
            f"downloaded={downloaded}",
            f"not_downloaded={len(rows) - downloaded}",
            f"results_csv={results_path.resolve()}",
            f"missing_csv={missing_path.resolve()}",
        ]
    )
    write_utf8_no_bom(out_dir / "summary.txt", summary + "\n")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
