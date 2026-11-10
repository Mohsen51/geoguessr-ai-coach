import json

from geocoach.duels import Mode
from geocoach.store import Store
from geocoach.sync import sync


class FakeClient:
    def __init__(self, summaries: dict[str, dict]):
        self.summaries = summaries
        self.fetched: list[str] = []

    def iter_duel_ids(self):
        yield from self.summaries

    def duel_summary(self, game_id):
        self.fetched.append(game_id)
        return self.summaries[game_id]


def make_summary(base: dict, game_id: str, nmpz: bool, rated: bool = True) -> dict:
    s = json.loads(json.dumps(base))
    s["game"]["gameId"] = game_id
    s["game"]["options"]["isRated"] = rated
    s["game"]["options"]["movementOptions"]["forbidRotating"] = nmpz
    s["game"]["options"]["movementOptions"]["forbidZooming"] = nmpz
    return s


def fake_geocoder(lat, lng):
    return "ar" if lat < 0 else "se"


def test_sync_stops_after_last_n_matching(duel_page_props):
    client = FakeClient(
        {
            "g1": make_summary(duel_page_props, "g1", nmpz=True),
            "g2": make_summary(duel_page_props, "g2", nmpz=False),
            "g3": make_summary(duel_page_props, "g3", nmpz=True),
            "g4": make_summary(duel_page_props, "g4", nmpz=True),
        }
    )
    store = Store()
    added = sync(store, client, last_n=2, modes=[Mode.NMPZ], geocoder=fake_geocoder)

    assert added == 3
    assert client.fetched == ["g1", "g2", "g3"]
    assert {r["game_id"] for r in store.recent_duels(5, [Mode.NMPZ])} == {"g1", "g3"}
    row = store.conn.execute(
        "SELECT guess_country FROM guesses WHERE game_id='g1' AND is_me=1 AND n=1"
    ).fetchone()
    assert row["guess_country"] == "ar"


def test_sync_skips_stored_duels(duel_page_props):
    summaries = {"g1": make_summary(duel_page_props, "g1", nmpz=True)}
    store = Store()
    sync(store, FakeClient(summaries), 1, [Mode.NMPZ], geocoder=fake_geocoder)
    client = FakeClient(summaries)
    added = sync(store, client, 1, [Mode.NMPZ], geocoder=fake_geocoder)
    assert added == 0
    assert client.fetched == []
