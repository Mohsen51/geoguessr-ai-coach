# geocoach

GeoGuessr duel coaching CLI for No Move and NMPZ. It pulls your recent ranked duels, renders the Street View views of the rounds you lost, and asks Claude to explain what you missed, using the community meta PDFs you drop in `metas/`. It also suggests training maps from slashP's directory and builds country meta sheets.

Personal, unofficial tool: it uses undocumented GeoGuessr endpoints with your own session cookie, read-only, on your own data, and an undocumented Google Street View thumbnail endpoint. Both can change or stop working without notice.

## Requirements

- macOS or Linux, `uv` 0.12+ (a `mise.toml` pins it), `fzf`
- Claude Code CLI (`claude`) logged in, used headless for the analysis and encyclopedia modes

## Setup

```sh
uv sync
cp .env.example .env
```

Get your `_ncfa` cookie: on geoguessr.com while logged in, open the browser devtools, Application (Chrome) or Storage (Firefox), Cookies, copy the value of `_ncfa` and paste it after `GEOGUESSR_NCFA=` in `.env`. The cookie is a full login to your account, so never commit or share it. Alternative to `.env` on macOS:

```sh
security add-generic-password -s geocoach -a ncfa -w '<cookie value>'
```

Drop community meta PDFs in `metas/` and index them:

```sh
uv run geocoach ingest
```

## Usage

```sh
uv run geocoach            # fzf menu
uv run geocoach analyze --last 10 --mode nmpz
uv run geocoach training --last 10 --mode nm
uv run geocoach encyclopedia br
uv run geocoach stats --last 15
uv run geocoach sync --last 15
```

- **Analyze**: syncs the last N rated duels, picks the rounds where you lost the most points, fetches one view (NMPZ) or two opposite views (No Move) per round, and runs Claude with the images, your guess, the opponent's guess and the matching meta notes. The report is saved under `data/reports/`.
- **Training**: ranks slashP maps by how much of their locations fall in your weak countries.
- **Encyclopedia**: meta sheet for a country from your PDFs plus Claude's knowledge, each fact flagged by source.
- **Stats**: local tables, no Claude call.

Everything lives in `data/` (sqlite database, cached images, rendered PDF pages, reports), which is gitignored.

## MCP server

The analysis runs `claude -p` with a small read-only MCP server attached (`uv run geocoach-mcp`). Tools: `get_analytics`, `get_recent_duels`, `get_duel_round`, `get_weak_spots`, `search_metas`, `get_meta_pages`, `recommend_maps`. You can also add it to an interactive Claude Code session:

```sh
claude mcp add geocoach -- uv run --directory "$PWD" geocoach-mcp
```

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

One small PR per change, CI must be green before merge. Unofficial endpoints are isolated in `gg_api.py` and `panorama.py` so a breakage is contained there.
