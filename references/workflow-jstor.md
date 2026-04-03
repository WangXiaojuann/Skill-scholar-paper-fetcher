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
Also open the three supported source pages in that same session before the batch starts.

If the queue came from `build-queues`, run `jstor_input_known_stable.csv` before any other
publisher batch. Leave `jstor_input_search.csv` for the later JSTOR cleanup pass after the known-
stable JSTOR batch and Wiley batch are complete.

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

1. open ScienceDirect, Wiley, and JSTOR in the same session
2. sign in through personal, institutional, or campus JSTOR access
3. confirm that the same window shows your access route
4. open a representative JSTOR article page
5. click `Download` once to confirm the session can open the PDF
6. keep that window open

Helper command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_live_session_logins.ps1
```

The download wrapper calls that helper automatically unless `-PrepareLogin $false` is passed.

## Run the Batch

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_jstor_live_session_fetch.ps1 `
  -InputCsv .\input-jstor.csv `
  -OutDir .\out\run-jstor-001 `
  -PageWaitSeconds 10 `
  -InterItemSleepSeconds 3
```

If the same Edge session is already prepared and you want to skip the interactive pause:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_jstor_live_session_fetch.ps1 `
  -InputCsv .\input-jstor.csv `
  -OutDir .\out\run-jstor-001 `
  -PrepareLogin $false
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
- prefer rerunning those repaired rows through `jstor_input_known_stable.csv` on the next pass
