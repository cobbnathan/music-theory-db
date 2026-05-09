"""Google Books API scraper for academic music theory volumes.

Searches the Google Books API for music theory titles from major academic
publishers, extracting book-level metadata and — for edited volumes with a
parseable table of contents — chapter-level records.

API docs: https://developers.google.com/books/docs/v1/using
Requires: GOOGLE_BOOKS_API_KEY environment variable.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")

_BASE = "https://www.googleapis.com/books/v1/volumes"
_DELAY = 1.0          # seconds between every API call
_MAX_PER_QUERY = 200  # hard cap per search query
_PAGE_SIZE = 40       # Google Books max per request

SEARCH_QUERIES: list[str] = [
    "music theory",
    "music analysis",
    "music harmony",
    "counterpoint music",
    "Schenkerian analysis",
    "post-tonal music theory",
    "musical form analysis",
    "music cognition",
    "rhythm meter music",
    "transformational music theory",
]

# Publisher filter — only keep volumes whose publisher field contains one of these
ALLOWED_PUBLISHERS: list[str] = [
    "Oxford", "Cambridge", "Chicago", "MIT", "Routledge", "Norton", "Yale",
    "Princeton", "California", "Michigan", "Rochester", "Eastman", "Duke",
    "Cornell", "Pennsylvania", "Harvard", "Indiana",
]

# Publisher-targeted search: subjects × publishers cross-product
PUBLISHER_SUBJECTS: list[str] = [
    "music theory",
    "music analysis",
]

# inpublisher: strings as they appear in Google Books publisher metadata
PUBLISHER_TARGETS: list[str] = [
    "Oxford University Press",
    "Cambridge University Press",
    "University of Chicago Press",
    "MIT Press",
    "Routledge",
    "W. W. Norton",
    "Yale University Press",
    "Princeton University Press",
    "University of California Press",
    "University of Michigan Press",
    "University of Rochester Press",
    "Duke University Press",
    "Cornell University Press",
]

_MIN_YEAR = 1950  # drop books published before this year at ingest

# Patterns that indicate an edited volume
_EDITOR_RE = re.compile(
    r"\b(ed\.|editor|editors|edited\s+by)\b", re.IGNORECASE
)

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "music-theory-db/1.0 (research metadata harvester; "
                  "github.com/music-theory-db)",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_json(url: str, params: dict) -> dict | None:
    """GET *url* with *params*, return parsed JSON or None on error."""
    try:
        resp = _SESSION.get(url, params=params, timeout=20)
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", 30))
            logger.warning("Google Books rate-limited; sleeping %ds", retry)
            time.sleep(retry)
            resp = _SESSION.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Google Books fetch failed (%s): %s", url, exc)
        return None


def _is_allowed_publisher(publisher: str) -> bool:
    """Return True if *publisher* contains any of ALLOWED_PUBLISHERS (case-insensitive)."""
    pub_lower = publisher.lower()
    return any(p.lower() in pub_lower for p in ALLOWED_PUBLISHERS)


def _extract_isbn13(industry_ids: list[dict]) -> str | None:
    """Return the ISBN-13 from a list of industryIdentifiers dicts, or None."""
    for item in industry_ids or []:
        if item.get("type") == "ISBN_13":
            return item.get("identifier")
    # Fall back to ISBN-10 if no ISBN-13
    for item in industry_ids or []:
        if item.get("type") == "ISBN_10":
            return item.get("identifier")
    return None


def _extract_year(published_date: str | None) -> int | None:
    """Parse the first four digits from a publishedDate string."""
    if not published_date:
        return None
    m = re.search(r"\b(\d{4})\b", published_date)
    return int(m.group(1)) if m else None


def _is_edited_volume(authors: list[str], description: str | None) -> bool:
    """Return True when the work appears to be an edited volume."""
    for a in authors:
        if _EDITOR_RE.search(a):
            return True
    if description and _EDITOR_RE.search(description):
        return True
    return False


def _iter_query(query: str) -> Iterator[dict]:
    """
    Yield raw Google Books volume dicts for *query*, paginating up to
    _MAX_PER_QUERY results with _PAGE_SIZE items per request.
    """
    fetched = 0
    start_index = 0

    while fetched < _MAX_PER_QUERY:
        params: dict = {
            "q": query,
            "maxResults": _PAGE_SIZE,
            "startIndex": start_index,
            "printType": "books",
            "key": _API_KEY,
        }
        data = _get_json(_BASE, params)
        time.sleep(_DELAY)

        if data is None:
            break

        items = data.get("items") or []
        if not items:
            break

        yield from items
        fetched += len(items)
        start_index += len(items)

        # Google Books caps totalItems at 1000 regardless; also stop if short page
        if len(items) < _PAGE_SIZE:
            break


def _build_book_record(volume_info: dict) -> dict:
    """Convert a Google Books volumeInfo dict to a DB-ready record dict."""
    authors_raw = volume_info.get("authors") or []
    publisher = volume_info.get("publisher") or ""
    year = _extract_year(volume_info.get("publishedDate"))
    isbn = _extract_isbn13(volume_info.get("industryIdentifiers") or [])
    description = volume_info.get("description") or None
    categories = volume_info.get("categories") or []
    title = (volume_info.get("title") or "").strip()

    # Combine title and subtitle
    subtitle = (volume_info.get("subtitle") or "").strip()
    if subtitle:
        title = f"{title}: {subtitle}"

    book_type = (
        "edited_volume"
        if _is_edited_volume(authors_raw, description)
        else "monograph"
    )

    # Cover thumbnail — prefer larger zoom=2, fall back to zoom=1 thumbnail
    image_links = volume_info.get("imageLinks") or {}
    thumbnail = (
        image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or None
    )
    # Force HTTPS and strip edge-curl parameter for cleaner rendering
    if thumbnail:
        thumbnail = thumbnail.replace("http://", "https://").replace("&edge=curl", "")

    return {
        "item_type": "book",
        "title": title,
        "authors": authors_raw,   # list — _prepare() in db.py will JSON-encode
        "year": year,
        "abstract": description,
        "isbn": isbn,
        "publisher": publisher,
        "book_type": book_type,
        "cover_url": thumbnail,
        "source": "google_books",
        # categories stored separately as keywords; not a DB column
        "_categories": categories,
    }


# ---------------------------------------------------------------------------
# Table-of-contents chapter extraction
# ---------------------------------------------------------------------------

# Patterns for attributable chapter lines.  We accept several common formats:
#   "Jane Smith, 'Chapter Title'"
#   "Jane Smith — Chapter Title"
#   "Chapter Title, by Jane Smith"
# The pattern must capture an author-like proper-name fragment.
_TOC_AUTHOR_LINE_RE = re.compile(
    r"""
    (?:
        # "Author Name, 'Title'" or "Author Name, \"Title\""
        (?P<author1>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*,\s*['""](?P<title1>[^'""\n]{5,})['""]
        |
        # "Author Name — Title" (em-dash or long dash)
        (?P<author2>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*[—–]\s*(?P<title2>[^\n]{5,})
        |
        # "Title, by Author Name"
        (?P<title3>[^\n]{5,}),\s+by\s+(?P<author3>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)
    )
    """,
    re.VERBOSE,
)


def _parse_toc_chapters(toc_text: str) -> list[dict]:
    """
    Parse *toc_text* and return a list of dicts with keys ``title`` and
    ``authors`` for each author-attributable chapter line found.
    Returns empty list if no attributable chapters are found.
    """
    chapters: list[dict] = []
    for m in _TOC_AUTHOR_LINE_RE.finditer(toc_text):
        g = m.groupdict()
        if g.get("author1") and g.get("title1"):
            chapters.append({"title": g["title1"].strip(), "authors": [g["author1"].strip()]})
        elif g.get("author2") and g.get("title2"):
            chapters.append({"title": g["title2"].strip(), "authors": [g["author2"].strip()]})
        elif g.get("title3") and g.get("author3"):
            chapters.append({"title": g["title3"].strip(), "authors": [g["author3"].strip()]})
    return chapters


def _fetch_toc(volume_id: str) -> str | None:
    """
    Fetch the full volume detail for *volume_id* and return the
    tableOfContents string, or None if unavailable.
    """
    data = _get_json(f"{_BASE}/{volume_id}", {"key": _API_KEY})
    time.sleep(_DELAY)
    if data is None:
        return None
    return data.get("volumeInfo", {}).get("tableOfContents")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_google_books(db=None) -> dict[str, int]:
    """
    Harvest Google Books metadata for academic music theory volumes.

    Parameters
    ----------
    db:
        sqlite_utils.Database instance.  If None, opens the default DB.

    Returns
    -------
    Dict with keys ``found``, ``inserted``, ``skipped``.
    """
    if not _API_KEY:
        print(
            "WARNING: GOOGLE_BOOKS_API_KEY environment variable is not set. "
            "Skipping Google Books scrape."
        )
        return {"found": 0, "inserted": 0, "skipped": 0}

    if db is None:
        from db import get_db
        db = get_db()

    from db import upsert_item, add_keywords_to_item

    counts = {"found": 0, "inserted": 0, "skipped": 0}

    for query in SEARCH_QUERIES:
        logger.info("Google Books: searching '%s'", query)
        print(f"\nGoogle Books: searching '{query}' …")
        query_found = 0
        query_inserted = 0
        query_skipped = 0

        for item in _iter_query(query):
            vi = item.get("volumeInfo") or {}
            publisher = vi.get("publisher") or ""

            # Filter to allowed academic publishers
            if not _is_allowed_publisher(publisher):
                continue

            record = _build_book_record(vi)
            if not record["title"]:
                continue

            categories: list[str] = record.pop("_categories", [])
            query_found += 1

            item_id = upsert_item(db, record)

            # Explicit subject keywords from Google Books categories
            if categories:
                add_keywords_to_item(db, item_id, categories, source="explicit")

            # Check whether this was a new insertion or an update
            # (upsert_item always returns an id; track via simple counter heuristic)
            query_inserted += 1

            # For edited volumes: attempt to fetch and parse table of contents
            if record.get("book_type") == "edited_volume":
                volume_id = item.get("id")
                if volume_id:
                    toc_text = _fetch_toc(volume_id)
                    if toc_text:
                        chapters = _parse_toc_chapters(toc_text)
                        for ch in chapters:
                            ch_record = {
                                "item_type": "chapter",
                                "title": ch["title"],
                                "authors": ch["authors"],
                                "year": record.get("year"),
                                "publisher": publisher,
                                "parent_id": item_id,
                                "source": "google_books",
                            }
                            ch_id = upsert_item(db, ch_record)
                            if categories:
                                add_keywords_to_item(
                                    db, ch_id, categories, source="explicit"
                                )
                        if chapters:
                            db.conn.execute(
                                "UPDATE items SET chapters_available = ? WHERE id = ?",
                                [len(chapters), item_id],
                            )
                            db.conn.commit()
                            logger.info(
                                "  → %d chapters from ToC for '%s'",
                                len(chapters), record["title"],
                            )

        counts["found"] += query_found
        counts["inserted"] += query_inserted
        counts["skipped"] += query_skipped

        print(
            f"  found: {query_found}  inserted/updated: {query_inserted}  "
            f"skipped: {query_skipped}"
        )

    total_found = counts["found"]
    total_ins = counts["inserted"]
    total_skip = counts["skipped"]
    print(
        f"\nGoogle Books done. "
        f"Total found: {total_found}  inserted/updated: {total_ins}  "
        f"skipped: {total_skip}"
    )
    return counts


def scrape_google_books_by_publisher(db=None) -> dict[str, int]:
    """
    Harvest Google Books using publisher-targeted queries.

    For each combination of PUBLISHER_SUBJECTS × PUBLISHER_TARGETS, issues a
    query of the form ``music theory inpublisher:"Oxford University Press"``
    and upserts matching books.  Deduplication is handled by upsert_item.

    Returns dict with keys ``found``, ``inserted``, ``skipped``.
    """
    if not _API_KEY:
        print("WARNING: GOOGLE_BOOKS_API_KEY not set. Skipping.")
        return {"found": 0, "inserted": 0, "skipped": 0}

    if db is None:
        from db import get_db
        db = get_db()

    from db import upsert_item, add_keywords_to_item

    counts = {"found": 0, "inserted": 0, "skipped": 0}
    total_queries = len(PUBLISHER_SUBJECTS) * len(PUBLISHER_TARGETS)
    n = 0

    for subject in PUBLISHER_SUBJECTS:
        for publisher in PUBLISHER_TARGETS:
            n += 1
            query = f'{subject} inpublisher:"{publisher}"'
            print(f"[{n}/{total_queries}] {query} …", flush=True)
            q_found = q_ins = q_skip = 0

            for item in _iter_query(query):
                vi = item.get("volumeInfo") or {}

                # Year filter — skip pre-1950
                year = _extract_year(vi.get("publishedDate"))
                if year and year < _MIN_YEAR:
                    q_skip += 1
                    continue

                pub = vi.get("publisher") or ""
                if not _is_allowed_publisher(pub):
                    q_skip += 1
                    continue

                record = _build_book_record(vi)
                if not record["title"]:
                    q_skip += 1
                    continue

                categories: list[str] = record.pop("_categories", [])
                q_found += 1

                item_id = upsert_item(db, record)

                if categories:
                    add_keywords_to_item(db, item_id, categories, source="explicit")

                q_ins += 1

                if record.get("book_type") == "edited_volume":
                    volume_id = item.get("id")
                    if volume_id:
                        toc_text = _fetch_toc(volume_id)
                        if toc_text:
                            chapters = _parse_toc_chapters(toc_text)
                            for ch in chapters:
                                ch_record = {
                                    "item_type": "chapter",
                                    "title": ch["title"],
                                    "authors": ch["authors"],
                                    "year": record.get("year"),
                                    "publisher": pub,
                                    "parent_id": item_id,
                                    "source": "google_books",
                                }
                                ch_id = upsert_item(db, ch_record)
                                if categories:
                                    add_keywords_to_item(
                                        db, ch_id, categories, source="explicit"
                                    )
                            if chapters:
                                db.conn.execute(
                                    "UPDATE items SET chapters_available = ? WHERE id = ?",
                                    [len(chapters), item_id],
                                )
                                db.conn.commit()

            counts["found"] += q_found
            counts["inserted"] += q_ins
            counts["skipped"] += q_skip
            print(f"  found: {q_found}  inserted/updated: {q_ins}  skipped: {q_skip}")

    print(
        f"\nPublisher search done. "
        f"Total found: {counts['found']}  inserted/updated: {counts['inserted']}  "
        f"skipped: {counts['skipped']}"
    )
    return counts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Harvest Google Books metadata for music theory volumes"
    )
    parser.add_argument(
        "--query",
        metavar="QUERY",
        help="Run only this search query instead of all default queries",
    )
    parser.add_argument(
        "--publisher-search",
        action="store_true",
        help="Run publisher-targeted search (subject × publisher cross-product)",
    )
    args = parser.parse_args()

    from db import get_db

    _db = get_db()

    if args.publisher_search:
        result = scrape_google_books_by_publisher(_db)
    elif args.query:
        original = SEARCH_QUERIES[:]
        SEARCH_QUERIES.clear()
        SEARCH_QUERIES.append(args.query)
        result = scrape_google_books(_db)
        SEARCH_QUERIES.clear()
        SEARCH_QUERIES.extend(original)
    else:
        result = scrape_google_books(_db)

    print(
        f"\nDone. found={result['found']}  "
        f"inserted/updated={result['inserted']}  skipped={result['skipped']}"
    )
