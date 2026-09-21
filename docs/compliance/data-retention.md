# YouTube API data retention

Implemented in `collector/retention.py`; runs after every collection pass (at most once per hour per process) and on demand:

```
python -m collector.retention --dry-run   # count only
python -m collector.retention             # apply
```

| Data | Where | Rule | Action |
|---|---|---|---|
| Views, likes, comments, concurrent viewers | `stx_observations` | 36 calendar months | rows deleted |
| Subscribers, total views, video count | `stx_channel_stats` | 36 calendar months | rows deleted |
| STX / intelligence snapshots (derived) | `stx_intelligence_snapshots` | 36 calendar months | rows deleted |
| Video title, thumbnail, category | `stx_videos` | refreshed within 30 days | cleared if `api_refreshed_at` older than 30 days (title becomes `[title not retained]`) |
| Channel avatar, handle | `stx_channels` | refreshed within 30 days | cleared if `api_refreshed_at` older than 30 days |

Video IDs, channel IDs, numeric statistics and STAXIS-derived `topic` are kept. Re-collecting a video restores its metadata and resets the timer.

Channel display names (`stx_channels.name`) are editorial labels set from `config/channels.json` or the admin rename tool, not refreshed from the API, so they are not scrubbed. `stx_videos.published_at` is kept because age and velocity calculations depend on it.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `STAXIS_RETENTION_ENABLED` | `true` | set `false` to switch off |
| `STAXIS_RETENTION_DRY_RUN` | `false` | log counts only |
| `STAXIS_RETENTION_STATS_MONTHS` | `36` | 1 to 36; invalid or larger values fall back to 36 |
| `STAXIS_RETENTION_API_DATA_DAYS` | `30` | 1 to 30; invalid or larger values fall back to 30 |

## First deploy

The migration adds `api_refreshed_at` to `stx_videos` and `stx_channels` and stamps existing rows with the migration time, so nothing is scrubbed until it has gone 30 days without a refresh.
