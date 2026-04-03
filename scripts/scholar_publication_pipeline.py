#!/usr/bin/env python3
"""Build and maintain scholar-paper discovery, download, and citation artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - dependency is validated at runtime
    PdfReader = None


TITLE_LIST_SEP = " || "
DOI_LIST_SEP = " || "
CONTEXT_REL = Path("_runs") / "pipeline_context.json"

ROUTE_LABELS = {
    "sciencedirect": "ScienceDirect / Elsevier",
    "wiley": "Wiley",
    "jstor": "JSTOR",
    "unsupported": "Unsupported",
}

MASTER_FIELDS = [
    "record_type",
    "seed_author",
    "title",
    "authors",
    "journal",
    "journal_abbrev",
    "year",
    "volume",
    "issue",
    "pages_or_article",
    "doi",
    "publisher_platform",
    "article_url",
    "published_status",
    "source_basis",
    "source_confidence",
    "notes",
    "download_supported",
    "preferred_download_route",
    "download_status",
    "citing_count",
    "citing_titles",
    "citing_dois",
    "primary_output_path",
    "stable_id",
    "stable_url",
    "jstor_status",
]

MANIFEST_FIELDS = [
    "scope",
    "seed_author",
    "source_paper_title",
    "title",
    "authors",
    "journal_abbrev",
    "year",
    "doi",
    "platform",
    "pdf_filename",
    "pdf_path",
    "status",
]

CONFIDENCE_RANK = {"": 0, "low": 1, "medium": 2, "high": 3}
PUBLISHED_STATUS_RANK = {"unknown": 0, "online_in_press": 1, "published": 2}
DOWNLOAD_STATUS_RANK = {
    "": 0,
    "unsupported_platform": 1,
    "pending": 2,
    "failed": 3,
    "downloaded": 4,
}

JOURNAL_ABBREV_MAP = {
    "international economic review": "IER",
    "journal of asset management": "JAM",
    "journal of banking & finance": "JBF",
    "journal of banking and finance": "JBF",
    "journal of econometrics": "JE",
    "journal of finance": "JF",
    "the journal of finance": "JF",
    "journal of financial and quantitative analysis": "JFQA",
    "journal of financial economics": "JFE",
    "journal of financial markets": "JFM",
    "journal of quantitative analysis in sports": "JQAS",
    "journal of risk": "JOR",
    "quarterly journal of economics": "QJE",
    "review of asset pricing studies": "RAPS",
    "review of economic studies": "REStud",
    "review of financial studies": "RFS",
}

WORD_ABBREV_MAP = {
    "american": "A",
    "analysis": "A",
    "asset": "A",
    "banking": "B",
    "business": "Bus",
    "corporate": "Corp",
    "economic": "Econ",
    "econometric": "Ectr",
    "econometrics": "E",
    "economics": "Econ",
    "empirical": "Emp",
    "finance": "F",
    "financial": "F",
    "international": "I",
    "journal": "J",
    "management": "Mgmt",
    "market": "M",
    "markets": "M",
    "policy": "Pol",
    "political": "Pol",
    "quantitative": "Q",
    "review": "R",
    "risk": "Risk",
    "sports": "S",
    "studies": "Stud",
}

STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "&"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and maintain the scholar publication pipeline outputs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init-run",
        help="Create the run root and initialize the canonical output files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    init_parser.add_argument("--author-name", "--scholar-name", dest="author_name", required=True, help="Target scholar name")
    init_parser.add_argument("--google-scholar-url", required=True, help="Google Scholar profile URL used to anchor identity")
    init_parser.add_argument("--out-dir", required=True, help="Run root directory")
    init_parser.add_argument("--force", action="store_true", help="Reinitialize even if the run root already exists")

    import_parser = subparsers.add_parser(
        "import-records",
        help="Normalize raw discovery rows into master_catalog.csv.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    import_parser.add_argument("--master-catalog", required=True, help="Canonical master catalog CSV")
    import_parser.add_argument("--input-csv", required=True, help="Raw discovery CSV to normalize and import")
    import_parser.add_argument(
        "--record-type",
        required=True,
        choices=["author_published", "cited_published"],
        help="Logical record type to assign to the imported rows",
    )
    import_parser.add_argument("--seed-author", "--seed-scholar", dest="seed_author", default="", help="Scholar name to stamp onto imported rows when missing")
    import_parser.add_argument("--default-source-basis", default="", help="Default provenance label to apply when the input omits it")
    import_parser.add_argument("--default-source-confidence", default="medium", help="Default source-confidence label")
    import_parser.add_argument("--default-published-status", default="published", help="Default publication-status label")

    queue_parser = subparsers.add_parser(
        "build-queues",
        help="Create per-platform queue CSVs from master_catalog.csv.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    queue_parser.add_argument("--master-catalog", required=True, help="Canonical master catalog CSV")
    queue_parser.add_argument("--scope", required=True, choices=["author", "cite"], help="Queue scope: scholar papers or cited papers")
    queue_parser.add_argument("--out-dir", required=True, help="Directory where queue CSVs should be written")

    ingest_parser = subparsers.add_parser(
        "ingest-results",
        help="Update master_catalog.csv and materialize final PDFs from platform results.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ingest_parser.add_argument("--master-catalog", required=True, help="Canonical master catalog CSV")
    ingest_parser.add_argument("--download-manifest", required=True, help="Canonical physical-file manifest CSV")
    ingest_parser.add_argument("--scope", required=True, choices=["author", "cite"], help="Result scope: scholar papers or cited papers")
    ingest_parser.add_argument("--platform", required=True, choices=["sciencedirect", "wiley", "jstor"], help="Platform that produced the results CSV")
    ingest_parser.add_argument("--results-csv", required=True, help="Platform results CSV to ingest")

    refs_parser = subparsers.add_parser(
        "extract-reference-text",
        help="Extract reference sections from downloaded scholar PDFs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    refs_parser.add_argument("--master-catalog", required=True, help="Canonical master catalog CSV")
    refs_parser.add_argument("--out-dir", required=True, help="Directory for extracted reference-text artifacts")
    refs_parser.add_argument("--max-tail-pages", type=int, default=10, help="Maximum number of trailing PDF pages to scan")

    return parser.parse_args()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize_title(text: str) -> str:
    lowered = normalize_whitespace(text).lower().replace("-", " ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_doi(text: str) -> str:
    doi = normalize_whitespace(text).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    return doi.strip().strip(".")


def normalize_bool_str(value: str) -> str:
    lowered = normalize_whitespace(value).lower()
    if lowered in {"1", "true", "yes", "y"}:
        return "true"
    if lowered in {"0", "false", "no", "n"}:
        return "false"
    return lowered


def normalize_route(text: str) -> str:
    lowered = normalize_whitespace(text).lower().replace(" ", "").replace("-", "")
    if lowered in {"sciencedirect", "elsevier", "sciencedirect/elsevier"}:
        return "sciencedirect"
    if lowered in {"wiley", "wileyonlinelibrary"}:
        return "wiley"
    if lowered == "jstor":
        return "jstor"
    return "unsupported"


def canonical_download_status(value: str) -> str:
    lowered = normalize_whitespace(value).lower()
    if lowered in {"downloaded", "success"}:
        return "downloaded"
    if lowered in {"pending", "queued", "not_started"}:
        return "pending"
    if lowered in {"unsupported", "unsupported_platform"}:
        return "unsupported_platform"
    if lowered:
        return "failed"
    return ""


def canonical_published_status(value: str, default: str = "published") -> str:
    lowered = normalize_whitespace(value).lower()
    if not lowered:
        lowered = default.lower()
    if "press" in lowered:
        return "online_in_press"
    if "published" in lowered or lowered in {"journal_article", "article"}:
        return "published"
    return "unknown"


def canonical_confidence(value: str, default: str = "medium") -> str:
    lowered = normalize_whitespace(value).lower()
    if lowered in {"high", "medium", "low"}:
        return lowered
    return default


def parse_year(value: str) -> str:
    match = re.search(r"(19|20)\d{2}", value or "")
    return match.group(0) if match else ""


def parse_volume_issue(row: dict[str, str]) -> tuple[str, str]:
    volume = normalize_whitespace(row.get("volume", ""))
    issue = normalize_whitespace(row.get("issue", ""))
    if volume or issue:
        return volume, issue

    vol_issue = normalize_whitespace(row.get("vol_issue", ""))
    match = re.match(r"(?P<vol>[^()]+)\((?P<issue>[^)]+)\)", vol_issue)
    if match:
        return normalize_whitespace(match.group("vol")), normalize_whitespace(match.group("issue"))
    if vol_issue:
        return vol_issue, ""
    return "", ""


def dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = normalize_whitespace(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def split_multi(value: str, separator: str) -> list[str]:
    if not normalize_whitespace(value):
        return []
    return dedupe_preserve([part for part in value.split(separator)])


def merge_multi(existing: str, new_values: list[str], separator: str) -> str:
    merged = split_multi(existing, separator)
    merged.extend(new_values)
    return separator.join(dedupe_preserve(merged))


def join_unique(parts: list[str], separator: str = "; ") -> str:
    return separator.join(dedupe_preserve(parts))


def sanitize_file_component(text: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", text or "")
    cleaned = normalize_whitespace(cleaned).replace(" ", "_")
    cleaned = cleaned.strip("._")
    cleaned = cleaned[:120]
    return cleaned or fallback


def sanitize_dir_component(text: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", text or "")
    cleaned = normalize_whitespace(cleaned).strip(".")
    cleaned = cleaned[:120]
    return cleaned or fallback


def extract_surname(author_name: str) -> str:
    cleaned = normalize_whitespace(author_name)
    if not cleaned:
        return "Unknown"
    if "," in cleaned:
        return sanitize_file_component(cleaned.split(",", 1)[0], "Unknown")
    parts = cleaned.split(" ")
    return sanitize_file_component(parts[-1], "Unknown")


def author_surnames(authors: str) -> list[str]:
    chunks = re.split(r"\s*;\s*", authors or "")
    surnames = [extract_surname(chunk) for chunk in chunks if normalize_whitespace(chunk)]
    return surnames or ["Unknown"]


def infer_journal_abbrev(journal: str, fallback: str = "Journal") -> str:
    normalized = normalize_whitespace(journal)
    if not normalized:
        return fallback
    mapped = JOURNAL_ABBREV_MAP.get(normalized.lower())
    if mapped:
        return mapped

    tokens = re.findall(r"[A-Za-z0-9&]+", normalized)
    abbreviations: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in STOPWORDS:
            continue
        abbreviations.append(WORD_ABBREV_MAP.get(lowered, token[:3].title()))
    if not abbreviations:
        return fallback
    result = "".join(part for part in abbreviations[:5])
    return sanitize_file_component(result, fallback)


def make_pdf_filename(row: dict[str, str]) -> str:
    surnames = "_".join(author_surnames(row.get("authors", "")))
    journal_abbrev = sanitize_file_component(
        row.get("journal_abbrev") or infer_journal_abbrev(row.get("journal", "")),
        "Journal",
    )
    year = parse_year(row.get("year", "")) or "nd"
    return f"{surnames}_{journal_abbrev}_{year}.pdf"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [{key: value for key, value in row.items()} for row in csv.DictReader(handle)]


def load_context(root_dir: Path) -> dict[str, str]:
    context_path = root_dir / CONTEXT_REL
    if not context_path.exists():
        return {}
    return json.loads(context_path.read_text(encoding="utf-8"))


def write_context(root_dir: Path, payload: dict[str, str]) -> None:
    context_path = root_dir / CONTEXT_REL
    ensure_parent(context_path)
    context_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def derive_stable_id(row: dict[str, str]) -> str:
    direct = normalize_whitespace(row.get("stable_id", ""))
    if direct:
        return direct
    for key in ("stable_url", "article_url", "source_url", "jstor_search_url"):
        value = normalize_whitespace(row.get(key, ""))
        match = re.search(r"/stable/([^/?#]+)", value)
        if match:
            return match.group(1)
    return ""


def derive_article_url(row: dict[str, str]) -> str:
    for key in ("article_url", "source_url", "stable_url"):
        value = normalize_whitespace(row.get(key, ""))
        if value:
            return value
    return ""


def has_jstor_route_signal(row: dict[str, str]) -> bool:
    article_url = derive_article_url(row).lower()
    jstor_status = normalize_whitespace(row.get("jstor_status", "")).lower()
    return bool(derive_stable_id(row) or "jstor.org" in article_url or jstor_status == "confirmed_on_jstor")


def infer_platform_label(row: dict[str, str]) -> str:
    explicit = normalize_whitespace(row.get("publisher_platform") or row.get("platform") or "")
    if explicit:
        return explicit

    article_url = derive_article_url(row).lower()
    doi = normalize_doi(row.get("doi", ""))

    if "sciencedirect.com" in article_url or doi.startswith("10.1016/"):
        return ROUTE_LABELS["sciencedirect"]
    if "wiley.com" in article_url or doi.startswith("10.1111/"):
        return ROUTE_LABELS["wiley"]
    if has_jstor_route_signal(row):
        return ROUTE_LABELS["jstor"]
    return "Unknown"


def infer_route(row: dict[str, str]) -> str:
    if has_jstor_route_signal(row):
        return "jstor"

    explicit = normalize_route(row.get("preferred_download_route", ""))
    if explicit != "unsupported":
        return explicit

    article_url = derive_article_url(row).lower()
    doi = normalize_doi(row.get("doi", ""))
    platform_text = normalize_whitespace(row.get("publisher_platform") or row.get("platform") or "").lower()

    if "sciencedirect" in platform_text or "elsevier" in platform_text or "sciencedirect.com" in article_url or doi.startswith("10.1016/"):
        return "sciencedirect"
    if "wiley" in platform_text or "wiley.com" in article_url or doi.startswith("10.1111/"):
        return "wiley"
    return "unsupported"


def truthy_download_supported(route: str, value: str) -> str:
    explicit = normalize_bool_str(value)
    if explicit in {"true", "false"}:
        return explicit
    return "true" if route in {"sciencedirect", "wiley", "jstor"} else "false"


def refresh_download_fields(row: dict[str, str]) -> None:
    row["jstor_status"] = choose_jstor_status("", row.get("jstor_status", ""))
    if derive_stable_id(row):
        row["jstor_status"] = "confirmed_on_jstor"
    route = infer_route(row)
    row["preferred_download_route"] = route
    row["download_supported"] = truthy_download_supported(route, row.get("download_supported", ""))
    status = canonical_download_status(row.get("download_status", ""))
    if status == "downloaded":
        row["download_status"] = status
        return
    if row["download_supported"] == "true":
        row["download_status"] = status or "pending"
    else:
        row["download_status"] = "unsupported_platform"


def build_formatted_citation(row: dict[str, str]) -> str:
    authors = normalize_whitespace(row.get("authors", ""))
    year = parse_year(row.get("year", ""))
    title = normalize_whitespace(row.get("title", ""))
    journal = normalize_whitespace(row.get("journal", ""))
    volume = normalize_whitespace(row.get("volume", ""))
    issue = normalize_whitespace(row.get("issue", ""))
    pages = normalize_whitespace(row.get("pages_or_article", ""))
    vol_issue = volume
    if volume and issue:
        vol_issue = f"{volume}({issue})"
    pieces = [authors]
    if year:
        pieces.append(f"({year}).")
    if title:
        pieces.append(f"{title}.")
    if journal:
        if vol_issue:
            pieces.append(f"{journal}, {vol_issue}")
        else:
            pieces.append(journal)
    if pages:
        pieces.append(pages)
    return " ".join(piece for piece in pieces if piece).strip()


def make_record_key(row: dict[str, str]) -> str:
    record_type = row.get("record_type", "")
    doi = normalize_doi(row.get("doi", ""))
    stable_id = normalize_whitespace(row.get("stable_id", ""))
    title = normalize_title(row.get("title", ""))
    year = parse_year(row.get("year", ""))
    if doi:
        return f"{record_type}|doi|{doi}"
    if stable_id:
        return f"{record_type}|stable|{stable_id}"
    return f"{record_type}|title|{title}|{year}"


def choose_value(existing: str, new_value: str) -> str:
    return normalize_whitespace(existing) or normalize_whitespace(new_value)


def choose_jstor_status(existing: str, new_value: str) -> str:
    current = normalize_whitespace(existing)
    incoming = normalize_whitespace(new_value)
    if incoming.lower() == "confirmed_on_jstor":
        return "confirmed_on_jstor"
    if current.lower() == "confirmed_on_jstor":
        return "confirmed_on_jstor"
    return current or incoming


def choose_better(existing: str, new_value: str, rank_map: dict[str, int], default: str = "") -> str:
    current = normalize_whitespace(existing).lower()
    incoming = normalize_whitespace(new_value).lower()
    if rank_map.get(incoming, rank_map.get(default, 0)) >= rank_map.get(current, rank_map.get(default, 0)):
        return incoming or current
    return current


def normalize_input_row(
    raw: dict[str, str],
    *,
    record_type: str,
    seed_author: str,
    default_source_basis: str,
    default_source_confidence: str,
    default_published_status: str,
) -> dict[str, str]:
    title = normalize_whitespace(raw.get("title", ""))
    if not title:
        return {}

    status_value = normalize_whitespace(raw.get("published_status", ""))
    if not status_value:
        candidate = normalize_whitespace(raw.get("status", ""))
        if any(token in candidate.lower() for token in ("published", "press", "forthcoming")):
            status_value = candidate

    download_status = normalize_whitespace(raw.get("download_status", ""))
    if not download_status:
        candidate = normalize_whitespace(raw.get("status", ""))
        if candidate and candidate.lower() in {"downloaded", "failed", "pending", "unsupported_platform"}:
            download_status = candidate

    volume, issue = parse_volume_issue(raw)
    article_url = derive_article_url(raw)
    stable_id = derive_stable_id(raw)
    stable_url = normalize_whitespace(raw.get("stable_url", ""))
    if not stable_url and stable_id:
        stable_url = f"https://www.jstor.org/stable/{stable_id}"

    citing_titles = split_multi(raw.get("citing_titles", ""), TITLE_LIST_SEP)
    citing_dois = [normalize_doi(value) for value in split_multi(raw.get("citing_dois", ""), DOI_LIST_SEP)]
    fallback_citing_title = normalize_whitespace(
        raw.get("sample_paper_title", "") or raw.get("source_paper_title", "") or raw.get("citing_title", "")
    )
    fallback_citing_doi = normalize_doi(
        raw.get("sample_paper_doi", "") or raw.get("source_paper_doi", "") or raw.get("citing_doi", "")
    )
    if record_type == "cited_published" and fallback_citing_title:
        citing_titles.append(fallback_citing_title)
    if record_type == "cited_published" and fallback_citing_doi:
        citing_dois.append(fallback_citing_doi)
    citing_titles = dedupe_preserve(citing_titles)
    citing_dois = dedupe_preserve([value for value in citing_dois if value])

    normalized = {field: "" for field in MASTER_FIELDS}
    normalized["record_type"] = record_type
    normalized["seed_author"] = normalize_whitespace(raw.get("seed_author", "")) or seed_author
    normalized["title"] = title
    normalized["authors"] = normalize_whitespace(raw.get("authors", ""))
    normalized["journal"] = normalize_whitespace(raw.get("journal", ""))
    normalized["journal_abbrev"] = normalize_whitespace(raw.get("journal_abbrev", "")) or infer_journal_abbrev(
        raw.get("journal", ""),
        fallback="Journal",
    )
    normalized["year"] = parse_year(raw.get("year", ""))
    normalized["volume"] = volume
    normalized["issue"] = issue
    normalized["pages_or_article"] = normalize_whitespace(
        raw.get("pages_or_article", "") or raw.get("pages", "") or raw.get("article_number", "")
    )
    normalized["doi"] = normalize_doi(raw.get("doi", ""))
    normalized["publisher_platform"] = infer_platform_label(raw)
    normalized["article_url"] = article_url or stable_url
    normalized["published_status"] = canonical_published_status(status_value, default=default_published_status)
    normalized["source_basis"] = normalize_whitespace(raw.get("source_basis", "")) or default_source_basis
    normalized["source_confidence"] = canonical_confidence(
        raw.get("source_confidence", ""),
        default=default_source_confidence,
    )
    normalized["notes"] = normalize_whitespace(raw.get("notes", "") or raw.get("note", ""))
    normalized["download_supported"] = normalize_bool_str(raw.get("download_supported", ""))
    normalized["preferred_download_route"] = normalize_whitespace(raw.get("preferred_download_route", ""))
    normalized["download_status"] = download_status
    normalized["citing_count"] = str(len(citing_titles)) if citing_titles else ""
    normalized["citing_titles"] = TITLE_LIST_SEP.join(citing_titles)
    normalized["citing_dois"] = DOI_LIST_SEP.join(citing_dois)
    normalized["primary_output_path"] = normalize_whitespace(raw.get("primary_output_path", ""))
    normalized["stable_id"] = stable_id
    normalized["stable_url"] = stable_url
    normalized["jstor_status"] = normalize_whitespace(raw.get("jstor_status", ""))
    refresh_download_fields(normalized)
    return normalized


def merge_rows(existing: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    merged = existing.copy()
    simple_fields = [
        "seed_author",
        "title",
        "authors",
        "journal",
        "journal_abbrev",
        "year",
        "volume",
        "issue",
        "pages_or_article",
        "doi",
        "publisher_platform",
        "article_url",
        "primary_output_path",
        "stable_id",
        "stable_url",
    ]
    for field in simple_fields:
        merged[field] = choose_value(existing.get(field, ""), incoming.get(field, ""))
    merged["jstor_status"] = choose_jstor_status(existing.get("jstor_status", ""), incoming.get("jstor_status", ""))

    merged["published_status"] = choose_better(
        existing.get("published_status", ""),
        incoming.get("published_status", ""),
        PUBLISHED_STATUS_RANK,
    )
    merged["source_confidence"] = choose_better(
        existing.get("source_confidence", ""),
        incoming.get("source_confidence", ""),
        CONFIDENCE_RANK,
        default="medium",
    )
    merged["download_status"] = choose_better(
        existing.get("download_status", ""),
        incoming.get("download_status", ""),
        DOWNLOAD_STATUS_RANK,
    )
    merged["source_basis"] = join_unique(
        [existing.get("source_basis", ""), incoming.get("source_basis", "")],
        separator="; ",
    )
    merged["notes"] = join_unique(
        [existing.get("notes", ""), incoming.get("notes", "")],
        separator=" | ",
    )
    merged["citing_titles"] = merge_multi(
        existing.get("citing_titles", ""),
        split_multi(incoming.get("citing_titles", ""), TITLE_LIST_SEP),
        TITLE_LIST_SEP,
    )
    merged["citing_dois"] = merge_multi(
        existing.get("citing_dois", ""),
        split_multi(incoming.get("citing_dois", ""), DOI_LIST_SEP),
        DOI_LIST_SEP,
    )
    citing_titles = split_multi(merged.get("citing_titles", ""), TITLE_LIST_SEP)
    merged["citing_count"] = str(len(citing_titles)) if citing_titles else ""
    refresh_download_fields(merged)
    if merged["download_status"] == "downloaded" and existing.get("primary_output_path"):
        merged["primary_output_path"] = existing["primary_output_path"]
    return merged


def load_master_catalog(path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized = {field: normalize_whitespace(row.get(field, "")) for field in MASTER_FIELDS}
        refresh_download_fields(normalized)
        normalized_rows.append(normalized)
    return normalized_rows


def load_manifest(path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    return [{field: normalize_whitespace(row.get(field, "")) for field in MANIFEST_FIELDS} for row in rows]


def manifest_key(row: dict[str, str]) -> str:
    return "|".join(
        [
            normalize_whitespace(row.get("scope", "")).lower(),
            normalize_title(row.get("source_paper_title", "")),
            normalize_doi(row.get("doi", "")) or normalize_title(row.get("title", "")),
        ]
    )


def allocate_target_path(desired: Path, existing_path: str = "") -> Path:
    if existing_path:
        return Path(existing_path)
    if not desired.exists():
        return desired
    stem = desired.stem
    suffix = desired.suffix
    for index in range(2, 1000):
        candidate = desired.with_name(f"{stem}__{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate a unique target path under {desired.parent}")


def upsert_manifest(manifest_rows: list[dict[str, str]], entry: dict[str, str]) -> dict[str, str]:
    key = manifest_key(entry)
    for index, row in enumerate(manifest_rows):
        if manifest_key(row) == key:
            manifest_rows[index] = {field: entry.get(field, "") for field in MANIFEST_FIELDS}
            return manifest_rows[index]
    manifest_rows.append({field: entry.get(field, "") for field in MANIFEST_FIELDS})
    return manifest_rows[-1]


def root_dir_from_master(master_catalog_path: Path) -> Path:
    return master_catalog_path.resolve().parent


def author_dir_from_context(root_dir: Path) -> Path:
    context = load_context(root_dir)
    author_dir_name = context.get("author_dir_name") or "author"
    return root_dir / author_dir_name


def copy_pdf(src: Path, dest_dir: Path, filename: str, existing_path: str = "") -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    desired = dest_dir / filename
    target = allocate_target_path(desired, existing_path=existing_path)
    shutil.copy2(src, target)
    return target


def find_matching_row(
    master_rows: list[dict[str, str]],
    *,
    scope: str,
    result_row: dict[str, str],
) -> dict[str, str] | None:
    target_record_type = "author_published" if scope == "author" else "cited_published"
    doi = normalize_doi(result_row.get("doi", ""))
    stable_id = normalize_whitespace(result_row.get("stable_id", "")) or derive_stable_id(result_row)
    title = normalize_title(result_row.get("title", ""))

    for row in master_rows:
        if row.get("record_type") != target_record_type:
            continue
        if doi and normalize_doi(row.get("doi", "")) == doi:
            return row
    for row in master_rows:
        if row.get("record_type") != target_record_type:
            continue
        if stable_id and normalize_whitespace(row.get("stable_id", "")) == stable_id:
            return row
    for row in master_rows:
        if row.get("record_type") != target_record_type:
            continue
        if title and normalize_title(row.get("title", "")) == title:
            return row
    return None


def append_note(row: dict[str, str], note: str) -> None:
    row["notes"] = join_unique([row.get("notes", ""), note], separator=" | ")


def sort_master_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    def sort_key(row: dict[str, str]) -> tuple[int, int, str]:
        record_rank = 0 if row.get("record_type") == "author_published" else 1
        year = parse_year(row.get("year", "")) or "9999"
        return (record_rank, int(year), normalize_title(row.get("title", "")))

    return sorted(rows, key=sort_key)


def queue_row_for_science_like(record: dict[str, str], number: int) -> dict[str, str]:
    return {
        "number": str(number),
        "title": record.get("title", ""),
        "doi": record.get("doi", ""),
        "year": record.get("year", ""),
        "journal": record.get("journal", ""),
        "note": record.get("article_url", "") or record.get("stable_url", ""),
        "formatted": build_formatted_citation(record),
    }


def queue_row_for_jstor(record: dict[str, str], number: int) -> dict[str, str]:
    stable_id = record.get("stable_id", "")
    stable_url = record.get("stable_url", "") or (
        f"https://www.jstor.org/stable/{stable_id}" if stable_id else ""
    )
    article_url = record.get("article_url", "") or stable_url
    return {
        "number": str(number),
        "ref_no": str(number),
        "title": record.get("title", ""),
        "authors": record.get("authors", ""),
        "year": record.get("year", ""),
        "journal": record.get("journal", ""),
        "doi": record.get("doi", ""),
        "stable_id": stable_id,
        "stable_url": stable_url,
        "article_url": article_url,
        "source_url": article_url,
        "jstor_status": record.get("jstor_status", ""),
        "note": record.get("notes", ""),
    }


def jstor_row_has_known_stable(row: dict[str, str]) -> bool:
    return bool(derive_stable_id(row))


def write_recommended_download_order(
    out_dir: Path,
    *,
    jstor_known_count: int,
    wiley_count: int,
    jstor_search_count: int,
    sciencedirect_count: int,
) -> Path:
    order_path = out_dir / "recommended_download_order.txt"
    lines = [
        "Recommended mixed-source batch order",
        "",
        "Run the available queue files in this order:",
        f"1. jstor_input_known_stable.csv ({jstor_known_count} rows)",
        "   JSTOR rows that already have a stable_id or stable_url.",
        f"2. wiley_input.csv ({wiley_count} rows)",
        "   Wiley rows after the known-stable JSTOR batch is complete.",
        f"3. jstor_input_search.csv ({jstor_search_count} rows)",
        "   Remaining JSTOR rows that still require title-search resolution.",
        f"4. sciencedirect_input.csv ({sciencedirect_count} rows)",
        "   ScienceDirect / Elsevier rows as the final publisher batch.",
        "",
        "Notes:",
        "- Skip any file that was not written for this queue build.",
        "- jstor_input.csv remains as the backward-compatible all-JSTOR file.",
    ]
    order_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return order_path


def cmd_init_run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    author_dir_name = sanitize_dir_component(args.author_name, "author")
    directories = [
        out_dir,
        out_dir / author_dir_name,
        out_dir / "cite",
        out_dir / "_runs" / "discovery",
        out_dir / "_runs" / "queues" / "author",
        out_dir / "_runs" / "queues" / "cite",
        out_dir / "_runs" / "platform" / "author",
        out_dir / "_runs" / "platform" / "cite",
        out_dir / "_runs" / "reference_extract",
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    master_catalog = out_dir / "master_catalog.csv"
    download_manifest = out_dir / "download_manifest.csv"
    if args.force or not master_catalog.exists():
        write_csv(master_catalog, MASTER_FIELDS, [])
    if args.force or not download_manifest.exists():
        write_csv(download_manifest, MANIFEST_FIELDS, [])

    write_context(
        out_dir,
        {
            "author_name": args.author_name,
            "author_dir_name": author_dir_name,
            "google_scholar_url": args.google_scholar_url,
        },
    )

    print(f"Initialized run root: {out_dir}")
    print(f"Author folder: {out_dir / author_dir_name}")
    print(f"Cite folder: {out_dir / 'cite'}")
    print(f"Master catalog: {master_catalog}")
    print(f"Download manifest: {download_manifest}")
    return 0


def cmd_import_records(args: argparse.Namespace) -> int:
    master_catalog_path = Path(args.master_catalog).resolve()
    input_csv_path = Path(args.input_csv).resolve()
    root_dir = root_dir_from_master(master_catalog_path)
    context = load_context(root_dir)
    seed_author = args.seed_author or context.get("author_name", "")

    master_rows = load_master_catalog(master_catalog_path)
    keyed_rows = {make_record_key(row): row for row in master_rows}

    imported = 0
    skipped = 0
    raw_rows = read_csv_rows(input_csv_path)
    for raw in raw_rows:
        normalized = normalize_input_row(
            raw,
            record_type=args.record_type,
            seed_author=seed_author,
            default_source_basis=args.default_source_basis,
            default_source_confidence=args.default_source_confidence,
            default_published_status=args.default_published_status,
        )
        if not normalized:
            skipped += 1
            continue
        key = make_record_key(normalized)
        if key in keyed_rows:
            keyed_rows[key] = merge_rows(keyed_rows[key], normalized)
        else:
            keyed_rows[key] = normalized
        imported += 1

    sorted_rows = sort_master_rows(list(keyed_rows.values()))
    write_csv(master_catalog_path, MASTER_FIELDS, sorted_rows)
    print(f"Imported rows: {imported}")
    print(f"Skipped rows without title: {skipped}")
    print(f"Master catalog updated: {master_catalog_path}")
    return 0


def cmd_build_queues(args: argparse.Namespace) -> int:
    master_catalog_path = Path(args.master_catalog).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    master_rows = load_master_catalog(master_catalog_path)
    target_record_type = "author_published" if args.scope == "author" else "cited_published"

    eligible_rows = []
    for row in master_rows:
        refresh_download_fields(row)
        if row.get("record_type") != target_record_type:
            continue
        if row.get("download_supported") != "true":
            continue
        if row.get("download_status") == "downloaded":
            continue
        eligible_rows.append(row)

    write_csv(master_catalog_path, MASTER_FIELDS, sort_master_rows(master_rows))

    sciencedirect_records: list[dict[str, str]] = []
    wiley_records: list[dict[str, str]] = []
    jstor_records: list[dict[str, str]] = []
    for record in eligible_rows:
        route = record.get("preferred_download_route", "")
        if route == "sciencedirect":
            sciencedirect_records.append(record)
        elif route == "wiley":
            wiley_records.append(record)
        elif route == "jstor":
            jstor_records.append(record)

    jstor_known_records = [record for record in jstor_records if jstor_row_has_known_stable(record)]
    jstor_search_records = [record for record in jstor_records if not jstor_row_has_known_stable(record)]

    sciencedirect_rows = [
        queue_row_for_science_like(record, index)
        for index, record in enumerate(sciencedirect_records, start=1)
    ]
    wiley_rows = [
        queue_row_for_science_like(record, index)
        for index, record in enumerate(wiley_records, start=1)
    ]
    jstor_rows = [
        queue_row_for_jstor(record, index)
        for index, record in enumerate(jstor_known_records + jstor_search_records, start=1)
    ]
    jstor_known_rows = [
        queue_row_for_jstor(record, index)
        for index, record in enumerate(jstor_known_records, start=1)
    ]
    jstor_search_rows = [
        queue_row_for_jstor(record, index)
        for index, record in enumerate(jstor_search_records, start=1)
    ]

    outputs = [
        ("sciencedirect_input.csv", ["number", "title", "doi", "year", "journal", "note", "formatted"], sciencedirect_rows),
        ("wiley_input.csv", ["number", "title", "doi", "year", "journal", "note", "formatted"], wiley_rows),
        (
            "jstor_input.csv",
            ["number", "ref_no", "title", "authors", "year", "journal", "doi", "stable_id", "stable_url", "article_url", "source_url", "jstor_status", "note"],
            jstor_rows,
        ),
        (
            "jstor_input_known_stable.csv",
            ["number", "ref_no", "title", "authors", "year", "journal", "doi", "stable_id", "stable_url", "article_url", "source_url", "jstor_status", "note"],
            jstor_known_rows,
        ),
        (
            "jstor_input_search.csv",
            ["number", "ref_no", "title", "authors", "year", "journal", "doi", "stable_id", "stable_url", "article_url", "source_url", "jstor_status", "note"],
            jstor_search_rows,
        ),
    ]
    for filename, fieldnames, rows in outputs:
        target = out_dir / filename
        if rows:
            write_csv(target, fieldnames, rows)
        elif target.exists():
            target.unlink()

    order_path = write_recommended_download_order(
        out_dir,
        jstor_known_count=len(jstor_known_rows),
        wiley_count=len(wiley_rows),
        jstor_search_count=len(jstor_search_rows),
        sciencedirect_count=len(sciencedirect_rows),
    )

    print(f"Queue scope: {args.scope}")
    print(f"ScienceDirect rows: {len(sciencedirect_rows)}")
    print(f"Wiley rows: {len(wiley_rows)}")
    print(f"JSTOR rows: {len(jstor_rows)}")
    print(f"JSTOR known-stable rows: {len(jstor_known_rows)}")
    print(f"JSTOR search rows: {len(jstor_search_rows)}")
    print(f"Recommended order file: {order_path}")
    print(f"Queue directory: {out_dir}")
    return 0


def cmd_ingest_results(args: argparse.Namespace) -> int:
    master_catalog_path = Path(args.master_catalog).resolve()
    manifest_path = Path(args.download_manifest).resolve()
    results_path = Path(args.results_csv).resolve()
    root_dir = root_dir_from_master(master_catalog_path)
    author_dir = author_dir_from_context(root_dir)
    cite_root = root_dir / "cite"

    master_rows = load_master_catalog(master_catalog_path)
    manifest_rows = load_manifest(manifest_path)
    result_rows = read_csv_rows(results_path)

    success_count = 0
    failure_count = 0
    unmatched_count = 0

    for result in result_rows:
        matched = find_matching_row(master_rows, scope=args.scope, result_row=result)
        if not matched:
            unmatched_count += 1
            continue

        status = canonical_download_status(result.get("status", ""))
        if status != "downloaded":
            matched["download_status"] = status or "failed"
            append_note(matched, f"{args.platform}_result={result.get('status', '')}")
            failure_count += 1
            continue

        raw_pdf_path = Path(result.get("pdf_path", "")).resolve()
        if not raw_pdf_path.exists():
            matched["download_status"] = "failed"
            append_note(matched, f"{args.platform}_pdf_missing={raw_pdf_path}")
            failure_count += 1
            continue

        pdf_filename = make_pdf_filename(matched)
        if args.scope == "author":
            final_paths = [
                copy_pdf(
                    raw_pdf_path,
                    author_dir,
                    pdf_filename,
                    existing_path=matched.get("primary_output_path", ""),
                )
            ]
            manifest_entry = {
                "scope": "author",
                "seed_author": matched.get("seed_author", ""),
                "source_paper_title": "",
                "title": matched.get("title", ""),
                "authors": matched.get("authors", ""),
                "journal_abbrev": matched.get("journal_abbrev", ""),
                "year": matched.get("year", ""),
                "doi": matched.get("doi", ""),
                "platform": args.platform,
                "pdf_filename": final_paths[0].name,
                "pdf_path": str(final_paths[0]),
                "status": "downloaded",
            }
            upsert_manifest(manifest_rows, manifest_entry)
        else:
            citing_titles = split_multi(matched.get("citing_titles", ""), TITLE_LIST_SEP) or ["Unassigned"]
            final_paths = []
            for citing_title in citing_titles:
                cite_dir = cite_root / sanitize_dir_component(citing_title, "Unassigned")
                existing_manifest_path = ""
                target_key = {
                    "scope": "cite",
                    "source_paper_title": citing_title,
                    "title": matched.get("title", ""),
                    "doi": matched.get("doi", ""),
                }
                for manifest_row in manifest_rows:
                    if manifest_key(manifest_row) == manifest_key(target_key):
                        existing_manifest_path = manifest_row.get("pdf_path", "")
                        break
                final_path = copy_pdf(
                    raw_pdf_path,
                    cite_dir,
                    pdf_filename,
                    existing_path=existing_manifest_path,
                )
                final_paths.append(final_path)
                manifest_entry = {
                    "scope": "cite",
                    "seed_author": matched.get("seed_author", ""),
                    "source_paper_title": citing_title,
                    "title": matched.get("title", ""),
                    "authors": matched.get("authors", ""),
                    "journal_abbrev": matched.get("journal_abbrev", ""),
                    "year": matched.get("year", ""),
                    "doi": matched.get("doi", ""),
                    "platform": args.platform,
                    "pdf_filename": final_path.name,
                    "pdf_path": str(final_path),
                    "status": "downloaded",
                }
                upsert_manifest(manifest_rows, manifest_entry)

        matched["download_status"] = "downloaded"
        matched["primary_output_path"] = str(final_paths[0]) if final_paths else ""
        success_count += 1

    write_csv(master_catalog_path, MASTER_FIELDS, sort_master_rows(master_rows))
    write_csv(manifest_path, MANIFEST_FIELDS, manifest_rows)
    print(f"Ingest scope: {args.scope}")
    print(f"Platform: {args.platform}")
    print(f"Successful rows: {success_count}")
    print(f"Failed rows: {failure_count}")
    print(f"Unmatched result rows: {unmatched_count}")
    print(f"Master catalog updated: {master_catalog_path}")
    print(f"Download manifest updated: {manifest_path}")
    return 0


def locate_reference_text(pages: list[str], max_tail_pages: int) -> tuple[str, str]:
    heading_re = re.compile(r"(?im)^\s*(references|bibliography|works cited)\s*$")
    stop_re = re.compile(r"(?im)^\s*(appendix|internet appendix|supplementary appendix|supplementary material)\s*$")

    start_page = None
    start_offset = 0
    for page_index, text in enumerate(pages):
        match = heading_re.search(text or "")
        if match:
            start_page = page_index
            start_offset = match.start()
            break

    if start_page is None:
        tail = pages[-max_tail_pages:] if max_tail_pages > 0 else pages
        return "\n\n".join(tail).strip(), "tail_pages_fallback"

    collected: list[str] = []
    for page_index in range(start_page, len(pages)):
        text = pages[page_index] or ""
        if page_index == start_page:
            text = text[start_offset:]
        elif stop_re.search(text):
            break
        collected.append(text)
    return "\n\n".join(collected).strip(), "references_heading"


def cmd_extract_reference_text(args: argparse.Namespace) -> int:
    if PdfReader is None:
        print("pypdf is required for extract-reference-text. Add it to the environment first.", file=sys.stderr)
        return 2

    master_catalog_path = Path(args.master_catalog).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    master_rows = load_master_catalog(master_catalog_path)

    index_rows: list[dict[str, str]] = []
    extracted = 0
    failed = 0

    for row in master_rows:
        if row.get("record_type") != "author_published":
            continue
        if row.get("download_status") != "downloaded":
            continue
        pdf_path = Path(row.get("primary_output_path", ""))
        if not pdf_path.exists():
            index_rows.append(
                {
                    "source_paper_title": row.get("title", ""),
                    "source_paper_doi": row.get("doi", ""),
                    "source_pdf_path": str(pdf_path),
                    "reference_text_path": "",
                    "status": "missing_pdf",
                    "note": "primary_output_path does not exist",
                }
            )
            failed += 1
            continue

        try:
            reader = PdfReader(str(pdf_path))
            pages = [(page.extract_text() or "") for page in reader.pages]
            reference_text, extraction_mode = locate_reference_text(pages, max_tail_pages=args.max_tail_pages)
            target_path = out_dir / f"{sanitize_file_component(row.get('title', ''), 'paper')}.references.txt"
            target_path.write_text(reference_text, encoding="utf-8")
            index_rows.append(
                {
                    "source_paper_title": row.get("title", ""),
                    "source_paper_doi": row.get("doi", ""),
                    "source_pdf_path": str(pdf_path),
                    "reference_text_path": str(target_path),
                    "status": "extracted",
                    "note": extraction_mode,
                }
            )
            extracted += 1
        except Exception as exc:  # pragma: no cover - depends on PDF content
            index_rows.append(
                {
                    "source_paper_title": row.get("title", ""),
                    "source_paper_doi": row.get("doi", ""),
                    "source_pdf_path": str(pdf_path),
                    "reference_text_path": "",
                    "status": "failed",
                    "note": str(exc),
                }
            )
            failed += 1

    index_path = out_dir / "reference_extract_index.csv"
    write_csv(
        index_path,
        ["source_paper_title", "source_paper_doi", "source_pdf_path", "reference_text_path", "status", "note"],
        index_rows,
    )
    print(f"Extracted reference files: {extracted}")
    print(f"Failed extractions: {failed}")
    print(f"Reference extract index: {index_path}")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "init-run":
        return cmd_init_run(args)
    if args.command == "import-records":
        return cmd_import_records(args)
    if args.command == "build-queues":
        return cmd_build_queues(args)
    if args.command == "ingest-results":
        return cmd_ingest_results(args)
    if args.command == "extract-reference-text":
        return cmd_extract_reference_text(args)
    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
