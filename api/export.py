"""Role-aware filtered Excel export for StatAxis dashboard reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from api.access import UserRole, require_capability, video_access_policy
from collector.storage import Channel, Observation, Video
from metrics.persistence import IntelligenceSnapshotRecord


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


def filtered_observations(session: Session, filters: ObservationExportFilters) -> list[tuple[Observation, Video, Channel]]:
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


def export_observations_xlsx(session: Session, filters: ObservationExportFilters) -> bytes:
    """Build an Excel workbook containing filtered data and latest intelligence."""
    rows = filtered_observations(session, filters)
    workbook = Workbook()

    data = workbook.active
    data.title = "StatAxis Data"
    data.append([
        "Observed At", "Video ID", "YouTube Video ID", "Title", "Channel", "Language",
        "Region", "Classification", "Live", "Views", "Likes", "Comments",
        "Concurrent Viewers", "Source",
    ])
    video_ids = set()
    for observation, video, channel in rows:
        video_ids.add(video.id)
        data.append([
            observation.observed_at, video.id, video.youtube_video_id, video.title,
            channel.name, channel.language, channel.region, observation.classification,
            observation.is_live, observation.view_count, observation.like_count,
            observation.comment_count, observation.concurrent_viewers, observation.source,
        ])
    _format_sheet(data)

    intelligence = workbook.create_sheet("StatAxis Intelligence")
    intelligence.append([
        "Video ID", "YouTube Video ID", "Title", "STX Index", "Confidence",
        "Available Signals", "Generated At", "StatAxis View", "Signal Contributions",
    ])
    if video_ids:
        stmt = (
            select(IntelligenceSnapshotRecord, Video)
            .join(Video, Video.id == IntelligenceSnapshotRecord.video_id)
            .where(IntelligenceSnapshotRecord.video_id.in_(video_ids))
            .order_by(IntelligenceSnapshotRecord.generated_at.desc())
        )
        latest: dict[int, IntelligenceSnapshotRecord] = {}
        for record, video in session.execute(stmt):
            latest.setdefault(video.id, record)
        for _, video, _ in rows:
            record = latest.get(video.id)
            if record is None:
                continue
            view = json.loads(record.view_json)
            contributions = json.loads(record.contributions_json)
            intelligence.append([
                video.id, video.youtube_video_id, video.title, record.score,
                record.confidence, record.available_signals, record.generated_at,
                view.get("view", view.get("summary", "")), json.dumps(contributions, sort_keys=True),
            ])
    _format_sheet(intelligence)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_for_role(session: Session, role: UserRole | str, filters: ObservationExportFilters) -> bytes:
    """Authorize and export the dashboard report for an authenticated role."""
    policy = video_access_policy(role)
    require_capability(policy, "can_download_report")
    return export_observations_xlsx(session, filters)


def export_response(session: Session, role: UserRole | str, filters: ObservationExportFilters) -> tuple[int, dict[str, str], bytes]:
    """Return an HTTP-ready report response with server-side role enforcement."""
    try:
        payload = export_for_role(session, role, filters)
    except PermissionError as exc:
        return 403, {"Content-Type": "application/json"}, json.dumps({"error": str(exc)}).encode()
    except ValueError as exc:
        return 400, {"Content-Type": "application/json"}, json.dumps({"error": str(exc)}).encode()

    return 200, {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": "attachment; filename=stataxis-report.xlsx",
    }, payload


def _format_sheet(sheet) -> None:
    """Apply simple spreadsheet usability defaults."""
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        width = min(max(len(str(cell.value or "")) for cell in column) + 2, 48)
        sheet.column_dimensions[column[0].column_letter].width = width
