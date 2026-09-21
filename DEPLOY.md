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
- `LIVE_POLL_SECONDS` — live polling interval; default 30, minimum 5. Live polling runs in its own thread, so a long collection pass no longer delays it. Both share the YouTube request budget below.
- `STAXIS_YOUTUBE_LIVE_RESERVE_PER_MINUTE` — requests per minute kept free for live polling; collection cannot use them. Default 0 (no reserve). Suggested with a 300 per minute budget: 100.
- `PORT` — HTTP port supplied by the platform or used by Docker Compose.
- `STAXIS_TRUSTED_PROXIES` — number of trusted reverse proxies in front of the web process (default `1`, correct for Render). Used to find the real client IP for login/registration rate limits. Set `0` if the app is exposed directly with no proxy, otherwise clients can forge `X-Forwarded-For`.
- Collection and live polling run in separate threads, so a long collection pass over many channels never delays live polling. (The old `STAXIS_COLLECT_SLICE_CHANNELS` setting is no longer used.)
- `STAXIS_YOUTUBE_DAILY_QUOTA_UNITS` — your project's YouTube Data API daily quota (default `10000`). The worker logs a warning at the start of every pass when the channel count and intervals would exceed it.
- `STAXIS_PRIMARY_MIN_LIVE_HOURS` — how long a live stream must have been running before it counts as a channel's Primary feed (default `720`, i.e. 30 days). Other concurrent streams are Secondary feeds; All feed = Primary + Secondary.

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

## Growing the channel universe

STAXIS collects the channels listed in `config/channels.json`. Each entry has a `segment`
(`news`, `business`, `print`, `party`, `leader`, `commentator`) and a `language`; together they decide the
market a channel is reported in (Hindi News, English News, Business News, Print Media, Political Parties &
Leaders, Political Commentators).

`config/channel_candidates.json` lists channels to add, by name, with no IDs. To register them (needs `YOUTUBE_API_KEY`):

```bash
python -m collector.resolve_candidates --resolve --limit 20   # finds likely channels (100 quota units per search)
python -m collector.resolve_candidates --list                 # review the suggestions
python -m collector.resolve_candidates --approve "Zee News"   # accept the best match (or --pick 2)
python -m collector.candidate_importer --add-verified         # re-verifies against the API and registers
```

A name search can return fan or re-upload channels, so nothing is registered without an approval. Commit
`config/channels.json` and redeploy the worker to start collecting the new channels. One channel failing
(deleted, renamed) is skipped and logged; it no longer stops the rest of the pass.

### YouTube quota

Each channel costs 3 quota units per collection pass, and live polling costs 1 unit per 50 live videos per poll.
The default quota is 10,000 units/day.

| Channels | `COLLECT_SECONDS` | Units/day | Fits 10,000? |
|---|---|---|---|
| 5 | 600 | about 5,000 | yes |
| 60 | 600 | about 31,700 | no |
| 60 | 5,676 | about 8,500 | yes, but a pass only every 95 minutes |

For a large universe, request a higher quota from Google (Google Cloud console, YouTube Data API v3, Quotas),
then set `STAXIS_YOUTUBE_DAILY_QUOTA_UNITS` and `STAXIS_YOUTUBE_REQUESTS_PER_DAY` to the new value.

## Live feed statistics

- `GET /api/v1/audience/live/snapshot?at=...` viewers at one instant, per channel and market: Primary / Secondary / All.
- `GET /api/v1/audience/live/stats?start=...&end=...` average and peak concurrent viewers for Primary / Secondary / All
  over a window of up to 24 hours, with share % and a ready-to-post headline per market.
- `GET /api/v1/audience/live/stats/export?...` the same as an Excel file, with a Method sheet.

Optional `language`, `segment` and `bucket_seconds` (minimum 30, default 60) parameters apply. Times are UTC.
