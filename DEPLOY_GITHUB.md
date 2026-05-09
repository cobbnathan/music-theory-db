# Deploying to GitHub Pages

The app can run as a fully static site — no server, no API, no cost. A single `data.json` file contains the entire database, and `app.js` loads it client-side.

## How it works

- `scripts/export_static.py` exports the SQLite database to `frontend/data/data.json`
- `scripts/build_info.py` exports statistics to `frontend/data/info.json`
- `scripts/export_static.py` also generates `frontend/index-gh.html`, which is a copy of `index.html` with a one-line script injected that tells `app.js` to use the local JSON file instead of API calls
- GitHub Pages serves everything from the `frontend/` directory

---

## Prerequisites

- Python 3.9+ with the project venv activated (or dependencies installed)
- The SQLite database built locally at `data/music_theory.db`
- Git and the GitHub CLI (`gh`), or manual pushes are fine

---

## Build the static files

From the repo root:

```bash
# Activate your venv first
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

# Export database → data.json and info.json
python scripts/export_static.py
python scripts/build_info.py
```

This writes:

| File | Description |
|---|---|
| `frontend/data/data.json` | All keywords + items (~5–8 MB compressed) |
| `frontend/data/info.json` | Statistics for the info panel |
| `frontend/index-gh.html` | `index.html` with `STATIC_DATA_URL` injected |

Re-run these scripts any time the database changes.

---

## Deploy

### Option A: GitHub Actions (recommended)

Create `.github/workflows/pages.yml`:

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements-api.txt
      - name: Build static files
        run: |
          python scripts/export_static.py
          python scripts/build_info.py
      - name: Prepare pages directory
        run: |
          cp frontend/index-gh.html frontend/index.html
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: frontend/
      - uses: actions/deploy-pages@v4
        id: deployment
```

> **Note:** This workflow requires `data/music_theory.db` to be committed to the repo (or fetched from an artifact). If the database is large, consider committing it with Git LFS, or run the scrapers as part of the workflow.

Then enable GitHub Pages in your repo settings:
**Settings → Pages → Source → GitHub Actions**

### Option B: Manual deploy

1. Run the build scripts (see above).
2. Copy `frontend/index-gh.html` to `frontend/index.html`:

   ```bash
   cp frontend/index-gh.html frontend/index.html
   ```

3. Push the `frontend/` directory to the `gh-pages` branch:

   ```bash
   git subtree push --prefix frontend origin gh-pages
   ```

   Or use the `gh-pages` npm package:

   ```bash
   npx gh-pages -d frontend
   ```

4. In your repo settings: **Settings → Pages → Source → Deploy from branch → `gh-pages` / `/ (root)`**

Your site will be live at `https://<your-username>.github.io/<repo-name>/`.

---

## Keeping data fresh

The static export is a snapshot. To update:

1. Re-run scrapers locally (or on a schedule)
2. Re-run `export_static.py` and `build_info.py`
3. Commit and push — GitHub Actions redeploys automatically

---

## File size notes

`data.json` contains the full database (~8,800 items × all fields). Typical sizes:

| Content | Approx size |
|---|---|
| Uncompressed JSON | 6–9 MB |
| Gzip (served by GitHub Pages) | 1.5–2.5 MB |

GitHub Pages automatically serves gzip-compressed responses, so load time is fast even on slow connections.

---

## Differences from the Render deployment

| Feature | GitHub Pages (static) | Render (API) |
|---|---|---|
| Cost | Free | Free tier available |
| Backend | None | Flask + gunicorn |
| Data freshness | Manual rebuild | Live DB queries |
| Search | Client-side (all fields) | Server-side (SQLite FTS) |
| Cold starts | None | ~30s on free tier |
| Custom domain | Yes (CNAME) | Yes |
