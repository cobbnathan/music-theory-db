# Deploying to Render.com

This app runs as a Python web service on Render's free tier. A persistent disk stores the SQLite database across redeploys.

## Prerequisites

- A [Render.com](https://render.com) account (free)
- This repo pushed to GitHub or GitLab
- A Google Books API key (optional — only needed if you want to re-run the books scraper)

---

## First-time deploy

### 1. Create the web service

1. Go to **New → Web Service** in the Render dashboard.
2. Connect your GitHub/GitLab repo.
3. Render will detect `render.yaml` automatically. Click **Apply** to use its settings, or configure manually:

   | Setting | Value |
   |---|---|
   | Environment | Python |
   | Build command | `bash build.sh` |
   | Start command | `gunicorn api.app:app --workers 2 --timeout 120` |
   | Plan | Free |

4. Under **Disks**, add a disk:

   | Setting | Value |
   |---|---|
   | Name | `db-data` |
   | Mount path | `/data` |
   | Size | 1 GB |

5. Under **Environment Variables**, set:

   | Key | Value |
   |---|---|
   | `DATABASE_PATH` | `/data/music_theory.db` |
   | `PYTHON_VERSION` | `3.12` |
   | `GOOGLE_BOOKS_API_KEY` | *(your key, or leave blank)* |

6. Click **Create Web Service**. The build will run `bash build.sh`, which only installs the lightweight API dependencies (`requirements-api.txt`). The app will start but return 500 errors until the database is seeded.

---

### 2. Seed the database (one-time, ~10–30 min)

The database must be built once on the persistent disk. Do this from the Render shell:

1. In the Render dashboard, go to your service → **Shell** tab.
2. Run:

   ```bash
   bash seed.sh
   ```

   This will:
   - Install the full ML/scraper dependencies (`requirements.txt`)
   - Run all five scrapers (journals, CrossRef, Google Books, Open Library, publishers)
   - Run the normalization pipeline
   - Write `music_theory.db` to `/data/`

3. When it completes, your service should start returning data from the API. Visit your Render URL to confirm.

> **Note:** The free tier shell session may time out for very long runs. If `seed.sh` is interrupted, just re-run it — the scrapers are additive (they upsert, not overwrite).

---

## Redeploys

Subsequent deploys run `bash build.sh` again, which:
- Reinstalls `requirements-api.txt` (fast)
- Checks for the DB at `$DATABASE_PATH` and prints its size

The database on the persistent disk is **preserved across redeploys**. You never need to re-run `seed.sh` unless you want to re-scrape.

To update the database content after a redeploy, open the Shell and run individual scrapers:

```bash
python -m scrapers.crossref
python pipeline/normalize.py
```

---

## Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `DATABASE_PATH` | Yes | Path to the SQLite file, e.g. `/data/music_theory.db` |
| `PYTHON_VERSION` | Yes | Set to `3.12` |
| `GOOGLE_BOOKS_API_KEY` | No | Used by `scrapers/books_google.py` only |

---

## Troubleshooting

**App returns 500 errors after deploy**
→ The database hasn't been seeded yet. Open the Shell and run `bash seed.sh`.

**Shell session times out during seeding**
→ Re-run `bash seed.sh`. All scrapers upsert, so partial runs are safe to resume.

**`gunicorn` can't find `api.app`**
→ Make sure the repo root is the working directory. The `api/app.py` file must exist.

**Free tier spins down after inactivity**
→ This is expected on Render's free tier. The first request after a spin-down takes ~30 seconds. Upgrade to a paid plan to avoid cold starts.
