"""Normalize and deduplicate scraped records before inserting into the database."""
import sqlite_utils


def normalize_record(record: dict) -> dict:
    return record


def upsert_records(db: sqlite_utils.Database, table: str, records: list[dict], pk: str = "id"):
    db[table].upsert_all(records, pk=pk)
