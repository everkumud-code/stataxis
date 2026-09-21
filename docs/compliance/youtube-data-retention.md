# YouTube API data-retention classification

StatAxis uses public YouTube API data only. This inventory is the implementation basis for the 36-month / 30-day retention rules.

| Table | Public statistics / derived metrics | Other YouTube API data | Retention enforcement |
|---|---|---|---|
| `stx_observations` | `view_count`, `like_count`, `comment_count`, `concurrent_viewers` and timestamped observation history | `is_live`, classification/source metadata are stored with the observation | Rows older than the configured 36 calendar months are deleted |
| `stx_channel_stats` | `subscribers`, `total_views`, `video_count` | — | Rows older than the configured 36 calendar months are deleted |
| `stx_intelligence_snapshots` | STX score, confidence, signal values, contributions and measurement provenance | Snapshot `data`, `analysis` and `view` may contain video/title context | Snapshots older than 36 months are deleted; within the 36-month window, expired metadata-bearing fields are sanitized after the configured 30 days |
| `stx_videos` | Stable `youtube_video_id` / internal ID relationships | `title`, `published_at`, `thumbnail_url`, `category_id`, `topic` | Metadata is refreshed on collection; if not refreshed within 30 days it is cleared while IDs and numeric observations remain |
| `stx_channels` | Stable `youtube_channel_id` | API `avatar_url`, `handle`; `name` is the StatAxis display name/configuration field | API metadata is refreshed on collection and cleared after 30 days when stale |
| `stx_collection_runs` | Operational run timestamps/counts | No YouTube API payload | Operational records are not part of the YouTube data-retention purge |

## Derived-metric provenance

STX and related derived metrics are generated independently by StatAxis from stored observations. They are not supplied, calculated, endorsed or certified by YouTube.

Visible label used in UI/export surfaces:

> **Generated independently by StatAxis; not sourced from YouTube**

## Configuration safety

Destructive retention requires both environment variables to be present and valid:

- `STAXIS_RETENTION_STATISTICS_MONTHS` — positive integer; intended production value: `36`
- `STAXIS_RETENTION_METADATA_DAYS` — positive integer; intended production value: `30`

If either variable is missing or invalid, the retention job performs **no deletion or metadata clearing** and logs the reason.

## Dry run

With the database environment available:

```bash
STAXIS_RETENTION_STATISTICS_MONTHS=36 STAXIS_RETENTION_METADATA_DAYS=30 python -m collector.retention --dry-run
```

No Render service is added. The normal collection cycle invokes the retention job after collection/intelligence processing.
