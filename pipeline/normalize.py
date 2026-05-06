"""Keyword extraction and post-scrape normalization pipeline.

Post-scrape normalization
-------------------------
Call run_normalization_pipeline(db) after all scrapers complete.  Steps run
in this order:

  0. tag_items_without_keywords  – KeyBERT extraction for abstract-only items
  1. lowercase_keywords          – lower-case every keyword; merge exact dups
  2. merge_near_duplicates       – fuzzy-merge near-dups (thefuzz, threshold 90)
  3. expand_abbreviations        – expand known short forms to canonical terms
  4. remove_stop_keywords        – delete analytically meaningless stand-alones
  5. recalculate_weights         – recompute 0–1 weight from item-type counts
  6. print_summary               – report totals and top-30 keywords by weight
"""
from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from typing import TYPE_CHECKING

import sqlite_utils

if TYPE_CHECKING:
    from keybert import KeyBERT as _KBType

# ---------------------------------------------------------------------------
# Music-theory domain vocabulary used as pre-scored candidates
# ---------------------------------------------------------------------------

DOMAIN_TERMS: list[str] = [
    "voice leading",
    "counterpoint",
    "harmony",
    "form",
    "rhythm",
    "meter",
    "timbre",
    "Schenkerian analysis",
    "post-tonal",
    "serialism",
    "modality",
    "tonality",
    "improvisation",
    "performance",
    "cognition",
    "perception",
    "semiotics",
    "neo-Riemannian",
    "transformational theory",
    "spectralism",
    "microtonality",
]

_DOMAIN_LOWER = [t.lower() for t in DOMAIN_TERMS]

# Minimum cosine similarity to include a keyword
_THRESHOLD = 0.25

# ---------------------------------------------------------------------------
# Normalization constants
# ---------------------------------------------------------------------------

FUZZY_THRESHOLD: int = 90  # fuzz.ratio threshold for near-duplicate merging

# Short forms (already lowercased, since step 1 runs first) → canonical term.
# All canonical terms are lowercase to stay consistent with the pipeline.
ABBREVIATION_MAP: dict[str, str] = {
    # Pitch-class set theory
    "pc set":                   "pitch-class set theory",
    "pc sets":                  "pitch-class set theory",
    "set theory":               "pitch-class set theory",
    "pitch class set":          "pitch-class set theory",
    "pitch-class set":          "pitch-class set theory",
    "pitch class":              "pitch-class",
    # Neo-Riemannian
    "neo-r":                    "neo-riemannian theory",
    "neo-riemannian":           "neo-riemannian theory",
    # Schenkerian
    "schenkerian":              "schenkerian analysis",
    "schenker":                 "schenkerian analysis",
    # Transformational theory
    "transformational":         "transformational theory",
    # British/American spelling variants
    "metre":                    "meter",
    "metres":                   "meter",
    # Rhythm/metric
    "rhythmic":                 "rhythm",
    # Spectral / microtonal
    "spectral":                 "spectralism",
    "microtonal":               "microtonality",
}

# Stand-alone keywords with no analytical specificity.
# A keyword is removed only when its full text equals one of these strings
# (compound terms like "music theory" or "harmonic analysis" are kept).
STOP_KEYWORDS: frozenset[str] = frozenset(
    ["music", "musical", "theory", "analysis"]
)

# ---------------------------------------------------------------------------
# KeyBERT singleton — model load is expensive, do it once
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_model() -> "_KBType":
    from keybert import KeyBERT
    return KeyBERT()


# ---------------------------------------------------------------------------
# Keyword extraction (used by scrapers and pipeline step 0)
# ---------------------------------------------------------------------------

def extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """
    Return up to *top_n* keywords for *text* using a two-pass KeyBERT strategy.

    Pass 1 — domain scoring
        Score each term in DOMAIN_TERMS against the document.  Terms whose
        cosine similarity exceeds _THRESHOLD are included.

    Pass 2 — free extraction
        Extract novel n-gram phrases (1–3 words) from the text itself using
        MMR for diversity.  Phrases already covered by pass 1 are dropped.

    Returns a deduplicated, relevance-sorted list of lowercase keyword strings.
    """
    text = _clean(text)
    if not text:
        return []

    model = _get_model()

    domain_hits: list[tuple[str, float]] = model.extract_keywords(
        text,
        candidates=_DOMAIN_LOWER,
        top_n=len(_DOMAIN_LOWER),
    )
    domain_kws = {kw for kw, score in domain_hits if score >= _THRESHOLD}

    free_hits: list[tuple[str, float]] = model.extract_keywords(
        text,
        keyphrase_ngram_range=(1, 3),
        stop_words="english",
        use_mmr=True,
        diversity=0.5,
        top_n=top_n,
    )
    free_kws = [
        kw for kw, score in free_hits
        if score >= _THRESHOLD and not _covered_by_domain(kw, domain_kws)
    ]

    merged: list[str] = []
    seen: set[str] = set()
    for kw in list(domain_kws) + free_kws:
        norm = kw.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            merged.append(norm)

    return merged[:top_n]


def tag_items_without_keywords(db: sqlite_utils.Database) -> int:
    """
    For every item that has a non-null abstract but no *explicit* keywords,
    run extract_keywords() and insert results into item_keywords with
    source='extracted'.

    Returns the number of items processed.
    """
    from db import add_keywords_to_item  # avoid circular import at module level

    query = """
        SELECT i.id, i.abstract
        FROM items i
        WHERE i.abstract IS NOT NULL
          AND i.abstract != ''
          AND NOT EXISTS (
              SELECT 1 FROM item_keywords ik
              WHERE ik.item_id = i.id AND ik.source = 'explicit'
          )
    """
    rows = list(db.execute(query).fetchall())
    processed = 0

    for item_id, abstract in rows:
        keywords = extract_keywords(abstract)
        if keywords:
            add_keywords_to_item(db, item_id, keywords, source="extracted", weight=0.8)
        processed += 1

    return processed


# ---------------------------------------------------------------------------
# Low-level merge helper
# ---------------------------------------------------------------------------

def _merge_keyword(
    db: sqlite_utils.Database, keep_id: int, drop_id: int
) -> None:
    """Re-point all item_keywords from *drop_id* to *keep_id*, then delete *drop_id*."""
    # UPDATE OR IGNORE skips rows where the (item_id, keep_id) pair already exists.
    db.execute(
        "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
        [keep_id, drop_id],
    )
    # Delete any rows that couldn't be re-pointed (pre-existing duplicates).
    db.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [drop_id])
    db.execute("DELETE FROM keywords WHERE id = ?", [drop_id])


# ---------------------------------------------------------------------------
# Pipeline step 1: lowercase
# ---------------------------------------------------------------------------

def lowercase_keywords(db: sqlite_utils.Database) -> int:
    """
    Lowercase every keyword in the keywords table in place.  Where lowercasing
    produces a duplicate (e.g. "Harmony" and "harmony" both exist), merge the
    lower-link-count row into the higher-link-count row.

    Returns the number of rows that were merged away.
    """
    rows = list(
        db.execute(
            """
            SELECT k.id, k.keyword, COUNT(ik.item_id) AS cnt
            FROM keywords k
            LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
            GROUP BY k.id
            """
        ).fetchall()
    )

    # Group by lowercase form
    groups: dict[str, list[tuple[int, int]]] = defaultdict(list)  # lower → [(cnt, id)]
    for kid, kw, cnt in rows:
        groups[kw.lower()].append((cnt, kid))

    merged = 0
    with db.conn:
        for lower_form, members in groups.items():
            if len(members) == 1:
                _, kid = members[0]
                db.conn.execute(
                    "UPDATE keywords SET keyword = ? WHERE id = ? AND keyword != ?",
                    [lower_form, kid, lower_form],
                )
            else:
                members.sort(reverse=True)  # sort by cnt desc
                _, keep_id = members[0]
                for _, drop_id in members[1:]:
                    # _merge_keyword uses db.execute; call raw conn inside the same txn
                    db.conn.execute(
                        "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
                        [keep_id, drop_id],
                    )
                    db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [drop_id])
                    db.conn.execute("DELETE FROM keywords WHERE id = ?", [drop_id])
                    merged += 1
                db.conn.execute(
                    "UPDATE keywords SET keyword = ? WHERE id = ?",
                    [lower_form, keep_id],
                )

    return merged


# ---------------------------------------------------------------------------
# Pipeline step 2: fuzzy near-duplicate merge
# ---------------------------------------------------------------------------

def merge_near_duplicates(
    db: sqlite_utils.Database,
    threshold: int = FUZZY_THRESHOLD,
) -> int:
    """
    Compare every pair of keywords and merge pairs whose fuzz.ratio ≥ *threshold*.
    The keyword with more item_keywords links is kept as canonical; the other is
    merged into it.

    Returns the number of keywords merged away.
    """
    from thefuzz import fuzz

    rows = list(
        db.execute(
            """
            SELECT k.id, k.keyword, COUNT(ik.item_id) AS cnt
            FROM keywords k
            LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
            GROUP BY k.id
            ORDER BY cnt DESC
            """
        ).fetchall()
    )

    # Build mutable lookup; iterate in count-descending order so the keyword
    # with more links is always the canonical one.
    active: dict[int, str] = {kid: kw for kid, kw, _ in rows}
    order: list[int] = [kid for kid, _, _ in rows]
    dropped: set[int] = set()
    merges: list[tuple[int, int]] = []  # (keep_id, drop_id) collected then committed in one txn

    for i, kid1 in enumerate(order):
        if kid1 in dropped:
            continue
        kw1 = active[kid1]

        for kid2 in order[i + 1 :]:
            if kid2 in dropped:
                continue
            kw2 = active[kid2]

            lo, hi = sorted([len(kw1), len(kw2)])
            if hi == 0 or lo / hi < (threshold / 100) * 0.6:
                continue

            if fuzz.ratio(kw1, kw2) >= threshold:
                merges.append((kid1, kid2))
                dropped.add(kid2)
                del active[kid2]

    with db.conn:
        for keep_id, drop_id in merges:
            db.conn.execute(
                "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
                [keep_id, drop_id],
            )
            db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [drop_id])
            db.conn.execute("DELETE FROM keywords WHERE id = ?", [drop_id])

    return len(merges)


# ---------------------------------------------------------------------------
# Pipeline step 3: abbreviation expansion
# ---------------------------------------------------------------------------

def expand_abbreviations(db: sqlite_utils.Database) -> int:
    """
    Replace known abbreviated keyword forms with their canonical expansions.
    If the canonical form already exists as a keyword, the short form is merged
    into it; otherwise the short form is renamed in place.

    Returns the number of keywords expanded.
    """
    def _row(sql: str, val: str) -> int | None:
        rows = db.execute(sql, [val]).fetchall()
        return rows[0][0] if rows else None

    expanded = 0
    with db.conn:
        for short, canonical in ABBREVIATION_MAP.items():
            short_id = _row("SELECT id FROM keywords WHERE keyword = ?", short)
            if short_id is None:
                continue

            canon_id = _row("SELECT id FROM keywords WHERE keyword = ?", canonical)
            if canon_id is not None and canon_id != short_id:
                db.conn.execute(
                    "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
                    [canon_id, short_id],
                )
                db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [short_id])
                db.conn.execute("DELETE FROM keywords WHERE id = ?", [short_id])
            elif canon_id is None:
                db.conn.execute(
                    "UPDATE keywords SET keyword = ? WHERE id = ?",
                    [canonical, short_id],
                )

            expanded += 1

    return expanded


# ---------------------------------------------------------------------------
# Pipeline step 4: stop-keyword removal
# ---------------------------------------------------------------------------

def remove_stop_keywords(db: sqlite_utils.Database) -> int:
    """
    Delete keywords whose full text exactly matches a term in STOP_KEYWORDS.
    Compound terms that merely *contain* a stop word (e.g. "music theory") are
    unaffected.

    Returns the number of keywords removed.
    """
    removed = 0
    with db.conn:
        for term in STOP_KEYWORDS:
            rows = db.conn.execute(
                "SELECT id FROM keywords WHERE keyword = ?", [term]
            ).fetchall()
            if rows:
                kid = rows[0][0]
                db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [kid])
                db.conn.execute("DELETE FROM keywords WHERE id = ?", [kid])
                removed += 1
    return removed


# ---------------------------------------------------------------------------
# Pipeline step 5: weight recalculation
# ---------------------------------------------------------------------------

def recalculate_weights(db: sqlite_utils.Database) -> None:
    """
    Recompute each keyword's weight as a normalized 0–1 score:

        raw = (article_count × 1.0) + (book_count × 2.0) + (chapter_count × 0.5)
        weight = raw / max(raw across all keywords)

    Updates keywords.weight in place.
    """
    rows = list(
        db.execute(
            """
            SELECT
                k.id,
                SUM(CASE WHEN i.item_type = 'article' THEN 1.0 ELSE 0 END)  AS a,
                SUM(CASE WHEN i.item_type = 'book'    THEN 2.0 ELSE 0 END)  AS b,
                SUM(CASE WHEN i.item_type = 'chapter' THEN 0.5 ELSE 0 END)  AS c
            FROM keywords k
            LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
            LEFT JOIN items i          ON i.id = ik.item_id
            GROUP BY k.id
            """
        ).fetchall()
    )

    scores: list[tuple[int, float]] = []
    for kid, a, b, c in rows:
        raw = (a or 0.0) + (b or 0.0) + (c or 0.0)
        scores.append((kid, raw))

    max_score = max((s for _, s in scores), default=1.0) or 1.0

    with db.conn:
        for kid, raw in scores:
            db.conn.execute(
                "UPDATE keywords SET weight = ? WHERE id = ?",
                [raw / max_score, kid],
            )


# ---------------------------------------------------------------------------
# Pipeline step 6: summary report
# ---------------------------------------------------------------------------

def print_summary(db: sqlite_utils.Database) -> None:
    """Print total item / keyword counts and the top 30 keywords by weight."""
    total_items    = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    total_keywords = db.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
    total_links    = db.execute("SELECT COUNT(*) FROM item_keywords").fetchone()[0]

    by_type = dict(
        db.execute(
            "SELECT item_type, COUNT(*) FROM items GROUP BY item_type"
        ).fetchall()
    )

    top30 = db.execute(
        """
        SELECT k.keyword, k.weight, COUNT(ik.item_id) AS links
        FROM keywords k
        LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
        GROUP BY k.id
        ORDER BY k.weight DESC
        LIMIT 30
        """
    ).fetchall()

    bar = "=" * 62
    print(f"\n{bar}")
    print("  Music Theory DB — Normalization Summary")
    print(bar)
    print(f"  {'Total items:':<22} {total_items:>6,}")
    for itype in ("article", "book", "chapter"):
        n = by_type.get(itype, 0)
        if n:
            print(f"    {'  ' + itype + ':':<20} {n:>6,}")
    print(f"  {'Total keywords:':<22} {total_keywords:>6,}")
    print(f"  {'Total keyword links:':<22} {total_links:>6,}")
    print(f"\n  {'Top 30 keywords by weight':}")
    print(f"  {'keyword':<38} {'weight':>7}  {'links':>5}")
    print(f"  {'-'*38} {'-'*7}  {'-'*5}")
    for kw, weight, links in top30:
        print(f"  {kw:<38} {weight:>7.4f}  {links:>5}")
    print()


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

def run_normalization_pipeline(db: sqlite_utils.Database | None = None) -> None:
    """
    Run the full post-scrape normalization pipeline.

    Steps
    -----
    0. KeyBERT extraction for items with abstracts but no explicit keywords
    1. Lowercase all keywords; merge exact duplicates produced by casing
    2. Fuzzy-merge near-duplicates (threshold 90)
    3. Expand known abbreviations to canonical long forms
    4. Remove analytically meaningless stand-alone stop keywords
    5. Recalculate keyword weights from item-type-weighted article counts
    6. Print summary report
    """
    if db is None:
        from db import get_db
        db = get_db()

    # Step 0 — KeyBERT extraction
    print("Step 0: Extracting keywords from abstracts (KeyBERT)…", flush=True)
    n = tag_items_without_keywords(db)
    print(f"        {n} items processed.", flush=True)

    # Step 1 — Lowercase
    print("Step 1: Lowercasing keywords…", flush=True)
    n = lowercase_keywords(db)
    print(f"        {n} duplicate(s) merged by casing.", flush=True)

    # Step 2 — Fuzzy merge
    print(f"Step 2: Fuzzy-merging near-duplicates (threshold={FUZZY_THRESHOLD})…", flush=True)
    n = merge_near_duplicates(db)
    print(f"        {n} near-duplicate(s) merged.", flush=True)

    # Step 3 — Abbreviation expansion
    print("Step 3: Expanding abbreviations…", flush=True)
    n = expand_abbreviations(db)
    print(f"        {n} abbreviation(s) expanded.", flush=True)

    # Step 4 — Stop-keyword removal
    print("Step 4: Removing stop keywords…", flush=True)
    n = remove_stop_keywords(db)
    print(f"        {n} stop keyword(s) removed.", flush=True)

    # Step 5 — Weight recalculation
    print("Step 5: Recalculating keyword weights…", flush=True)
    recalculate_weights(db)
    print("        Done.", flush=True)

    # Step 6 — Summary
    print_summary(db)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def normalize_record(record: dict) -> dict:
    """Light normalisation pass before DB insert (stub — extend as needed)."""
    return record


def upsert_records(
    db: sqlite_utils.Database, table: str, records: list[dict], pk: str = "id"
) -> None:
    db[table].upsert_all(records, pk=pk)


def _clean(text: str) -> str:
    """Strip citation markers, normalize hyphens in compound terms, collapse whitespace."""
    text = re.sub(r"\(\d{4}\)", "", text)           # (2003)
    text = re.sub(r"\[\d+\]", "", text)             # [1]
    # Normalize hyphenated music terms so they match space-separated domain vocabulary
    text = re.sub(r"(?<=[a-zA-Z])-(?=[a-zA-Z])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _covered_by_domain(phrase: str, domain_kws: set[str]) -> bool:
    """Return True if *phrase* is a substring of any domain keyword already selected."""
    p = phrase.lower()
    return any(p in dk or dk in p for dk in domain_kws)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    from db import get_db
    run_normalization_pipeline(get_db())
