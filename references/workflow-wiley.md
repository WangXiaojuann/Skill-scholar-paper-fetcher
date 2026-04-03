# Wiley Workflow

Use this workflow when the paper list already exists and the user wants direct official-PDF downloading from Wiley Online Library.

## Before Running

- prepare an input CSV with `number` and `doi`
- optionally include `title`, `note`, `year`, `journal`, and `formatted`
- launch the shared Edge remote-debugging session
- make sure the user can open a real Wiley article PDF in that same session
- open the three supported source pages in that same session before the batch starts

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
2. complete personal or institutional sign-in for Wiley Online Library
3. open a representative Wiley article page
4. click `PDF` once so the ePDF reader is available in the same session
5. keep that window open

Helper command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_live_session_logins.ps1
```

The download wrapper calls that helper automatically unless `-PrepareLogin $false` is passed.

## Run the Batch

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_wiley_live_session_fetch.ps1 `
  -InputCsv .\input.csv `
  -OutDir .\out\run-wiley-001 `
  -PageWaitSeconds 8 `
  -InterItemSleepSeconds 5 `
  -ViewerWsTimeoutSeconds 180
```

If the same Edge session is already prepared and you want to skip the interactive pause:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_wiley_live_session_fetch.ps1 `
  -InputCsv .\input.csv `
  -OutDir .\out\run-wiley-001 `
  -PrepareLogin $false
```

Recommended defaults:

- `PageWaitSeconds`: `8` to `10`
- `InterItemSleepSeconds`: `5`
- `ViewerWsTimeoutSeconds`: `180` to `300`

## How the Fetch Works

1. open the article page from DOI or candidate URL
2. locate the article `PDF` link that leads to the Wiley ePDF reader
3. open the ePDF reader target in the live session
4. extract the `pdfdirect` article PDF link from the ePDF reader page
5. fetch the PDF bytes inside that same browser session

This order matters because Wiley pages can expose supplement or appendix links that are not the main article.

## Status Guide

- `downloaded`: the row completed successfully
- `no_epdf_link`: the article page did not expose the Wiley ePDF entry
- `epdf_open_failed`: the click did not stabilize on a usable ePDF page
- `no_pdfdirect_link`: the ePDF page loaded but did not expose the direct article PDF target yet
- `viewer_extract_failed` or `viewer_extract_exception`: the article PDF target did not return a valid PDF body in the current session

`no_pdfdirect_link` does not always mean lack of access. Wiley's reader can be slow, so retry with a longer wait before declaring failure.

## Retry Rules

- create a smaller CSV from `wiley_missing.csv`
- keep the same Edge session open
- manually test one failed DOI if the pattern is unclear
- rerun only the failed subset
