# JSTOR Troubleshooting

## Status Codes

### `no_exact_search_hit`

Meaning:

- JSTOR search did not expose a title card the fetcher could confidently match

Common causes:

- the citation title in the input CSV does not match the JSTOR title card closely enough
- the row belongs to a publisher page that is not actually mirrored on JSTOR
- the first-author hint is missing or too ambiguous

What to do:

1. search the title manually in the same JSTOR session
2. if you find the article, add `stable_id` or `stable_url` to the CSV row
3. rerun only the failed rows

### `no_stable_id`

Meaning:

- a result appeared, but the stable identifier could not be parsed

Common causes:

- the result link did not expose a usable `/stable/...` path
- the page layout changed before the fetcher parsed the result

What to do:

- manually open the article in the same JSTOR session
- copy the stable article URL into `stable_url`
- rerun the row

### `pdf_fetch_failed`

Meaning:

- the JSTOR PDF endpoint did not return a valid PDF in the current session

Common causes:

- the current Edge session is not fully authorized for JSTOR PDF access
- JSTOR accepted the search page but denied the PDF endpoint
- the article opened in the browser, but the session expired before the PDF request

What to do:

1. keep the same Edge window open
2. manually open the target article and click `Download`
3. confirm that the same session can see the PDF
4. rerun only the failed rows

## Session Problems

### The JSTOR page still asks for login or access

Likely causes:

- JSTOR login was completed in another browser profile, not in the live remote-debugging session
- the institution login route did not finish in the dedicated Edge window

What to do:

- finish the JSTOR login in the exact Edge window launched for the skill
- confirm the article page shows your personal or institutional access
- only then rerun the fetcher

### The search result is ambiguous

Common causes:

- the title is generic
- multiple versions or nearby titles exist on JSTOR

What to do:

- add `stable_id` or `stable_url` to the input
- or create a smaller curated input CSV before running the batch
