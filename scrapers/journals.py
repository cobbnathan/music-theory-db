"""Scrapers for open-access music theory journals."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Iterator

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = (
    "music-theory-db/1.0 (research scraper; "
    "contact: github.com/music-theory-db)"
)

DELAY = 1.5  # seconds between requests


def _get(url: str) -> BeautifulSoup | None:
    """Fetch URL and return parsed soup, or None on error."""
    try:
        resp = _SESSION.get(url, timeout=20)
        resp.raise_for_status()
        # MTO pages are windows-1252 in old issues; let requests/BS detect it
        encoding = resp.apparent_encoding or "utf-8"
        return BeautifulSoup(resp.content, "html.parser", from_encoding=encoding)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None
    finally:
        time.sleep(DELAY)


# ---------------------------------------------------------------------------
# Music Theory Online (https://mtosmt.org)
# ---------------------------------------------------------------------------

_MTO_BASE = "https://www.mtosmt.org"
_MTO_INDEX = f"{_MTO_BASE}/issues/issues.php"

# Matches article filenames: mto.YY.VOL.ISS.authorname.html
_ARTICLE_RE = re.compile(
    r"mto\.(\d+)\.(\d+)\.(\d+)\.(?!personnel|toc|editors)[^/\"]+\.html$",
    re.IGNORECASE,
)
# Extracts vol/issue from directory: mto.YY.VOL.ISS
_DIR_RE = re.compile(r"mto\.(\d+)\.(\d+)\.(\d+)")


def _mto_issue_urls() -> list[str]:
    """Return absolute URLs for all MTO issue TOC pages, oldest-first."""
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


def _parse_vol_issue_year(soup: BeautifulSoup | None, toc_url: str) -> tuple[str, str, int]:
    """Extract volume, issue, year from a TOC page heading."""
    # <h2>Volume 31 Number 1, March 2025</h2>  or plain text variant
    h2 = soup.find("h2") if soup else None
    text = h2.get_text(strip=True) if h2 else ""
    if not text and soup:
        # Fall back to <title>
        title_tag = soup.find("title")
        text = title_tag.get_text(strip=True) if title_tag else ""

    vol_m = re.search(r"Volume\s+(\d+)", text, re.I)
    iss_m = re.search(r"Number\s+(\d+)", text, re.I)
    year_m = re.search(r"\b(19|20)\d{2}\b", text)

    volume = vol_m.group(1) if vol_m else ""
    issue = iss_m.group(1) if iss_m else ""
    year = int(year_m.group(0)) if year_m else 0

    # Last resort: extract from URL directory name mto.YY.VOL.ISS
    if not volume or not year:
        m = _DIR_RE.search(toc_url)
        if m:
            yy, vol_fallback, iss_fallback = m.group(1), m.group(2), m.group(3)
            if not volume:
                volume = vol_fallback
            if not issue:
                issue = iss_fallback
            if not year:
                century = 1900 if int(yy) >= 90 else 2000
                year = century + int(yy)

    return volume, issue, year


def _article_links_from_toc(soup: BeautifulSoup | None, toc_url: str) -> list[str]:
    """Return absolute article URLs found in a TOC page."""
    if not soup:
        return []
    base_dir = toc_url.rsplit("/", 1)[0]
    seen: set[str] = set()
    urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Normalise to absolute
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


def _extract_metadata_block(soup: BeautifulSoup) -> str:
    """
    Return the normalised text of the metadata header block (title through
    first paragraph number "[1]" or "Introduction").  KEYWORDS and ABSTRACT
    live in this region.
    """
    full_text = soup.get_text(separator="\n")
    # Trim everything after the body content starts (first paragraph marker)
    cut = re.search(r"\n\s*\[0?1\]|\nIntroduction\b|\nBackground\b", full_text)
    return full_text[: cut.start()] if cut else full_text[:4000]


def _parse_authors(soup: BeautifulSoup) -> list[str]:
    """
    Extract author names from an MTO article page.

    MTO consistently places author names as <a> links inside the first <h2>
    that follows the title <h1>.  Each author gets its own <a href="#AUTHORNOTEn">.
    """
    h1 = soup.find("h1")
    if not h1:
        return []
    h2 = h1.find_next("h2")
    if not h2:
        return []
    names = [a.get_text(strip=True) for a in h2.find_all("a") if a.get_text(strip=True)]
    return names if names else [h2.get_text(separator=" ", strip=True)]


def _parse_keywords(block: str) -> list[str]:
    """
    Parse 'KEYWORDS: foo, bar, baz' from metadata block.
    Early MTO issues split keyword lists across multiple lines.
    """
    m = re.search(
        r"KEYWORDS\s*:\s*(.+?)(?=\n\s*(?:ABSTRACT|DOI|PDF|Received|Volume\s+\d)|\Z)",
        block,
        re.I | re.S,
    )
    if not m:
        return []
    raw = re.sub(r"\s+", " ", m.group(1)).strip()
    return [k.strip() for k in re.split(r"[,;]", raw) if k.strip()]


def _parse_abstract(block: str) -> str:
    """Parse abstract text from metadata block."""
    m = re.search(
        r"ABSTRACT\s*:\s*(.+?)(?:\nDOI\s*:|\nPDF\s|\nReceived\b|\nVolume\s+\d|\Z)",
        block,
        re.I | re.S,
    )
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _parse_doi(block: str) -> str:
    """Parse DOI line, e.g. 'DOI: 10.30535/mto.31.1.1'."""
    m = re.search(r"DOI\s*:\s*(10\.\S+)", block, re.I)
    return m.group(1).strip() if m else ""


def _parse_title(soup: BeautifulSoup) -> str:
    """
    Return the article title.  MTO always places it in the first <h1>.
    Use separator=" " to avoid words merging across inline tags (e.g. <i>).
    Strip footnote markers (superscript *, 1, 2 …).
    """
    h1 = soup.find("h1")
    if h1:
        # Remove <sup> footnote markers before extracting text
        for sup in h1.find_all("sup"):
            sup.decompose()
        return re.sub(r"\s+", " ", h1.get_text(separator=" ")).strip()

    # Fallback for any edge cases: first sizable <h2> before KEYWORDS
    block = _extract_metadata_block(soup)
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    kw_pos = next(
        (i for i, l in enumerate(lines) if l.upper().startswith("KEYWORDS")), len(lines)
    )
    candidates = [l for l in lines[:kw_pos] if len(l) > 20]
    return candidates[0] if candidates else ""


def _scrape_mto_article(
    url: str, volume: str, issue: str, year: int
) -> dict | None:
    """Fetch one MTO article page and return a record dict ready for db.py."""
    soup = _get(url)
    if not soup:
        return None

    block = _extract_metadata_block(soup)
    title = _parse_title(soup)
    if not title:
        logger.warning("No title found at %s", url)
        return None

    authors = _parse_authors(soup)
    keywords = _parse_keywords(block)
    abstract = _parse_abstract(block)
    doi = _parse_doi(block)

    return {
        "item_type": "article",
        "title": title,
        "authors": json.dumps(authors),
        "year": year,
        "abstract": abstract or None,
        "doi": doi or None,
        "url": url,
        "journal": "Music Theory Online",
        "volume": volume,
        "issue": issue,
        "source": "mto",
        "_keywords": keywords,  # popped before db insert
    }


def scrape_mto(db=None) -> Iterator[dict]:
    """
    Scrape all Music Theory Online articles.

    Yields each article record dict (with '_keywords' key containing the
    keyword list).  If *db* is supplied (a sqlite_utils.Database), records
    are written directly and keyword links are created; the function still
    yields each record for logging/testing.
    """
    from db import upsert_item, add_keywords_to_item  # local import avoids circular dep

    issue_urls = _mto_issue_urls()
    logger.info("Found %d MTO issues to scrape", len(issue_urls))

    for toc_url in issue_urls:
        logger.info("TOC: %s", toc_url)
        toc_soup = _get(toc_url)
        if not toc_soup:
            continue

        volume, issue, year = _parse_vol_issue_year(toc_soup, toc_url)
        article_urls = _article_links_from_toc(toc_soup, toc_url)
        logger.info(
            "  Vol %s No %s (%s): %d articles", volume, issue, year, len(article_urls)
        )

        for art_url in article_urls:
            record = _scrape_mto_article(art_url, volume, issue, year)
            if not record:
                continue

            keywords = record.pop("_keywords", [])

            if db is not None:
                item_id = upsert_item(db, record)
                if keywords:
                    add_keywords_to_item(db, item_id, keywords, source="explicit")

            yield {**record, "_keywords": keywords}


# ---------------------------------------------------------------------------
# Entry point for ad-hoc runs
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    from db import get_db

    database = get_db()
    total = 0
    for rec in scrape_mto(db=database):
        total += 1
        kws = rec.get("_keywords", [])
        print(
            f"[{total:4d}] Vol {rec['volume']} No {rec['issue']} ({rec['year']}) | "
            f"{rec['title'][:60]!r} | {len(kws)} keywords"
        )

    print(f"\nDone. {total} articles scraped.")
