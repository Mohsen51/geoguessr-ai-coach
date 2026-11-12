"""Free-text questions answered from plonkit and the meta PDFs."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from geocoach import coach, metas, plonkit, prompts
from geocoach.store import Store

STOPWORDS = {
    "about", "between", "difference", "does", "from", "have", "how", "into", "like", "mainland",
    "should", "tell", "that", "there", "they", "this", "understand", "what", "when", "where",
    "which", "with", "would", "your",
}  # fmt: skip


@dataclass
class QuestionBundle:
    prompt: str
    countries: list[str]
    pages: list[str] = field(default_factory=list)


def keywords(question: str) -> list[str]:
    """Words worth searching for, country names excluded (they filter the search instead)."""
    names = {w.lower() for c in metas.tag_countries(question) for w in _country_words(c)}
    words = [w.lower() for w in re.findall(r"\w{4,}", question)]
    return [w for w in dict.fromkeys(words) if w not in STOPWORDS and w not in names]


def _country_words(code: str) -> list[str]:
    from geocoach.geocode import country_name

    return re.findall(r"\w+", country_name(code) or "")


def prepare_question(
    store: Store,
    question: str,
    plonkit_client: plonkit.PlonkitClient | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> QuestionBundle:
    countries = metas.tag_countries(question)
    if plonkit_client is not None and countries:
        coach.ensure_plonkit(store, plonkit_client, set(countries), log)
    terms = keywords(question)
    blocks: list[str] = []
    pages: list[str] = []
    for code in countries:
        blocks.append(country_block(store, code, terms))
        pages += [str(metas.render_page(d, p)) for d, p in metas.pages_for_country(store, code, 2)]
    if not countries:
        hits = metas.search_any(store, " ".join(terms), None, 12)
        blocks.append(prompts.hits_block("Best matches in plonkit and my PDFs", hits))
    return QuestionBundle(prompts.ask_prompt(question, blocks, pages), countries, pages)


def country_block(store: Store, code: str, terms: list[str]) -> str:
    """Identifying tips, question-matched plonkit tips and PDF notes for one country."""
    matched = [
        h["text"]
        for h in metas.search_any(store, " ".join(terms), code, 12)
        if h["kind"] == "plonkit" and h["country_tags"].split()[0] == code
    ]
    bodies = {m.partition("] ")[2] for m in matched}
    region_tips = [
        t
        for t in plonkit.regional_tips(store, code, terms, 8 + len(bodies))
        if t.partition(": ")[2] not in bodies and t not in bodies
    ][:8]
    notes = [
        h["text"]
        for h in metas.search_any(store, " ".join(terms), code, 6)
        if h["kind"] != "plonkit"
    ]
    notes = notes or [c["text"] for c in coach.pdf_chunks(store, code, 3)]
    return prompts.country_knowledge_block(
        code, coach.identifying_tips(store, code, 6), matched, region_tips, notes
    )
