import json

import httpx
import pytest
import respx

from geocoach import config, examples
from geocoach.panorama import THUMB_URL, ViewFetcher
from geocoach.store import Store

PANO = "FvgH8Prb3g9q16A6jg0ecw"
VIEW_URL = (
    f"https://www.google.com/maps/@-1.67,-79.98,3a,90y,224.78h,88.98t/data=!3m6!1e1!3m4!1s{PANO}"
    "!2e0!7i13312!8i6656"
)
PANO_URL = (
    f"https://www.google.com/maps/@?api=1&map_action=pano&pano={PANO}&viewpoint=-64.6,-62.6"
    "&heading=343.3&pitch=-2.9&fov=133&shorturl=1"
)


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())


def test_parse_streetview_urls():
    assert examples.parse_streetview_url(VIEW_URL) == (PANO, 224.78, pytest.approx(1.02))
    assert examples.parse_streetview_url(PANO_URL) == (PANO, 343.3, -2.9)
    assert examples.parse_streetview_url("https://www.google.com/maps/place/Kuching") is None


def test_links_in_text():
    text = (
        "Poles like [this](https://maps.app.goo.gl/abc123) and https://goo.gl/maps/XyZ9, "
        "or https://www.google.com/maps/@1,2,3a,90y,1h,90t/data=!1sAAAAAAAAAAAAAAAAAAAAAA!2e0."
    )
    assert examples.links_in(text) == [
        "https://maps.app.goo.gl/abc123",
        "https://goo.gl/maps/XyZ9",
        "https://www.google.com/maps/@1,2,3a,90y,1h,90t/data=!1sAAAAAAAAAAAAAAAAAAAAAA!2e0",
    ]


@respx.mock
def test_examples_from_tips_resolve_links_once(tmp_path):
    route = respx.head("https://maps.app.goo.gl/abc123").mock(
        return_value=httpx.Response(302, headers={"location": VIEW_URL})
    )
    respx.head(VIEW_URL).mock(return_value=httpx.Response(200))
    respx.head("https://maps.app.goo.gl/dead").mock(side_effect=httpx.ConnectError("x"))
    tips = [
        "**Holey poles** [here](https://maps.app.goo.gl/abc123) and again https://maps.app.goo.gl/abc123",
        "Nothing [here](https://maps.app.goo.gl/dead)",
        "Pano URL: " + PANO_URL,
    ]
    resolver = examples.LinkResolver(tmp_path / "links.json")
    found = examples.examples_from_tips(tips, resolver)
    resolver.close()
    assert [e.pano_id for e in found] == [PANO]  # same pano via both links, deduped
    assert found[0].tip.startswith("Holey poles here")
    assert route.call_count == 1
    cached = json.loads((tmp_path / "links.json").read_text())
    assert cached["https://maps.app.goo.gl/abc123"] == VIEW_URL
    assert cached["https://maps.app.goo.gl/dead"] == ""
    again = examples.LinkResolver(tmp_path / "links.json")
    assert again.resolve("https://maps.app.goo.gl/abc123") == VIEW_URL
    assert route.call_count == 1


def test_own_round_examples(duel):
    store = Store()
    store.upsert_duel(duel)
    found = examples.own_round_examples(store, "br", 2)
    assert len(found) == 1  # one Brazil round in the fixture
    assert found[0].tip == "Typical road scene in Brazil, Bahia (a round I played)"
    assert "map_action=pano&pano=" in found[0].url


def _jpeg(color: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (8, 8), (color, color, color)).save(buf, "JPEG")
    return buf.getvalue()


@respx.mock
def test_fetch_images_skips_failures_and_blank_thumbnails(tmp_path):
    def reply(req):
        pano = req.url.params["panoid"]
        if pano == PANO:
            return httpx.Response(200, content=_jpeg(120), headers={"content-type": "image/jpeg"})
        if pano == "b" * 22:
            return httpx.Response(200, content=_jpeg(0), headers={"content-type": "image/jpeg"})
        return httpx.Response(404)

    respx.get(THUMB_URL).mock(side_effect=reply)
    exs = [
        examples.Example("a", "u", PANO, 224.78, 1.0),
        examples.Example("black", "u", "b" * 22, 0, 0),
        examples.Example("missing", "u", "x" * 22, 0, 0),
    ]
    logs = []
    kept = examples.fetch_images(exs, ViewFetcher(min_interval_s=0), logs.append)
    assert [e.pano_id for e in kept] == [PANO]
    assert any("blank image" in m for m in logs) and any("HTTP 404" in m for m in logs)
    assert kept[0].image.endswith(f"{PANO}_y225_p+01_f100_1024x768.jpg")


def test_verify_keeps_confirmed_examples(tmp_path):
    exs = [
        examples.Example("holey poles", "u", PANO, 0, 0, image="/p/a.jpg"),
        examples.Example("yellow plates", "u", "b" * 22, 0, 0, image="/p/b.jpg"),
        examples.Example("no image", "u", "c" * 22, 0, 0),
    ]
    seen = {}

    def fake_run(prompt, name, model=None, echo=None, use_mcp=True):
        seen["prompt"] = prompt
        echo(
            '```json\n[{"image": "a.jpg", "ok": true, "note": "pole with holes"},'
            ' {"image": "/p/b.jpg", "ok": false, "note": "no plate visible"}]\n```'
        )
        return tmp_path / "r.md"

    kept = examples.verify(exs, run=fake_run)
    assert [e.image for e in kept] == ["/p/a.jpg"]
    assert kept[0].note == "pole with holes"
    assert exs[1].verified is False and exs[2].verified is None
    assert "claim: holey poles" in seen["prompt"] and "/p/c" not in seen["prompt"]
    assert examples.verify([], run=fake_run) == []


@respx.mock
def test_nearest_panorama_parses_rpc_response():
    msg = [
        None,
        [None, PANO],
        None,
        None,
        None,
        [[None, [[None, None, 5.98, 116.07], None, [31.09, 90, 0]]]],
    ]
    respx.post(examples.SEARCH_URL).mock(return_value=httpx.Response(200, json=[[0], msg]))
    assert examples.nearest_panorama(5.98, 116.07) == (PANO, 5.98, 116.07, 31.09)
    respx.post(examples.SEARCH_URL).mock(return_value=httpx.Response(200, json=[[5]]))
    assert examples.nearest_panorama(0, 0) is None
    respx.post(examples.SEARCH_URL).mock(return_value=httpx.Response(400))
    with pytest.raises(examples.PanoramaError):
        examples.nearest_panorama(0, 0)


def test_propose_examples_resolves_coordinates(tmp_path):
    def fake_run(prompt, name, model=None, echo=None, use_mcp=True):
        assert "Clue: white pole stickers" in prompt and "in Malaysia" in prompt
        echo(
            '[{"lat": 2.3, "lng": 111.8, "heading": 90, "claim": "white sticker near Sibu"},'
            ' {"lat": 0, "lng": 0, "heading": 0, "claim": "ocean"}, {"bad": 1}]'
        )
        return tmp_path / "r.md"

    def fake_search(lat, lng):
        return (PANO, lat, lng, 10.0) if lat else None

    logs = []
    found = examples.propose_examples(
        "white pole stickers", "my", run=fake_run, search=fake_search, log=logs.append
    )
    assert [e.pano_id for e in found] == [PANO]
    assert found[0].tip == "white sticker near Sibu (proposed by Claude)"
    assert found[0].heading == 90 and "pano=" + PANO in found[0].url
    assert logs == ["no coverage within 500 m of 0.0000, 0.0000"]
    assert examples.parse_proposals("no json here") == []
