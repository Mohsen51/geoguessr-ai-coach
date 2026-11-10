"""Pull recent duels from the feed into the store."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from geocoach.duels import Duel, Mode, parse_duel
from geocoach.geocode import country_of
from geocoach.gg_api import GeoGuessrClient
from geocoach.store import Store


def guess_countries(duel: Duel, geocoder: Callable[[float, float], str] = country_of):
    return {(g.round_number, g.player_id): geocoder(g.lat, g.lng) for g in duel.guesses}


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
    wanted = set(modes)
    matched = added = fetched = 0
    for game_id in client.iter_duel_ids():
        if fetched >= max_fetch or matched >= last_n:
            break
        if store.has_duel(game_id):
            row = store.conn.execute(
                "SELECT mode, rated FROM duels WHERE game_id = ?", (game_id,)
            ).fetchone()
            matched += int(row["rated"] and Mode(row["mode"]) in wanted)
            continue
        fetched += 1
        duel = parse_duel(client.duel_summary(game_id))
        store.upsert_duel(duel, guess_countries(duel, geocoder))
        added += 1
        if duel.rated and duel.mode in wanted:
            matched += 1
        log(f"stored {duel.mode.value} duel {game_id[:8]} ({matched}/{last_n})")
    return added
