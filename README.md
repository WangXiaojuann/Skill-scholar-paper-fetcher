# scholar-paper-fetcher

`scholar-paper-fetcher` is a Codex skill for building a scholar-centered corpus of official published papers and cited published papers, then downloading supported publisher PDFs through a live authorized Microsoft Edge session.

## What It Supports

- Full scholar pipeline:
  `scholar_name + google_scholar_url -> published scholar papers -> cited published papers -> official PDF download`
- Direct official-PDF downloading from supported platforms when the paper list already exists
- Supported publisher routes:
  `ScienceDirect / Elsevier`, `Wiley`, and `JSTOR`

## What It Does Not Do

- It does not create new access rights.
- It does not use SSRN-only items, working papers, or unpublished drafts as download targets.
- It does not parallelize PDF fetching.

## Repository Layout

- [SKILL.md](./SKILL.md): Codex skill instructions
- [agents/openai.yaml](./agents/openai.yaml): skill metadata
- [scripts](./scripts): PowerShell wrappers and Python entrypoints
- [references](./references): workflow and troubleshooting notes

The `runtime/` directory is intentionally not tracked in this repo because it can contain browser session data and local machine state.

## Install As A Local Codex Skill

Clone or copy this folder into your local Codex skills directory as:

```text
%USERPROFILE%\.codex\skills\scholar-paper-fetcher
```

After that, invoke it in Codex with:

```text
$scholar-paper-fetcher
```

## Environment

- Windows
- Microsoft Edge
- Python with dependencies from [scripts/requirements.txt](./scripts/requirements.txt)

Install Python dependencies with:

```powershell
pip install -r .\scripts\requirements.txt
```

## Security Note

Do not commit browser profiles, downloaded PDFs, or run artifacts. This repository is intended to track the reusable skill logic only.
