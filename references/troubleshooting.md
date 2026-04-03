# ScienceDirect Troubleshooting

## Status Codes

### `no_pdf_metadata`

Meaning:

- the fetcher could not recover a ScienceDirect PDF target from embedded metadata or the built-in fallback path

Common causes:

- the page is still on a sign-in or bot-verification screen
- the article page did not finish loading
- the session can see the landing page, but not the PDF route

What to do:

1. keep the same Edge window open
2. manually open the target article in that window
3. if the page shows `View full text`, open that first
4. click `View PDF`
5. rerun only the failed rows

### `no_view_pdf` or `no_pdf_href`

Meaning:

- the article page loaded, but the session never exposed a usable `View PDF` target

Common causes:

- the page stayed on a preview or abstract variant
- the `View PDF` control never rendered
- the control rendered, but never produced a usable URL

What to do:

1. keep the same Edge window open
2. manually reopen the article and wait for the page to settle
3. if the page offers `View full text`, click that first
4. then click `View PDF` once
5. retry only the failed subset

### `institution_no_subscription`

Meaning:

- the page text explicitly says the current institution does not subscribe to that ScienceDirect item

What to do:

- stop retrying the row in the same session
- keep the row recorded as inaccessible for this institution or network path
- only retry later if the user switches to a different authorized route

### `viewer_extract_failed`

Meaning:

- the PDF viewer stage did not return a valid PDF body

Common causes:

- the in-browser PDF viewer did not finish loading
- the tab opened a non-PDF error page
- the session expired between the article page and the viewer page

What to do:

- increase `PageWaitSeconds`
- keep `InterItemSleepSeconds` at `5+`
- manually test one failed DOI in the same session

## Session Problems

### The browser keeps showing bot-verification pages

Likely causes:

- the session is not fully authorized yet
- the current network path is triggering the challenge page
- the browser profile is too clean and still needs a full sign-in flow

What to do:

- finish the challenge in the same Edge window
- manually open a real article and its PDF first
- avoid opening too many articles quickly

### The fetcher cannot attach to the session

Check:

- Edge was launched with `--remote-debugging-port`
- the port matches your command, for example `9222`
- the Edge window is still open

If needed, start a fresh session with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_live_session.ps1
```

### Existing main Edge windows interfere

If you reuse a live profile, close all Edge windows first. The recommended path is to use the dedicated launcher and isolated user-data directory instead.

### Article rows have only DOI and no candidate URLs

This is supported. The fetcher opens `https://doi.org/<doi>` first.

### Network-specific access problems

This workflow does not solve access or routing problems by itself. If the institution requires a specific network path, VPN split tunneling, or campus egress route, fix that first and then rerun.
