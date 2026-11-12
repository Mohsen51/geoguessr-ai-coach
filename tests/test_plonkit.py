from pathlib import Path

import httpx
import pytest
import respx

from geocoach import config, metas, plonkit
from geocoach.store import Store

FIXTURE = (Path(__file__).parent / "fixtures" / "plonkit_guide.html").read_text()


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())


def test_parse_and_chunks():
    guide = plonkit.parse_preloaded(FIXTURE)
    assert guide["slug"] == "testland" and guide["communityDocs"]
    chunks = plonkit.guide_chunks(guide)
    assert [(c.section, c.subsection) for c in chunks] == [
        ("Identifying Testland", ""),
        ("Identifying Testland", "Poles"),
        ("Regional clues", ""),
        ("Maps and resources", ""),
    ]
    assert chunks[0].image_url == "/images/testland/plate.png"
    assert (
        plonkit.chunk_text(chunks[1]) == "[Identifying Testland > Poles] Concrete poles with holes."
    )


def test_parse_rejects_pages_without_data():
    with pytest.raises(ValueError):
        plonkit.parse_preloaded("<html>Log in</html>")


@respx.mock
def test_sync_indexes_guides_and_skips_unchanged():
    index = [
        {
            "slug": "testland",
            "code": "TL",
            "title": "Testland",
            "updatedAt": "2026-01-01T00:00:00.000Z",
        }
    ]
    respx.get("https://www.plonkit.net/api/guides").mock(
        return_value=httpx.Response(200, json={"success": True, "data": index})
    )
    page = respx.get("https://www.plonkit.net/testland").mock(
        return_value=httpx.Response(200, text=FIXTURE)
    )
    store = Store()
    client = plonkit.PlonkitClient(min_interval_s=0)
    assert plonkit.sync(store, client) == 1
    assert plonkit.sync(store, client) == 0
    assert page.call_count == 1
    sections = plonkit.sections_for_country(store, "tl")
    assert [s["section"] for s in sections] == [
        "Identifying Testland",
        "Regional clues",
        "Maps and resources",
    ]
    assert sections[0]["tips"][0].startswith("Testland uses **yellow** plates")
    hit = metas.search(store, "yellow plates", country="tl")[0]
    assert hit["doc"] == "plonkit:testland" and hit["kind"] == "plonkit"
    # the Spain mention is tagged too, but Testland's own doc ranks first for tl
    assert metas.chunks_for_country(store, "es")[0]["doc"] == "plonkit:testland"
    assert metas.pages_for_country(store, "tl") == []


@respx.mock
def test_images_for_guide_downloads_and_caches():
    respx.get("https://www.plonkit.net/images/testland/plate.png").mock(
        return_value=httpx.Response(200, content=b"png1", headers={"content-type": "image/png"})
    )
    respx.get("https://www.plonkit.net/images/testland/pole.png").mock(
        return_value=httpx.Response(200, content=b"png2", headers={"content-type": "image/png"})
    )
    client = plonkit.PlonkitClient(min_interval_s=0)
    guide = plonkit.parse_preloaded(FIXTURE)
    imgs = plonkit.images_for_guide(client, "testland", guide, limit=5)
    assert [p.name for _, p in imgs] == ["plate.png", "pole.png"]
    assert imgs[0][1].read_bytes() == b"png1"
    assert imgs[0][0].startswith("[Identifying Testland]")
    assert plonkit.images_for_guide(client, "testland", guide, limit=5)[0][1].exists()


def test_guide_for_country():
    index = [{"slug": "united-states", "code": "US"}, {"slug": "spain", "code": "ES"}]
    assert plonkit.guide_for_country(index, "es")["slug"] == "spain"
    assert plonkit.guide_for_country(index, "united-states")["code"] == "US"
    assert plonkit.guide_for_country(index, "xx") is None
    assert metas.doc_tags("plonkit:united-states") == ["us"]


@respx.mock
def test_get_retries_on_429(monkeypatch):
    sleeps = []
    monkeypatch.setattr(plonkit.time, "sleep", sleeps.append)
    route = respx.get("https://www.plonkit.net/api/guides")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(429),
        httpx.Response(200, json={"success": True, "data": []}),
    ]
    client = plonkit.PlonkitClient(min_interval_s=0, retry_base_s=5)
    assert client.guide_index() == []
    assert route.call_count == 3
    assert sleeps == [7.0, 10.0]


@respx.mock
def test_images_stop_at_challenge_page():
    respx.get("https://www.plonkit.net/images/testland/plate.png").mock(
        return_value=httpx.Response(
            403, text="<html>Just a moment...</html>", headers={"content-type": "text/html"}
        )
    )
    client = plonkit.PlonkitClient(min_interval_s=0)
    guide = plonkit.parse_preloaded(FIXTURE)
    assert plonkit.images_for_guide(client, "testland", guide, limit=5) == []


def test_regional_tips_prefer_named_places_then_fill(tmp_path):
    store = Store(tmp_path / "t.db")
    guide = plonkit.parse_preloaded(FIXTURE)
    plonkit.ingest_guide(store, "testland", "TL", guide)
    assert plonkit.regional_tips(store, "tl", ["North Province"]) == ["The north has pine forests."]
    assert plonkit.regional_tips(store, "tl", ["Sao Paulo"]) == ["The north has pine forests."]
    assert plonkit.regional_tips(store, "xx", ["North"]) == []


def test_country_lookups_ignore_neighbour_guides(tmp_path):
    store = Store(tmp_path / "t.db")
    guide = plonkit.parse_preloaded(FIXTURE)
    plonkit.ingest_guide(store, "testland", "TL", guide)
    plonkit.ingest_guide(store, "spain", "ES", guide)  # mentions Spain, tagged tl too
    assert len(plonkit.sections_for_country(store, "es")) == 3
    assert plonkit.sections_for_country(store, "tl")[0]["tips"][0].startswith("Testland uses")
    assert plonkit.regional_tips(store, "tl", []) == ["The north has pine forests."]
