# JSTOR Workflow

Use this workflow when the paper list already exists and the user wants direct official-PDF downloading from JSTOR.

## Before Running

Accepted input patterns:

- plain JSTOR citation list:
  - required: `title`
  - recommended: `authors`
  - optional: `ref_no` or `number`
- pre-screened JSTOR-positive list:
  - if a `jstor_status` column exists, the fetcher only attempts rows where `jstor_status=confirmed_on_jstor`
- direct stable identifiers:
  - optional: `stable_id` or `stable_url`

If `stable_id` or `stable_url` is already known, the fetcher skips search and goes straight to the JSTOR PDF route.

Launch command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_live_session.ps1
```

Useful override:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_live_session.ps1 `
  -RemoteDebuggingPort 9333
```

## Manual Session Preparation

In the opened Edge window:

1. sign in through personal, institutional, or campus JSTOR access
2. confirm that the same window shows your access route
3. open a representative JSTOR article page
4. click `Download` once to confirm the session can open the PDF
5. keep that window open

## Run the Batch

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_jstor_live_session_fetch.ps1 `
  -InputCsv .\input-jstor.csv `
  -OutDir .\out\run-jstor-001 `
  -PageWaitSeconds 10 `
  -InterItemSleepSeconds 3
```

Recommended defaults:

- `PageWaitSeconds`: `10`
- `InterItemSleepSeconds`: `3`

## How the Fetch Works

1. open the JSTOR search results page from title and first-author hint, unless a `stable_id` or `stable_url` is already available
2. resolve the matched `stable` article identifier
3. fetch `/stable/pdf/<stable_id>.pdf?acceptTC=1` inside the same live browser session
4. validate that the response is a real PDF before saving it

## Status Guide

- `downloaded`: the row completed successfully
- `skipped_input_not_confirmed`: the input row carried a non-positive `jstor_status`
- `missing_title`: the row could not be searched
- `no_exact_search_hit`: JSTOR search did not expose a matching title card
- `no_stable_id`: a result appeared but the stable identifier could not be parsed
- `pdf_fetch_failed`: the JSTOR PDF endpoint did not return a valid PDF in the current session

The fetcher writes:

- `pdfs/`
- `jstor_results.csv`
- `jstor_missing.csv`
- `downloaded_titles.txt`
- `missing_titles.txt`
- `summary.txt`

## Retry Rules

- create a smaller CSV from `jstor_missing.csv`
- keep the same Edge session open
- if search misses a known published item, add `stable_id` or `stable_url` and rerun only that smaller failed subset
