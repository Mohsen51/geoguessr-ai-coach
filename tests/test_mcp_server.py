import asyncio
import json

import pytest

from geocoach import config, mcp_server
from geocoach.duels import Mode
from geocoach.store import Store


@pytest.fixture
def seeded(duel, tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    store = Store()
    store.upsert_duel(duel)
    monkeypatch.setattr(mcp_server, "_store", store)
    return store


def test_parse_modes():
    assert mcp_server.parse_modes("all") == [Mode.NM, Mode.NMPZ]
    assert mcp_server.parse_modes("NMPZ") == [Mode.NMPZ]


def test_get_analytics_local(seeded, monkeypatch):
    monkeypatch.setattr(mcp_server, "ranked_snapshot", lambda: None)
    out = mcp_server.get_analytics(5, "nmpz")
    assert out["source"] == "local" and out["geoguessr_ranked"] is None
    assert out["duels"] == 1 and out["rounds"] == 5
    assert out["weak_countries"][0]["country"] == "in"
    assert out["rating_trend"][0]["my_rating"] == 862


def test_get_recent_duels_and_round(seeded):
    duels = mcp_server.get_recent_duels(5, "all")
    assert len(duels) == 1
    assert duels[0]["lost_on_country"] == 2 and duels[0]["lost_on_pin"] == 1
    gid = duels[0]["game_id"]
    rnd = mcp_server.get_duel_round(gid, 1)
    assert rnd["country"] == "in" and rnd["guess_country"] == "bd"
    assert rnd["images"] == []
    assert "error" in mcp_server.get_duel_round("nope", 1)


def test_get_weak_spots_lists_images(seeded):
    config.PANOS_DIR.mkdir(parents=True)
    (config.PANOS_DIR / "PANO1xxxxxxxxxxxxxxxxx_y116_p+00_f100_1024x768.jpg").write_bytes(b"x")
    spots = mcp_server.get_weak_spots(5, "nmpz", max_rounds=1, focus="all")
    assert spots[0]["n"] == 1
    assert len(spots[0]["images"]) == 1
    assert mcp_server.get_weak_spots(5, "nmpz", max_rounds=1)[0]["n"] == 5  # region focus


def test_tools_registered_and_callable(seeded):
    names = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert names == {
        "get_analytics",
        "get_recent_duels",
        "get_duel_round",
        "get_weak_spots",
        "search_metas",
        "get_meta_pages",
        "get_plonkit",
        "recommend_maps",
    }
    result = asyncio.run(mcp_server.server.call_tool("get_recent_duels", {"n": 3, "mode": "nmpz"}))
    first = json.loads(result.content[0].text)
    assert first["mode"] == "nmpz" and first["rounds"] == 5


def test_recommend_maps_uses_weak_countries(seeded, monkeypatch):
    maps = [
        {"mapName": "A Balanced Brazil", "mapId": "a" * 24, "category": "Country",
         "locationCount": 50000, "likes": 1, "plays": 1,
         "countryDistribution": [{"code": "BR", "count": 50000, "name": "Brazil"}]},
        {"mapName": "A Balanced Chile", "mapId": "b" * 24, "category": "Country",
         "locationCount": 50000, "likes": 1, "plays": 1,
         "countryDistribution": [{"code": "CL", "count": 50000, "name": "Chile"}]},
    ]  # fmt: skip
    monkeypatch.setattr(mcp_server.slashp, "load_maps", lambda: maps)
    assert [m["name"] for m in mcp_server.recommend_maps()] == ["A Balanced Brazil"]
    assert [m["name"] for m in mcp_server.recommend_maps(["cl"])] == ["A Balanced Chile"]


def test_get_analytics_with_ranked_snapshot(seeded, monkeypatch):
    snap = {"rating": 850, "mode_ratings": {"nmpzDuels": 725}, "worst_countries": ["co"]}
    monkeypatch.setattr(mcp_server, "ranked_snapshot", lambda: snap)
    out = mcp_server.get_analytics(5, "nmpz")
    assert out["source"] == "local+geoguessr"
    assert out["geoguessr_ranked"]["mode_ratings"]["nmpzDuels"] == 725


def test_ranked_snapshot_without_cookie(monkeypatch):
    monkeypatch.setattr(mcp_server, "_ranked_cache", None)
    monkeypatch.delenv("GEOGUESSR_NCFA", raising=False)
    monkeypatch.setattr(config, "_keychain_cookie", lambda: None)
    monkeypatch.setattr(config, "ROOT", config.DATA_DIR)
    assert mcp_server.ranked_snapshot() is None


def test_get_plonkit_sections_and_query(seeded):
    from pathlib import Path

    from geocoach import plonkit

    guide = plonkit.parse_preloaded(
        (Path(__file__).parent / "fixtures" / "plonkit_guide.html").read_text()
    )
    plonkit.ingest_guide(seeded, "testland", "TL", guide)
    out = mcp_server.get_plonkit("TL")
    assert [s["section"] for s in out["sections"]][0] == "Identifying Testland"
    hits = mcp_server.get_plonkit("tl", query="poles")
    assert hits["tips"] and "Concrete poles" in hits["tips"][0]
