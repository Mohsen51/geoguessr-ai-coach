import asyncio
import json

import pytest

from geocoach import config, mcp_server
from geocoach.duels import Mode, parse_duel
from geocoach.store import Store


@pytest.fixture
def seeded(duel_page_props, tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    store = Store()
    store.upsert_duel(
        parse_duel(duel_page_props),
        {(1, "me-0001"): "ar", (1, "opp-0002"): "br", (2, "me-0001"): "se", (2, "opp-0002"): "fi"},
    )
    monkeypatch.setattr(mcp_server, "_store", store)
    return store


def test_parse_modes():
    assert mcp_server.parse_modes("all") == [Mode.NM, Mode.NMPZ]
    assert mcp_server.parse_modes("NMPZ") == [Mode.NMPZ]


def test_get_analytics_local(seeded):
    out = mcp_server.get_analytics(5, "nmpz")
    assert out["source"] == "local"
    assert out["duels"] == 1 and out["rounds"] == 2
    assert out["weak_countries"][0]["country"] == "br"
    assert out["rating_trend"][0]["my_rating"] == 905


def test_get_recent_duels_and_round(seeded):
    duels = mcp_server.get_recent_duels(5, "all")
    assert len(duels) == 1
    assert duels[0]["lost_on_country"] == 2
    gid = duels[0]["game_id"]
    rnd = mcp_server.get_duel_round(gid, 1)
    assert rnd["country"] == "br" and rnd["guess_country"] == "ar"
    assert rnd["images"] == []
    assert "error" in mcp_server.get_duel_round("nope", 1)


def test_get_weak_spots_lists_images(seeded):
    config.PANOS_DIR.mkdir(parents=True)
    (config.PANOS_DIR / "RPS4EBhBrRCCyP1TJtKVuw_y172_p+00_f100_1024x768.jpg").write_bytes(b"x")
    spots = mcp_server.get_weak_spots(5, "nmpz", max_rounds=1)
    assert spots[0]["n"] == 1
    assert len(spots[0]["images"]) == 1


def test_tools_registered_and_callable(seeded):
    names = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert names == {
        "get_analytics",
        "get_recent_duels",
        "get_duel_round",
        "get_weak_spots",
        "search_metas",
        "get_meta_pages",
    }
    result = asyncio.run(mcp_server.server.call_tool("get_recent_duels", {"n": 3, "mode": "nmpz"}))
    first = json.loads(result.content[0].text)
    assert first["mode"] == "nmpz" and first["rounds"] == 2
