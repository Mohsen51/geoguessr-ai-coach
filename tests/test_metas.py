import pymupdf
import pytest

from geocoach import metas
from geocoach.store import Store

PAGE1 = (
    "Brazil\n\nBrazil has a distinctive short Gen 3 camera with a visible antenna.\n\n"
    "Road lines are yellow centre lines and the soil is red in the interior."
)
PAGE2 = (
    "Argentina and Uruguay\n\nUruguay uses yellow licence plates while Argentina has "
    "black and white plates. Confusing Argentina with Uruguay is common."
)


@pytest.fixture
def metas_dir(tmp_path):
    doc = pymupdf.open()
    for text in (PAGE1, PAGE2):
        page = doc.new_page()
        page.insert_text((50, 72), text, fontsize=11)
    doc.save(tmp_path / "south-america.pdf")
    doc.close()
    return tmp_path


def test_tag_countries_word_boundaries():
    assert metas.tag_countries("Niger is not Nigeria") == ["ng", "ne"]
    assert metas.tag_countries("the USA and the UK") == ["us", "gb"]
    assert metas.tag_countries("nothing here") == []


def test_tag_countries_demonyms_and_abbreviations():
    assert metas.tag_countries("Brazilian poles and Russian cars") == ["br", "ru"]
    assert metas.tag_countries("US rumble strips") == ["us"]
    assert metas.tag_countries("tell us more") == []
    assert metas.doc_tags("The Complete Guide To Russian Car Metas.pdf") == ["ru"]


def test_chunk_text_splits_on_paragraphs():
    text = "\n\n".join(["para " * 50] * 5)
    chunks = metas.chunk_text(text, size=600)
    assert len(chunks) >= 3
    assert all(len(c) <= 600 for c in chunks)


def test_ingest_search_and_pages(metas_dir):
    store = Store()
    assert metas.ingest(store, metas_dir) == 1
    assert metas.ingest(store, metas_dir) == 0

    hits = metas.search(store, "yellow plates")
    assert hits and hits[0]["page"] == 2
    assert metas.search(store, "yellow", country="br")[0]["page"] == 1
    assert metas.pages_for_country(store, "uy") == [("south-america.pdf", 2)]
    assert [c["page"] for c in metas.chunks_for_country(store, "ar")] == [2]


def test_ingest_tags_image_only_pages_from_filename(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "Look at the pole shapes below.", fontsize=11)
    doc.new_page()  # image-only page, no text
    doc.save(tmp_path / "Brazilian Poles.pdf")
    doc.close()
    store = Store()
    metas.ingest(store, tmp_path)
    assert metas.pages_for_country(store, "br") == [
        ("Brazilian Poles.pdf", 1),
        ("Brazilian Poles.pdf", 2),
    ]
    assert [c["page"] for c in metas.chunks_for_country(store, "br")] == [1]


def test_render_page(metas_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(metas.config, "PAGES_DIR", tmp_path / "pages")
    monkeypatch.setattr(metas.config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(metas.config, "PANOS_DIR", tmp_path / "panos")
    monkeypatch.setattr(metas.config, "REPORTS_DIR", tmp_path / "reports")
    out = metas.render_page("south-america.pdf", 1, metas_dir)
    assert out.exists() and out.suffix == ".png"
