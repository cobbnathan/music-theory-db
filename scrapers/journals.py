"""Scrapers for open-access music theory journals.

Implemented
-----------
* Music Theory Online          (mtosmt.org)           – static HTML
* Theory and Practice          (tnp.mtsnys.org)        – static HTML
* SMT-V                        (smt-v.org)             – static HTML
* Journal of Music Theory Pedagogy  (Lipscomb bepress) – OAI-PMH
* Analytical Approaches to World Music (journal.iftawm.org) – static HTML

Not implemented — reason documented in NOT_SCRAPABLE below.
"""
from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterator

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = (
    "music-theory-db/1.0 (research scraper; "
    "contact: github.com/music-theory-db)"
)

DELAY = 1.5  # seconds between requests (applied after every fetch)


# ---------------------------------------------------------------------------
# Journals that cannot be scraped and why
# ---------------------------------------------------------------------------

NOT_SCRAPABLE: dict[str, str] = {
    "Music Theory Spectrum": (
        "Oxford University Press (Oxford Academic). Abstracts paywalled; "
        "blocks automated agents (User-agent: 008 Disallow: /). "
        "Use CrossRef API (ISSN 0195-6167) for metadata only."
    ),
    "Journal of Music Theory": (
        "Duke University Press (Silverchair). Abstracts paywalled; robots.txt "
        "explicitly blocks ClaudeBot, anthropic-ai, GPTBot. "
        "Use CrossRef API (ISSN 0022-2909) for metadata only."
    ),
    "Music Analysis": (
        "Wiley Online Library. 403 returned to all automated agents; "
        "abstracts paywalled; blocks GPTBot and Google-Extended. "
        "Use CrossRef API (ISSN 0262-5245) for metadata only."
    ),
    "Music Perception": (
        "UC Press / Silverchair. 403 returned to automated agents; "
        "abstracts paywalled. "
        "Use CrossRef API (ISSN 0730-7829) for metadata only."
    ),
    "Journal of the Society for American Music": (
        "Cambridge University Press (Cambridge Core). Abstracts paywalled; "
        "JS-enhanced with restricted crawling. "
        "Use CrossRef API (ISSN 1752-1963) for metadata only."
    ),
    "Indiana Theory Review": (
        "Project MUSE paywall; IU Press robots.txt disallows all non-search-engine "
        "bots (Disallow: /). Use CrossRef API (ISSN 0741-4242) for metadata only."
    ),
    "Perspectives of New Music": (
        "Project MUSE (current) and JSTOR (archive) paywall. "
        "Use CrossRef API (ISSN 0031-6016) or JSTOR API for archived volumes."
    ),
    "Music Theory and Analysis": (
        "Leuven University Press. Subscription required; robots.txt sets "
        "crawl-delay 7s and blocks anthropic-ai/Claude-SearchBot/GPTBot. "
        "Use CrossRef API (ISSN 2295-1423) for metadata only."
    ),
    "Intégral": (
        "Eastman / University of Rochester. Volumes 1–32 are PDF-only with no "
        "article-level HTML metadata. Journal Index by Volume page does not "
        "expose structured article records. No OAI-PMH endpoint."
    ),
    "Gamut": (
        "MTSMA / University of Tennessee. Migrated from bepress to DSpace-CRIS; "
        "the old OAI-PMH set 'publication:gamut' no longer exists and all "
        "set identifiers tried return 'No matches for the query'. "
        "Direct HTML scraping blocked by aggressive rate-limiting (429)."
    ),
    "Journal of Schenkerian Studies": (
        "UNT Digital Library OAI-PMH (set=collection:JSCS) returns only "
        "volume-level records (one record per whole volume), not article-level. "
        "Individual articles are scanned PDFs without machine-readable metadata. "
        "Publication suspended 2020–2025."
    ),
    "Theoria": (
        "UNT Digital Library OAI-PMH (set=collection:THRJL) returns only "
        "volume-level records, not article-level. Individual articles are not "
        "separately indexed in the digital library."
    ),
    "Empirical Musicology Review": (
        "OSU Libraries / OJS. Anubis bot-protection middleware intercepts all "
        "automated requests (including OAI-PMH) and returns an HTML challenge "
        "page instead of XML. Cannot harvest without a headless browser + "
        "captcha solving."
    ),
    "Engaging Students: Essays in Music Pedagogy": (
        "OSU Libraries / OJS. Same Anubis bot-protection as EMR; OAI-PMH "
        "endpoint returns HTML challenge page to automated agents."
    ),
}


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _get(url: str, delay: float = DELAY) -> BeautifulSoup | None:
    """Fetch *url* and return parsed BeautifulSoup, or None on error."""
    try:
        resp = _SESSION.get(url, timeout=20)
        resp.raise_for_status()
        encoding = resp.apparent_encoding or "utf-8"
        return BeautifulSoup(resp.content, "html.parser", from_encoding=encoding)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None
    finally:
        time.sleep(delay)


def _raw_get(url: str, delay: float = DELAY) -> bytes | None:
    """Fetch *url* and return raw bytes (for XML / OAI responses)."""
    try:
        resp = _SESSION.get(url, timeout=20)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None
    finally:
        time.sleep(delay)


def _store(db, record: dict, keywords: list[str], kw_source: str = "explicit") -> int:
    """Upsert record and link keywords; return item_id."""
    from db import upsert_item, add_keywords_to_item
    item_id = upsert_item(db, record)
    if keywords:
        add_keywords_to_item(db, item_id, keywords, source=kw_source)
    return item_id


# ---------------------------------------------------------------------------
# OAI-PMH shared harvester
# ---------------------------------------------------------------------------

_OAI_NS = {
    "oai":    "http://www.openarchives.org/OAI/2.0/",
    "dc":     "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}


def _oai_records(
    base_url: str,
    set_spec: str | None = None,
    metadata_prefix: str = "oai_dc",
    delay: float = 2.0,
) -> Iterator[dict[str, list[str]]]:
    """
    Yield one dict per record from an OAI-PMH ListRecords harvest.
    Each dict maps DC element names → list of string values.
    Handles resumptionToken pagination automatically.
    """
    params: dict[str, str] = {
        "verb": "ListRecords",
        "metadataPrefix": metadata_prefix,
    }
    if set_spec:
        params["set"] = set_spec

    while True:
        url = base_url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        raw = _raw_get(url, delay=delay)
        if not raw:
            break

        # Sanitise invalid XML control characters (bepress quirk)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw.decode("utf-8", errors="replace"))
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            logger.warning("OAI XML parse error at %s: %s", url, exc)
            break

        for record in root.findall(".//oai:record", _OAI_NS):
            # Skip deleted records
            header = record.find("oai:header", _OAI_NS)
            if header is not None and header.get("status") == "deleted":
                continue
            dc = record.find(".//oai_dc:dc", _OAI_NS)
            if dc is None:
                continue
            fields: dict[str, list[str]] = {}
            for child in dc:
                tag = child.tag.split("}")[-1]
                val = (child.text or "").strip()
                if val:
                    fields.setdefault(tag, []).append(val)
            yield fields

        # Pagination
        rt = root.find(".//oai:resumptionToken", _OAI_NS)
        if rt is None or not (rt.text or "").strip():
            break
        params = {"verb": "ListRecords", "resumptionToken": rt.text.strip()}


def _doi_from_identifiers(identifiers: list[str]) -> str:
    """Extract a DOI string from a list of OAI dc:identifier values."""
    for ident in identifiers:
        if ident.startswith("info:doi/"):
            return ident[len("info:doi/"):]
        if re.match(r"10\.\d{4,}/", ident):
            return ident
        m = re.search(r"(10\.\d{4,}/\S+)", ident)
        if m:
            return m.group(1)
    return ""


def _year_from_date(dates: list[str]) -> int:
    """Extract a 4-digit year from a list of OAI dc:date strings."""
    for d in dates:
        m = re.search(r"\b(19|20)\d{2}\b", d)
        if m:
            return int(m.group(0))
    return 0


# ---------------------------------------------------------------------------
# Music Theory Online  (https://mtosmt.org)
# ---------------------------------------------------------------------------

_MTO_BASE  = "https://www.mtosmt.org"
_MTO_INDEX = f"{_MTO_BASE}/issues/issues.php"

_ARTICLE_RE = re.compile(
    r"mto\.(\d+)\.(\d+)\.(\d+)\.(?!personnel|toc|editors)[^/\"]+\.html$",
    re.IGNORECASE,
)
_DIR_RE = re.compile(r"mto\.(\d+)\.(\d+)\.(\d+)")


def _mto_issue_urls() -> list[str]:
    soup = _get(_MTO_INDEX)
    if not soup:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "toc" not in href or ".html" not in href:
            continue
        if not href.startswith("http"):
            href = f"{_MTO_BASE}/issues/{href}"
        if href not in seen:
            seen.add(href)
            urls.append(href)
    return list(reversed(urls))  # oldest first


def _mto_vol_issue_year(soup: BeautifulSoup | None, toc_url: str) -> tuple[str, str, int]:
    h2   = soup.find("h2") if soup else None
    text = h2.get_text(strip=True) if h2 else ""
    if not text and soup:
        t = soup.find("title")
        text = t.get_text(strip=True) if t else ""

    vol_m  = re.search(r"Volume\s+(\d+)", text, re.I)
    iss_m  = re.search(r"Number\s+(\d+)", text, re.I)
    year_m = re.search(r"\b(19|20)\d{2}\b", text)

    volume = vol_m.group(1)  if vol_m  else ""
    issue  = iss_m.group(1)  if iss_m  else ""
    year   = int(year_m.group(0)) if year_m else 0

    if not volume or not year:
        m = _DIR_RE.search(toc_url)
        if m:
            yy = m.group(1)
            if not volume: volume = m.group(2)
            if not issue:  issue  = m.group(3)
            if not year:
                year = (1900 if int(yy) >= 90 else 2000) + int(yy)

    return volume, issue, year


def _mto_article_links(soup: BeautifulSoup | None, toc_url: str) -> list[str]:
    if not soup:
        return []
    base_dir = toc_url.rsplit("/", 1)[0]
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http"):
            abs_href = href
        elif href.startswith("/"):
            abs_href = f"{_MTO_BASE}{href}"
        else:
            abs_href = f"{base_dir}/{href}"
        if _ARTICLE_RE.search(abs_href) and abs_href not in seen:
            seen.add(abs_href)
            urls.append(abs_href)
    return urls


def _mto_metadata_block(soup: BeautifulSoup) -> str:
    full = soup.get_text(separator="\n")
    cut  = re.search(r"\n\s*\[0?1\]|\nIntroduction\b|\nBackground\b", full)
    return full[: cut.start()] if cut else full[:4000]


def _mto_parse_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        for sup in h1.find_all("sup"):
            sup.decompose()
        return re.sub(r"\s+", " ", h1.get_text(separator=" ")).strip()
    block = _mto_metadata_block(soup)
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    kw_pos = next((i for i, l in enumerate(lines) if l.upper().startswith("KEYWORDS")), len(lines))
    candidates = [l for l in lines[:kw_pos] if len(l) > 20]
    return candidates[0] if candidates else ""


def _mto_parse_authors(soup: BeautifulSoup) -> list[str]:
    h1 = soup.find("h1")
    if not h1:
        return []
    h2 = h1.find_next("h2")
    if not h2:
        return []
    names = [a.get_text(strip=True) for a in h2.find_all("a") if a.get_text(strip=True)]
    return names if names else [h2.get_text(separator=" ", strip=True)]


def _mto_parse_keywords(block: str) -> list[str]:
    m = re.search(
        r"KEYWORDS\s*:\s*(.+?)(?=\n\s*(?:ABSTRACT|DOI|PDF|Received|Volume\s+\d)|\Z)",
        block, re.I | re.S,
    )
    if not m:
        return []
    raw = re.sub(r"\s+", " ", m.group(1)).strip()
    return [k.strip() for k in re.split(r"[,;]", raw) if k.strip()]


def _mto_parse_abstract(block: str) -> str:
    m = re.search(
        r"ABSTRACT\s*:\s*(.+?)(?:\nDOI\s*:|\nPDF\s|\nReceived\b|\nVolume\s+\d|\Z)",
        block, re.I | re.S,
    )
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _scrape_mto_article(url: str, volume: str, issue: str, year: int) -> dict | None:
    soup = _get(url)
    if not soup:
        return None
    block    = _mto_metadata_block(soup)
    title    = _mto_parse_title(soup)
    if not title:
        logger.warning("No title found at %s", url)
        return None
    doi_m    = re.search(r"DOI\s*:\s*(10\.\S+)", block, re.I)
    return {
        "item_type": "article",
        "title":     title,
        "authors":   json.dumps(_mto_parse_authors(soup)),
        "year":      year,
        "abstract":  _mto_parse_abstract(block) or None,
        "doi":       doi_m.group(1).strip() if doi_m else None,
        "url":       url,
        "journal":   "Music Theory Online",
        "volume":    volume,
        "issue":     issue,
        "source":    "mto",
        "_keywords": _mto_parse_keywords(block),
    }


def scrape_mto(db=None) -> Iterator[dict]:
    """Scrape all Music Theory Online articles (1993–present)."""
    issue_urls = _mto_issue_urls()
    logger.info("MTO: %d issues", len(issue_urls))
    for toc_url in issue_urls:
        toc_soup = _get(toc_url)
        vol, iss, year = _mto_vol_issue_year(toc_soup, toc_url)
        for art_url in _mto_article_links(toc_soup, toc_url):
            rec = _scrape_mto_article(art_url, vol, iss, year)
            if not rec:
                continue
            kws = rec.pop("_keywords", [])
            if db is not None:
                _store(db, rec, kws)
            yield {**rec, "_keywords": kws}


# ---------------------------------------------------------------------------
# Theory and Practice  (https://tnp.mtsnys.org)
# Robots.txt: none (404) — permissive. Only vols 47–48, 49–50, 51 online.
# ---------------------------------------------------------------------------

_TNP_BASE = "https://tnp.mtsnys.org"


def _tnp_volume_entries() -> list[tuple[str, str, int]]:
    """Return [(vol_label, url, year)] from the homepage volume selector."""
    soup = _get(_TNP_BASE + "/")
    if not soup:
        return []
    entries = []
    sel = soup.find("select", id="volume-select")
    if not sel:
        return []
    for opt in sel.find_all("option"):
        val  = opt.get("value", "")
        text = opt.get_text(strip=True)      # e.g. "Volume 47-48 (2024)"
        if not val or val == "":
            continue
        year_m = re.search(r"\((\d{4})\)", text)
        vol_m  = re.search(r"Volume\s+([\d\-]+)", text, re.I)
        year   = int(year_m.group(1)) if year_m else 0
        vol    = vol_m.group(1) if vol_m else val.lstrip("/vol")
        entries.append((vol, _TNP_BASE + val, year))
    return entries


def _tnp_article_links(vol_url: str) -> list[tuple[str, str]]:
    """Return [(article_url, author)] from a volume listing page."""
    soup = _get(vol_url)
    if not soup:
        return []
    results = []
    for a in soup.find_all("a", class_="title"):
        href = a.get("href", "")
        if not href:
            continue
        abs_url = (_TNP_BASE + href) if href.startswith("/") else href
        # Author is in the sibling .author div
        container = a.find_parent("div", class_="toc-item")
        author_div = container.find("div", class_="author") if container else None
        author = author_div.get_text(strip=True) if author_div else ""
        results.append((abs_url, author))
    return results


def _scrape_tnp_article(url: str, vol: str, year: int) -> dict | None:
    soup = _get(url)
    if not soup:
        return None

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    if not title:
        return None

    # Authors: <p class="author"><span class="author-name">…</span></p>
    authors: list[str] = []
    for p in soup.find_all("p", class_="author"):
        for span in p.find_all("span", class_="author-name"):
            name = span.get_text(strip=True)
            if name:
                authors.append(name)

    # Abstract: lives in a custom <abstract> element inside .abstract-wrapper
    abstract = ""
    abs_tag = soup.find("abstract")
    if abs_tag:
        abstract = re.sub(r"\s+", " ", abs_tag.get_text(separator=" ")).strip()

    # T&P does not publish explicit keyword lists
    return {
        "item_type": "article",
        "title":     title,
        "authors":   json.dumps(authors),
        "year":      year,
        "abstract":  abstract or None,
        "doi":       None,
        "url":       url,
        "journal":   "Theory and Practice",
        "volume":    vol,
        "issue":     None,
        "source":    "tnp",
        "_keywords": [],
    }


def scrape_theory_and_practice(db=None) -> Iterator[dict]:
    """Scrape Theory and Practice (vols 47–48, 49–50, 51 — publicly available)."""
    for vol, vol_url, year in _tnp_volume_entries():
        logger.info("T&P vol %s (%d): %s", vol, year, vol_url)
        for art_url, _author in _tnp_article_links(vol_url):
            rec = _scrape_tnp_article(art_url, vol, year)
            if not rec:
                continue
            kws = rec.pop("_keywords", [])
            if db is not None:
                _store(db, rec, kws)
            yield {**rec, "_keywords": kws}


# ---------------------------------------------------------------------------
# SMT-V  (https://www.smt-v.org)
# Robots.txt: none (404) — permissive. Fully open access, Jekyll static site.
# ---------------------------------------------------------------------------

_SMTV_BASE     = "https://www.smt-v.org"
_SMTV_ARCHIVES = f"{_SMTV_BASE}/archives/"

# Article filenames: N_N_Author.html  e.g. 12_1_Park.html
_SMTV_ART_RE = re.compile(r"/archives/(\d+)_(\d+)_\w+\.html$", re.I)


def _smtv_article_links() -> list[tuple[str, str, str, int]]:
    """Return [(url, vol, issue, year)] from the archives page."""
    soup = _get(_SMTV_ARCHIVES)
    if not soup:
        return []

    results: list[tuple[str, str, str, int]] = []
    current_year = 0
    current_vol  = ""

    for tag in soup.find_all(["h3", "li"]):
        if tag.name == "h3":
            # "Volume 12 (2026)"
            vol_m  = re.search(r"Volume\s+(\d+)", tag.get_text(), re.I)
            year_m = re.search(r"\((\d{4})\)", tag.get_text())
            if vol_m:
                current_vol  = vol_m.group(1)
            if year_m:
                current_year = int(year_m.group(1))
        elif tag.name == "li":
            a = tag.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            m = _SMTV_ART_RE.search(href)
            if not m:
                continue
            vol_from_url = m.group(1)
            iss_from_url = m.group(2)
            abs_url = (_SMTV_BASE + href) if href.startswith("/") else href
            results.append((abs_url, current_vol or vol_from_url, iss_from_url, current_year))

    return results


def _scrape_smtv_article(url: str, vol: str, issue: str, year: int) -> dict | None:
    soup = _get(url)
    if not soup:
        return None

    content = soup.find("div", class_="post-content")
    if not content:
        return None

    # Title: first <h3>
    h3 = content.find("h3")
    title = h3.get_text(strip=True) if h3 else ""
    if not title:
        return None

    # Author: first <p> after <h3>. Take only the first line to avoid
    # adjacent volume headings bleeding in on some pages.
    authors: list[str] = []
    if h3:
        p = h3.find_next_sibling("p")
        if p:
            # "Joon Park (University of Illinois Chicago)"
            # get_text may include newlines if there are multiple children
            raw = p.get_text(separator="\n", strip=True).split("\n")[0].strip()
            # Strip affiliation in parentheses
            name = re.sub(r"\s*\(.*?\)\s*$", "", raw).strip()
            if name:
                authors = [name]

    # Abstract: italic <em> paragraphs (non-keyword, non-link)
    abstract_parts: list[str] = []
    keywords: list[str] = []
    doi = ""
    for p in content.find_all("p"):
        em = p.find("em")
        if not em:
            continue
        text = p.get_text(separator=" ", strip=True)
        # DOI comment in source: <!--DOI: …-->  (HTML comment, not in get_text)
        # Keywords: <em><strong>Keywords</strong>: …</em>
        strong = em.find("strong")
        if strong and "keyword" in strong.get_text(strip=True).lower():
            # Remove the "Keywords:" label; collect comma-separated terms
            kw_text = text
            kw_text = re.sub(r"Keywords?\s*:\s*", "", kw_text, flags=re.I)
            keywords = [k.strip() for k in re.split(r"[,;]", kw_text) if k.strip()]
        elif not p.find("a") or len(text) > 80:
            # Substantive italic paragraph → abstract sentence
            abstract_parts.append(text)

    # DOI from HTML comment
    raw_html = str(content)
    doi_m = re.search(r"<!--\s*DOI:\s*(10\.\S+)", raw_html)
    if doi_m:
        doi = doi_m.group(1).strip().rstrip(")")

    abstract = " ".join(abstract_parts).strip() or None

    return {
        "item_type": "article",
        "title":     title,
        "authors":   json.dumps(authors),
        "year":      year,
        "abstract":  abstract,
        "doi":       doi or None,
        "url":       url,
        "journal":   "SMT-V: Society for Music Theory Videocast Journal",
        "volume":    vol,
        "issue":     issue,
        "source":    "smtv",
        "_keywords": keywords,
    }


def scrape_smtv(db=None) -> Iterator[dict]:
    """Scrape all SMT-V articles."""
    entries = _smtv_article_links()
    logger.info("SMT-V: %d articles found in archive", len(entries))
    for url, vol, issue, year in entries:
        rec = _scrape_smtv_article(url, vol, issue, year)
        if not rec:
            continue
        kws = rec.pop("_keywords", [])
        if db is not None:
            _store(db, rec, kws)
        yield {**rec, "_keywords": kws}


# ---------------------------------------------------------------------------
# Journal of Music Theory Pedagogy  (Lipscomb bepress OAI-PMH)
# OAI base: https://digitalcollections.lipscomb.edu/do/oai/
# Set: publication:jmtp  (438 records as of 2025)
# Robots.txt: blocks ^Byte UA; disallows /cgi/ paths only — OAI is permitted.
# ---------------------------------------------------------------------------

_JMTP_OAI = "https://digitalcollections.lipscomb.edu/do/oai/"
_JMTP_SET  = "publication:jmtp"


def scrape_jmtp(db=None) -> Iterator[dict]:
    """Scrape JMTP via OAI-PMH (Dublin Core)."""
    total = 0
    for fields in _oai_records(_JMTP_OAI, set_spec=_JMTP_SET, delay=2.0):
        titles  = fields.get("title", [])
        if not titles:
            continue

        # Filter out non-music-theory records (Lipscomb repo has other depts)
        source_vals = " ".join(fields.get("source", []) + fields.get("publisher", [])).lower()
        if "music theory" not in source_vals and "jmtp" not in source_vals and "pedagogy" not in source_vals:
            continue

        title    = titles[0]
        authors  = fields.get("creator", [])
        # Normalise "Last, First" → keep as-is (already consistent in this repo)
        abstract = " ".join(fields.get("description", [])) or None
        subjects = fields.get("subject", [])
        year     = _year_from_date(fields.get("date", []))
        doi      = _doi_from_identifiers(fields.get("identifier", []))

        # Canonical URL: first non-doi, non-pdf identifier
        url = next(
            (i for i in fields.get("identifier", [])
             if i.startswith("http") and "viewcontent" not in i and "info:doi" not in i),
            None,
        )

        # Volume/issue from URL path: /jmtp/vol{N}/iss{N}/
        vol = iss = ""
        if url:
            vol_m = re.search(r"/vol(\d+)/iss(\d+)/", url)
            if vol_m:
                vol, iss = vol_m.group(1), vol_m.group(2)

        rec = {
            "item_type": "article",
            "title":     title,
            "authors":   json.dumps(authors),
            "year":      year,
            "abstract":  abstract,
            "doi":       doi or None,
            "url":       url,
            "journal":   "Journal of Music Theory Pedagogy",
            "volume":    vol,
            "issue":     iss,
            "source":    "jmtp",
            "_keywords": subjects,
        }
        kws = rec.pop("_keywords", [])
        if db is not None:
            _store(db, rec, kws, kw_source="explicit")
        yield {**rec, "_keywords": kws}
        total += 1

    logger.info("JMTP: %d records harvested", total)


# ---------------------------------------------------------------------------
# Analytical Approaches to World Music  (https://journal.iftawm.org)
# Robots.txt: Disallow /wp-admin/ only — all content paths permitted.
# Issue pages list article title, author, and abstract snippet in HTML.
# Individual article pages are PDF-only; issue pages are the metadata source.
# ---------------------------------------------------------------------------

_AAWM_BASE    = "https://journal.iftawm.org"
_AAWM_SITEMAP = f"{_AAWM_BASE}/wp-sitemap-posts-page-1.xml"

# Issue URL pattern: /previous/vol{N}no{N}/  (no trailing slug = issue index)
_AAWM_ISSUE_RE      = re.compile(r"/previous/vol(\d+)no(\d+)/?$", re.I)
# Article sub-page: /previous/vol{N}no{N}/some-slug
_AAWM_ARTICLE_RE    = re.compile(r"/previous/vol(\d+)no(\d+)/([^/]+)/?$", re.I)


def _aawm_issue_urls() -> list[tuple[str, str, str]]:
    """Return [(url, vol, issue)] for all AAWM issue index pages, oldest-first."""
    raw = _raw_get(_AAWM_SITEMAP, delay=DELAY)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    sm_ns   = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    entries: list[tuple[str, str, str]] = []
    seen:    set[str] = set()
    for loc in root.findall(".//sm:loc", sm_ns):
        url = (loc.text or "").strip()
        m   = _AAWM_ISSUE_RE.search(url)
        if m and url not in seen:
            seen.add(url)
            entries.append((url, m.group(1), m.group(2)))

    entries.sort(key=lambda x: (int(x[1]), int(x[2])))
    return entries


def _aawm_article_urls_from_issue(issue_url: str) -> list[tuple[str, str]]:
    """
    Return [(article_url, title)] for every article linked from an AAWM issue page.
    Issue pages list articles as <a href="/previous/volNnoN/slug">Title text</a>.
    """
    soup = _get(issue_url)
    if not soup:
        return []
    results: list[tuple[str, str]] = []
    seen:    set[str] = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if _AAWM_ARTICLE_RE.search(href) and href not in seen and len(title) > 5:
            abs_url = href if href.startswith("http") else _AAWM_BASE + href
            seen.add(href)
            results.append((abs_url, title))
    return results


def _scrape_aawm_article(url: str, title: str, vol: str, issue: str) -> dict | None:
    """
    Fetch one AAWM article sub-page.
    Page structure (plain text after nav):
        [author slug heading]
        AAWM JOURNAL VOL. N NO. N (YYYY)
        <Title>
        <Author Name>
        Abstract:
        <abstract text …>
        [body paragraphs]
        Read full article in PDF version  ← PDF link
    """
    soup = _get(url)
    if not soup:
        return None

    text  = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Year
    year_m = re.search(r"\((\d{4})\)", text)
    year   = int(year_m.group(1)) if year_m else 0

    # Author: look for the line immediately after the title
    author = ""
    for i, line in enumerate(lines):
        if title[:40].lower() in line.lower() and i + 1 < len(lines):
            candidate = lines[i + 1]
            # Reject nav-like lines
            if len(candidate) > 3 and "journal" not in candidate.lower() and "aawm" not in candidate.lower():
                author = candidate
            break

    # Abstract: everything between "Abstract:" and the start of the body
    abstract = ""
    abs_m = re.search(r"Abstract:\s*\n(.+?)(?=\n\s*\n|\Z)", text, re.S | re.I)
    if abs_m:
        abstract = re.sub(r"\s+", " ", abs_m.group(1)).strip()

    # PDF URL: the "Read full article in PDF version" link
    pdf_url = None
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            pdf_url = a["href"]
            break

    return {
        "item_type": "article",
        "title":     title,
        "authors":   json.dumps([author] if author else []),
        "year":      year,
        "abstract":  abstract or None,
        "doi":       None,
        "url":       pdf_url or url,
        "journal":   "Analytical Approaches to World Music",
        "volume":    vol,
        "issue":     issue,
        "source":    "aawm",
        "_keywords": [],
    }


def scrape_aawm(db=None) -> Iterator[dict]:
    """Scrape all AAWM articles: sitemap → issue index → article sub-pages."""
    issue_entries = _aawm_issue_urls()
    logger.info("AAWM: %d issue pages", len(issue_entries))
    for issue_url, vol, issue in issue_entries:
        for art_url, title in _aawm_article_urls_from_issue(issue_url):
            rec = _scrape_aawm_article(art_url, title, vol, issue)
            if not rec:
                continue
            kws = rec.pop("_keywords", [])
            if db is not None:
                _store(db, rec, kws)
            yield {**rec, "_keywords": kws}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def scrape_all_journals(db=None, include_crossref: bool = True) -> dict[str, int]:
    """
    Run all implemented journal scrapers in sequence, then CrossRef.

    Parameters
    ----------
    include_crossref:
        If True (default), also harvest CrossRef metadata for the paywalled
        journals listed in scrapers.crossref.TARGET_JOURNALS.

    Returns a dict of {source_name: article_count}.
    """
    scrapers = [
        ("mto",  scrape_mto),
        ("tnp",  scrape_theory_and_practice),
        ("smtv", scrape_smtv),
        ("jmtp", scrape_jmtp),
        ("aawm", scrape_aawm),
    ]
    counts: dict[str, int] = {}
    for name, fn in scrapers:
        logger.info("=== Starting scraper: %s ===", name)
        n = sum(1 for _ in fn(db=db))
        counts[name] = n
        logger.info("=== %s done: %d records ===", name, n)

    if include_crossref:
        from scrapers.crossref import scrape_crossref
        logger.info("=== Starting CrossRef harvester ===")
        cr_counts = scrape_crossref(db=db)
        for journal, n in cr_counts.items():
            counts[f"crossref:{journal}"] = n
        logger.info("=== CrossRef done: %d total records ===", sum(cr_counts.values()))

    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    import argparse
    from db import get_db

    parser = argparse.ArgumentParser(description="Music theory journal scraper")
    parser.add_argument(
        "journal",
        nargs="?",
        default="all",
        choices=["all", "mto", "tnp", "smtv", "jmtp", "aawm"],
        help="Which scraper to run (default: all)",
    )
    args   = parser.parse_args()
    db_    = get_db()
    fn_map = {
        "mto":  scrape_mto,
        "tnp":  scrape_theory_and_practice,
        "smtv": scrape_smtv,
        "jmtp": scrape_jmtp,
        "aawm": scrape_aawm,
    }

    if args.journal == "all":
        counts = scrape_all_journals(db=db_)
        for journal, count in counts.items():
            print(f"{journal:6} {count:4d} articles")
    else:
        total = 0
        for rec in fn_map[args.journal](db=db_):
            total += 1
            print(
                f"[{total:4d}] Vol {rec.get('volume','')} | "
                f"{rec.get('title','')[:65]!r} | "
                f"{len(rec.get('_keywords', []))} kws"
            )
        print(f"\nDone. {total} articles.")
