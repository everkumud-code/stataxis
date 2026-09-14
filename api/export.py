"""Admin-only filtered Excel export of StatAxis observation data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video


@dataclass(frozen=True)
class ObservationExportFilters:
    """Optional dashboard filters for an observation export."""

    start_at: datetime | None = None
    end_at: datetime | None = None
    language: str | None = None
    region: str | None = None
    channel_id: int | None = None
    video_id: int | None = None
    is_live: bool | None = None
    classification: str | None = None


def filtered_observations(
    session: Session,
    filters: ObservationExportFilters,
) -> list[tuple[Observation, Video, Channel]]:
    """Return observations matching the dashboard export filters."""
    stmt: Select[tuple[Observation, Video, Channel]] = (
        select(Observation, Video, Channel)
        .join(Video, Video.id == Observation.video_id)
        .join(Channel, Channel.id == Observation.channel_id)
        .order_by(Observation.observed_at.asc(), Observation.id.asc())
    )
    if filters.start_at is not None:
        stmt = stmt.where(Observation.observed_at >= filters.start_at)
    if filters.end_at is not None:
        stmt = stmt.where(Observation.observed_at <= filters.end_at)
    if filters.language is not None:
        stmt = stmt.where(Channel.language == filters.language)
    if filters.region is not None:
        stmt = stmt.where(Channel.region == filters.region)
    if filters.channel_id is not None:
        stmt = stmt.where(Observation.channel_id == filters.channel_id)
    if filters.video_id is not None:
        stmt = stmt.where(Observation.video_id == filters.video_id)
    if filters.is_live is not None:
        stmt = stmt.where(Observation.is_live == filters.is_live)
    if filters.classification is not None:
        stmt = stmt.where(Observation.classification == filters.classification)
    return list(session.execute(stmt).all())


def export_observations_xlsx(
    session: Session,
    filters: ObservationExportFilters,
) -> bytes:
    """Build an Excel workbook containing exactly the filtered observations."""
    rows = filtered_observations(session, filters)
    workbook = Workbook()
    data = workbook.active
    data.title = "StatAxis Data"
    headers = [
        "Observed At", "Video ID", "YouTube Video ID", "Title", "Channel",
        "Language", "Region", "Classification", "Live", "Views", "Likes",
        "Comments", "Concurrent Viewers", "Source",
    ]
    data.append(headers)
    for observation, video, channel in rows:
        data.append([
            observation.observed_at, video.id, video.youtube_video_id, video.title,
            channel.name, channel.language, channel.region, observation.classification,
            observation.is_live, observation.view_count, observation.like_count,
            observation.comment_count, observation.concurrent_viewers, observation.source,
        ])
    data.freeze_panes = "A2"
    data.auto_filter.ref = data.dimensions
    for column in data.columns:
        width = min(max(len(str(cell.value or "")) for cell in column) + 2, 48)
        data.column_dimensions[column[0].column_letter].width = width

    intelligence = workbook.create_sheet("StatAxis Intelligence")
    intelligence.append([
        "Video ID", "STX Index", "Confidence", "Available Signals",
        "Generated At", "StatAxis View",
    ])
    for _, video, _ in rows:
        intelligence.append([video.id, None, None, None, None, ""])
    intelligence.freeze_panes = "A2"
    intelligence.auto_filter.ref = intelligence.dimensions

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
