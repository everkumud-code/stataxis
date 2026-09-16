"""Persistence layer for timestamped STAXIS observations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
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


class Video(Base):
    __tablename__ = "stx_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("stx_channels.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


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
    """Customer identity and server-resolved SX entitlement."""

    __tablename__ = "stx_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    plan: Mapped[str] = mapped_column(String(32), default="sx_free", index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def create_database(url: str):
    """Create an SQLAlchemy engine and all STAXIS tables if absent."""
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    return engine


def save_observations(
    session: Session,
    channel_name: str,
    channel_youtube_id: str,
    network: str,
    language: str,
    observations: list[VideoObservation],
    region: str = "unknown",
) -> int:
    """Persist channel/video metadata and append only new timestamped observations."""
    channel = session.query(Channel).filter_by(youtube_channel_id=channel_youtube_id).one_or_none()
    if channel is None:
        channel = Channel(youtube_channel_id=channel_youtube_id, name=channel_name, network=network, language=language, region=region)
        session.add(channel)
        session.flush()
    else:
        channel.language = language
        channel.region = region

    saved = 0
    seen: set[tuple[str, datetime]] = set()
    for item in observations:
        key = (item.video_id, item.observed_at)
        if key in seen:
            continue
        seen.add(key)
        video = session.query(Video).filter_by(youtube_video_id=item.video_id).one_or_none()
        if video is None:
            video = Video(youtube_video_id=item.video_id, channel_id=channel.id, title=item.title, published_at=item.published_at)
            session.add(video)
            session.flush()
        else:
            video.title = item.title
            video.published_at = item.published_at
        existing = session.query(Observation.id).filter_by(video_id=video.id, observed_at=item.observed_at).first()
        if existing is not None:
            continue
        session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=item.observed_at, view_count=item.view_count, like_count=item.like_count, comment_count=item.comment_count, concurrent_viewers=item.concurrent_viewers, is_live=item.is_live, classification=item.classification))
        saved += 1
    session.commit()
    return saved
