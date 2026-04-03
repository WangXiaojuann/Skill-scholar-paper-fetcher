---
name: scholar-paper-fetcher
description: Build a scholar-centered corpus of official published papers and cited published papers by reusing a live authorized Microsoft Edge session on supported publisher platforms. Use when the user provides a scholar name plus Google Scholar URL, or already has a paper list and wants direct official-PDF downloading on ScienceDirect / Elsevier, Wiley, or JSTOR. Exclude SSRN, working papers, and unpublished versions.
---

# Scholar Paper Fetcher

Use this skill when the browser session is the source of truth and the agent should reuse the user's already authorized Microsoft Edge window.

## Use This Skill For

- the full scholar pipeline: `scholar_name + google_scholar_url -> published scholar papers -> cited published papers -> official PDF download`
- the direct platform pipeline: the paper list already exists and the user only wants official PDF downloads on supported platforms

Do not use this skill to create access the user does not already have.

## Core Rules

- download only official published versions
- exclude SSRN-only items, working papers, and unpublished drafts
- keep all platform downloads strictly serial; do not parallelize PDF fetching or use sub-agents to bulk-download
- keep the live Edge session open during every download run
- if a previous run was interrupted, inspect the existing `out_dir` before resuming; for a clean restart, use a new `out_dir` or reinitialize explicitly
- retry only the failed subset unless the user explicitly asks for a fresh full rerun
- do not silently drop unsupported or inaccessible items; keep them recorded in `master_catalog.csv`
- do not extract cited papers from scholar papers that were not downloaded as official PDFs

## Terminology

- `scholar papers`: the target scholar's own published papers
- `cited papers`: published journal articles cited by downloaded scholar papers
- the scripts still use the internal word `author` in places such as `author_published`, `--scope author`, and `<Author Name>/`; keep those literal values because they refer to the target scholar's own papers

## Choose a Path

### Path A: Full Scholar Pipeline

Use this path when the user starts from a scholar identity and wants the full corpus built.

### Path B: Direct Platform Downloads

Use this path when discovery is already done and the user only wants platform-specific downloading.

## Path A: Full Scholar Pipeline

### Canonical Outputs

These are the fixed user-facing outputs:

- `master_catalog.csv`
- `download_manifest.csv`
- `<Author Name>/`
- `cite/`

Everything else belongs under `_runs/`.

`master_catalog.csv` is the logical master table and must contain both:

- `record_type=author_published`
- `record_type=cited_published`

`download_manifest.csv` is the physical file manifest. Each row represents one PDF file that actually landed in the final output tree.

### Stage 1: Initialize the Run Root

Run [scripts/run_scholar_publication_pipeline.ps1](scripts/run_scholar_publication_pipeline.ps1) with `init-run`.

This creates:

- `master_catalog.csv`
- `download_manifest.csv`
- `<Author Name>/`
- `cite/`
- `_runs/`

Required inputs:

- `author_name`
- `google_scholar_url`
- `out_dir`

### Stage 2: Discover the Scholar's Published Papers

Use the Google Scholar page as the identity anchor, then verify in this order:

1. scholar homepage or CV
2. institution profile
3. publisher page

Published-paper rules:

- include formal journal publications
- include `online in press`
- exclude SSRN-only items
- exclude working papers
- exclude items that are only `forthcoming` without a live journal publication page

Write raw discovery rows to `_runs/discovery/author_published_raw.csv`, then import them into `master_catalog.csv` with `import-records`.

At minimum, raw discovery rows should carry:

- `title`
- `authors`
- `journal`
- `year`
- `doi`
- `platform` or `publisher_platform`
- `article_url`
- `status` or `published_status`
- `notes`

Checkpoint before downloading:

- review `master_catalog.csv`
- confirm the scholar-paper set before any download starts

### Stage 3: Download the Scholar Papers

Run `build-queues --scope author` to create platform queues under `_runs/queues/author/`.

Supported routes:

- `ScienceDirect / Elsevier`
- `Wiley`
- `JSTOR`

Routing rule:

- if a row carries JSTOR-positive evidence such as `stable_id`, `stable_url`, a `jstor.org` article URL, or `jstor_status=confirmed_on_jstor`, `build-queues` must route it to `JSTOR` first even if publisher metadata or an older `preferred_download_route` says Wiley or ScienceDirect

Unsupported or currently inaccessible records must remain in `master_catalog.csv` with:

- `download_supported=false`
- `preferred_download_route=unsupported`
- `download_status=unsupported_platform`

Run the platform wrappers into `_runs/platform/author/<platform>/...`:

- [scripts/run_sciencedirect_live_session_fetch.ps1](scripts/run_sciencedirect_live_session_fetch.ps1)
- [scripts/run_wiley_live_session_fetch.ps1](scripts/run_wiley_live_session_fetch.ps1)
- [scripts/run_jstor_live_session_fetch.ps1](scripts/run_jstor_live_session_fetch.ps1)

Default mixed-source batch order after `build-queues`:

1. `jstor_input_known_stable.csv`
2. `wiley_input.csv`
3. `jstor_input_search.csv`
4. `sciencedirect_input.csv`

`build-queues` also writes `recommended_download_order.txt` and keeps the backward-compatible
all-in-one `jstor_input.csv`.

If you add JSTOR evidence later, rerun `build-queues` so the row moves from a prior Wiley / ScienceDirect route into the JSTOR queue.

Platform notes:

- ScienceDirect already includes built-in `View PDF` / `View full text` fallback logic
- if a ScienceDirect page explicitly says the institution `does not subscribe to this content`, stop retrying that item in the current session
- on Wiley, `no_pdfdirect_link` can still be a slow reader-loading state; retry with a longer wait before declaring failure

Then ingest platform result CSVs back into the canonical outputs with `ingest-results --scope author`.

Final scholar-paper PDFs must end up in `<Author Name>/` with this filename rule:

- `<AuthorLastName>_<JournalAbbrev>_<PublicationYear>.pdf`

Example:

- `Author_JFE_2025.pdf`

### Stage 4: Extract Cited Published Papers

Only use downloaded official scholar-paper PDFs.

Run `extract-reference-text` after the scholar-paper downloads are ingested. This writes intermediate extraction artifacts under `_runs/reference_extract/`.

Use the extracted reference text plus web verification to build `_runs/discovery/cited_published_raw.csv`.

Cited-paper rules:

- keep only cited journal articles that are already published
- de-duplicate them logically in `master_catalog.csv`
- keep citation lineage only in aggregated form:
  - `citing_count`
  - `citing_titles`
  - `citing_dois`

Import the cited rows with `import-records --record-type cited_published`.

Checkpoint before cited downloads:

- review the cited-paper block in `master_catalog.csv`
- confirm the cited-paper set before cited downloads start

### Stage 5: Download the Cited Papers

Run `build-queues --scope cite`, then run the same platform wrappers into `_runs/platform/cite/<platform>/...`.

Default mixed-source batch order after `build-queues`:

1. `jstor_input_known_stable.csv`
2. `wiley_input.csv`
3. `jstor_input_search.csv`
4. `sciencedirect_input.csv`

`build-queues` also writes `recommended_download_order.txt` and keeps the backward-compatible
all-in-one `jstor_input.csv`.

The same JSTOR-first routing rule applies to cited-paper queues; rerun `build-queues` after adding `stable_id`, `stable_url`, or `jstor_status=confirmed_on_jstor`.

For cited downloads:

- keep the same serial-download discipline as the scholar-paper stage
- if JSTOR title search misses a known published item, allow a manual retry with explicit `stable_id` or `stable_url` in the input CSV rather than dropping the paper immediately

After the platform runs finish, ingest them with `ingest-results --scope cite`.

Final cited PDFs must be materialized under:

- `cite/<AuthorPaperTitle>/`

Use physical duplication for cited PDFs:

- if one cited paper is referenced by multiple scholar papers, place one copy in each relevant `cite/<AuthorPaperTitle>/` folder
- logical de-duplication still lives in `master_catalog.csv`
- physical-file tracking lives in `download_manifest.csv`

## Path B: Direct Platform Downloads

Use this path when the paper list already exists and the user only wants downloading.

### Shared Setup

1. Prepare or confirm the input CSV.

For ScienceDirect or Wiley:

- required columns: `number`, `doi`
- optional columns: `title`, `note`, `year`, `journal`, `formatted`

For JSTOR:

- required column: `title`
- recommended column: `authors`
- optional columns: `ref_no`, `number`, `stable_id`, `stable_url`, `jstor_status`

For mixed-source queue building, treat `stable_id`, `stable_url`, and `jstor_status=confirmed_on_jstor` as positive JSTOR route signals.

2. Launch a dedicated Edge session with remote debugging.

Use [scripts/launch_edge_live_session.ps1](scripts/launch_edge_live_session.ps1).

3. Before each download batch, open the three supported source pages in that same Edge session.

Use [scripts/prepare_live_session_logins.ps1](scripts/prepare_live_session_logins.ps1), or rely on the three `run_*_live_session_fetch.ps1` wrappers because they now call it by default.

4. Let the user complete the manual setup in that Edge window.

They must:

- sign in to the source pages they need
- pass any bot verification or challenge page
- open a representative article
- click `View PDF`, `PDF`, or `Download` once
- keep the window open

### ScienceDirect / Elsevier

1. If needed, probe the live session with [scripts/probe_sciencedirect_live_session.py](scripts/probe_sciencedirect_live_session.py).
2. Run [scripts/run_sciencedirect_live_session_fetch.ps1](scripts/run_sciencedirect_live_session_fetch.ps1). It opens the three source pages first and waits for login confirmation unless `-PrepareLogin $false` is passed.
3. Review `devtools_results.csv`, retry only failed rows, and validate the downloaded article PDFs.

### Wiley

1. Open a Wiley article page in the same Edge session and click `PDF` once.
2. Run [scripts/run_wiley_live_session_fetch.ps1](scripts/run_wiley_live_session_fetch.ps1). It opens the three source pages first and waits for login confirmation unless `-PrepareLogin $false` is passed.
3. Validate that the result is the published article PDF, not a supplement or appendix.

### JSTOR

1. Sign in to JSTOR in the same Edge session.
2. Optionally open a representative JSTOR article and click `Download` once.
3. Run [scripts/run_jstor_live_session_fetch.ps1](scripts/run_jstor_live_session_fetch.ps1). It opens the three source pages first and waits for login confirmation unless `-PrepareLogin $false` is passed.

## Core Commands

Initialize the full scholar pipeline:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_scholar_publication_pipeline.ps1 `
  init-run `
  --author-name "Author Name" `
  --google-scholar-url "https://scholar.google.com/..." `
  --out-dir C:\path\to\run-root
```

Import discovery rows into the master catalog:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_scholar_publication_pipeline.ps1 `
  import-records `
  --master-catalog C:\path\to\run-root\master_catalog.csv `
  --input-csv C:\path\to\run-root\_runs\discovery\author_published_raw.csv `
  --record-type author_published `
  --default-source-basis "google_scholar_anchor;multi_source_check"
```

Build platform queues:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_scholar_publication_pipeline.ps1 `
  build-queues `
  --master-catalog C:\path\to\run-root\master_catalog.csv `
  --scope author `
  --out-dir C:\path\to\run-root\_runs\queues\author
```

After queue build, follow `recommended_download_order.txt` in that queue directory. The default
mixed-source order is:

1. `jstor_input_known_stable.csv`
2. `wiley_input.csv`
3. `jstor_input_search.csv`
4. `sciencedirect_input.csv`

Any row with JSTOR-positive evidence is expected to land in one of the JSTOR queue files before Wiley or ScienceDirect.

Ingest platform results:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_scholar_publication_pipeline.ps1 `
  ingest-results `
  --master-catalog C:\path\to\run-root\master_catalog.csv `
  --download-manifest C:\path\to\run-root\download_manifest.csv `
  --scope cite `
  --platform jstor `
  --results-csv C:\path\to\run-root\_runs\platform\cite\jstor\jstor_results.csv
```

Extract reference sections from downloaded scholar PDFs:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_scholar_publication_pipeline.ps1 `
  extract-reference-text `
  --master-catalog C:\path\to\run-root\master_catalog.csv `
  --out-dir C:\path\to\run-root\_runs\reference_extract
```

Launch the shared Edge session:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_live_session.ps1
```

Prepare the three source login pages:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_live_session_logins.ps1
```

Run direct ScienceDirect downloading:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_sciencedirect_live_session_fetch.ps1 `
  -InputCsv C:\path\to\input.csv `
  -OutDir C:\path\to\out-dir
```

## References

- Read [references/workflow-author-pipeline.md](references/workflow-author-pipeline.md) for the full scholar workflow.
- Read [references/workflow.md](references/workflow.md) for the direct ScienceDirect / Elsevier run order.
- Read [references/troubleshooting.md](references/troubleshooting.md) for ScienceDirect troubleshooting.
- Read [references/workflow-wiley.md](references/workflow-wiley.md) for the Wiley run order.
- Read [references/troubleshooting-wiley.md](references/troubleshooting-wiley.md) for Wiley troubleshooting.
- Read [references/workflow-jstor.md](references/workflow-jstor.md) for the JSTOR run order.
- Read [references/troubleshooting-jstor.md](references/troubleshooting-jstor.md) for JSTOR troubleshooting.
