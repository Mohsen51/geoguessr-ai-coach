from geocoach.duels import Mode
from geocoach.store import Store


def test_upsert_and_read_back(duel):
    store = Store()
    store.upsert_duel(duel, raw='{"x":1}')
    assert store.has_duel(duel.game_id)
    assert len(store.rounds_for(duel.game_id)) == 5
    guesses = store.guesses_for(duel.game_id)
    assert len(guesses) == 10
    mine_r1 = next(g for g in guesses if g["is_me"] and g["n"] == 1)
    assert mine_r1["guess_country"] == "bd" and mine_r1["time_spent_ms"] == 14281
    assert store.results_for(duel.game_id)[0]["my_health_after"] == 2941
    row = store.conn.execute("SELECT raw, map_name FROM duels").fetchone()
    assert row["raw"] == '{"x":1}' and row["map_name"] == "Test Map"


def test_upsert_is_idempotent(duel):
    store = Store()
    store.upsert_duel(duel)
    store.upsert_duel(duel)
    assert store.conn.execute("SELECT count(*) FROM rounds").fetchone()[0] == 5


def test_recent_duels_filters_mode_and_rated(duel):
    store = Store()
    store.upsert_duel(duel)
    assert len(store.recent_duels(5, [Mode.NMPZ])) == 1
    assert len(store.recent_duels(5, [Mode.NM])) == 0
    store.conn.execute("UPDATE duels SET rated = 0")
    assert len(store.recent_duels(5, [Mode.NMPZ])) == 0
    assert len(store.recent_duels(5, [Mode.NMPZ], rated_only=False)) == 1
