"""Ingest community meta PDFs into searchable chunks, render pages on demand."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import pycountry

from geocoach import config
from geocoach.store import Store

CHUNK_CHARS = 800
ALIASES = {
    "usa": "us", "united states": "us", "america": "us", "uk": "gb", "britain": "gb",
    "england": "gb", "scotland": "gb", "wales": "gb", "russia": "ru", "south korea": "kr",
    "korea": "kr", "vietnam": "vn", "laos": "la", "czechia": "cz", "czech republic": "cz",
    "bolivia": "bo", "venezuela": "ve", "iran": "ir", "syria": "sy", "tanzania": "tz",
    "eswatini": "sz", "swaziland": "sz", "ivory coast": "ci", "cape verde": "cv",
    "turkey": "tr", "türkiye": "tr", "taiwan": "tw", "macau": "mo", "hong kong": "hk",
    "palestine": "ps", "kosovo": "xk", "north macedonia": "mk", "macedonia": "mk",
    "moldova": "md", "brunei": "bn", "micronesia": "fm", "curacao": "cw", "réunion": "re",
    "reunion": "re", "faroe islands": "fo", "falklands": "fk", "us virgin islands": "vi",
    "northern mariana islands": "mp", "christmas island": "cx", "cocos islands": "cc",
}  # fmt: skip
DEMONYMS = {
    "brazilian": "br", "russian": "ru", "american": "us", "canadian": "ca", "mexican": "mx",
    "argentinian": "ar", "argentine": "ar", "chilean": "cl", "peruvian": "pe", "colombian": "co",
    "bolivian": "bo", "ecuadorian": "ec", "uruguayan": "uy", "french": "fr", "german": "de",
    "spanish": "es", "portuguese": "pt", "italian": "it", "british": "gb", "irish": "ie",
    "dutch": "nl", "belgian": "be", "swiss": "ch", "austrian": "at", "polish": "pl", "czech": "cz",
    "slovak": "sk", "hungarian": "hu", "romanian": "ro", "bulgarian": "bg", "greek": "gr",
    "turkish": "tr", "ukrainian": "ua", "swedish": "se", "norwegian": "no", "finnish": "fi",
    "danish": "dk", "icelandic": "is", "estonian": "ee", "latvian": "lv", "lithuanian": "lt",
    "serbian": "rs", "croatian": "hr", "slovenian": "si", "albanian": "al", "montenegrin": "me",
    "bosnian": "ba", "macedonian": "mk", "japanese": "jp", "korean": "kr", "taiwanese": "tw",
    "thai": "th", "malaysian": "my", "indonesian": "id", "filipino": "ph", "philippine": "ph",
    "cambodian": "kh", "vietnamese": "vn", "laotian": "la", "mongolian": "mn", "indian": "in",
    "sri lankan": "lk", "bangladeshi": "bd", "bhutanese": "bt", "nepali": "np", "pakistani": "pk",
    "kazakh": "kz", "kyrgyz": "kg", "israeli": "il", "jordanian": "jo", "emirati": "ae",
    "qatari": "qa", "omani": "om", "lebanese": "lb", "tunisian": "tn", "moroccan": "ma",
    "egyptian": "eg", "kenyan": "ke", "ugandan": "ug", "rwandan": "rw", "tanzanian": "tz",
    "south african": "za", "botswanan": "bw", "namibian": "na", "lesotho": "ls", "eswatini": "sz",
    "ghanaian": "gh", "nigerian": "ng", "senegalese": "sn", "malagasy": "mg", "australian": "au",
    "new zealand": "nz", "kiwi": "nz", "guatemalan": "gt", "panamanian": "pa", "costa rican": "cr",
    "dominican": "do", "puerto rican": "pr", "curaçao": "cw", "greenlandic": "gl",
}  # fmt: skip
UPPER_ABBREVIATIONS = {"US": "us", "USA": "us", "UK": "gb", "UAE": "ae", "NZ": "nz"}


def _country_patterns() -> list[tuple[re.Pattern, str]]:
    names: dict[str, str] = {}
    for c in pycountry.countries:
        names[c.name.lower()] = c.alpha_2.lower()
        common = getattr(c, "common_name", None)
        if common:
            names[common.lower()] = c.alpha_2.lower()
    names.update(ALIASES)
    names.update(DEMONYMS)
    ordered = sorted(names.items(), key=lambda kv: -len(kv[0]))
    pats = [(re.compile(rf"\b{re.escape(n)}\b", re.I), code) for n, code in ordered]
    pats += [(re.compile(rf"\b{a}\b"), code) for a, code in UPPER_ABBREVIATIONS.items()]
    return pats


_PATTERNS: list[tuple[re.Pattern, str]] | None = None


def tag_countries(text: str) -> list[str]:
    global _PATTERNS
    if _PATTERNS is None:
        _PATTERNS = _country_patterns()
    found: list[str] = []
    for pat, code in _PATTERNS:
        if code not in found and pat.search(text):
            found.append(code)
    return found


def doc_tags(filename: str) -> list[str]:
    """Countries named in the file name, applied to every page of that document."""
    return tag_countries(Path(filename).stem.replace("_", " ").replace("-", " "))


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z•\-–*])", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) + 1 > size:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ingest(
    store: Store, metas_dir: Path = config.METAS_DIR, log=lambda _: None, force: bool = False
) -> int:
    """Index new or changed PDFs (all of them with force). Returns documents (re)indexed."""
    import pymupdf

    done = 0
    for pdf in sorted(metas_dir.glob("*.pdf")):
        sha = sha256_of(pdf)
        row = store.conn.execute(
            "SELECT sha256 FROM meta_docs WHERE doc = ?", (pdf.name,)
        ).fetchone()
        if row and row["sha256"] == sha and not force:
            continue
        with pymupdf.open(pdf) as doc, store.conn:
            n_pages = doc.page_count
            store.conn.execute("DELETE FROM meta_docs WHERE doc = ?", (pdf.name,))
            store.conn.execute(
                "INSERT INTO meta_docs VALUES (?,?,?,?)",
                (pdf.name, sha, n_pages, int(time.time() * 1000)),
            )
            base = doc_tags(pdf.name)
            for page in doc:
                chunks = chunk_text(page.get_text()) or [""]
                for chunk in chunks:
                    tags = base + [c for c in tag_countries(chunk) if c not in base]
                    store.conn.execute(
                        "INSERT INTO meta_chunks(doc, page, country_tags, text) VALUES (?,?,?,?)",
                        (pdf.name, page.number + 1, " ".join(tags), chunk),
                    )
        done += 1
        log(f"indexed {pdf.name} ({n_pages} pages)")
    return done


def _fts_query(text: str) -> str:
    terms = re.findall(r"\w+", text)
    return " ".join(f'"{t}"' for t in terms) if terms else '""'


def search(store: Store, query: str, country: str | None = None, limit: int = 8) -> list[dict]:
    sql = (
        "SELECT c.id, c.doc, c.page, c.country_tags, c.text, bm25(meta_fts) AS rank "
        "FROM meta_fts JOIN meta_chunks c ON c.id = meta_fts.rowid WHERE meta_fts MATCH ?"
    )
    params: list = [_fts_query(query)]
    if country:
        sql += " AND (' ' || c.country_tags || ' ') LIKE ?"
        params.append(f"% {country.lower()} %")
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    return [dict(r) for r in store.conn.execute(sql, params).fetchall()]


def chunks_for_country(store: Store, country: str, limit: int = 20) -> list[dict]:
    rows = store.conn.execute(
        "SELECT id, doc, page, country_tags, text FROM meta_chunks "
        "WHERE (' ' || country_tags || ' ') LIKE ? AND text != '' "
        "ORDER BY length(text) DESC, doc, page LIMIT ?",
        (f"% {country.lower()} %", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def pages_for_country(store: Store, country: str, limit: int = 6) -> list[tuple[str, int]]:
    rows = store.conn.execute(
        "SELECT doc, page, count(*) AS hits FROM meta_chunks "
        "WHERE (' ' || country_tags || ' ') LIKE ? GROUP BY doc, page "
        "ORDER BY hits DESC, doc, page LIMIT ?",
        (f"% {country.lower()} %", limit),
    ).fetchall()
    return [(r["doc"], r["page"]) for r in rows]


def render_page(doc: str, page: int, metas_dir: Path = config.METAS_DIR, dpi: int = 110) -> Path:
    """Render one PDF page to PNG (cached) so Claude can look at the figures."""
    import pymupdf

    config.ensure_dirs()
    out = config.PAGES_DIR / f"{Path(doc).stem}_p{page:03d}.png"
    if not out.exists():
        with pymupdf.open(metas_dir / doc) as d:
            d[page - 1].get_pixmap(dpi=dpi).save(out)
    return out
