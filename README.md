# geocoach

GeoGuessr duel coaching CLI for No Move and NMPZ. Pulls your recent ranked duels, renders the panoramas of the rounds you lost, and asks Claude to explain what you missed using community meta PDFs you provide.

Personal, unofficial tool. It uses undocumented GeoGuessr endpoints and your own session cookie, read-only, on your own data.

## Requirements

- macOS or Linux, [mise](https://mise.jdx.dev) or `uv` 0.12+, `fzf`
- Claude Code CLI (`claude`) for the analysis and encyclopedia modes

## Setup

```sh
uv sync
cp .env.example .env   # paste your _ncfa cookie
```

Drop community meta PDFs in `metas/`. Reports and caches go to `data/` (gitignored).

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

One small PR per change, CI must be green before merge.
