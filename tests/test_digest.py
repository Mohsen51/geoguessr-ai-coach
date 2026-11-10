import pymupdf
import pytest

from geocoach import config, digest, metas
from geocoach.store import Store


@pytest.fixture
def metas_dir(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    d = tmp_path / "metas"
    d.mkdir()
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((50, 72), "Square poles", fontsize=11)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    pix.clear_with(120)
    p1.insert_image(pymupdf.Rect(50, 100, 150, 200), pixmap=pix)
    p2 = doc.new_page()
    p2.insert_text((50, 72), "\n".join(["Long text page with many words."] * 16), fontsize=11)
    p2.insert_image(pymupdf.Rect(50, 300, 150, 400), pixmap=pix)
    doc.new_page().insert_text((50, 72), "No image here", fontsize=11)
    doc.save(d / "Brazilian Poles.pdf")
    doc.close()
    return d


def test_pages_to_digest_selects_image_pages_with_little_text(metas_dir):
    store = Store()
    metas.ingest(store, metas_dir)
    assert digest.pages_to_digest(store, metas_dir) == [("Brazilian Poles.pdf", 1)]
    assert digest.pages_to_digest(store, metas_dir, doc_filter="nothing") == []


def test_parse_digest_output_tolerates_fences():
    text = 'Here you go:\n```json\n[{"page": "/a.png", "description": "A square pole."}]\n```'
    assert digest.parse_digest_output(text) == {"/a.png": "A square pole."}
    assert digest.parse_digest_output("nonsense") == {}


def test_digest_stores_descriptions_and_is_idempotent(metas_dir):
    store = Store()
    metas.ingest(store, metas_dir)
    prompts = []

    def fake_run(prompt, name, model=None, echo=None, use_mcp=True):
        prompts.append(prompt)
        path = [line[2:] for line in prompt.splitlines() if line.startswith("- /")][0]
        echo(f'[{{"page": "{path}", "description": "Map of Bahia with square poles in red."}}]')
        return config.REPORTS_DIR / "x.md"

    assert digest.digest(store, metas_dir, run=fake_run) == 1
    assert use_mcp_false(prompts)
    row = store.conn.execute("SELECT text, kind, country_tags FROM meta_chunks WHERE kind='digest'")
    text, kind, tags = row.fetchone()
    assert "Bahia" in text and kind == "digest" and tags == "br"
    assert metas.search(store, "Bahia")[0]["page"] == 1
    assert digest.digest(store, metas_dir, run=fake_run) == 0
    assert len(prompts) == 1


def use_mcp_false(prompts):
    return bool(prompts) and "JSON only" in prompts[0]


def test_store_migration_adds_kind_column(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE meta_docs (doc TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
        "pages INTEGER NOT NULL, ingested_at_ms INTEGER NOT NULL);"
        "CREATE TABLE meta_chunks (id INTEGER PRIMARY KEY, doc TEXT NOT NULL, "
        "page INTEGER NOT NULL, country_tags TEXT NOT NULL, text TEXT NOT NULL);"
    )
    conn.close()
    store = Store(db)
    cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(meta_chunks)")}
    assert "kind" in cols
