#!/usr/bin/env python3
"""Generate frontend/data/info.json from the SQLite database.

Run from any directory:
    python scripts/build_info.py

Re-run after any scrape that adds new items or keywords.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB   = ROOT / "data" / "music_theory.db"
OUT  = ROOT / "frontend" / "data" / "info.json"


def main() -> None:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Global stats (mirrors /api/stats without decade filter)
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN item_type = 'article' THEN 1 ELSE 0 END)  AS articles,
            SUM(CASE WHEN item_type = 'book'    THEN 1 ELSE 0 END)  AS books,
            SUM(CASE WHEN item_type = 'chapter' THEN 1 ELSE 0 END)  AS chapters,
            COUNT(DISTINCT NULLIF(TRIM(journal),   ''))              AS journals,
            COUNT(DISTINCT NULLIF(TRIM(publisher), ''))              AS publishers,
            MIN(CASE WHEN year > 0 THEN year END)                   AS year_min,
            MAX(CASE WHEN year > 0 THEN year END)                   AS year_max
        FROM items
    """).fetchone()

    keywords = conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]

    stats = {
        "articles":   row["articles"]   or 0,
        "books":      row["books"]      or 0,
        "chapters":   row["chapters"]   or 0,
        "journals":   row["journals"]   or 0,
        "publishers": row["publishers"] or 0,
        "keywords":   keywords,
        "year_min":   row["year_min"],
        "year_max":   row["year_max"],
    }

    # Top journals by article/chapter count
    journals = conn.execute("""
        SELECT TRIM(journal) AS name, COUNT(*) AS count
        FROM items
        WHERE item_type IN ('article', 'chapter')
          AND journal IS NOT NULL AND TRIM(journal) != ''
        GROUP BY TRIM(journal)
        ORDER BY count DESC
        LIMIT 30
    """).fetchall()

    # Canonical publisher name map — normalises variant spellings from Google Books
    _CANONICAL: dict[str, str] = {
        "Oxford University Press, USA": "Oxford University Press",
        "OUP Oxford":                   "Oxford University Press",
        "Univ of California Press":     "University of California Press",
        "Mit Press":                    "MIT Press",
        "MIT Press (MA)":               "MIT Press",
        "W. W. Norton & Company":                "W. W. Norton",
        "W W Norton & Company Incorporated":     "W. W. Norton",
        "New York : W.W. Norton":                "W. W. Norton",
        "New York : W. W. Norton":               "W. W. Norton",
        "New Haven [Conn.] : Yale University Press": "Yale University Press",
        "University of MICHIGAN REGIONAL":       "University of Michigan Press",
        "University Rochester Press":            "University of Rochester Press",
        "Eastman Studies in Music":              "University of Rochester Press",
    }

    raw_publishers = conn.execute("""
        SELECT TRIM(publisher) AS name, COUNT(*) AS count
        FROM items
        WHERE item_type = 'book'
          AND publisher IS NOT NULL AND TRIM(publisher) != ''
        GROUP BY TRIM(publisher)
        ORDER BY count DESC
    """).fetchall()

    pub_counts: dict[str, int] = {}
    for r in raw_publishers:
        canonical = _CANONICAL.get(r["name"], r["name"])
        pub_counts[canonical] = pub_counts.get(canonical, 0) + r["count"]

    publishers_sorted = sorted(pub_counts.items(), key=lambda x: -x[1])
    publishers = [{"name": n, "count": c} for n, c in publishers_sorted]

    payload = {
        "stats":      stats,
        "journals":   [dict(r) for r in journals],
        "publishers": publishers,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    size = OUT.stat().st_size
    print(f"Written {OUT.relative_to(ROOT)}  ({size:,} bytes)")
    print(f"  articles={stats['articles']:,}  books={stats['books']:,}  "
          f"chapters={stats['chapters']:,}  keywords={stats['keywords']:,}")
    print(f"  year range: {stats['year_min']}–{stats['year_max']}")
    print(f"  journals in list: {len(payload['journals'])}  "
          f"publishers in list: {len(payload['publishers'])}")


if __name__ == "__main__":
    main()
