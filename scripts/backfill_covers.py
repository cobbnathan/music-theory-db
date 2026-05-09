#!/usr/bin/env python3
"""Backfill cover_url for books using the Google Books API.

Queries Google Books by ISBN for each book lacking a stored cover_url.
Falls back to the Open Library Books API (no key required) if Google
returns no thumbnail for a given ISBN.

Usage:
  GOOGLE_BOOKS_API_KEY=<key> python scripts/backfill_covers.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
from pathlib import Path

import requests

ROOT    = Path(__file__).parent.parent
DB      = ROOT / "data" / "music_theory.db"
GB_URL  = "https://www.googleapis.com/books/v1/volumes"
OL_URL  = "https://openlibrary.org/api/books"
API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
OL_BATCH = 20


def fetch_gb_thumbnail(isbn: str, session: requests.Session) -> str | None:
    """Return a Google Books thumbnail URL for the ISBN, or None.
    Retries up to 4 times with exponential backoff on 429/503."""
    params: dict = {"q": f"isbn:{isbn}", "maxResults": 1}
    if API_KEY:
        params["key"] = API_KEY
    for attempt in range(3):
        try:
            r = session.get(GB_URL, params=params, timeout=12)
            if r.status_code == 429:
                return "QUOTA_EXCEEDED"
            if r.status_code == 503:
                wait = 2 ** attempt + 1
                print(f"    503, waiting {wait}s…")
                time.sleep(wait)
                continue
            r.raise_for_status()
            items = r.json().get("items") or []
            if not items:
                return None
            image_links = items[0].get("volumeInfo", {}).get("imageLinks") or {}
            thumb = image_links.get("thumbnail") or image_links.get("smallThumbnail")
            if thumb:
                thumb = thumb.replace("http://", "https://").replace("&edge=curl", "")
            return thumb or None
        except Exception as exc:
            if attempt == 2:
                print(f"    GB error for {isbn}: {exc}")
            else:
                time.sleep(2 ** attempt)
    return None


def fetch_ol_batch(isbns: list[str], session: requests.Session) -> dict[str, str]:
    """Return {isbn: cover_url} for ISBNs that have OL covers."""
    bibkeys = ",".join(f"ISBN:{isbn}" for isbn in isbns)
    try:
        r = session.get(OL_URL, params={"bibkeys": bibkeys, "format": "json", "jscmd": "data"}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"    OL error: {exc}")
        return {}
    result = {}
    for key, book in data.items():
        isbn = key.removeprefix("ISBN:")
        cover = book.get("cover", {}).get("medium")
        if cover:
            result[isbn] = cover.replace("http://", "https://")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not API_KEY:
        print("WARNING: GOOGLE_BOOKS_API_KEY not set — will use Open Library only.")

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT id, title, isbn, cover_isbn
        FROM items
        WHERE item_type = 'book'
          AND (cover_url IS NULL OR cover_url = '')
          AND (isbn IS NOT NULL OR cover_isbn IS NOT NULL)
        ORDER BY id
        """
    ).fetchall()

    print(f"{len(rows)} books need cover backfill")
    if args.dry_run:
        print("(dry-run — no DB writes)")

    session = requests.Session()
    session.headers["User-Agent"] = "music-theory-db/1.0"

    gb_found = ol_found = skipped = 0
    processed = 0

    # Collect ISBNs that miss GB for a batched OL fallback pass
    ol_needed: list[tuple[int, str, str]] = []  # (id, isbn, title)

    for row in rows:
        processed += 1
        isbn = row["cover_isbn"] or row["isbn"]
        title_short = (row["title"] or "")[:55]

        cover_url = None
        if API_KEY:
            cover_url = fetch_gb_thumbnail(isbn, session)

        if cover_url == "QUOTA_EXCEEDED":
            print(f"[{processed}/{len(rows)}] QUOTA EXCEEDED — stopping GB pass.")
            # Queue remaining books for OL fallback
            ol_needed.append((row["id"], isbn, title_short))
            for rem in rows[processed:]:
                rem_isbn = rem["cover_isbn"] or rem["isbn"]
                ol_needed.append((rem["id"], rem_isbn, (rem["title"] or "")[:55]))
            break
        elif cover_url:
            gb_found += 1
            print(f"[{processed}/{len(rows)}] GB ✓  {title_short}")
            if not args.dry_run:
                conn.execute("UPDATE items SET cover_url = ? WHERE id = ?", [cover_url, row["id"]])
                conn.commit()  # commit immediately so kills don't lose work
            time.sleep(1.0)
        else:
            ol_needed.append((row["id"], isbn, title_short))
            print(f"[{processed}/{len(rows)}] GB —  {title_short}")
            time.sleep(1.0)

    if not args.dry_run:
        conn.commit()

    # OL fallback pass in batches
    if ol_needed:
        print(f"\nOL fallback for {len(ol_needed)} books…")
        for batch_start in range(0, len(ol_needed), OL_BATCH):
            batch = ol_needed[batch_start: batch_start + OL_BATCH]
            covers = fetch_ol_batch([t[1] for t in batch], session)
            for item_id, isbn, title_short in batch:
                cover_url = covers.get(isbn)
                if cover_url:
                    ol_found += 1
                    print(f"  OL ✓  {title_short}")
                    if not args.dry_run:
                        conn.execute("UPDATE items SET cover_url = ? WHERE id = ?", [cover_url, item_id])
                        conn.commit()
                else:
                    skipped += 1
            time.sleep(1.0)

    if not args.dry_run:
        conn.commit()
    conn.close()

    total = gb_found + ol_found
    print(f"\nDone.  GB: {gb_found}  OL fallback: {ol_found}  not found: {skipped}")
    if not args.dry_run and total:
        print("Re-run `python scripts/export_static.py` to update data.json")


if __name__ == "__main__":
    main()
