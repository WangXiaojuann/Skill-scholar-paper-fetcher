# Scholar Pipeline Workflow

Use this workflow when the user starts from a scholar identity rather than a prebuilt paper list.

## Stage Order

1. Initialize the run root with `init-run`.
2. Discover the scholar's published papers from Google Scholar plus higher-confidence secondary sources.
3. Import those rows into `master_catalog.csv`.
4. Pause for confirmation before scholar-paper downloads.
5. Build scholar-paper queues and run the supported platform downloaders.
6. Ingest the scholar-paper platform results so the final PDFs land in `<Author Name>/`.
7. Extract reference text from the downloaded scholar PDFs.
8. Normalize and verify cited published papers from the extracted reference text.
9. Import cited rows into `master_catalog.csv`.
10. Pause for confirmation before cited-paper downloads.
11. Build cited-paper queues and run the supported platform downloaders.
12. Ingest cited-platform results so the final PDFs land in `cite/<AuthorPaperTitle>/`.

## Discovery Standards

- use Google Scholar only as the scholar identity anchor
- verify publications with scholar CVs, institution profiles, and publisher pages
- include formal journal publications
- include `online in press`
- exclude SSRN-only items, working papers, and unsupported forthcoming items without a live journal page

## Checkpoints

Pause twice for human confirmation:

- after importing scholar papers into `master_catalog.csv`
- after importing cited papers into `master_catalog.csv`

Do not start the next download stage until the relevant block in `master_catalog.csv` looks correct.

## Canonical Outputs

The only user-facing structured outputs are:

- `master_catalog.csv`
- `download_manifest.csv`
- `<Author Name>/`
- `cite/`

Everything else belongs under `_runs/`.

## Raw Discovery Inputs

Store raw manually curated discovery rows under `_runs/discovery/`.

Recommended raw files:

- `_runs/discovery/author_published_raw.csv`
- `_runs/discovery/cited_published_raw.csv`

Useful raw fields:

- `title`
- `authors`
- `journal`
- `year`
- `doi`
- `platform` or `publisher_platform`
- `article_url`
- `status` or `published_status`
- `notes`
- for cited rows: `citing_titles`, `citing_dois`, or `sample_paper_title` / `sample_paper_doi`

## Download Discipline

- build queues from `master_catalog.csv`; do not hand-maintain queue files
- write platform runs under `_runs/platform/<scope>/<platform>/...`
- ingest platform results back into `master_catalog.csv` and `download_manifest.csv`
- keep PDF downloads strictly serial
- retry only the failed subset when possible
- keep unsupported or inaccessible items recorded instead of silently dropping them

## Final File Layout

- scholar-paper PDFs go to `<Author Name>/`
- cited PDFs go to `cite/<AuthorPaperTitle>/`
- if one cited paper belongs under multiple scholar-paper folders, keep one physical copy in each folder and let `master_catalog.csv` handle logical deduplication

## Internal Naming Note

The scripts still use the internal word `author` in places such as:

- `author_published`
- `--scope author`
- `<Author Name>/`

Keep those literal values. In this skill they refer to the target scholar's own papers.
