"""Normalize scraped records and extract keywords from abstracts via KeyBERT."""
from __future__ import annotations

import re
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

# Minimum cosine similarity to include a keyword (keeps noise out)
_THRESHOLD = 0.25

# ---------------------------------------------------------------------------
# KeyBERT singleton — model load is expensive, do it once
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_model() -> "_KBType":
    from keybert import KeyBERT
    return KeyBERT()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """
    Return up to *top_n* keywords for *text* using a two-pass KeyBERT strategy:

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

    # --- Pass 1: domain terms ---
    domain_hits: list[tuple[str, float]] = model.extract_keywords(
        text,
        candidates=_DOMAIN_LOWER,
        top_n=len(_DOMAIN_LOWER),   # score every domain term
    )
    domain_kws = {kw for kw, score in domain_hits if score >= _THRESHOLD}

    # --- Pass 2: free n-gram extraction ---
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

    # Merge: domain terms first (they're explicit vocabulary), then free phrases
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

    # Items with an abstract but zero explicit keyword links
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
