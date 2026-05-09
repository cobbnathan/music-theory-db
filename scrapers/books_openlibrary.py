"""Open Library enrichment scraper for books already in the DB.

For every item in the ``items`` table that has an ISBN but has not yet been
enriched via Open Library (``ol_enriched = 0``), this scraper:

  1. Queries the Open Library Books API for subject tags.
  2. Merges any new subjects into ``keywords`` with source='explicit'.
  3. Records the cover ISBN from OL (may differ from the book's own ISBN).
  4. Marks the item ``ol_enriched = 1`` so it is skipped on future runs.

API docs: https://openlibrary.org/dev/docs/api
"""
from __future__ import annotations

import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

_BASE = "https://openlibrary.org/api/books"
_DELAY = 1.0  # seconds between API calls

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "music-theory-db/1.0 (research metadata harvester; "
                  "github.com/music-theory-db)",
})


# ---------------------------------------------------------------------------
# Schema migration (idempotent)
# ---------------------------------------------------------------------------

def _ensure_ol_columns(db) -> None:
    """Add ol_enriched and cover_isbn columns if they don't already exist."""
    for col, definition in [
        ("ol_enriched", "INTEGER DEFAULT 0"),
        ("cover_isbn", "TEXT"),
    ]:
        try:
            db.conn.execute(f"ALTER TABLE items ADD COLUMN {col} {definition}")
            db.conn.commit()
            logger.info("Added column 'items.%s'", col)
        except Exception:
            # Column already exists — safe to ignore
            pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_json(isbn: str) -> dict | None:
    """
    Query the Open Library Books API for *isbn*.
    Returns the parsed data dict for that ISBN, or None on error / not found.
    """
    params = {
        "bibkeys": f"ISBN:{isbn}",
        "format": "json",
        "jscmd": "data",
    }
    try:
        resp = _SESSION.get(_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data.get(f"ISBN:{isbn}")
    except Exception as exc:
        logger.warning("Open Library fetch failed for ISBN %s: %s", isbn, exc)
        return None


_OL_REJECT_RE = re.compile(
    r"""
    # Person + lifespan dates (e.g. "Wagner, Richard, 1813-1883")
    \d{4}\s*[-–]\s*\d{4}
    # Trailing date after comma (e.g. "..., 1950-")
    |,\s*\d{4}\s*-\s*$
    # Parenthetical qualifier (e.g. "Conductors (music)")
    |\(
    # Non-ASCII characters (foreign-language subject headings)
    |[^\x00-\x7F]
    """,
    re.VERBOSE,
)

_OL_REJECT_EXACT: frozenset[str] = frozenset({
    "biography", "history and criticism", "criticism and interpretation",
    "social aspects", "philosophy and aesthetics", "analysis, appreciation",
    "letters", "music", "musicians", "composers", "songs",
    "musical criticism", "discography",
})


def _ol_subject_ok(name: str) -> bool:
    """Return False for LCSH headings that are junk for music-theory tagging."""
    low = name.lower().strip()
    if low in _OL_REJECT_EXACT:
        return False
    if _OL_REJECT_RE.search(name):
        return False
    # Reject very long strings (library catalog phrases, not keywords)
    if len(name) > 60:
        return False
    return True


def _extract_subjects(ol_data: dict) -> list[str]:
    """Return a filtered list of subject strings from an OL data dict."""
    subjects: list[str] = []
    for subj in ol_data.get("subjects") or []:
        if isinstance(subj, dict):
            name = (subj.get("name") or "").strip()
        else:
            name = str(subj).strip()
        if name and _ol_subject_ok(name):
            subjects.append(name)
    return subjects


def _extract_cover_isbn(ol_data: dict) -> str | None:
    """
    Return the ISBN shown in the OL cover URL, which may differ from the
    book's primary ISBN (e.g. a paperback vs. hardback ISBN).
    """
    identifiers = ol_data.get("identifiers") or {}
    # OL sometimes lists the cover ISBN under isbn_13 or isbn_10
    for key in ("isbn_13", "isbn_10"):
        vals = identifiers.get(key) or []
        if vals:
            return vals[0]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_openlibrary(db=None) -> dict[str, int]:
    """
    Enrich books in *db* that have an ISBN but have not yet been OL-enriched.

    Parameters
    ----------
    db:
        sqlite_utils.Database instance.  If None, opens the default DB.

    Returns
    -------
    Dict with keys ``processed``, ``enriched``, ``skipped``.
    """
    if db is None:
        from db import get_db
        db = get_db()

    _ensure_ol_columns(db)

    from db import add_keywords_to_item

    rows = list(
        db.execute(
            """
            SELECT id, isbn
            FROM items
            WHERE isbn IS NOT NULL
              AND isbn != ''
              AND (ol_enriched IS NULL OR ol_enriched = 0)
            ORDER BY id
            """
        ).fetchall()
    )

    total = len(rows)
    print(f"Open Library: {total} item(s) to enrich …")

    processed = 0
    enriched = 0
    skipped = 0

    for item_id, isbn in rows:
        logger.info("OL: enriching item %d (ISBN %s)", item_id, isbn)

        ol_data = _get_json(isbn)
        time.sleep(_DELAY)

        if ol_data is None:
            logger.info("  → not found in Open Library, marking skipped")
            # Mark as attempted so we don't retry every run
            db.conn.execute(
                "UPDATE items SET ol_enriched = 1 WHERE id = ?", [item_id]
            )
            db.conn.commit()
            skipped += 1
            processed += 1
            continue

        # Subject tags
        subjects = _extract_subjects(ol_data)
        if subjects:
            add_keywords_to_item(db, item_id, subjects, source="explicit")

        # Cover ISBN
        cover_isbn = _extract_cover_isbn(ol_data)
        if cover_isbn:
            try:
                db.conn.execute(
                    "UPDATE items SET cover_isbn = ? WHERE id = ?",
                    [cover_isbn, item_id],
                )
            except Exception as exc:
                logger.warning("Could not set cover_isbn for item %d: %s", item_id, exc)

        # Mark enriched
        db.conn.execute(
            "UPDATE items SET ol_enriched = 1 WHERE id = ?", [item_id]
        )
        db.conn.commit()

        enriched += 1
        processed += 1

        if processed % 25 == 0:
            print(f"  … {processed}/{total} processed")

    print(
        f"\nOpen Library done. "
        f"processed: {processed}  enriched: {enriched}  skipped: {skipped}"
    )
    return {"processed": processed, "enriched": enriched, "skipped": skipped}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Enrich book records via the Open Library Books API"
    )
    args = parser.parse_args()

    from db import get_db

    result = enrich_openlibrary(get_db())
    print(
        f"\nDone. processed={result['processed']}  "
        f"enriched={result['enriched']}  skipped={result['skipped']}"
    )
