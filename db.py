"""Database helpers: schema init, deduplication-aware upserts, keyword linking."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import sqlite_utils

DB_PATH = Path(__file__).parent / "data" / "music_theory.db"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def get_db(path: Path = DB_PATH) -> sqlite_utils.Database:
    db = sqlite_utils.Database(path)
    _ensure_schema(db)
    return db


def _ensure_schema(db: sqlite_utils.Database) -> None:
    if "items" not in db.table_names():
        db["items"].create(
            {
                "id": int,
                "item_type": str,       # 'article' | 'book' | 'chapter'
                "title": str,
                "authors": str,         # JSON array
                "year": int,
                "abstract": str,
                "doi": str,
                "isbn": str,
                "url": str,
                "journal": str,
                "volume": str,
                "issue": str,
                "publisher": str,
                "book_type": str,       # 'monograph' | 'edited_volume' | 'textbook'
                "parent_id": int,       # → items.id for chapters
                "cover_isbn": str,
                "chapters_available": int,  # 0/1 boolean
                "source": str,
                "scraped_at": str,
            },
            pk="id",
            not_null={"item_type", "title", "source", "scraped_at"},
            defaults={"chapters_available": 0},
        )
        db["items"].create_index(["doi"], unique=True, if_not_exists=True)
        db["items"].create_index(["isbn"], unique=True, if_not_exists=True)
        db["items"].create_index(["item_type"], if_not_exists=True)
        db["items"].create_index(["year"], if_not_exists=True)
        db["items"].create_index(["journal"], if_not_exists=True)

    if "keywords" not in db.table_names():
        db["keywords"].create(
            {"id": int, "keyword": str, "weight": float},
            pk="id",
            not_null={"keyword"},
            defaults={"weight": 1.0},
        )
        db["keywords"].create_index(["keyword"], unique=True, if_not_exists=True)

    if "item_keywords" not in db.table_names():
        db["item_keywords"].create(
            {
                "item_id": int,
                "keyword_id": int,
                "source": str,  # 'explicit' | 'extracted'
            },
            not_null={"item_id", "keyword_id", "source"},
            foreign_keys=[
                ("item_id", "items", "id"),
                ("keyword_id", "keywords", "id"),
            ],
        )
        db["item_keywords"].create_index(
            ["item_id", "keyword_id"], unique=True, if_not_exists=True
        )


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def _find_existing(db: sqlite_utils.Database, record: dict) -> int | None:
    """Return the id of an existing row that matches record, or None."""
    items = db["items"]

    # 1. DOI match (articles/chapters)
    doi = (record.get("doi") or "").strip()
    if doi:
        row = next(items.rows_where("doi = ?", [doi], select="id"), None)
        if row:
            return row["id"]

    # 2. ISBN match (books)
    isbn = (record.get("isbn") or "").strip()
    if isbn:
        row = next(items.rows_where("isbn = ?", [isbn], select="id"), None)
        if row:
            return row["id"]

    # 3. title + first-author + year fallback
    title = (record.get("title") or "").strip().lower()
    year = record.get("year")
    authors_raw = record.get("authors", "[]")
    try:
        authors_list = json.loads(authors_raw) if isinstance(authors_raw, str) else authors_raw
    except (json.JSONDecodeError, TypeError):
        authors_list = []
    first_author = (authors_list[0] if authors_list else "").strip().lower()

    if title and first_author and year:
        for row in items.rows_where(
            "lower(title) = ? AND year = ?",
            [title, year],
            select="id, authors",
        ):
            try:
                existing_authors = json.loads(row["authors"] or "[]")
            except (json.JSONDecodeError, TypeError):
                existing_authors = []
            existing_first = (existing_authors[0] if existing_authors else "").strip().lower()
            if existing_first == first_author:
                return row["id"]

    return None


# ---------------------------------------------------------------------------
# Public insert / upsert API
# ---------------------------------------------------------------------------

def _prepare(record: dict) -> dict:
    """Coerce types and fill scraped_at before writing."""
    r = dict(record)
    if isinstance(r.get("authors"), list):
        r["authors"] = json.dumps(r["authors"])
    r.setdefault("scraped_at", datetime.now(timezone.utc).isoformat())
    r.setdefault("chapters_available", 0)
    return r


def upsert_item(db: sqlite_utils.Database, record: dict) -> int:
    """
    Insert record if no duplicate exists, otherwise update in place.
    Returns the id of the inserted or updated row.
    """
    r = _prepare(record)
    existing_id = _find_existing(db, r)

    if existing_id is not None:
        r["id"] = existing_id
        r["scraped_at"] = datetime.now(timezone.utc).isoformat()
        db["items"].update(existing_id, r)
        return existing_id

    return db["items"].insert(r, pk="id").last_pk


def upsert_items(db: sqlite_utils.Database, records: Iterable[dict]) -> list[int]:
    """Bulk upsert; returns list of ids in insertion order."""
    return [upsert_item(db, r) for r in records]


# ---------------------------------------------------------------------------
# Keyword API
# ---------------------------------------------------------------------------

def upsert_keyword(db: sqlite_utils.Database, keyword: str, weight: float = 1.0) -> int:
    """Insert keyword if new, update weight if changed. Returns keyword id."""
    keyword = keyword.strip().lower()
    if not keyword:
        raise ValueError("keyword must be a non-empty string")

    row = next(db["keywords"].rows_where("keyword = ?", [keyword], select="id, weight"), None)
    if row:
        if row["weight"] != weight:
            db["keywords"].update(row["id"], {"weight": weight})
        return row["id"]

    return db["keywords"].insert({"keyword": keyword, "weight": weight}, pk="id").last_pk


def link_item_keyword(
    db: sqlite_utils.Database,
    item_id: int,
    keyword_id: int,
    source: str = "explicit",
) -> None:
    """Create item↔keyword join row, ignoring duplicates."""
    db["item_keywords"].insert(
        {"item_id": item_id, "keyword_id": keyword_id, "source": source},
        ignore=True,
    )


def add_keywords_to_item(
    db: sqlite_utils.Database,
    item_id: int,
    keywords: Iterable[str],
    source: str = "explicit",
    weight: float = 1.0,
) -> None:
    """Upsert each keyword and link it to item_id."""
    for kw in keywords:
        kid = upsert_keyword(db, kw, weight=weight)
        link_item_keyword(db, item_id, kid, source=source)


# ---------------------------------------------------------------------------
# Convenience queries
# ---------------------------------------------------------------------------

def get_item(db: sqlite_utils.Database, item_id: int) -> dict | None:
    return next(db["items"].rows_where("id = ?", [item_id]), None)


def get_keywords_for_item(db: sqlite_utils.Database, item_id: int) -> list[dict]:
    return list(
        db.execute(
            """
            SELECT k.keyword, k.weight, ik.source
            FROM keywords k
            JOIN item_keywords ik ON ik.keyword_id = k.id
            WHERE ik.item_id = ?
            ORDER BY k.weight DESC
            """,
            [item_id],
        ).fetchall()
    )
