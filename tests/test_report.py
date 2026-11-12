from geocoach import coach, report
from geocoach.duels import Mode
from geocoach.store import Store

ANSWER = """Short intro line.

### Round 5 of duel game-000 (NMPZ)
Bahia clues: dry orange soil. Pin should go to Jequié.

### Round 1 of duel game-0001
India clues: dry scrub, black and white kerb.

## Summary
- Study Bahia versus São Paulo.
"""


def make_bundle(duel, tmp_path):
    store = Store()
    store.upsert_duel(duel)
    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], max_rounds=3)
    bundle.images[(duel.game_id, 5)] = [str(tmp_path / "r5.jpg")]
    return bundle


def test_split_answer_maps_rounds_and_summary(duel, tmp_path):
    bundle = make_bundle(duel, tmp_path)
    sections, intro, closing = report.split_answer(ANSWER, bundle.rounds)
    assert intro == "Short intro line."
    assert sections[("game-0001", 5)].startswith("Bahia clues")
    assert sections[("game-0001", 1)].startswith("India clues")
    assert closing.startswith("## Summary")


def test_split_answer_without_headings_keeps_everything_as_closing(duel, tmp_path):
    bundle = make_bundle(duel, tmp_path)
    sections, intro, closing = report.split_answer("just prose", bundle.rounds)
    assert sections == {} and intro == "" and closing == "just prose"


def test_render_html_places_images_links_and_text(duel, tmp_path):
    bundle = make_bundle(duel, tmp_path)
    page = report.render_html(bundle, ANSWER, "test report")
    assert "<title>test report</title>" in page
    assert "r5.jpg" in page and "Pin should go to Jequié" in page
    assert "map_action=pano&pano=PANO5" in page
    assert "geoguessr.com/duels/game-0001/summary?round=5" in page
    assert "map_action=pano&viewpoint=-23.77710,-48.68416" in page
    assert "Actual:</b> Brazil, Bahia" in page
    assert "No explanation returned" in page  # round 4 has none in ANSWER
    assert "Study Bahia" in page


def test_markdown_keeps_nested_lists_with_three_space_indent():
    text = "1. **Clues:**\n   - red soil\n   - brick\n2. **Pin:** Bahia\n"
    out = report._md(text)
    assert out.count("<li>") == 4 and "<ul>" in out and "<ol>" in out
    assert "- red soil" not in out


def test_write_report_saves_html(duel, tmp_path, monkeypatch):
    from geocoach import config

    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    out = report.write_report(make_bundle(duel, tmp_path), ANSWER, "analysis_nmpz_5")
    assert out.suffix == ".html" and out.read_text().startswith("<!doctype html>")


def test_render_ask_html_lists_verified_examples():
    from geocoach.examples import Example

    ex = Example("Holey poles", "https://maps.example/x", "p" * 22, 0, 0, "/p/a.jpg", True, "seen")
    out = report.render_ask_html("Spain poles?", "**Short answer:** holes.", [ex], "ask")
    assert "<b>Question:</b> Spain poles?" in out
    assert "<strong>Short answer:</strong>" in out
    assert "file:///p/a.jpg" in out and "Open in Street View" in out and "seen" in out
    assert "Street View examples" not in report.render_ask_html("q", "a", [], "ask")
