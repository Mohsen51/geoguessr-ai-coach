from pathlib import Path

from geocoach import ask, config, plonkit
from geocoach.store import Store

FIXTURE = (Path(__file__).parent / "fixtures" / "plonkit_guide.html").read_text()


def test_keywords_drop_country_names_and_stopwords():
    words = ask.keywords("How to understand the difference between mainland Malaysia and Borneo?")
    assert words == ["borneo"]


def test_prepare_question_inlines_country_knowledge(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    store = Store(tmp_path / "t.db")
    plonkit.ingest_guide(store, "spain", "ES", plonkit.parse_preloaded(FIXTURE))
    bundle = ask.prepare_question(store, "What are the plates and poles like in Spain?")
    assert bundle.countries == ["es"]
    assert "Question: What are the plates and poles like in Spain?" in bundle.prompt
    assert "### Spain (es)" in bundle.prompt
    assert "Plonkit tips matching the question:" in bundle.prompt
    assert "Concrete poles with holes." in bundle.prompt
    assert "- Plonkit regional clues:\n  * The north has pine forests." in bundle.prompt


def test_prepare_question_without_country_searches_everything(tmp_path):
    store = Store(tmp_path / "t.db")
    plonkit.ingest_guide(store, "spain", "ES", plonkit.parse_preloaded(FIXTURE))
    bundle = ask.prepare_question(store, "Which guides mention holes in poles?")
    assert bundle.countries == []
    assert "Best matches in plonkit and my PDFs" in bundle.prompt
    assert "Concrete poles with holes." in bundle.prompt
    empty = ask.prepare_question(store, "zebra crossings")
    assert "nothing indexed matches" in empty.prompt
