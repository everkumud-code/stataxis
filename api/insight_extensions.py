"""Deterministic, evidence-first insight extensions for StatAxis.

This module deliberately avoids fabricated causality. Sentiment is lexical and
narrative detection is title-term based until a richer NLP provider is enabled.
Every result exposes coverage/confidence so downstream UI can distinguish signal
from interpretation.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import parse_qs

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from api.ttl_cache import ttl_cache
from collector.storage import Channel, Observation, Video
from metrics.eligibility import analysis_observation_clause

POSITIVE = {
    "growth", "grow", "gain", "gains", "rise", "rises", "rising", "surge", "surges",
    "success", "win", "wins", "victory", "profit", "profits", "record", "strong", "positive",
    "boost", "breakthrough", "recovery", "recover", "improve", "improved", "good", "great",
    "बढ़त", "बढ़ा", "बढ़ी", "जीत", "सफलता", "मुनाफा", "रिकॉर्ड", "सकारात्मक", "सुधार",
}
NEGATIVE = {
    "fall", "falls", "falling", "drop", "drops", "decline", "declines", "crisis", "loss", "losses",
    "fail", "fails", "failure", "negative", "scandal", "controversy", "warning", "attack", "dead",
    "death", "war", "threat", "risk", "down", "बढ़ा संकट", "गिरावट", "गिरा", "नुकसान", "हार",
    "संकट", "विवाद", "चेतावनी", "हमला", "मौत", "युद्ध", "खतरा",
}
STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "will", "news", "live",
    "latest", "breaking", "today", "new", "a", "an", "of", "to", "in", "on", "at", "by", "is",
    "की", "के", "का", "और", "में", "से", "पर", "को", "है", "हैं", "एक", "यह", "वो", "आज", "न्यूज़",
}
TOKEN_RE = re.compile(r"[\w\u0900-\u097F]{3,}", re.UNICODE)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sentiment(text: str) -> dict[str, Any]:
    tokens = [t.lower() for t in TOKEN_RE.findall(text or "")]
    pos = sum(t in POSITIVE for t in tokens)
    neg = sum(t in NEGATIVE for t in tokens)
    scored = pos + neg
    score = 0.0 if not scored else (pos - neg) / scored
    label = "positive" if score > 0.15 else "negative" if score < -0.15 else "mixed/neutral"
    coverage = min(1.0, scored / max(len(tokens), 1))
    return {"label": label, "score": round(score, 3), "positive_terms": pos, "negative_terms": neg, "lexical_coverage": round(coverage, 3)}


def _terms(titles: list[str], limit: int = 8) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for title in titles:
        for token in TOKEN_RE.findall(title or ""):
            token = token.lower()
            if token not in STOPWORDS and not token.isdigit():
                counter[token] += 1
    return [{"term": term, "mentions": count} for term, count in counter.most_common(limit)]


def _newest_per_video(session: Session, channel_ids: list[int], start: datetime, end: datetime) -> tuple[dict[tuple[int, int], int | None], dict[int, int]]:
    """For each video seen in the window: its newest view count and how many observations it has in the window. Counted in the database, not by loading every row."""
    if not channel_ids:
        return {}, {}
    window = (Observation.channel_id.in_(channel_ids), Observation.observed_at >= start, Observation.observed_at <= end, analysis_observation_clause())
    agg = select(Observation.channel_id.label("c"), Observation.video_id.label("v"), func.count().label("n"), func.max(Observation.observed_at).label("m")).where(*window).group_by(Observation.channel_id, Observation.video_id).subquery()
    stmt = (select(Observation.channel_id, Observation.video_id, Observation.view_count, agg.c.n)
            .join(agg, and_(Observation.channel_id == agg.c.c, Observation.video_id == agg.c.v, Observation.observed_at == agg.c.m))
            .order_by(Observation.channel_id.asc(), Observation.video_id.asc()))
    views: dict[tuple[int, int], int | None] = {}
    rows_per_video: dict[int, int] = {}
    for channel_id, video_id, view_count, n in session.execute(stmt):
        views[(channel_id, video_id)] = view_count
        rows_per_video[video_id] = rows_per_video.get(video_id, 0) + int(n)
    return views, rows_per_video


@ttl_cache()
def build_what_changed(session: Session, *, channel_id: int | None = None, hours: int = 24, as_of: datetime | None = None) -> dict[str, Any]:
    hours = max(1, min(int(hours), 168))
    as_of = _utc(as_of or datetime.now(UTC))
    current_start = as_of - timedelta(hours=hours)
    previous_start = current_start - timedelta(hours=hours)
    channel_ids = [channel_id] if channel_id is not None else list(session.execute(select(Channel.id).where(Channel.active.is_(True))).scalars())
    latest, current_rows_per_video = _newest_per_video(session, channel_ids, current_start, as_of)
    previous_latest, previous_rows_per_video = _newest_per_video(session, channel_ids, previous_start, current_start - timedelta(microseconds=1))
    titles_by_id: dict[int, str | None] = {}
    video_ids = list(current_rows_per_video)
    for i in range(0, len(video_ids), 500):
        for vid, title in session.execute(select(Video.id, Video.title).where(Video.id.in_(video_ids[i:i + 500]))):
            titles_by_id[vid] = title

    changes: list[dict[str, Any]] = []
    for key, view_count in latest.items():
        prior_views = previous_latest.get(key)
        delta = None if key not in previous_latest or view_count is None or prior_views is None else view_count - prior_views
        if delta is not None and delta != 0:
            changes.append({"channel_id": key[0], "video_id": key[1], "title": titles_by_id.get(key[1]), "view_delta": delta})
    changes.sort(key=lambda item: abs(item["view_delta"]), reverse=True)

    current_titles = [title for vid, n in current_rows_per_video.items() if (title := titles_by_id.get(vid)) for _ in range(n)]   # one title per observation, as before
    sentiment = _sentiment(" ".join(current_titles))
    narrative_terms = _terms(current_titles)
    current_views = [item["view_delta"] for item in changes if item["view_delta"] is not None]
    total_delta = sum(current_views) if current_views else None
    previous_count = sum(previous_rows_per_video.values())
    current_count = sum(current_rows_per_video.values())
    coverage = current_count / max(previous_count, current_count, 1)
    confidence = min(1.0, 0.35 + 0.45 * min(1.0, current_count / 100) + 0.20 * coverage)

    if total_delta is None:
        headline = "No measurable view movement in the selected evidence window."
    elif total_delta > 0:
        headline = f"Observed view movement increased by {total_delta:,} across measured videos."
    else:
        headline = f"Observed view movement decreased by {abs(total_delta):,} across measured videos."

    return {
        "as_of": as_of.isoformat(),
        "window": {"hours": hours, "start_at": current_start.isoformat(), "end_at": as_of.isoformat()},
        "headline": headline,
        "changes": changes[:20],
        "sentiment": {**sentiment, "method": "lexical_title_sentiment", "confidence": round(confidence, 3)},
        "narrative": {"top_terms": narrative_terms, "method": "title_term_frequency", "confidence": round(confidence, 3)},
        "evidence": {
            "channel_count": len(channel_ids),
            "current_observation_count": current_count,
            "previous_observation_count": previous_count,
            "coverage": round(coverage, 3),
            "missing_values_are_not_zero_filled": True,
            "causality_inferred": False,
        },
    }


def get_what_changed(session: Session, *, channel_id: int | None = None, hours: int = 24, as_of: datetime | None = None) -> tuple[int, dict[str, Any]]:
    if channel_id is not None and channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        return 400, {"error": "hours must be an integer"}
    if not 1 <= hours <= 168:
        return 400, {"error": "hours must be between 1 and 168"}
    return 200, build_what_changed(session, channel_id=channel_id, hours=hours, as_of=as_of)


def insight_application(session_factory: Callable[[], Session]):
    """WSGI endpoint for evidence-first change, sentiment and narrative intelligence."""
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _response(start_response, 405, {"error": "method not allowed"})
        path = environ.get("PATH_INFO", "")
        if path != "/api/v1/insights/what-changed":
            return _response(start_response, 404, {"error": "not found"})
        query = parse_qs(environ.get("QUERY_STRING", ""))
        raw_channel = query.get("channel_id", [""])[0].strip()
        try:
            channel_id = int(raw_channel) if raw_channel else None
        except ValueError:
            return _response(start_response, 400, {"error": "channel_id must be an integer"})
        session = session_factory()
        try:
            status, payload = get_what_changed(session, channel_id=channel_id, hours=query.get("hours", ["24"])[0])
        finally:
            session.close()
        return _response(start_response, status, payload)
    return application


def _response(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    body = json.dumps(payload, default=str).encode("utf-8")
    phrase = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "OK")
    start_response(f"{status} {phrase}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
