# scholar-paper-fetcher

`scholar-paper-fetcher` is a Codex skill for collecting official published papers around one scholar. You give Codex the scholar's name and the URL of that scholar's Google Scholar profile. From there, the skill helps Codex find the scholar's published papers, download supported official PDFs, extract references from those papers, and then download the published versions of the cited papers when they are available from supported sources.

## What this skill does

- Works inside Codex as a reusable skill
- Starts from:
  `scholar_name + google_scholar_url`
- Targets:
  - the scholar's own published papers
  - the published versions of papers cited by those papers
- Downloads only official published PDFs from supported publisher platforms

## Supported sources

At the moment, this skill is set up for these three sources:

- `ScienceDirect / Elsevier`
- `Wiley`
- `JSTOR`

## Browser and access requirements

This skill currently assumes the user is working with `Microsoft Edge`.

Before running the download steps, the user needs to:

- manually sign in through their institution or personal access route


The skill reuses the user's live logged-in browser session. It does not create new access, bypass paywalls, or obtain permissions the user does not already have.

## Typical use in Codex

Use this skill when you want Codex to assemble a scholar's papers and the papers cited in those papers.

Typical input:

```text
Scholar name + Google Scholar profile URL
```

Example:

```text
Use $scholar-paper-fetcher for Jane Doe with Google Scholar URL https://scholar.google.com/...
```






