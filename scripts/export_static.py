#!/usr/bin/env python3
"""Export the full database to a single static JSON file for GitHub Pages hosting.

Generates:
  frontend/data/data.json      — all keywords + items (with embedded keyword IDs)
  frontend/index-gh.html       — index.html patched with STATIC_DATA_URL for GitHub Pages

Usage:
  python scripts/export_static.py

Re-run after any scrape that changes items or keywords.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DB       = ROOT / "data" / "music_theory.db"
OUT_JSON = ROOT / "frontend" / "data" / "data.json"
OUT_HTML = ROOT / "frontend" / "index-gh.html"
SRC_HTML = ROOT / "frontend" / "index.html"

COVER_BASE = "https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"


def main() -> None:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    print("Exporting keywords…")
    kw_rows = conn.execute(
        "SELECT id, keyword, weight FROM keywords ORDER BY weight DESC"
    ).fetchall()
    # Count distinct items per keyword for cloud eligibility
    link_counts = dict(conn.execute(
        "SELECT keyword_id, COUNT(DISTINCT item_id) FROM item_keywords GROUP BY keyword_id"
    ).fetchall())
    # cloud=true requires weight >= 0.02 AND at least 5 distinct items linking to it
    # (prevents single-book subject tags from polluting the cloud)
    keywords = [{"id": r["id"], "keyword": r["keyword"], "weight": r["weight"],
                 "cloud": r["weight"] >= 0.02 and link_counts.get(r["id"], 0) >= 5}
                for r in kw_rows]
    cloud_count = sum(1 for k in keywords if k["cloud"])
    print(f"  {len(keywords):,} keywords ({cloud_count:,} in cloud)")

    print("Exporting items…")
    item_rows = conn.execute(
        """
        SELECT id, title, authors, year, item_type, journal, doi, url,
               abstract, publisher, volume, issue, isbn, cover_isbn, cover_url,
               parent_id, chapters_available
        FROM items
        ORDER BY id
        """
    ).fetchall()
    print(f"  {len(item_rows):,} items")

    print("Exporting item–keyword associations…")
    ik_rows = conn.execute(
        "SELECT item_id, keyword_id, source FROM item_keywords"
    ).fetchall()

    # Build per-item keyword sets (all keywords, not filtered by cloud weight)
    kw_ids_by_item: dict[int, list[int]] = {}
    explicit_by_item: dict[int, list[int]] = {}
    for ik in ik_rows:
        iid, kid, src = ik["item_id"], ik["keyword_id"], ik["source"]
        kw_ids_by_item.setdefault(iid, []).append(kid)
        if src == "explicit":
            explicit_by_item.setdefault(iid, []).append(kid)

    items: list[dict] = []
    for row in item_rows:
        iid = row["id"]
        cover_isbn = row["cover_isbn"]
        stored_cover = row["cover_url"]
        if stored_cover:
            resolved_cover = stored_cover
        else:
            isbn_for_cover = cover_isbn or row["isbn"]
            resolved_cover = COVER_BASE.format(isbn=isbn_for_cover) if isbn_for_cover else None
        items.append({
            "id":                 iid,
            "title":              row["title"],
            "authors":            row["authors"],
            "year":               row["year"] or 0,
            "item_type":          row["item_type"],
            "journal":            row["journal"],
            "doi":                row["doi"],
            "url":                row["url"],
            "abstract":           row["abstract"],
            "publisher":          row["publisher"],
            "volume":             row["volume"],
            "issue":              row["issue"],
            "cover_isbn":         cover_isbn,
            "cover_url":          resolved_cover,
            "parent_id":          row["parent_id"],
            "chapters_available": row["chapters_available"] or 0,
            "kw_ids":             kw_ids_by_item.get(iid, []),
            "kw_explicit_ids":    explicit_by_item.get(iid, []),
        })

    # ── Co-occurrence (cloud keywords only) ──────────────────────────────────
    print("Computing keyword co-occurrence…")
    cloud_set = {kw['id'] for kw in keywords if kw['cloud']}
    cooccur_raw: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for item in items:
        cloud_in = [kid for kid in item['kw_ids'] if kid in cloud_set]
        for a, b in combinations(sorted(cloud_in), 2):
            cooccur_raw[a][b] += 1
            cooccur_raw[b][a] += 1

    cooccur: dict[str, list] = {}
    for kid, peers in cooccur_raw.items():
        top = sorted(peers.items(), key=lambda x: -x[1])[:15]
        cooccur[str(kid)] = [[pid, c] for pid, c in top]
    print(f"  {len(cooccur):,} keywords have co-occurrence data")

    # ── Year trends (cloud keywords only) ────────────────────────────────────
    print("Computing keyword year trends…")
    by_year_raw: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for item in items:
        yr = item.get('year', 0)
        if not yr or yr <= 0:
            continue
        for kid in item['kw_ids']:
            if kid in cloud_set:
                by_year_raw[kid][yr] += 1

    by_year: dict[str, list] = {
        str(kid): sorted(yr_counts.items())
        for kid, yr_counts in by_year_raw.items()
    }
    print(f"  {len(by_year):,} keywords have trend data")

    payload = {"keywords": keywords, "items": items, "cooccur": cooccur, "byYear": by_year}

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT_JSON.write_text(text)
    size_kb = OUT_JSON.stat().st_size / 1024
    print(f"  Written {OUT_JSON.relative_to(ROOT)}  ({size_kb:,.0f} KB)")

    # Patch index.html for GitHub Pages
    print("Patching index.html for GitHub Pages…")
    src = SRC_HTML.read_text()
    inject = '<script>window.STATIC_DATA_URL="data/data.json";</script>\n  '
    patched = re.sub(
        r'(<script src="app\.js[^"]*">)',
        inject + r'\1',
        src,
        count=1,
    )
    if inject not in patched:
        print("  WARNING: could not inject STATIC_DATA_URL — patch index.html manually.")
    OUT_HTML.write_text(patched)
    print(f"  Written {OUT_HTML.relative_to(ROOT)}")

    print("\nDone. Summary:")
    print(f"  keywords : {len(keywords):,}")
    print(f"  items    : {len(items):,}")
    print(f"  data.json: {size_kb:,.0f} KB  (≈{size_kb/1024:.1f} MB)")
    print(f"\nFor GitHub Pages, deploy the frontend/ directory using index-gh.html as index.html.")


if __name__ == "__main__":
    main()
