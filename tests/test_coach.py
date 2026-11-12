import pytest

from geocoach import coach, config
from geocoach.duels import Mode
from geocoach.panorama import PanoramaError
from geocoach.store import Store


class FakeFetcher:
    def __init__(self, fail_for: set[str] = frozenset()):
        self.fail_for = fail_for
        self.calls = []

    def views_for_round(self, pano_id, heading, mode, pitch=0, full=False):
        self.calls.append((pano_id, round(heading), mode, full))
        if pano_id in self.fail_for:
            raise PanoramaError("HTTP 403")
        return [config.PANOS_DIR / f"{pano_id}_y{round(heading):03d}.jpg"]


@pytest.fixture
def store(duel, tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    s = Store()
    s.upsert_duel(duel)
    return s


def test_prepare_analysis_builds_prompt_with_images(store):
    fetcher = FakeFetcher()
    bundle = coach.prepare_analysis(store, fetcher, 5, [Mode.NMPZ], max_rounds=5)
    assert [r.n for r in bundle.rounds] == [5, 1, 4]  # pin loss first with the region focus
    assert fetcher.calls[1] == ("PANO1xxxxxxxxxxxxxxxxx", 116, "nmpz", False)
    p = bundle.prompt
    assert "rating about 862" in p and "plays NMPZ" in p and "regional guessing" in p
    assert "Actual: India (in)" in p and "My guess: Bangladesh" in p
    assert "Actual: Brazil (br), Bahia" in p and "My guess: Brazil, Sao Paulo" in p
    assert "PANO1xxxxxxxxxxxxxxxxx_y116.jpg" in p
    assert "India (3059 pts over 1 rounds)" in p
    assert "Weakest regions (country right, pin wrong): Bahia (Brazil, 2679 pts" in p
    assert "Bangladesh at 23.861" in p and "Opponent: India at 22.709" in p
    all_rounds = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], focus="all").rounds
    assert [r.n for r in all_rounds] == [1, 5, 4]


def test_prepare_analysis_includes_clue_cards(store, tmp_path):
    calls = []

    def fetch(cc):
        calls.append(cc)
        return [{"type": "poles", "title": "Ladder poles", "description": "Concrete steps.",
                 "regions": [{"name": "North"}]}]  # fmt: skip

    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], 1, clue_fetch=fetch, focus="all")
    assert calls == ["in"]
    assert "poles: Ladder poles. Concrete steps. (regions: North)" in bundle.prompt
    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], 1, clue_fetch=fetch, focus="all")
    assert calls == ["in"]  # second call served from the disk cache


def test_prepare_analysis_survives_image_failure(store):
    logs = []
    fetcher = FakeFetcher(fail_for={"PANO1xxxxxxxxxxxxxxxxx"})
    bundle = coach.prepare_analysis(store, fetcher, 5, [Mode.NMPZ], log=logs.append)
    assert bundle.images[(bundle.rounds[0].game_id, 1)] == []
    assert "No image available" in bundle.prompt
    assert logs and "403" in logs[0]


def test_prepare_analysis_attaches_meta_page_image(store, tmp_path, monkeypatch):
    import pymupdf

    metas_dir = tmp_path / "metas"
    metas_dir.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "Indian poles are concrete.", fontsize=11)
    doc.save(metas_dir / "India guide.pdf")
    doc.close()
    from geocoach import metas

    metas.ingest(store, metas_dir)
    monkeypatch.setattr(metas.config, "METAS_DIR", metas_dir)
    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], max_rounds=1, focus="all")
    assert "Meta PDF page(s) about this country" in bundle.prompt
    assert "India guide_p001.png" in bundle.prompt


def test_prepare_analysis_uses_plonkit_tips_first(store):
    from geocoach import plonkit

    guide = plonkit.parse_preloaded(
        (
            __import__("pathlib").Path(__file__).parent / "fixtures" / "plonkit_guide.html"
        ).read_text()
    )
    plonkit.ingest_guide(store, "india", "IN", guide)
    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], max_rounds=2)
    assert "Plonkit, identifying India" in bundle.prompt  # round 1 missed the country
    assert "Testland uses **yellow** plates" in bundle.prompt
    assert (
        bundle.prompt.index("Plonkit, identifying") < bundle.prompt.index("Bonus notes")
        if "Bonus notes" in bundle.prompt
        else True
    )


def test_prepare_analysis_inlines_plonkit_regional_tips(store):
    from geocoach import plonkit

    guide = plonkit.parse_preloaded(
        (
            __import__("pathlib").Path(__file__).parent / "fixtures" / "plonkit_guide.html"
        ).read_text()
    )
    plonkit.ingest_guide(store, "brazil", "BR", guide)
    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], max_rounds=6, focus="region")
    assert "Plonkit regional clues for Brazil (actual region Bahia):" in bundle.prompt
    assert "* The north has pine forests." in bundle.prompt
    assert "get_plonkit('br'" not in bundle.prompt  # no dividers, so no outline line
    assert "use them, and call\nget_plonkit(country, query) when a clue you see" in bundle.prompt
