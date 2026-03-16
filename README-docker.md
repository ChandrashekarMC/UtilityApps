# PersMgr Docker Project

This is an isolated copy of the app for containerized deployment experiments.
It does not modify the original `MCApps` project.

## Quick start

1. Copy env file:
   - Linux/macOS: `cp .env.example .env`
   - Windows PowerShell: `Copy-Item .env.example .env`
2. Fill `.env` with `FLASK_SECRET_KEY` and Google OAuth values.
3. Build and run:
   - `docker compose up -d --build`
4. Open app:
   - `http://localhost:8000`
5. OAuth health check:
   - `http://localhost:8000/health/google-login`

## Persistent data

The app stores SQLite DB and uploads in Docker volume `persmgr_data` under `/app/data`.

## Stop

- `docker compose down`

## Notes

- This setup intentionally keeps SQLite for low-complexity migration.
- If you later switch to MySQL, convert DB access layer first (current code uses sqlite3 APIs directly).
