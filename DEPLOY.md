# StatAxis deployment

The always-on worker has no GitHub Actions dependency. Run `python -m collector.service` as a long-lived process.

## Environment variables

- `YOUTUBE_API_KEY`: YouTube Data API key.
- `DATABASE_URL`: SQLAlchemy database URL.
- `STX_LOG_LEVEL`: logging level; default `INFO`.
- `STAXIS_COLLECTION_INTERVAL_SECONDS`: legacy worker interval.
- `STAXIS_COLLECTION_MAX_VIDEOS`: legacy worker maximum videos per channel.
- `STAXIS_YOUTUBE_REQUESTS_PER_MINUTE`: YouTube request budget per minute; default `60`.
- `STAXIS_YOUTUBE_REQUESTS_PER_DAY`: YouTube request budget per day; default `9000`.
- `STAXIS_AUTH_SECRET`: authentication secret.
- `STAXIS_ADMIN_EMAIL`: first-admin email.
- `STAXIS_ADMIN_PASSWORD`: first-admin password.
- `COLLECT_SECONDS`: full collection interval; default `600`, minimum `60`.
- `LIVE_POLL_SECONDS`: live polling interval; default `30`, minimum `30`.

Put environment names only in `.env.example`; put real values in deployment environment/secrets.

## First admin

Set `STAXIS_ADMIN_EMAIL` and `STAXIS_ADMIN_PASSWORD` before the first web startup. Application bootstrap creates or promotes that user as an approved admin. Never commit either value.

## Render

Create two services from the same repository/image:

1. **Web service**: build the Dockerfile and run the Dockerfile command (or `gunicorn web:application`). Set Render's `PORT` and the application environment variables.
2. **Background worker**: build the same image and start it with `python -m collector.service`. Set the same database/API environment variables.
3. Use managed Postgres and set `DATABASE_URL` on both services.

The worker is independent of GitHub Actions.

## VPS with Docker Compose

1. Copy `.env.example` to `.env` and fill in real values.
2. Run `docker compose up -d --build`.
3. Web, worker, and Postgres run as separate services; Postgres data is stored in the named `postgres_data` volume.
4. Check with `docker compose ps` and `docker compose logs worker`.

## Postgres backup

For the Compose database:

`docker compose exec -T postgres pg_dump -U stataxis -d stataxis > stataxis-$(date +%Y%m%d-%H%M%S).sql`

For managed Postgres, run `pg_dump` from a trusted machine using the deployment's database credentials.
