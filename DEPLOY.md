# StatAxis Deployment

This deployment uses the same application image for the web process and the always-on background worker. The worker runs `python -m collector.service`; GitHub Actions is not required for collection.

## Environment variables

Application:
- `YOUTUBE_API_KEY` — YouTube Data API key.
- `DATABASE_URL` — SQLAlchemy database URL used by the application and worker.
- `STAXIS_DATABASE_URL` — optional web-process fallback database URL when `DATABASE_URL` is absent.
- `STX_LOG_LEVEL` — application log level.
- `STAXIS_AUTH_SECRET` — authentication secret.
- `STAXIS_ADMIN_EMAIL` — first-admin email.
- `STAXIS_ADMIN_PASSWORD` — first-admin password.
- `COLLECT_SECONDS` — full collection interval; default 600, minimum 60.
- `LIVE_POLL_SECONDS` — live polling interval; default 30, minimum 5. Live polling shares the YouTube request budget below and runs in the same loop as full collection, so a long collection pass delays live polls.
- `PORT` — HTTP port supplied by the platform or used by Docker Compose.

Existing collector settings:
- `STAXIS_COLLECTION_INTERVAL_SECONDS` — interval for the legacy `collector.worker` entry point.
- `STAXIS_COLLECTION_MAX_VIDEOS` — maximum videos for the legacy worker/manual collection path.
- `STAXIS_YOUTUBE_REQUESTS_PER_MINUTE` — process-local YouTube request budget per minute.
- `STAXIS_YOUTUBE_REQUESTS_PER_DAY` — process-local YouTube request budget per day.

Docker Compose/Postgres:
- `POSTGRES_DB` — local Postgres database name.
- `POSTGRES_USER` — local Postgres user.
- `POSTGRES_PASSWORD` — local Postgres password.

Do not commit API keys, passwords, database URLs containing credentials, or authentication secrets.

## First admin

Set `STAXIS_ADMIN_EMAIL` and `STAXIS_ADMIN_PASSWORD` before starting the web service.

On application startup, StatAxis bootstraps that account:
- creates it if it does not exist;
- promotes an existing account with that email to admin;
- marks it active and approved;
- assigns the Enterprise plan;
- hashes the password and never logs the password.

After the first admin is created, keep the bootstrap credentials in the deployment secret store rather than in source control.

## Render: web + background worker + Postgres

Use three Render resources: one web service, one Background Worker, and one Render Postgres database.

### 1. Postgres

Create a Render Postgres database in the same region as the application. Copy its internal connection URL into `DATABASE_URL` for both the web service and worker.

### 2. Web service

Create a Render Web Service from this repository.

- Build command: `pip install -e .`
- Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 web:application`
- Health check: `/health`

Set:
- `DATABASE_URL`
- `YOUTUBE_API_KEY`
- `STAXIS_AUTH_SECRET`
- `STAXIS_ADMIN_EMAIL`
- `STAXIS_ADMIN_PASSWORD`

Secret values should be stored as Render environment variables, not committed to the repository.

### 3. Background Worker

Create a Render Background Worker from the same repository/image.

- Build command: `pip install -e .`
- Start command: `python -m collector.service`

Set the same database/API/auth variables needed by the worker and:
- `COLLECT_SECONDS` (optional; default 600)
- `LIVE_POLL_SECONDS` (optional; default 30)
- `STAXIS_YOUTUBE_REQUESTS_PER_MINUTE`
- `STAXIS_YOUTUBE_REQUESTS_PER_DAY`

The worker is independent of GitHub Actions and stays alive as a Render Background Worker.

### render.yaml

The repository's worker block starts `python -m collector.service`. Secret keys use `sync: false`; no secret values are stored in the file.

## VPS: Docker Compose

1. Copy the repository to the VPS.
2. Copy `.env.example` to `.env`.
3. Set the required variables, including `POSTGRES_PASSWORD`.
4. For the Compose stack, set `DATABASE_URL` to the Postgres service, for example using host `postgres` rather than `localhost`.
5. Start all services:

```bash
docker compose up -d --build
```

The stack contains:
- `web` — Gunicorn HTTP service.
- `worker` — `python -m collector.service`.
- `postgres` — PostgreSQL with a persistent named volume.

Check status:

```bash
docker compose ps
docker compose logs -f worker
```

The worker and web service use the same image, so application dependencies stay aligned.

## PostgreSQL backup

Run a logical dump from the Compose Postgres container:

```bash
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > stataxis-$(date +%F).sql
```

Store the resulting SQL dump outside the application container and test restores periodically.
