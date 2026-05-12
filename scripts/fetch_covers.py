#!/usr/bin/env python3
"""Fetch missing book cover URLs from Open Library by ISBN.

Uses the Open Library covers endpoint — no API key, no daily quota.
HEAD ISBN/{isbn}-M.jpg?default=false → 200 means a cover exists; 404 means none.

Usage:
  python3 scripts/fetch_covers.py
  python3 scripts/fetch_covers.py --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import time

import requests

ROOT = __import__('pathlib').Path(__file__).parent.parent
DB   = ROOT / "data" / "music_theory.db"

_COVER_CHECK = "https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg?default=false"
_COVER_URL   = "https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
_DELAY = 0.4   # seconds between requests (~2.5 req/s)


def fetch_covers(dry_run: bool = False) -> None:
    conn = sqlite3.connect(str(DB))
    session = requests.Session()
    session.headers["User-Agent"] = (
        "music-theory-db/1.0 (research; github.com/cobbnathan/music-theory-db)"
    )

    rows = conn.execute("""
        SELECT id, isbn FROM items
        WHERE item_type = 'book'
          AND (cover_url IS NULL OR cover_url = '')
          AND isbn IS NOT NULL AND isbn != ''
        ORDER BY year DESC
    """).fetchall()

    print(f"Checking Open Library covers for {len(rows)} books…")
    found = updated = errors = 0

    for i, (item_id, isbn) in enumerate(rows, 1):
        check_url = _COVER_CHECK.format(isbn=isbn)
        try:
            r = session.head(check_url, timeout=10, allow_redirects=True)
        except Exception as e:
            errors += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(rows)}] error: {e}")
            time.sleep(_DELAY)
            continue

        if r.status_code == 200:
            cover = _COVER_URL.format(isbn=isbn)
            found += 1
            if dry_run:
                print(f"  [{i}/{len(rows)}] ISBN {isbn} → {cover}")
            else:
                conn.execute(
                    "UPDATE items SET cover_url=? WHERE id=?", (cover, item_id)
                )
                conn.commit()
                updated += 1
                if i <= 10 or i % 100 == 0:
                    print(f"  [{i}/{len(rows)}] {found} covers found so far")

        time.sleep(_DELAY)

    print(f"\nDone. covers found: {found}  updated: {updated}  errors: {errors}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print URLs without writing to DB")
    args = parser.parse_args()
    fetch_covers(dry_run=args.dry_run)
