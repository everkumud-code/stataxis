CREATE TABLE IF NOT EXISTS stx_channels (
    id BIGSERIAL PRIMARY KEY,
    youtube_channel_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    network TEXT,
    language TEXT,
    category TEXT NOT NULL DEFAULT 'news',
    uploads_playlist_id TEXT,
    priority SMALLINT NOT NULL DEFAULT 3,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stx_videos (
    id BIGSERIAL PRIMARY KEY,
    youtube_video_id TEXT UNIQUE NOT NULL,
    channel_id BIGINT NOT NULL REFERENCES stx_channels(id),
    title TEXT NOT NULL,
    description TEXT,
    published_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    live_broadcast_content TEXT,
    live_started_at TIMESTAMPTZ,
    live_ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stx_observations (
    id BIGSERIAL PRIMARY KEY,
    video_id BIGINT NOT NULL REFERENCES stx_videos(id),
    channel_id BIGINT NOT NULL REFERENCES stx_channels(id),
    observed_at TIMESTAMPTZ NOT NULL,
    view_count BIGINT,
    like_count BIGINT,
    comment_count BIGINT,
    concurrent_viewers BIGINT,
    is_live BOOLEAN NOT NULL DEFAULT FALSE,
    source TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    UNIQUE(video_id, observed_at, source)
);

CREATE INDEX IF NOT EXISTS idx_stx_observations_video_time
    ON stx_observations(video_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_stx_observations_channel_time
    ON stx_observations(channel_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS stx_collection_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    channels_attempted INTEGER NOT NULL DEFAULT 0,
    videos_observed INTEGER NOT NULL DEFAULT 0,
    api_calls INTEGER NOT NULL DEFAULT 0,
    quota_estimate INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);
