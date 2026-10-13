"""Audience geography and age, only where it is really known.

YouTube shows nobody else's audience: the public API has no age, gender or location of viewers, and STAXIS does not guess them. A profile is stored when the channel itself
(for example from its YouTube Studio analytics or its media kit) or a named study supplied it, together with the source and the date, and every screen shows that.
The media planner can then match a target (age bands, states, gender) against the profiles that exist; channels without a profile are listed as "no audience data", never filled in.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from collector.storage import AudienceProfile, Channel

AGE_BANDS = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
GENDERS = ["male", "female", "other"]
SOURCES = {
    "youtube_analytics": "YouTube Studio analytics shown by the channel",
    "channel_media_kit": "Channel's media kit",
    "third_party_study": "Named third-party study",
    "admin_entered": "Entered by the STAXIS team (note says from where)",
}
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
MAX_COUNTRIES = 40


def _clean_shares(raw: Any, allowed: list[str] | None, name: str, *, total_min: float | None = None) -> dict[str, float]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be a list of name and percent")
    out: dict[str, float] = {}
    for key, value in raw.items():
        label = str(key).strip()
        if allowed is not None and label not in allowed:
            raise ValueError(f"{name}: '{label}' is not one of: {', '.join(allowed)}")
        if allowed is None and (not label or len(label) > 60):
            raise ValueError(f"{name}: a name is missing or too long")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}: the percent for '{label}' is not a number") from exc
        if not 0 <= number <= 100:
            raise ValueError(f"{name}: the percent for '{label}' must be between 0 and 100")
        out[label] = round(number, 2)
    total = sum(out.values())
    if total > 100.5:
        raise ValueError(f"{name}: the percents add up to {total:.1f}, which is more than 100")
    if total_min is not None and out and total < total_min:
        raise ValueError(f"{name}: the percents add up to {total:.1f}; enter all the bands so they come to about 100")
    return out


def set_profile(session: Session, *, channel_id: int, source: str, source_note: str, as_of: str, age: Any, gender: Any, states: Any, countries: Any, by: str) -> dict[str, Any]:
    if session.get(Channel, channel_id) is None:
        raise LookupError("channel not found")
    if source not in SOURCES:
        raise ValueError("source must be one of: " + ", ".join(SOURCES))
    if not (source_note or "").strip():
        raise ValueError("say where these figures come from (document, screen or study, and who gave it)")
    try:
        when = date.fromisoformat(str(as_of))
    except ValueError as exc:
        raise ValueError("as_of must look like 2026-10-09") from exc
    if when > date.today():
        raise ValueError("as_of cannot be in the future")
    data = {"age": _clean_shares(age, AGE_BANDS, "age", total_min=97), "gender": _clean_shares(gender, GENDERS, "gender", total_min=97),
            "states": _clean_shares(states, STATES, "states"), "countries": _clean_shares(countries, None, "countries")}
    if len(data["countries"]) > MAX_COUNTRIES:
        raise ValueError(f"at most {MAX_COUNTRIES} countries")
    if not any(data.values()):
        raise ValueError("enter at least one of age, gender, states or countries")
    row = session.query(AudienceProfile).filter_by(channel_id=channel_id).one_or_none()
    if row is None:
        row = AudienceProfile(channel_id=channel_id, source=source, as_of=when.isoformat())
        session.add(row)
    row.source, row.source_note, row.as_of, row.updated_by = source, source_note.strip()[:2000], when.isoformat(), by
    row.age_json, row.gender_json, row.states_json, row.countries_json = (json.dumps(data[k]) for k in ("age", "gender", "states", "countries"))
    session.commit()
    return profile_payload(session, row)


def remove_profile(session: Session, channel_id: int) -> dict[str, Any]:
    row = session.query(AudienceProfile).filter_by(channel_id=channel_id).one_or_none()
    if row is None:
        raise LookupError("this channel has no audience profile")
    session.delete(row)
    session.commit()
    return {"channel_id": channel_id, "removed": True}


def profile_payload(session: Session, row: AudienceProfile) -> dict[str, Any]:
    channel = session.get(Channel, row.channel_id)
    return {"channel_id": row.channel_id, "name": channel.name if channel else "", "source": row.source, "source_label": SOURCES.get(row.source, row.source), "source_note": row.source_note,
            "as_of": row.as_of, "age": json.loads(row.age_json or "{}"), "gender": json.loads(row.gender_json or "{}"), "states": json.loads(row.states_json or "{}"),
            "countries": json.loads(row.countries_json or "{}"), "updated_by": row.updated_by}


def profiles(session: Session) -> dict[int, dict[str, Any]]:
    return {r.channel_id: profile_payload(session, r) for r in session.query(AudienceProfile).all()}


def overview(session: Session) -> dict[str, Any]:
    """Every active channel with its profile or the plain statement that none is known."""
    known = profiles(session)
    rows = []
    for c in session.query(Channel).filter(Channel.active.is_(True)).order_by(Channel.name).all():
        p = known.get(c.id)
        rows.append({"channel_id": c.id, "name": c.name, "segment": c.segment or "news", "language": c.language, "profile": p})
    return {"channels": rows, "with_profile": sum(1 for r in rows if r["profile"]), "total": len(rows), "age_bands": AGE_BANDS, "states": STATES, "genders": GENDERS, "sources": SOURCES,
            "note": "YouTube does not publish another channel's audience. These profiles exist only where the channel or a named study supplied them; everything else is shown as not known."}


def parse_target(ages: Any = None, states: Any = None, gender: Any = None) -> dict[str, Any]:
    """The place / age group / gender a reader asked for, checked. Lists may come as comma-separated text."""
    def lst(v: Any) -> list[str]:
        if not v:
            return []
        return [x.strip() for x in (v.split(",") if isinstance(v, str) else v) if str(x).strip()]
    t_ages, t_states, t_gender = lst(ages), lst(states), str(gender or "").strip().lower()
    if any(a not in AGE_BANDS for a in t_ages):
        raise ValueError("age group must be among: " + ", ".join(AGE_BANDS))
    if any(s not in STATES for s in t_states):
        raise ValueError("place must be Indian states or union territories")
    if t_gender and t_gender not in GENDERS:
        raise ValueError("gender must be male, female or other")
    return {"ages": t_ages, "states": t_states, "gender": t_gender, "active": bool(t_ages or t_states or t_gender)}


def apply_target(rows: list[dict[str, Any]], value_key: str, profiles: dict[int, dict[str, Any]] | None, target: dict[str, Any] | None, *, known_only: bool = False) -> list[dict[str, Any]]:
    """Adds `audience_match` (share of the channel's audience inside the target) and `matched_<value_key>` to each row, re-ranks by the matched figure and, if asked,
    drops channels whose audience nobody has supplied. A channel with no profile is never given a made-up share."""
    if not target or not target.get("active"):
        return rows
    for r in rows:
        fit = match((profiles or {}).get(r["channel_id"]), ages=target["ages"], states=target["states"], gender=target["gender"])
        r["audience_match"] = fit
        r[f"matched_{value_key}"] = round(r[value_key] * fit["share"], 1) if fit and r.get(value_key) is not None else None
    if known_only:
        rows = [r for r in rows if r["audience_match"]]
    rows.sort(key=lambda r: (r[f"matched_{value_key}"] is not None, r[f"matched_{value_key}"] or 0, r.get(value_key) or 0), reverse=True)
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank
    return rows


def match(profile: dict[str, Any] | None, *, ages: list[str], states: list[str], gender: str) -> dict[str, Any] | None:
    """Share of a channel's audience inside the target. Age, state and gender are combined as if they were independent of each other (the profile only gives each one separately);
    a part of the target the profile does not cover is left out of the calculation and named in `missing`."""
    if not profile:
        return None
    share, used, missing = 1.0, [], []
    if ages:
        if profile["age"]:
            share *= sum(profile["age"].get(a, 0) for a in ages) / 100
            used.append("age")
        else:
            missing.append("age")
    if states:
        if profile["states"]:
            share *= sum(profile["states"].get(s, 0) for s in states) / 100
            used.append("states")
        else:
            missing.append("states")
    if gender in GENDERS:
        if profile["gender"]:
            share *= profile["gender"].get(gender, 0) / 100
            used.append("gender")
        else:
            missing.append("gender")
    if not used:
        return None
    return {"share": round(share, 4), "used": used, "missing": missing, "as_of": profile["as_of"], "source": profile["source"]}
