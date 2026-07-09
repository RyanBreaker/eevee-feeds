# Feedings

A simple web app for tracking a baby's oral (PO) and NG-tube feedings, with daily totals and a weekly target that increases every Wednesday.

## Stack

- Python + FastAPI
- SQLModel + SQLAlchemy
- PostgreSQL (production/Railway) or SQLite (local)
- Jinja2 + HTMX + Chart.js

## Run locally

### With SQLite

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.import_csv
uvicorn app.main:app --reload --log-config log_config.json
```

Open http://localhost:8000.

### With Docker Compose + PostgreSQL

```bash
docker compose up
```

Open http://localhost:8000.

## Import existing CSV

From the command line:

```bash
python -m scripts.import_csv
```

Or from the app: go to **Settings** and use the **Import CSV** upload form.

The CSV should have columns `Timestamp, PO, NG`. If feedings already exist in the database, the import is skipped to avoid duplicates.

## Deploy to Railway

1. Push this repo to GitHub.
2. Create a Railway project from the repo.
3. Add a Railway PostgreSQL database (`DATABASE_URL` is set automatically).
4. Set environment variables:
   - `AUTH_USERNAME`
   - `AUTH_PASSWORD`
   - `SECRET_KEY` (a long random string used to sign session cookies)
   - `SESSION_SECURE=true` (so the session cookie is only sent over HTTPS)
   - `NTFY_TOPIC` (optional, for ntfy push notifications)
   - `NTFY_SERVER` (optional, defaults to `https://ntfy.sh`)
5. Deploy.

Railway uses the `Dockerfile`.

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection URL | `sqlite:///./feedings.db` |
| `AUTH_USERNAME` | Login username | none (auth disabled) |
| `AUTH_PASSWORD` | Login password | none (auth disabled) |
| `SECRET_KEY` | Secret key used to sign session cookies | fallback to `AUTH_PASSWORD` or `dev-secret-key` |
| `SESSION_MAX_AGE` | Session cookie lifetime in seconds | `2592000` (30 days) |
| `SESSION_SECURE` | Only send session cookie over HTTPS | `false` |
| `TZ` | Server timezone for period boundaries (e.g. `America/Chicago`) | `America/Chicago` |
| `NTFY_TOPIC` | ntfy topic for push notifications | none (disabled) |
| `NTFY_SERVER` | ntfy server URL | `https://ntfy.sh` |
| `NTFY_THRESHOLDS` | Hours since last feed to notify, comma-separated | `2,3,4` |
| `APP_URL` | Optional URL added to ntfy notifications as a click link | none |

## Notifications

The app can push alerts to [ntfy](https://ntfy.sh) when a configurable number of hours have passed since the most recent feeding.

To enable notifications:

1. Create a topic on ntfy (e.g., from the ntfy app or by picking a unique topic name).
2. Set `NTFY_TOPIC` to that topic name.
3. Optional: set `NTFY_SERVER` if you are self-hosting, and `APP_URL` if you want the notification to open the app when tapped.

The default thresholds are 2, 3, and 4 hours. The app checks once per minute and sends one alert per threshold. Alerts stop after the highest threshold.

Go to **Settings** to see the configured topic, the next expected notification time, and to send a test notification.

## Timezone

Period boundaries are based on server time. When deploying to Railway, set `TZ` to your local timezone (e.g. `America/New_York`) so the 6AM cutoff and current period line up with your day.

## CSV export

Go to **Settings** and click **Export Feedings** to download a CSV of all feedings.
