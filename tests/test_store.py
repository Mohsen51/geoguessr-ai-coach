from geocoach.duels import Mode, parse_duel
from geocoach.store import Store


def test_upsert_and_read_back(duel_page_props):
    store = Store()
    duel = parse_duel(duel_page_props)
    store.upsert_duel(duel, {(1, "me-0001"): "ar"})

    assert store.has_duel(duel.game_id)
    assert len(store.rounds_for(duel.game_id)) == 2
    guesses = store.guesses_for(duel.game_id)
    assert len(guesses) == 4
    mine_r1 = next(g for g in guesses if g["is_me"] and g["n"] == 1)
    assert mine_r1["guess_country"] == "ar"
    assert store.results_for(duel.game_id)[1]["my_health_after"] == 3900


def test_upsert_is_idempotent(duel_page_props):
    store = Store()
    duel = parse_duel(duel_page_props)
    store.upsert_duel(duel)
    store.upsert_duel(duel)
    assert store.conn.execute("SELECT count(*) FROM rounds").fetchone()[0] == 2


def test_recent_duels_filters_mode_and_rated(duel_page_props):
    store = Store()
    duel = parse_duel(duel_page_props)
    store.upsert_duel(duel)
    assert len(store.recent_duels(5, [Mode.NMPZ])) == 1
    assert len(store.recent_duels(5, [Mode.NM])) == 0
    duel_page_props["game"]["options"]["isRated"] = False
    duel_page_props["game"]["gameId"] = "other"
    store.upsert_duel(parse_duel(duel_page_props))
    assert len(store.recent_duels(5, [Mode.NMPZ])) == 1
    assert len(store.recent_duels(5, [Mode.NMPZ], rated_only=False)) == 2
