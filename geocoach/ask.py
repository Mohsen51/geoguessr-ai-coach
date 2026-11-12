"""Free-text questions answered from plonkit and the meta PDFs."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from geocoach import coach, examples, metas, plonkit, prompts, runner
from geocoach.examples import Example, LinkResolver
from geocoach.geocode import country_name
from geocoach.panorama import ViewFetcher
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
    tips: dict[str, list[str]] = field(default_factory=dict)
    blocks: list[str] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)

    def with_examples(self, question: str, found: list[Example]) -> QuestionBundle:
        """Same bundle with verified examples listed in the prompt."""
        prompt = prompts.ask_prompt(question, self.blocks, self.pages, found)
        return QuestionBundle(prompt, self.countries, self.pages, self.tips, self.blocks, found)


def keywords(question: str) -> list[str]:
    """Words worth searching for, country names excluded (they filter the search instead)."""
    names = {w.lower() for c in metas.tag_countries(question) for w in _country_words(c)}
    words = [w.lower() for w in re.findall(r"\w{4,}", question)]
    return [w for w in dict.fromkeys(words) if w not in STOPWORDS and w not in names]


def _country_words(code: str) -> list[str]:
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
    tips: dict[str, list[str]] = {}
    for code in countries:
        identifying, matched, regional, notes = country_context(store, code, terms)
        tips[code] = matched + regional + identifying
        blocks.append(prompts.country_knowledge_block(code, identifying, matched, regional, notes))
        pages += [str(metas.render_page(d, p)) for d, p in metas.pages_for_country(store, code, 2)]
    if not countries:
        hits = metas.search_any(store, " ".join(terms), None, 12)
        blocks.append(prompts.hits_block("Best matches in plonkit and my PDFs", hits))
    prompt = prompts.ask_prompt(question, blocks, pages)
    return QuestionBundle(prompt, countries, pages, tips, blocks)


def country_context(
    store: Store, code: str, terms: list[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Identifying tips, question-matched plonkit tips, regional tips and PDF notes."""
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
    return coach.identifying_tips(store, code, 6), matched, region_tips, notes


def gather_examples(
    store: Store,
    bundle: QuestionBundle,
    question: str,
    resolver: LinkResolver,
    fetcher: ViewFetcher,
    confirm: Callable[[str], bool] = lambda _: False,
    run: Callable[..., Path] = runner.run_claude,
    log: Callable[[str], None] = lambda _: None,
) -> list[Example]:
    """Verified Street View examples per country; Claude's own search only when confirmed."""
    found: list[Example] = []
    for code in bundle.countries:
        name = country_name(code) or code
        candidates = examples.examples_from_tips(bundle.tips.get(code, []), resolver, 8)
        candidates += examples.own_round_examples(store, code, 3)
        log(f"{name}: {len(candidates)} candidate locations")
        kept = examples.verify(examples.fetch_images(candidates, fetcher, log), run=run)
        if not kept and confirm(name):
            proposed = examples.propose_examples(question, code, run=run, log=log)
            kept = examples.verify(examples.fetch_images(proposed, fetcher, log), run=run)
        log(f"{name}: {len(kept)} verified example(s)")
        found += kept
    return found
