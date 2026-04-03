# ScienceDirect Workflow

Use this workflow when the paper list already exists and the user wants direct official-PDF downloading on ScienceDirect / Elsevier.

## Before Running

- prepare an input CSV with `number` and `doi`
- optionally include `title`, `note`, `year`, `journal`, and `formatted`
- launch the dedicated Edge session with remote debugging
- keep the session inside the user's authorized institution or personal access route

Launch command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_live_session.ps1
```

Useful override:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_live_session.ps1 `
  -RemoteDebuggingPort 9333 `
  -CloneUserDataDir D:\edge-clones\sd-session\User Data `
  -Url "https://www.sciencedirect.com/"
```

## Manual Session Preparation

In the opened Edge window:

1. complete account or institutional sign-in
2. pass any bot-verification page
3. open a representative article page
4. click `View PDF` once
5. keep that window open

## Optional Session Probe

Use the probe when you want a quick yes/no check before a full batch:

```powershell
python .\scripts\probe_sciencedirect_live_session.py `
  --debugger-address 127.0.0.1:9222 `
  --url "https://www.sciencedirect.com/science/article/pii/S0886779824005960?via%3Dihub"
```

Healthy signs:

- `attached: true`
- `bot_verification_page: false`
- `has_pdf_metadata: true`

## Run the Batch

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_sciencedirect_live_session_fetch.ps1 `
  -InputCsv .\examples\input-template.csv `
  -OutDir .\out\run-001 `
  -PageWaitSeconds 8 `
  -InterItemSleepSeconds 6 `
  -ViewerWsTimeoutSeconds 180
```

Recommended defaults:

- `PageWaitSeconds`: `8`
- `InterItemSleepSeconds`: `5` to `8`
- `ViewerWsTimeoutSeconds`: `180` to `420`

The bundled fetcher already includes the built-in `View PDF` / `View full text` fallback path. Do not keep a separate ad hoc ScienceDirect helper script in the run directory.

## Status Guide

- `downloaded`: the row completed successfully
- `no_pdf_metadata`: the fetcher could not recover a PDF target from embedded metadata or the built-in fallback path
- `no_view_pdf` or `no_pdf_href`: the article page loaded, but the current session never exposed a usable `View PDF` target
- `institution_no_subscription`: the page text explicitly says the current institution does not subscribe to that ScienceDirect item; stop retrying in the same session
- `viewer_extract_failed`: the PDF viewer did not return a valid PDF body
- `viewer_extract_exception`: the viewer stage threw an exception and should be treated like a focused retry candidate

## Retry Rules

- create a smaller CSV from `devtools_missing.csv`
- keep the same Edge session open
- rerun only rows that are plausibly recoverable
- do not blindly retry rows already marked `institution_no_subscription`
