"""Describe image-heavy PDF pages with Claude so maps and photos become searchable text."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from geocoach import config, metas, runner
from geocoach.store import Store

MIN_TEXT_CHARS = 400
DIGEST_PROMPT = """You are indexing GeoGuessr meta documents for a No Move / NMPZ player.
Read each page image below and write a factual description a search engine can use, 2 to 6
sentences: what the picture shows (pole shape, car and camera details, sign, plate, bollard,
landscape, vegetation, map), every piece of text visible in the image, and for maps the
regions or states that are highlighted and what the legend says each colour means. Do not
add knowledge that is not on the page. If a page is only a title or decoration, say so in
one short sentence.

Answer with JSON only, no prose and no code fence: a list of objects with keys "page"
(the file path exactly as given) and "description".

Pages:
"""


def pages_to_digest(store: Store, metas_dir: Path, doc_filter: str | None = None):
    """(doc, page) pairs with embedded images and little text, not digested yet."""
    import pymupdf

    rows = store.conn.execute(
        "SELECT doc, page, sum(length(text)) AS chars, "
        "sum(kind = 'digest') AS digested FROM meta_chunks GROUP BY doc, page"
    ).fetchall()
    out: list[tuple[str, int]] = []
    docs: dict[str, pymupdf.Document] = {}
    try:
        for r in rows:
            if doc_filter and doc_filter.lower() not in r["doc"].lower():
                continue
            if r["digested"] or r["chars"] >= MIN_TEXT_CHARS:
                continue
            pdf = docs.get(r["doc"])
            if pdf is None:
                path = metas_dir / r["doc"]
                if not path.exists():
                    continue
                pdf = docs[r["doc"]] = pymupdf.open(path)
            if pdf[r["page"] - 1].get_images():
                out.append((r["doc"], r["page"]))
    finally:
        for pdf in docs.values():
            pdf.close()
    return out


def parse_digest_output(text: str) -> dict[str, str]:
    """Map image path to description from Claude's JSON answer, tolerant to fences."""
    body = text.strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body)
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end < 0:
        return {}
    try:
        items = json.loads(body[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return {
        str(i.get("page", "")): str(i.get("description", "")).strip()
        for i in items
        if isinstance(i, dict) and i.get("description")
    }


def store_digest(store: Store, doc: str, page: int, description: str) -> None:
    tags = metas.doc_tags(doc)
    tags += [c for c in metas.tag_countries(description) if c not in tags]
    with store.conn:
        store.conn.execute(
            "DELETE FROM meta_chunks WHERE doc = ? AND page = ? AND kind = 'digest'", (doc, page)
        )
        store.conn.execute(
            "INSERT INTO meta_chunks(doc, page, country_tags, text, kind) VALUES (?,?,?,?,?)",
            (doc, page, " ".join(tags), description, "digest"),
        )


def digest(
    store: Store,
    metas_dir: Path | None = None,
    batch: int = 8,
    doc_filter: str | None = None,
    model: str | None = runner.DIGEST_MODEL,
    log: Callable[[str], None] = lambda _: None,
    run: Callable[..., Path] = runner.run_claude,
) -> int:
    """Digest pending image pages in batches. Returns the number of pages digested."""
    metas_dir = metas_dir or config.METAS_DIR
    pending = pages_to_digest(store, metas_dir, doc_filter)
    log(f"{len(pending)} pages to digest")
    done = 0
    for i in range(0, len(pending), batch):
        chunk = pending[i : i + batch]
        paths = {str(metas.render_page(d, p, metas_dir)): (d, p) for d, p in chunk}
        prompt = DIGEST_PROMPT + "\n".join(f"- {p}" for p in paths)
        collected: list[str] = []
        run(prompt, f"digest_{i // batch:03d}", model, echo=collected.append, use_mcp=False)
        parsed = parse_digest_output("".join(collected))
        for path, (d, p) in paths.items():
            desc = parsed.get(path)
            if desc:
                store_digest(store, d, p, desc)
                done += 1
            else:
                log(f"no description for {d} p.{p}")
        log(f"digested {done}/{len(pending)}")
    return done
