"""Persistence layer for timestamped STAXIS observations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from collector.topics import assign_topic
from collector.youtube.collector import VideoObservation


class Base(DeclarativeBase):
    pass


class Channel(Base):
    __tablename__ = "stx_channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    network: Mapped[str] = mapped_column(String(255), default="unknown")
    language: Mapped[str] = mapped_column(String(100), default="unknown")
    region: Mapped[str] = mapped_column(String(100), default="unknown", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # When YouTube API-sourced fields (avatar, handle) were last refreshed from the API.
    api_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=lambda: datetime.now(UTC))
    segment: Mapped[str] = mapped_column(String(32), default="news", index=True)


class ChannelLanguageOverride(Base):
    __tablename__ = "stx_channel_language_overrides"
    __table_args__ = (UniqueConstraint("channel_id", name="uq_stx_channel_language_override"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("stx_channels.id"), index=True)
    language: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Video(Base):
    __tablename__ = "stx_videos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("stx_channels.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # When YouTube API-sourced non-statistic fields (title, thumbnail, category) were last refreshed.
    api_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=lambda: datetime.now(UTC))
    live_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    live_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChannelStats(Base):
    __tablename__ = "stx_channel_stats"
    __table_args__ = (UniqueConstraint("channel_id", "observed_at", name="uq_stx_channel_stats_channel_timestamp"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("stx_channels.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    subscribers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    video_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Observation(Base):
    __tablename__ = "stx_observations"
    __table_args__ = (UniqueConstraint("video_id", "observed_at", name="uq_stx_observation_video_timestamp"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("stx_videos.id"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("stx_channels.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concurrent_viewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    classification: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    source: Mapped[str] = mapped_column(String(50), default="youtube_data_api")
    collector_version: Mapped[str] = mapped_column(String(32), default="0.1.0")


class CollectionRun(Base):
    __tablename__ = "stx_collection_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    channels_attempted: Mapped[int] = mapped_column(Integer, default=0)
    videos_observed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base):
    __tablename__ = "stx_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    plan: Mapped[str] = mapped_column(String(32), default="sx_free", index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose_of_use: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_plan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PackageConfig(Base):
    """Reserved commercial package slot; intentionally empty until configured."""
    __tablename__ = "stx_package_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    criteria_json: Mapped[str] = mapped_column(Text, default="[]")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


def _add_column_if_missing(connection, table: str, name: str, definition: str, known_columns: set[str]) -> None:
    if name in known_columns:
        return
    dialect = connection.dialect.name
    statement = (
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}"
        if dialect == "postgresql"
        else f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
    )
    try:
        connection.execute(text(statement))
    except Exception as exc:
        message = str(exc).lower()
        duplicate_column = "duplicate column" in message or "duplicate_column" in message
        if dialect == "postgresql" or not duplicate_column:
            raise


def create_database(url: str):
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    if url.startswith("sqlite:"):
        engine = create_engine(url, future=True)
    else:
        engine = create_engine(url, future=True, pool_pre_ping=True, pool_recycle=240)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        columns = {item["name"] for item in inspect(connection).get_columns("stx_users")}
        additions = {
            "approval_status": "VARCHAR(20) DEFAULT 'pending'",
            "full_name": "VARCHAR(255)",
            "mobile": "VARCHAR(32)",
            "organization": "VARCHAR(255)",
            "purpose_of_use": "TEXT",
            "requested_plan": "VARCHAR(32)",
        }
        for name, definition in additions.items():
            _add_column_if_missing(connection, "stx_users", name, definition, columns)
        connection.execute(text("UPDATE stx_users SET approval_status='approved' WHERE approval_status IS NULL"))
        channel_columns = {item["name"] for item in inspect(connection).get_columns("stx_channels")}
        for name, definition in {"avatar_url": "VARCHAR(1000)", "handle": "VARCHAR(255)", "segment": "VARCHAR(32) DEFAULT 'news'"}.items():
            _add_column_if_missing(connection, "stx_channels", name, definition, channel_columns)
        connection.execute(text("UPDATE stx_channels SET segment='news' WHERE segment IS NULL"))
        video_columns = {item["name"] for item in inspect(connection).get_columns("stx_videos")}
        for name, definition in {"thumbnail_url": "VARCHAR(1000)", "category_id": "VARCHAR(32)", "topic": "VARCHAR(64)", "live_started_at": "TIMESTAMP WITH TIME ZONE", "live_ended_at": "TIMESTAMP WITH TIME ZONE"}.items():
            _add_column_if_missing(connection, "stx_videos", name, definition, video_columns)
        # api_refreshed_at powers the 30-day refresh-or-delete rule. Existing rows are
        # stamped "now" once, when the column is first added, so nothing is scrubbed
        # before it has had a full retention window to be refreshed.
        timestamp_type = "TIMESTAMPTZ" if connection.dialect.name == "postgresql" else "DATETIME"
        for table, known in (("stx_channels", channel_columns), ("stx_videos", video_columns)):
            if "api_refreshed_at" not in known:
                _add_column_if_missing(connection, table, "api_refreshed_at", timestamp_type, known)
                connection.execute(text(f"UPDATE {table} SET api_refreshed_at = CURRENT_TIMESTAMP WHERE api_refreshed_at IS NULL"))
    return engine


def effective_channel_language(session: Session, channel: Channel, fallback: str = "unknown") -> str:
    override = session.query(ChannelLanguageOverride).filter_by(channel_id=channel.id).one_or_none()
    if override is not None:
        return override.language
    return channel.language or fallback


def _parse_rfc3339(value: str | None) -> datetime | None:
    """Parse a YouTube RFC 3339 timestamp; return None when absent or malformed."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def save_observations(
    session: Session,
    channel_name: str,
    channel_youtube_id: str,
    network: str,
    language: str,
    observations: list[VideoObservation],
    region: str | None = None,
    *,
    avatar_url: str | None = None,
    handle: str | None = None,
    segment: str | None = None,
    channel_stats: tuple[datetime, int | None, int | None, int | None] | None = None,
) -> int:
    channel = session.query(Channel).filter_by(youtube_channel_id=channel_youtube_id).one_or_none()
    if channel is None:
        channel = Channel(youtube_channel_id=channel_youtube_id, name=channel_name, network=network, language=language, region=region or "unknown", segment=segment or "news")
        session.add(channel)
        session.flush()
    else:
        override = session.query(ChannelLanguageOverride).filter_by(channel_id=channel.id).one_or_none()
        channel.language = override.language if override is not None else (language if language and language.strip().lower() != "unknown" else channel.language)
        if region is not None:
            channel.region = region
    if avatar_url is not None:
        channel.avatar_url = avatar_url
        channel.api_refreshed_at = datetime.now(UTC)
    if handle is not None:
        channel.handle = handle
        channel.api_refreshed_at = datetime.now(UTC)
    if segment is not None:
        channel.segment = segment
    if channel_stats is not None:
        observed_at, subscribers, total_views, video_count = channel_stats
        session.add(ChannelStats(
            channel_id=channel.id,
            observed_at=observed_at,
            subscribers=subscribers,
            total_views=total_views,
            video_count=video_count,
        ))
    saved = 0
    seen: set[tuple[str, datetime]] = set()
    for item in observations:
        key = (item.video_id, item.observed_at)
        if key in seen:
            continue
        seen.add(key)
        video = session.query(Video).filter_by(youtube_video_id=item.video_id).one_or_none()
        if video is None:
            video = Video(
                youtube_video_id=item.video_id, channel_id=channel.id, title=item.title,
                published_at=item.published_at, thumbnail_url=item.thumbnail_url,
                category_id=item.category_id, topic=item.topic or assign_topic(item.title),
                live_started_at=_parse_rfc3339(getattr(item, "live_started_at", None)),
                live_ended_at=_parse_rfc3339(getattr(item, "live_ended_at", None)),
            )
            session.add(video)
            session.flush()
        else:
            # Start/end are set once YouTube reports them; never overwritten with a missing value.
            started = _parse_rfc3339(getattr(item, "live_started_at", None))
            ended = _parse_rfc3339(getattr(item, "live_ended_at", None))
            if started is not None:
                video.live_started_at = started
            if ended is not None:
                video.live_ended_at = ended
            video.title = item.title
            video.published_at = item.published_at
            video.api_refreshed_at = datetime.now(UTC)
            if item.thumbnail_url is not None:
                video.thumbnail_url = item.thumbnail_url
            if item.category_id is not None:
                video.category_id = item.category_id
            if item.topic is not None:
                video.topic = item.topic
            elif video.topic is None:
                video.topic = assign_topic(video.title)
        if session.query(Observation.id).filter_by(video_id=video.id, observed_at=item.observed_at).first() is not None:
            continue
        session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=item.observed_at, view_count=item.view_count, like_count=item.like_count, comment_count=item.comment_count, concurrent_viewers=item.concurrent_viewers, is_live=item.is_live, classification=item.classification))
        saved += 1
    session.commit()
    return saved
