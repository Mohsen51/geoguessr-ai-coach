import json

from conftest import fake_place_geocoder

from geocoach.duels import Mode
from geocoach.store import Store
from geocoach.sync import sync


class FakeClient:
    def __init__(self, games: dict[str, dict]):
        self.games = games
        self.batches: list[list[str]] = []

    def user_id(self):
        return "me-0001"

    def iter_duel_ids(self):
        yield from self.games

    def duel_results(self, ids):
        self.batches.append(list(ids))
        return [self.games[i] for i in ids]


def make_game(base: dict, game_id: str, mode: str = "NoMoveZoomPan", rated=True) -> dict:
    g = json.loads(json.dumps(base))
    g["gameId"] = game_id
    g["options"]["isRated"] = rated
    g["options"]["mode"] = mode
    return g


def test_sync_batches_and_stops_after_last_n(duel_game):
    client = FakeClient(
        {
            "g1": make_game(duel_game, "g1"),
            "g2": make_game(duel_game, "g2", mode="Standard"),
            "g3": make_game(duel_game, "g3"),
            "g4": make_game(duel_game, "g4"),
        }
    )
    store = Store()
    added = sync(store, client, last_n=2, modes=[Mode.NMPZ], geocoder=fake_place_geocoder)
    assert added == 4  # ids are batched, so the whole batch is fetched once
    assert client.batches == [["g1", "g2", "g3", "g4"]]
    assert {r["game_id"] for r in store.recent_duels(5, [Mode.NMPZ])} == {"g1", "g3", "g4"}
    row = store.conn.execute(
        "SELECT guess_country FROM guesses WHERE game_id='g1' AND is_me=1 AND n=1"
    ).fetchone()
    assert row["guess_country"] == "bd"
    assert json.loads(store.conn.execute("SELECT raw FROM duels WHERE game_id='g1'").fetchone()[0])


def test_sync_skips_stored_duels(duel_game):
    games = {"g1": make_game(duel_game, "g1")}
    store = Store()
    sync(store, FakeClient(games), 1, [Mode.NMPZ], geocoder=fake_place_geocoder)
    client = FakeClient(games)
    assert sync(store, client, 1, [Mode.NMPZ], geocoder=fake_place_geocoder) == 0
    assert client.batches == []
