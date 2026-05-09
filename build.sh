#!/usr/bin/env bash
# Render.com build script
# Installs only the API dependencies (no ML/scraper stack).
# The database must already exist at $DATABASE_PATH (see DEPLOY_RENDER.md).
set -euo pipefail

echo "==> Installing API dependencies"
pip install -r requirements-api.txt

DB="${DATABASE_PATH:-/data/music_theory.db}"

if [ -f "$DB" ]; then
  echo "==> Database found at $DB ($(du -h "$DB" | cut -f1))"
else
  echo ""
  echo "⚠️  No database found at $DB."
  echo "    After this deploy completes, open the Render shell and run:"
  echo ""
  echo "      bash seed.sh"
  echo ""
  echo "    That will install the full pipeline dependencies and build the DB."
  echo "    The app will return 500 errors until the database is present."
  echo ""
fi
