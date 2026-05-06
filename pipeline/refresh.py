"""Orchestrates a full data refresh: scrape → normalize → store."""
import sqlite_utils
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "music_theory.db"


def run_refresh():
    db = sqlite_utils.Database(DB_PATH)
    # TODO: call scrapers and normalize results
    print("Refresh complete.")


if __name__ == "__main__":
    run_refresh()
