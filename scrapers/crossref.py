"""CrossRef API scraper for paywalled music theory journals.

Fetches article-level metadata (title, authors, DOI, year, volume, issue,
abstract when available) for journals that cannot be scraped directly.
Uses cursor-based pagination to retrieve all works registered with CrossRef
for each target ISSN.

API docs: https://api.crossref.org/swagger-ui/index.html
Polite pool: add ?mailto=<email> to get faster responses from dedicated servers.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Target journals: name → ISSN (print or online)
# ---------------------------------------------------------------------------

TARGET_JOURNALS: dict[str, str] = {
    "Music Theory Spectrum":                "0195-6167",
    "Journal of Music Theory":              "0022-2909",
    "Music Analysis":                       "0262-5245",
    "Music Perception":                     "0730-7829",
    "Journal of the Society for American Music": "1752-1963",
    # Indiana Theory Review: 0741-4242 — no CrossRef records registered
    "Perspectives of New Music":            "0031-6016",
    "Music Theory and Analysis":            "2295-5917",  # online ISSN
}

_BASE = "https://api.crossref.org/works"
_ROWS = 200          # max items per page
_DELAY = 1.0         # seconds between requests (CrossRef recommends ≤ 1 req/s)

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "music-theory-db/1.0 (research metadata harvester; "
        "contact: github.com/music-theory-db)"
    ),
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_json(url: str, params: dict) -> dict | None:
    try:
        resp = _SESSION.get(url, params=params, timeout=20)
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", 30))
            logger.warning("CrossRef rate-limited; sleeping %ds", retry)
            time.sleep(retry)
            resp = _SESSION.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("CrossRef fetch failed (%s): %s", url, exc)
        return None


def _iter_works(issn: str) -> Iterator[dict]:
    """Yield every work registered under *issn* via cursor pagination."""
    cursor = "*"
    while True:
        data = _get_json(
            _BASE,
            {
                "filter": f"issn:{issn}",
                "rows": _ROWS,
                "cursor": cursor,
                "select": (
                    "DOI,title,author,issued,volume,issue,"
                    "abstract,type,container-title,ISSN"
                ),
            },
        )
        time.sleep(_DELAY)

        if data is None:
            break

        message = data.get("message", {})
        items = message.get("items", [])
        if not items:
            break

        yield from items

        next_cursor = message.get("next-cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor


def _extract_year(item: dict) -> int | None:
    parts = (item.get("issued") or {}).get("date-parts", [[]])
    if parts and parts[0]:
        try:
            return int(parts[0][0])
        except (TypeError, ValueError):
            pass
    return None


def _extract_authors(item: dict) -> list[str]:
    authors = []
    for a in item.get("author") or []:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        name = f"{given} {family}".strip() if given else family
        if name:
            authors.append(name)
    return authors


def _clean_abstract(raw: str | None) -> str | None:
    """Strip JATS XML tags that CrossRef embeds in abstracts."""
    if not raw:
        return None
    import re
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _to_record(item: dict, journal_name: str) -> dict | None:
    """Convert a CrossRef work item to a DB-ready record dict."""
    doi = (item.get("DOI") or "").strip()
    titles = item.get("title") or []
    title = titles[0].strip() if titles else None
    if not title:
        return None

    # Only harvest journal articles
    if item.get("type") not in ("journal-article", "proceedings-article", None):
        return None

    authors = _extract_authors(item)
    year = _extract_year(item)
    abstract = _clean_abstract(item.get("abstract"))

    container = item.get("container-title") or []
    journal = container[0].strip() if container else journal_name

    return {
        "item_type": "article",
        "title": title,
        "authors": json.dumps(authors),
        "year": year,
        "abstract": abstract,
        "doi": doi or None,
        "journal": journal,
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "source": "crossref",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_crossref(
    db=None,
    journals: dict[str, str] | None = None,
) -> dict[str, int]:
    """
    Harvest CrossRef metadata for *journals* (default: TARGET_JOURNALS).

    Parameters
    ----------
    db:
        sqlite_utils.Database instance.  If None, opens the default DB.
    journals:
        Dict mapping journal name → ISSN.  Defaults to TARGET_JOURNALS.

    Returns
    -------
    Dict mapping journal name → number of records upserted.
    """
    if db is None:
        from db import get_db
        db = get_db()
    if journals is None:
        journals = TARGET_JOURNALS

    from db import upsert_item, add_keywords_to_item
    from pipeline.normalize import extract_keywords

    counts: dict[str, int] = {}

    for journal_name, issn in journals.items():
        logger.info("CrossRef: harvesting %s (ISSN %s)", journal_name, issn)
        n = 0
        for item in _iter_works(issn):
            record = _to_record(item, journal_name)
            if record is None:
                continue
            item_id = upsert_item(db, record)

            # Extract keywords from abstract when available
            if record.get("abstract"):
                kws = extract_keywords(record["abstract"])
                if kws:
                    add_keywords_to_item(
                        db, item_id, kws,
                        source="extracted", weight=0.8,
                    )
            n += 1

        counts[journal_name] = n
        logger.info("  → %d records", n)
        print(f"  {journal_name}: {n} records")

    return counts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Harvest CrossRef metadata")
    parser.add_argument(
        "--journal",
        metavar="NAME",
        help="Harvest only this journal (must match TARGET_JOURNALS key exactly)",
    )
    args = parser.parse_args()

    if args.journal:
        if args.journal not in TARGET_JOURNALS:
            parser.error(
                f"{args.journal!r} not in TARGET_JOURNALS. "
                f"Options: {list(TARGET_JOURNALS)}"
            )
        journals = {args.journal: TARGET_JOURNALS[args.journal]}
    else:
        journals = TARGET_JOURNALS

    counts = scrape_crossref(journals=journals)
    total = sum(counts.values())
    print(f"\nDone. {total} records across {len(counts)} journals.")
    for name, n in counts.items():
        print(f"  {name}: {n}")
