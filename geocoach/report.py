"""HTML report of an analysis: each round's views beside Claude's explanation, with links."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt

from geocoach import config
from geocoach.analysis import RoundReview
from geocoach.coach import AnalysisBundle
from geocoach.geocode import country_name

ROUND_HEADING_RE = re.compile(r"^#{1,4}\s*\**\s*Round\s+(?P<n>\d+)\b(?P<rest>[^\n]*)", re.I | re.M)
DUEL_ID_RE = re.compile(r"duel\s+(?P<gid>[\w-]{4,})", re.I)
HEADING_RE = re.compile(r"^#{1,4}\s", re.M)

CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:1200px;
margin:2rem auto;padding:0 1rem;color:#1d1d1f;background:#fafafa;line-height:1.45}
h1{font-size:1.6rem}h2{font-size:1.25rem;margin-top:2.5rem}
.round{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1.5rem;background:#fff;
border:1px solid #e3e3e3;border-radius:10px;padding:1.25rem;margin:1.5rem 0}
.round img{width:100%;height:auto;border-radius:6px;margin-bottom:.75rem}
.meta{font-size:.92rem;color:#444;margin:.25rem 0 .75rem}
.meta b{color:#1d1d1f}.links a{margin-right:1rem;font-size:.92rem}
.lost{color:#b00020;font-weight:600}.explain{font-size:.97rem}
.explain h3,.explain h4{display:none}
.summary{background:#fff;border:1px solid #e3e3e3;border-radius:10px;padding:1.25rem}
@media (max-width:800px){.round{grid-template-columns:1fr}}
"""


def streetview_url(r: RoundReview) -> str:
    return (
        "https://www.google.com/maps/@?api=1&map_action=pano"
        f"&pano={r.pano_id}&heading={r.heading:.0f}&pitch=0&fov=90"
    )


def duel_url(r: RoundReview) -> str:
    return f"https://www.geoguessr.com/duels/{r.game_id}/summary?round={r.n}"


def guess_streetview_url(r: RoundReview) -> str:
    """Nearest Street View panorama to where I dropped the pin."""
    return (
        "https://www.google.com/maps/@?api=1&map_action=pano"
        f"&viewpoint={r.guess_lat:.5f},{r.guess_lng:.5f}"
    )


def split_answer(
    answer: str, rounds: list[RoundReview]
) -> tuple[dict[tuple[str, int], str], str, str]:
    """Map (game_id, n) to its explanation; also return the intro and the closing summary."""
    matches = list(ROUND_HEADING_RE.finditer(answer))
    if not matches:
        return {}, "", answer.strip()
    intro = answer[: matches[0].start()].strip()
    sections: dict[tuple[str, int], str] = {}
    closing = ""
    by_order = list(rounds)
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(answer)
        body = answer[m.end() : end]
        # a non-round heading after the last round starts the closing summary
        if i + 1 == len(matches):
            tail = HEADING_RE.search(body)
            if tail:
                closing = body[tail.start() :].strip()
                body = body[: tail.start()]
        key = _match_round(m, by_order, rounds)
        if key is not None:
            sections[key] = body.strip()
    return sections, intro, closing


def _match_round(m: re.Match, by_order: list[RoundReview], rounds: list[RoundReview]):
    n = int(m.group("n"))
    gid_match = DUEL_ID_RE.search(m.group("rest") or "")
    gid = gid_match.group("gid").lower() if gid_match else ""
    for r in rounds:
        if r.n == n and (not gid or r.game_id.lower().startswith(gid)):
            if r in by_order:
                by_order.remove(r)
            return (r.game_id, r.n)
    if by_order:  # heading without a usable id: take the next unmatched round in order
        r = by_order.pop(0)
        return (r.game_id, r.n)
    return None


_MD = MarkdownIt("commonmark", {"typographer": False})


def _md(text: str) -> str:
    """CommonMark rendering: tolerant of the 3-space nested lists Claude writes."""
    return _MD.render(text)


def render_html(bundle: AnalysisBundle, answer: str, title: str) -> str:
    sections, intro, closing = split_answer(answer, bundle.rounds)
    parts = [f"<h1>{html.escape(title)}</h1>"]
    if intro:
        parts.append(f'<div class="summary">{_md(intro)}</div>')
    for r in bundle.rounds:
        imgs = (
            "".join(
                f'<a href="file://{html.escape(p)}"><img src="file://{html.escape(p)}" '
                f'alt="round {r.n} view"></a>'
                for p in bundle.images.get((r.game_id, r.n), [])
            )
            or "<p><i>No image available.</i></p>"
        )
        region = f", {html.escape(r.region)}" if r.region else ""
        guess_region = f", {html.escape(r.guess_region)}" if r.guess_region else ""
        meta = (
            f"<p class='meta'><b>Actual:</b> {html.escape(country_name(r.country))}{region}<br>"
            f"<b>My guess:</b> {html.escape(country_name(r.guess_country) or 'none')}"
            f"{guess_region}, <span class='lost'>{r.distance_m / 1000:.0f} km off, "
            f"{r.my_score} pts</span><br>"
            f"<b>Opponent:</b> {html.escape(country_name(r.opp_guess_country) or 'none')}, "
            f"{r.opp_distance_m / 1000:.0f} km off, {r.opp_score} pts<br>"
            f"<b>Outcome:</b> {html.escape(r.loss_type.replace('_', ' '))}, "
            f"{r.damage_taken} damage, x{r.multiplier:g}"
            + (f", answered in {r.time_to_guess_s:.0f}s" if r.time_to_guess_s else "")
            + "</p>"
        )
        links = (
            "<p class='links'>"
            f"<a href='{streetview_url(r)}'>Street View of the round</a>"
            f"<a href='{guess_streetview_url(r)}'>Street View where I pinned</a>"
            f"<a href='{duel_url(r)}'>Round {r.n} on GeoGuessr</a></p>"
        )
        explain = sections.get((r.game_id, r.n)) or "<i>No explanation returned for this round.</i>"
        parts.append(
            f"<h2>Round {r.n}, {html.escape(country_name(r.country))}{region} "
            f"<small>({r.mode.upper()}, duel {html.escape(r.game_id[:8])})</small></h2>"
            f"<div class='round'><div>{imgs}{meta}{links}</div>"
            f"<div class='explain'>{_md(explain)}</div></div>"
        )
    if closing:
        parts.append(f'<div class="summary">{_md(closing)}</div>')
    body = "\n".join(parts)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def write_report(bundle: AnalysisBundle, answer: str, name: str) -> Path:
    config.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = config.REPORTS_DIR / f"{stamp}_{name}.html"
    out.write_text(render_html(bundle, answer, f"geocoach {name} {stamp}"))
    return out


def render_ask_html(question: str, answer: str, examples: list, title: str) -> str:
    """Answer page: the markdown answer, then the verified Street View examples."""
    parts = [
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='meta'><b>Question:</b> {html.escape(question)}</p>",
        f"<div class='summary'>{_md(answer)}</div>",
    ]
    if examples:
        parts.append("<h2>Street View examples</h2>")
    for e in examples:
        parts.append(
            "<div class='round'><div>"
            f"<a href='file://{html.escape(e.image)}'><img src='file://{html.escape(e.image)}' "
            f"alt='{html.escape(e.tip[:80])}'></a></div>"
            f"<div class='explain'><p>{html.escape(e.tip)}</p>"
            f"<p class='meta'>{html.escape(e.note)}</p>"
            f"<p class='links'><a href='{html.escape(e.url)}'>Open in Street View</a></p>"
            "</div></div>"
        )
    body = "\n".join(parts)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def write_ask_report(question: str, answer: str, examples: list, name: str = "ask") -> Path:
    config.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = config.REPORTS_DIR / f"{stamp}_{name}.html"
    out.write_text(render_ask_html(question, answer, examples, f"geocoach {name} {stamp}"))
    return out
