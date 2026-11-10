import httpx
import pytest
import respx

from geocoach import config, panorama
from geocoach.duels import Mode
from geocoach.panorama import THUMB_URL, PanoramaError, ViewFetcher, headings_for

JPEG = b"\xff\xd8\xff\xe0fakejpeg"


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())


def test_headings_for_modes():
    assert headings_for(Mode.NMPZ, 172.4) == [(172, 100)]
    assert headings_for("nm", 300) == [(300, 120), (120, 120)]
    assert headings_for(Mode.NM, 10, full=True) == [(10, 120), (130, 120), (250, 120)]
    assert headings_for(Mode.NMPZ, -10) == [(350, 100)]


@respx.mock
def test_fetch_view_params_and_cache():
    route = respx.get(THUMB_URL).mock(
        return_value=httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
    )
    f = ViewFetcher(min_interval_s=0)
    out = f.fetch_view("PANO1", yaw=49, pitch=0, fov=100)
    assert out.read_bytes() == JPEG
    assert out.name == "PANO1_y049_p+00_f100_1024x768.jpg"
    q = route.calls[0].request.url.params
    assert q["panoid"] == "PANO1" and q["yaw"] == "49" and q["thumbfov"] == "100"
    assert route.calls[0].request.headers["user-agent"] == panorama.USER_AGENT

    f.fetch_view("PANO1", yaw=49, pitch=0, fov=100)
    assert route.call_count == 1


@respx.mock
def test_views_for_round_nm_fetches_two():
    respx.get(THUMB_URL).mock(
        return_value=httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
    )
    paths = ViewFetcher(min_interval_s=0).views_for_round("PANO2", 90, Mode.NM)
    assert [p.name for p in paths] == [
        "PANO2_y090_p+00_f120_1024x768.jpg",
        "PANO2_y270_p+00_f120_1024x768.jpg",
    ]


@respx.mock
def test_fetch_view_raises_on_403():
    respx.get(THUMB_URL).mock(return_value=httpx.Response(403, json={"error": "denied"}))
    with pytest.raises(PanoramaError, match="403"):
        ViewFetcher(min_interval_s=0).fetch_view("PANO3", yaw=0)
