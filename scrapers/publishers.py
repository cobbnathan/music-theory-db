"""Publisher catalog scrapers: Oxford University Press and Cambridge University Press.

Uses Playwright (headless Chromium) to render JavaScript-heavy listing pages.

CUP listing (1,337 music books, 67 pages):
  https://www.cambridge.org/core/browse-subjects/music/listing
  ?aggs[productTypes][filters]=BOOK&pageSize=20&page={n}

OUP: URL structure changed — OUP books are captured via Google Books API.
"""
from __future__ import annotations

import logging
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

_PAGE_TIMEOUT = 30_000   # ms
_WAIT_TIMEOUT = 12_000   # ms
_DELAY        = 2.0      # seconds between page turns


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extract_year(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", text)
    return int(m.group(1)) if m else None


def _extract_isbn13(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"\b(97[89]\d{10})\b", text.replace("-", "").replace(" ", ""))
    return m.group(1) if m else None


def _is_edited(author_str: str | None) -> bool:
    if not author_str:
        return False
    return bool(re.search(r"\b(ed\.|editor|editors|edited\s+by)\b", author_str, re.IGNORECASE))


def _new_context(playwright):
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    )
    return browser, context


# ---------------------------------------------------------------------------
# CUP scraper
# ---------------------------------------------------------------------------

_CUP_LISTING = (
    "https://www.cambridge.org/core/browse-subjects/music/listing"
    "?aggs[productTypes][filters]=BOOK&pageSize=20"
)

_CUP_EXTRACT_JS = """() => {
    const cards = document.querySelectorAll("div.product-listing-with-inputs-content");
    const results = [];
    cards.forEach(card => {
        // Title
        const titleEl = card.querySelector("span.title h3 span, span.title h3, h3 a, h3");
        const title = titleEl ? titleEl.textContent.trim() : null;
        if (!title) return;

        // Title link → derives a relative URL we can ignore (no DOI/ISBN in it)
        const linkEl = card.querySelector("a.part-link");
        const href = linkEl ? linkEl.getAttribute("href") : null;

        // Authors — multiple <li class="author"> possible
        const authorEls = card.querySelectorAll("li.author");
        const authors = Array.from(authorEls).map(a => a.textContent.trim()).filter(Boolean);
        const authorStr = authors.join("; ");

        // Year — prefer the "Print publication:" date
        const dates = card.querySelectorAll("span.date");
        let year = null;
        dates.forEach(d => {
            const y = d.textContent.match(/\\b(1[89]\\d\\d|20\\d\\d)\\b/);
            if (y) year = parseInt(y[1]);
        });

        // ISBN from the altmetric badge sibling
        const badge = card.closest("[class*=listing]")
                       ?.querySelector("[data-isbn]")
                     || card.parentElement?.querySelector("[data-isbn]");
        const isbn = badge ? badge.getAttribute("data-isbn") : null;

        // Sub-title (treat as subtitle, not abstract)
        const subEl = card.querySelector("li.sub-title");
        const subtitle = subEl ? subEl.textContent.trim() : null;

        results.push({ title, subtitle, authorStr, authors, year, isbn, href });
    });
    return results;
}"""


def scrape_cup(db=None) -> dict[str, int]:
    """Scrape the CUP music book catalog (all 67 pages) using Playwright."""
    if db is None:
        from db import get_db
        db = get_db()

    from db import upsert_item

    counts = {"found": 0, "inserted": 0, "skipped": 0}
    print("CUP: launching browser …")

    with sync_playwright() as pw:
        browser, context = _new_context(pw)
        page = context.new_page()
        page_num = 1

        # Load first page — give JS time to render listing cards
        try:
            page.goto(_CUP_LISTING, timeout=_PAGE_TIMEOUT, wait_until="domcontentloaded")
            time.sleep(5)
        except Exception as exc:
            logger.warning("CUP: failed to load first page: %s", exc)
            browser.close()
            return counts

        while True:
            print(f"  CUP page {page_num} …", end=" ", flush=True)

            try:
                records = page.evaluate(_CUP_EXTRACT_JS)
            except Exception as exc:
                logger.warning("CUP page %d JS eval error: %s", page_num, exc)
                break

            if not records:
                print("0 items (end of catalog)")
                break

            print(f"{len(records)} items")

            for raw in records:
                full_title = raw["title"]
                if raw.get("subtitle"):
                    full_title = f"{full_title}: {raw['subtitle']}"

                book_type = "edited_volume" if _is_edited(raw.get("authorStr")) else "monograph"

                # Parse author list: strip "Edited by" prefix and collapse whitespace
                author_str = " ".join(raw.get("authorStr", "").split())
                author_str_clean = re.sub(r"^edited\s+by\s+", "", author_str, flags=re.IGNORECASE).strip()
                authors = [a.strip() for a in re.split(r",\s*|\s+and\s+", author_str_clean) if a.strip()]

                record = {
                    "item_type": "book",
                    "title":     full_title,
                    "authors":   authors,
                    "year":      raw.get("year"),
                    "isbn":      _extract_isbn13(raw.get("isbn")),
                    "publisher": "Cambridge University Press",
                    "book_type": book_type,
                    "source":    "cup_catalog",
                }
                counts["found"] += 1
                try:
                    upsert_item(db, record)
                    counts["inserted"] += 1
                except Exception as exc:
                    logger.warning("CUP upsert failed for '%s': %s", full_title, exc)
                    counts["skipped"] += 1

            # Click "Next »" to advance — URL-based pagination doesn't work on CUP
            try:
                next_link = (
                    page.query_selector("a:has-text('Next »')") or
                    page.query_selector("a[rel='next']") or
                    page.query_selector(".pagination-next a")
                )
                if not next_link:
                    print("  (no next-page link — done)")
                    break
                next_link.click()
                time.sleep(_DELAY + 1)  # extra second for re-render
            except PWTimeout:
                print("  (next page timeout — stopping)")
                break
            except Exception as exc:
                logger.warning("CUP: next-page error on page %d: %s", page_num, exc)
                break

            page_num += 1

        browser.close()

    print(f"CUP done. found={counts['found']}  inserted/updated={counts['inserted']}  skipped={counts['skipped']}")
    return counts


# ---------------------------------------------------------------------------
# OUP stub — captured via Google Books API instead
# ---------------------------------------------------------------------------

def scrape_oup(db=None) -> dict[str, int]:
    """OUP catalog URL structure changed; OUP books are captured via Google Books."""
    print("OUP: skipping (catalog URL unavailable; OUP titles captured via Google Books API)")
    return {"found": 0, "inserted": 0, "skipped": 0}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Scrape publisher music book catalogs")
    parser.add_argument("--publisher", choices=["oup", "cup"], help="Scrape only one publisher")
    args = parser.parse_args()

    from db import get_db
    _db = get_db()
    totals: dict[str, int] = {"found": 0, "inserted": 0, "skipped": 0}

    if args.publisher in (None, "oup"):
        result = scrape_oup(_db)
        for k in totals:
            totals[k] += result.get(k, 0)

    if args.publisher in (None, "cup"):
        result = scrape_cup(_db)
        for k in totals:
            totals[k] += result.get(k, 0)

    print(f"\nDone. found={totals['found']}  inserted/updated={totals['inserted']}  skipped={totals['skipped']}")
