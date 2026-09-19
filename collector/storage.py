"""Persistence layer for timestamped STAXIS observations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

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


class ChannelStats(Base):
    __tablename__ = "stx_channel_stats"
    __table_args__ = (UniqueConstraint("channel_id", "observed_at", name="uq_stx_channel_stats_channel_timestamp"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("stx_channels.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    subscribers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
            if name not in columns:
                connection.execute(text(f"ALTER TABLE stx_users ADD COLUMN {name} {definition}"))
        connection.execute(text("UPDATE stx_users SET approval_status='approved' WHERE approval_status IS NULL"))
        channel_columns = {item["name"] for item in inspect(connection).get_columns("stx_channels")}
        for name, definition in {"avatar_url": "VARCHAR(1000)", "handle": "VARCHAR(255)"}.items():
            if name not in channel_columns:
                connection.execute(text(f"ALTER TABLE stx_channels ADD COLUMN {name} {definition}"))
        video_columns = {item["name"] for item in inspect(connection).get_columns("stx_videos")}
        for name, definition in {"thumbnail_url": "VARCHAR(1000)", "category_id": "VARCHAR(32)", "topic": "VARCHAR(64)"}.items():
            if name not in video_columns:
                connection.execute(text(f"ALTER TABLE stx_videos ADD COLUMN {name} {definition}"))
    return engine


def effective_channel_language(session: Session, channel: Channel, fallback: str = "unknown") -> str:
    override = session.query(ChannelLanguageOverride).filter_by(channel_id=channel.id).one_or_none()
    if override is not None:
        return override.language
    return channel.language or fallback


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
    channel_stats: tuple[datetime, int | None, int | None, int | None] | None = None,
) -> int:
    channel = session.query(Channel).filter_by(youtube_channel_id=channel_youtube_id).one_or_none()
    if channel is None:
        channel = Channel(youtube_channel_id=channel_youtube_id, name=channel_name, network=network, language=language, region=region or "unknown")
        session.add(channel)
        session.flush()
    else:
        override = session.query(ChannelLanguageOverride).filter_by(channel_id=channel.id).one_or_none()
        channel.language = override.language if override is not None else (language if language and language.strip().lower() != "unknown" else channel.language)
        if region is not None:
            channel.region = region
    if avatar_url is not None:
        channel.avatar_url = avatar_url
    if handle is not None:
        channel.handle = handle
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
                category_id=item.category_id, topic=item.topic,
            )
            session.add(video)
            session.flush()
        else:
            video.title = item.title
            video.published_at = item.published_at
            video.thumbnail_url = item.thumbnail_url
            video.category_id = item.category_id
            video.topic = item.topic
        if session.query(Observation.id).filter_by(video_id=video.id, observed_at=item.observed_at).first() is not None:
            continue
        session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=item.observed_at, view_count=item.view_count, like_count=item.like_count, comment_count=item.comment_count, concurrent_viewers=item.concurrent_viewers, is_live=item.is_live, classification=item.classification))
        saved += 1
    session.commit()
    return saved
