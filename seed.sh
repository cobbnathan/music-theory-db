#!/usr/bin/env bash
# Run inside the Render shell to seed the database on first deploy.
# This installs heavy ML dependencies and runs all scrapers + the pipeline.
# Only needed once — the persistent disk keeps the DB across redeploys.
set -euo pipefail

echo "==> Installing full pipeline dependencies"
pip install -r requirements.txt

DB="${DATABASE_PATH:-/data/music_theory.db}"
echo "==> Database will be written to $DB"

echo "==> Running scrapers"
python -m scrapers.journals
python -m scrapers.crossref
python -m scrapers.books_google
python -m scrapers.books_openlibrary
python -m scrapers.publishers

echo "==> Running normalization pipeline"
python pipeline/normalize.py

echo "==> Done. DB size: $(du -h "$DB" | cut -f1)"
