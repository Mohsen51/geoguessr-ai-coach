"""Read-only MCP server exposing duel analysis and meta search to Claude."""

from __future__ import annotations

import time
from typing import Any

from mcp.server.mcpserver import MCPServer

from geocoach import analysis, config, metas, plonkit, slashp
from geocoach.duels import Mode
from geocoach.store import Store

server = MCPServer(
    "geocoach",
    instructions=(
        "Tools over the user's own GeoGuessr duel history (No Move and NMPZ) and their "
        "community meta PDFs. All data is local and read-only."
    ),
)

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        config.ensure_dirs()
        _store = Store(config.DB_PATH)
    return _store


def parse_modes(mode: str) -> list[Mode]:
    mode = (mode or "all").lower()
    if mode == "all":
        return [Mode.NM, Mode.NMPZ]
    return [Mode(mode)]


_ranked_cache: tuple[float, dict[str, Any]] | None = None


def ranked_snapshot(ttl_s: int = 600) -> dict[str, Any] | None:
    """Rating per mode, division and GeoGuessr's own best/worst countries, if a cookie exists."""
    global _ranked_cache
    if _ranked_cache and time.monotonic() - _ranked_cache[0] < ttl_s:
        return _ranked_cache[1]
    from geocoach.gg_api import GeoGuessrClient

    try:
        client = GeoGuessrClient(config.get_cookie())
    except config.MissingCookieError:
        return None
    try:
        progress = client.ranked_progress(client.user_id())
        stats = client.stats_me()
    except Exception:
        return None
    finally:
        client.close()
    snap = {
        "rating": progress.get("rating"),
        "division": progress.get("divisionName"),
        "mode_ratings": progress.get("gameModeRatings"),
        "best_countries": progress.get("bestCountries"),
        "worst_countries": progress.get("worstCountries"),
        "latest_games_won": progress.get("latestGames"),
        "guessed_first_rate": progress.get("guessedFirstRate"),
        "per_mode_stats": {k: v for k, v in stats.items() if k.startswith("ranked")},
    }
    _ranked_cache = (time.monotonic(), snap)
    return snap


def image_paths(pano_id: str) -> list[str]:
    if not pano_id or not config.PANOS_DIR.exists():
        return []
    return sorted(str(p) for p in config.PANOS_DIR.glob(f"{pano_id}_*.jpg"))


@server.tool(
    description="Aggregated analytics over the last N rated duels: weak countries, "
    "confusions, time buckets, damage by round, rating trend. mode: nm, nmpz or all."
)
def get_analytics(n_games: int = 10, mode: str = "all") -> dict[str, Any]:
    store = get_store()
    modes = parse_modes(mode)
    reviews = analysis.round_reviews(store, n_games, modes)
    ranked = ranked_snapshot()
    return {
        "source": "local+geoguessr" if ranked else "local",
        "geoguessr_ranked": ranked,
        "duels": len({r.game_id for r in reviews}),
        "rounds": len(reviews),
        "weak_countries": analysis.weak_countries(reviews),
        "confusions": analysis.confusions(reviews),
        "time_buckets": analysis.time_buckets(reviews),
        "damage_by_round": analysis.damage_by_round(reviews),
        "rating_trend": analysis.rating_trend(store, n_games, modes),
    }


@server.tool(description="Summaries of the last N rated duels (result, ratings, loss types).")
def get_recent_duels(n: int = 10, mode: str = "all") -> list[dict[str, Any]]:
    store = get_store()
    reviews = analysis.round_reviews(store, n, parse_modes(mode))
    by_game: dict[str, list] = {}
    for r in reviews:
        by_game.setdefault(r.game_id, []).append(r)
    out = []
    for duel in store.recent_duels(n, parse_modes(mode)):
        rows = by_game.get(duel["game_id"], [])
        out.append(
            {
                "game_id": duel["game_id"],
                "played_at_ms": duel["played_at_ms"],
                "mode": duel["mode"],
                "won": duel["won"],
                "my_rating": duel["my_rating"],
                "opp_rating": duel["opp_rating"],
                "rounds": len(rows),
                "lost_on_country": sum(r.loss_type == "lost_on_country" for r in rows),
                "lost_on_pin": sum(r.loss_type == "lost_on_pin" for r in rows),
                "points_lost": sum(r.points_lost for r in rows),
            }
        )
    return out


@server.tool(
    description="Full detail of one round: location, my guess vs opponent, timing, "
    "damage, and paths of rendered Street View images if any."
)
def get_duel_round(game_id: str, round_n: int) -> dict[str, Any]:
    store = get_store()
    row = store.conn.execute("SELECT mode FROM duels WHERE game_id = ?", (game_id,)).fetchone()
    if row is None:
        return {"error": f"unknown duel {game_id}"}
    for r in analysis.round_reviews(store, 10_000, [Mode(row["mode"])]):
        if r.game_id == game_id and r.n == round_n:
            d = r.as_dict()
            d["images"] = image_paths(r.pano_id)
            return d
    return {"error": f"round {round_n} not found in {game_id}"}


@server.tool(description="Worst rounds of the last N duels ranked by points lost times multiplier.")
def get_weak_spots(n_games: int = 10, mode: str = "all", max_rounds: int = 12):
    reviews = analysis.round_reviews(get_store(), n_games, parse_modes(mode))
    picked = analysis.select_rounds_for_review(reviews, max_rounds)
    return [dict(r.as_dict(), images=image_paths(r.pano_id)) for r in picked]


@server.tool(
    description="Full-text search in the community meta PDFs. Optional ISO country filter."
)
def search_metas(query: str, country: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    return metas.search(get_store(), query, country, limit)


@server.tool(
    description="Plonkit guide for an ISO country code: all sections, or only the tips matching "
    "a query (e.g. 'bollard', 'plate', 'pole'). Base knowledge, use before the PDF notes."
)
def get_plonkit(country: str, query: str | None = None, limit: int = 15) -> dict[str, Any]:
    store = get_store()
    if query:
        hits = metas.search(store, query, country, limit)
        tips = [h["text"] for h in hits if h["doc"].startswith(plonkit.DOC_PREFIX)]
        return {"country": country.lower(), "query": query, "tips": tips}
    return {"country": country.lower(), "sections": plonkit.sections_for_country(store, country)}


@server.tool(description="Meta chunks and rendered PDF page images for one ISO country code.")
def get_meta_pages(country: str, limit: int = 6) -> dict[str, Any]:
    store = get_store()
    pages = metas.pages_for_country(store, country, limit)
    return {
        "country": country.lower(),
        "chunks": metas.chunks_for_country(store, country, limit=20),
        "page_images": [str(metas.render_page(doc, page)) for doc, page in pages],
    }


@server.tool(
    description="Training maps from slashP's directory covering the given ISO country codes, "
    "or the weak countries of the last N duels when none are given."
)
def recommend_maps(
    country_codes: list[str] | None = None,
    n_games: int = 10,
    mode: str = "all",
    min_locations: int = 5000,
    include_subdivisions: bool = False,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if country_codes:
        weak = {c.lower(): 1.0 for c in country_codes}
    else:
        reviews = analysis.round_reviews(get_store(), n_games, parse_modes(mode))
        weak = {w["country"]: float(w["points_lost"]) for w in analysis.weak_countries(reviews)}
    if not weak:
        return []
    cats = slashp.DEFAULT_CATEGORIES + (("Subdivision",) if include_subdivisions else ())
    return slashp.recommend(slashp.load_maps(), weak, min_locations, cats, limit)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
