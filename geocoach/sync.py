"""Pull recent duels from the feed into the store."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable

from geocoach.duels import Mode, parse_duel
from geocoach.geocode import country_of
from geocoach.gg_api import GeoGuessrClient
from geocoach.store import Store


def sync(
    store: Store,
    client: GeoGuessrClient,
    last_n: int,
    modes: Iterable[Mode],
    max_fetch: int = 200,
    geocoder: Callable[[float, float], str] = country_of,
    log: Callable[[str], None] = lambda _: None,
) -> int:
    """Walk the feed until last_n rated duels in `modes` are stored. Returns new duels."""
    wanted = {m.value for m in modes}
    user_id = client.user_id()
    matched = added = 0
    pending: list[str] = []

    def flush() -> None:
        nonlocal matched, added
        if not pending:
            return
        for game in client.duel_results(pending):
            duel = parse_duel(game, user_id, geocoder)
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
