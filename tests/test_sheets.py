import json
from pathlib import Path

from geocoach import plonkit, sheets

FIXTURE = (Path(__file__).parent / "fixtures" / "plonkit_guide.html").read_text()


def test_render_sheet_is_deterministic_text_only():
    guide = plonkit.parse_preloaded(FIXTURE)
    md = sheets.render_sheet(guide)
    assert md.startswith("# Testland (tl)\n")
    assert "https://www.plonkit.net/testland" in md and "CC BY-NC-SA 4.0" in md
    assert "## Identifying Testland" in md and "### Poles" in md
    assert "- Testland uses **yellow** plates. NOTE: Neighbouring Spain uses white plates." in md
    assert "## Maps and resources\n\nPlay the Testland map." in md
    assert "## Community documents\n\n- [Testland doc]" in md
    assert "imageUrl" not in md and "summary.png" not in md
    assert sheets.render_sheet(guide) == md


def test_build_all_writes_only_coded_guides(tmp_path):
    guides = tmp_path / "guides"
    guides.mkdir()
    guide = plonkit.parse_preloaded(FIXTURE)
    (guides / "testland.json").write_text(json.dumps(guide))
    (guides / "maps.json").write_text(json.dumps({**guide, "code": None, "slug": "maps"}))
    out = tmp_path / "encyclopedia"
    written = sheets.build_all(out, guides)
    assert [p.name for p in written] == ["tl.md"]
    assert sheets.available_codes(out) == ["tl"]
    assert sheets.read_sheet("TL", out).startswith("# Testland")
    assert sheets.read_sheet("xx", out) is None
    mtime = (out / "tl.md").stat().st_mtime_ns
    sheets.build_all(out, guides)
    assert (out / "tl.md").stat().st_mtime_ns == mtime  # unchanged content is not rewritten
