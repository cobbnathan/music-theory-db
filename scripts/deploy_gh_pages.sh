#!/usr/bin/env bash
# Deploy the frontend to the gh-pages branch on GitHub.
#
# What it does:
#   1. Runs export_static.py to regenerate data.json and index-gh.html
#   2. Commits those files to main
#   3. Pushes the frontend/ subtree to origin/gh-pages with index-gh.html
#      served as index.html (GitHub Pages requires this name)
#
# Usage: bash scripts/deploy_gh_pages.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Regenerating static data..."
python3 scripts/export_static.py

echo "==> Committing updated data..."
git add frontend/data/data.json frontend/index-gh.html
git diff --cached --quiet && echo "    (nothing changed)" || git commit -m "Update static data"

echo "==> Pushing frontend/ to gh-pages branch..."
# git subtree push can't rename files, so we use a temp branch approach:
# 1. Extract frontend/ as a subtree commit
# 2. Rename index-gh.html → index.html on that branch
# 3. Force-push to origin/gh-pages

SUBTREE_COMMIT=$(git subtree split --prefix frontend)

# Create/reset a local deploy branch from that subtree commit
git branch -f _gh_pages_tmp "$SUBTREE_COMMIT"

# Stash any uncommitted changes so git checkout can proceed
STASH_OUT=$(git stash push -m "deploy-script-tmp" 2>&1)
STASHED=$( echo "$STASH_OUT" | grep -c "Saved working" || true )

# Rename index-gh.html to index.html on the deploy branch
git checkout _gh_pages_tmp
cp index-gh.html index.html 2>/dev/null || true
git add index.html
git diff --cached --quiet || git commit -m "chore: use static index.html for gh-pages"
DEPLOY_COMMIT=$(git rev-parse HEAD)

# Return to main
git checkout main

# Restore stashed changes
[ "$STASHED" -gt 0 ] && git stash pop

# Force-push the deploy branch to origin/gh-pages
git push origin "${DEPLOY_COMMIT}:refs/heads/gh-pages" --force

# Clean up temp branch
git branch -D _gh_pages_tmp

echo ""
echo "Done! Site will be live at your GitHub Pages URL in ~60 seconds."
