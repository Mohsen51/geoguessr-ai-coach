"""Pull recent duels from the feed into the store."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable

from geocoach.duels import Mode, parse_duel
from geocoach.geocode import place_of
from geocoach.gg_api import GeoGuessrClient
from geocoach.store import Store


def sync(
    store: Store,
    client: GeoGuessrClient,
    last_n: int,
    modes: Iterable[Mode],
    max_fetch: int = 200,
    geocoder: Callable[[float, float], tuple[str, str]] = place_of,
    log: Callable[[str], None] = lambda _: None,
) -> int:
    """Walk the feed until last_n rated duels in `modes` are stored. Returns new duels."""
    wanted = {m.value for m in modes}
    backfill_regions(store, geocoder)
    user_id = client.user_id()
    matched = added = 0
    pending: list[str] = []

    def flush() -> None:
        nonlocal matched, added
        if not pending:
            return
        for game in client.duel_results(pending):
            duel = parse_duel(game, user_id, place_geocoder=geocoder)
            store.upsert_duel(duel, json.dumps(game))
            added += 1
            if duel.rated and duel.mode.value in wanted:
                matched += 1
            log(f"stored {duel.mode.value} duel {duel.game_id[:8]} ({matched}/{last_n})")
        pending.clear()

    for game_id in client.iter_duel_ids():
        if matched >= last_n or added + len(pending) >= max_fetch:
            break
        row = store.conn.execute(
            "SELECT mode, rated FROM duels WHERE game_id = ?", (game_id,)
        ).fetchone()
        if row is not None:
            matched += int(row["rated"] and row["mode"] in wanted)
            continue
        pending.append(game_id)
        if len(pending) >= 20:
            flush()
    flush()
    return added


def backfill_regions(store: Store, geocoder: Callable[[float, float], tuple[str, str]]) -> int:
    """Fill region columns on rows stored before regions existed. Returns rows updated."""
    n = 0
    with store.conn:
        for r in store.conn.execute(
            "SELECT game_id, n, lat, lng FROM rounds WHERE region = '' AND lat IS NOT NULL"
        ).fetchall():
            store.conn.execute(
                "UPDATE rounds SET region = ? WHERE game_id = ? AND n = ?",
                (geocoder(r["lat"], r["lng"])[1], r["game_id"], r["n"]),
            )
            n += 1
        for g in store.conn.execute(
            "SELECT game_id, n, player_id, lat, lng FROM guesses "
            "WHERE guess_region = '' AND lat IS NOT NULL"
        ).fetchall():
            store.conn.execute(
                "UPDATE guesses SET guess_region = ? WHERE game_id = ? AND n = ? AND player_id = ?",
                (geocoder(g["lat"], g["lng"])[1], g["game_id"], g["n"], g["player_id"]),
            )
            n += 1
    return n
