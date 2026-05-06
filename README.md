# Music Theory DB

A searchable database of music theory books, journals, and articles, built with Python scrapers, SQLite, and a lightweight Flask API.

## Project Structure

```
music-theory-db/
├── scrapers/          # Source-specific scrapers (Google Books, Open Library, journals, publishers)
├── pipeline/          # Normalization and refresh orchestration
├── api/               # Flask REST API
├── frontend/          # Static HTML/CSS/JS search UI
├── data/              # SQLite database
└── .github/workflows/ # Weekly automated refresh via GitHub Actions
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Running locally

```bash
# Run a data refresh
python pipeline/refresh.py

# Start the API
python api/app.py
```

## Deployment

Configured for [Render](https://render.com) via `render.yaml`. The `Procfile` starts the app with Gunicorn.

## Automated refresh

A GitHub Actions workflow (`.github/workflows/weekly-refresh.yml`) runs every Sunday at 03:00 UTC, updates the database, and commits the result.
