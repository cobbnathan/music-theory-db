"""Flask API for the music-theory-db.

Endpoints
---------
GET /api/keywords                          all keywords weight ≥ 0.02
GET /api/keywords?decade=1990s             filtered to items from 1990–1999
GET /api/items?keyword=<kw>               items tagged with keyword, year DESC
GET /api/items?keyword=<kw>&type=article  filtered by item_type
GET /api/search?q=<query>                 FTS5 across title / authors / abstract
GET /api/stats                            aggregate DB counts
GET /api/health                           liveness check
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from flask import Flask, Response, g, jsonify, request
from flask_caching import Cache
from flask_cors import CORS

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)

cache = Cache(config={
    "CACHE_TYPE":            "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 3600,   # 1 hour
})
cache.init_app(app)

DB_PATH    = Path(__file__).parent.parent / "data" / "music_theory.db"
COVER_BASE = "https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"

# ---------------------------------------------------------------------------
# FTS index management
# ---------------------------------------------------------------------------

# Module-level flag so we only check FTS sync once per process, not per request.
_fts_ready: bool = False


def _sync_fts(conn: sqlite3.Connection) -> None:
    """
    Ensure the FTS5 index exists and is up-to-date.

    We use a *non-content* FTS5 table (no ``content=`` option) so that
    ``SELECT COUNT(*) FROM fts_items`` reliably returns the count of indexed
    rows rather than delegating to the base table.  Rows not yet indexed are
    inserted incrementally, so this is safe to call after each scrape run.
    """
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fts_items'"
    ).fetchone()

    if not exists:
        conn.execute("""
            CREATE VIRTUAL TABLE fts_items USING fts5(
                title, authors, abstract,
                tokenize = 'porter ascii'
            )
        """)
        conn.execute("""
            INSERT INTO fts_items(rowid, title, authors, abstract)
            SELECT id,
                   COALESCE(title,    ''),
                   COALESCE(authors,  ''),
                   COALESCE(abstract, '')
            FROM items
        """)
        conn.commit()
        return

    # Incremental update: add any items whose id is not yet a rowid in fts_items.
    new_rows = conn.execute("""
        SELECT id,
               COALESCE(title,    ''),
               COALESCE(authors,  ''),
               COALESCE(abstract, '')
        FROM items
        WHERE id NOT IN (SELECT rowid FROM fts_items)
    """).fetchall()

    if new_rows:
        conn.executemany(
            "INSERT INTO fts_items(rowid, title, authors, abstract) VALUES (?,?,?,?)",
            new_rows,
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Per-request DB connection
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    """Return a per-request SQLite connection, syncing the FTS index on first use."""
    global _fts_ready
    if "db" not in g:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
        if not _fts_ready:
            _sync_fts(conn)
            _fts_ready = True
    return g.db


@app.teardown_appcontext
def close_db(exc: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a Row to a plain dict, injecting cover_url for books."""
    d = dict(row)
    d.pop("_score", None)                       # internal ranking field
    cover_isbn = d.get("cover_isbn")
    d["cover_url"] = COVER_BASE.format(isbn=cover_isbn) if cover_isbn else None
    return d


def _parse_decade(s: str) -> tuple[int, int] | None:
    """
    Parse a decade string such as '1990s' into an inclusive year range (1990, 1999).
    Returns None if the string doesn't match the expected pattern.
    """
    m = re.fullmatch(r"(\d{3})0s", s.strip())
    if not m:
        return None
    start = int(m.group(1)) * 10
    return (start, start + 9)


def _fts_query(raw: str) -> str:
    """
    Build an FTS5 MATCH expression from a free-text query.

    Each non-punctuation token becomes a prefix-match term; all tokens are
    AND-ed together so only results containing every token are returned.
    The Porter stemmer (applied at index time) means stemmed forms also match.
    """
    tokens = re.sub(r"[^\w\s]", " ", raw).split()
    return " AND ".join(f'"{t}"*' for t in tokens)


def _err(message: str, status: int = 400) -> tuple[Response, int]:
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# GET /api/keywords
# ---------------------------------------------------------------------------

_KEYWORDS_SQL = """
    SELECT
        k.id,
        k.keyword,
        k.weight,
        SUM(CASE WHEN i.item_type = 'article' THEN 1 ELSE 0 END) AS article_count,
        SUM(CASE WHEN i.item_type = 'book'    THEN 1 ELSE 0 END) AS book_count,
        SUM(CASE WHEN i.item_type = 'chapter' THEN 1 ELSE 0 END) AS chapter_count
    FROM keywords k
    JOIN item_keywords ik ON ik.keyword_id = k.id
    JOIN items         i  ON i.id          = ik.item_id
    WHERE k.weight >= 0.02
"""

@app.get("/api/keywords")
@cache.cached(timeout=3600, query_string=True)
def get_keywords() -> Response:
    """
    Return all keywords with weight ≥ 0.02.

    Query params
    ------------
    decade : str, optional
        Restrict item counts to a specific decade, e.g. ``1990s`` (1990–1999).
    """
    decade_str = request.args.get("decade", "").strip()

    if decade_str:
        decade = _parse_decade(decade_str)
        if decade is None:
            return _err(
                f"Invalid decade {decade_str!r}. Use a string like '1990s', '2000s', etc."
            )
        yr_lo, yr_hi = decade
        sql = (
            _KEYWORDS_SQL
            + " AND i.year BETWEEN ? AND ?"
              " GROUP BY k.id"
              " HAVING article_count + book_count + chapter_count > 0"
              " ORDER BY k.weight DESC"
        )
        rows = get_db().execute(sql, [yr_lo, yr_hi]).fetchall()
    else:
        sql = _KEYWORDS_SQL + " GROUP BY k.id ORDER BY k.weight DESC"
        rows = get_db().execute(sql).fetchall()

    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/items
# ---------------------------------------------------------------------------

@app.get("/api/items")
@cache.cached(timeout=3600, query_string=True)
def get_items() -> Response:
    """
    Return items tagged with a keyword, ordered by year descending.

    Query params
    ------------
    keyword : str, required
        Keyword text.  Matching is case-insensitive.
    type : str, optional
        Filter by ``item_type``: ``article``, ``book``, or ``chapter``.
    """
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return _err("Missing required parameter: keyword")

    item_type = request.args.get("type", "").strip().lower()
    if item_type and item_type not in {"article", "book", "chapter"}:
        return _err(
            f"Invalid type {item_type!r}. Allowed values: article, book, chapter."
        )

    sql = """
        SELECT DISTINCT i.*
        FROM items         i
        JOIN item_keywords ik ON ik.item_id    = i.id
        JOIN keywords      k  ON k.id          = ik.keyword_id
        WHERE lower(k.keyword) = lower(?)
    """
    params: list[Any] = [keyword]

    if item_type:
        sql += " AND i.item_type = ?"
        params.append(item_type)

    sql += " ORDER BY i.year DESC"

    rows = get_db().execute(sql, params).fetchall()
    return jsonify([_row_to_dict(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/search
# ---------------------------------------------------------------------------

@app.get("/api/search")
@cache.cached(timeout=3600, query_string=True)
def search() -> Response:
    """
    Full-text search across title, authors, and abstract.

    Results are ranked by BM25 relevance (most relevant first, up to 100
    results).  Each search token is prefix-matched and the Porter stemmer
    normalises inflected forms.

    Query params
    ------------
    q : str, required
        Free-text search query.
    """
    raw_q = request.args.get("q", "").strip()
    if not raw_q:
        return _err("Missing required parameter: q")

    fts_q = _fts_query(raw_q)
    if not fts_q:
        return jsonify([])

    try:
        rows = get_db().execute(
            """
            SELECT i.*, bm25(fts_items) AS _score
            FROM fts_items
            JOIN items i ON fts_items.rowid = i.id
            WHERE fts_items MATCH ?
            ORDER BY bm25(fts_items)
            LIMIT 100
            """,
            [fts_q],
        ).fetchall()
    except sqlite3.OperationalError as exc:
        return _err(f"Search query error: {exc}")

    return jsonify([_row_to_dict(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
@cache.cached(timeout=3600)
def get_stats() -> Response:
    """
    Return aggregate database statistics.

    Response fields
    ---------------
    articles, books, chapters : int
        Item counts by type.
    keywords : int
        Total keyword rows.
    journals : int
        Number of distinct journal names.
    publishers : int
        Number of distinct publisher names (non-null).
    year_min, year_max : int | null
        Earliest and latest publication years (zero-years excluded).
    """
    conn = get_db()

    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN item_type = 'article' THEN 1 ELSE 0 END)              AS articles,
            SUM(CASE WHEN item_type = 'book'    THEN 1 ELSE 0 END)              AS books,
            SUM(CASE WHEN item_type = 'chapter' THEN 1 ELSE 0 END)              AS chapters,
            COUNT(DISTINCT NULLIF(TRIM(journal),   ''))                          AS journals,
            COUNT(DISTINCT NULLIF(TRIM(publisher), ''))                          AS publishers,
            MIN(CASE WHEN year > 0 THEN year END)                               AS year_min,
            MAX(CASE WHEN year > 0 THEN year END)                               AS year_max
        FROM items
        """
    ).fetchone()

    keywords = conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]

    return jsonify({
        "articles":   row["articles"]   or 0,
        "books":      row["books"]      or 0,
        "chapters":   row["chapters"]   or 0,
        "keywords":   keywords,
        "journals":   row["journals"]   or 0,
        "publishers": row["publishers"] or 0,
        "year_min":   row["year_min"],
        "year_max":   row["year_max"],
    })


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> Response:
    """Liveness check — also verifies the DB is reachable."""
    try:
        n = get_db().execute("SELECT COUNT(*) FROM items").fetchone()[0]
        return jsonify({"status": "ok", "items": n})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "detail": str(exc)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
