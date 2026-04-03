# Wiley Troubleshooting

## Output Problems

### The fetcher downloaded a supplement or appendix instead of the article

Common cause:

- the page exposed multiple PDF-like links and the wrong one was chosen

What to do:

- use the Wiley flow that opens the ePDF reader first
- prefer the `pdfdirect` article link from the ePDF reader page
- verify the first page shows the journal issue header and article abstract, not `Internet Appendix` or `Online Appendix`

## Status Codes

### `no_epdf_link`

Meaning:

- the article page did not expose the Wiley ePDF entry

Common causes:

- the page did not finish loading
- the session can see the abstract page but not the PDF entry
- the user is not fully signed in for Wiley in that Edge session

What to do:

1. keep the same Edge window open
2. manually open the target article in that window
3. click `PDF`
4. rerun only the failed rows

### `epdf_open_failed`

Meaning:

- the PDF click did not stabilize on a usable ePDF page in the DevTools session

Common causes:

- the click opened a transient target and the page had not settled yet
- the publisher flow redirected through a challenge or teaser page

What to do:

- wait a few more seconds and rerun
- manually confirm that the ePDF reader opens in the same Edge session
- retry one DOI before rerunning a larger list

### `no_pdfdirect_link`

Meaning:

- the ePDF page loaded, but the direct article PDF target was not exposed yet

Common causes:

- the ePDF reader did not finish initializing
- the session opened the reader but not the downloadable article target
- the article access is gated in the current session

What to do:

- manually open the article PDF in the same Edge window
- confirm the ePDF page exposes a download action
- retry only the failed rows
- increase wait time before declaring failure

### `viewer_extract_failed` or `viewer_extract_exception`

Meaning:

- the final article PDF target did not return a valid PDF body in the current session

Common causes:

- the `pdfdirect` target returned non-PDF content
- the session lost authorization between the article page and the PDF target
- the page triggered a challenge or redirect

What to do:

- keep the same Edge window open
- increase `PageWaitSeconds`
- manually open the article and click `PDF` again in the same session
- retry only the failed rows

## Session Problems

### The Wiley page still asks for login

Likely causes:

- login was completed in another browser window, not in the live remote-debugging session
- the institution route or SSO flow is not finished in the current Edge window

What to do:

- finish the Wiley login in the exact Edge window launched for the skill
- confirm the same window can open the article PDF manually
- only then rerun the fetcher
