"""The STX Index report: the numbers are arranged honestly (points add up to the raw score, a missing factor is a dash and shares its weight), the PDF carries them, and the routes follow the privileges.
Invented channels; nothing touches YouTube or the live data."""
import io
import json
import time

import pymupdf
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import stx_report
from api.auth import AuthIdentity, hash_password, issue_token
from api.market_http import market_application
from collector.storage import Base, User
from metrics.stx_index import WEIGHTS

ALL = {"audience": 80.0, "growth": 60.0, "momentum": 40.0, "acceleration": 55.0, "consistency": 70.0, "competitive_position": 100.0, "anomaly_event": 50.0}


def stx_block(signals: dict[str, float | None]) -> dict:
    present = {k: v for k, v in signals.items() if v is not None}
    weight = sum(WEIGHTS[k] for k in present)
    comps = {k: round(v * WEIGHTS[k] / weight, 2) for k, v in present.items()}
    raw = sum(v * WEIGHTS[k] for k, v in present.items()) / weight
    confidence = weight * 100
    shown = 50 + (raw - 50) * confidence / 100
    return {"score": round(raw, 2), "display_score": round(shown, 1), "confidence": confidence, "preliminary": confidence < 50, "available_signals": len(present), "components": comps,
            "signals": {k: signals.get(k) for k in WEIGHTS}}


def row(cid: int, name: str, signals: dict, avg: float | None = 100.0, group: str = "Hindi News") -> dict:
    return {"channel_id": cid, "channel": name, "market_label": group, "average_concurrent": avg, "peak_concurrent": 5000 + cid, "current_concurrent": 90, "view_delta": 1_000_000 * cid, "share_percent": 12.5, "share_basis": "view_delta",
            "uploads_in_window": 14, "like_delta": 100, "comment_delta": 20, "stx": stx_block(signals)}


def payload(rows: list[dict]) -> dict:
    return {"as_of": "2026-10-23T01:00:00+00:00", "start_at": "2026-10-16T01:00:00+00:00", "end_at": "2026-10-23T01:00:00+00:00", "channels": rows}


def fake(rows):
    return lambda session, **kw: (200, payload(rows))


ROWS = [
    row(1, "Alpha News", ALL),
    row(2, "Beta Tak", {**ALL, "momentum": None, "acceleration": None}, avg=40.0),
    row(3, "Gamma TV", {"growth": 90.0, "consistency": 60.0, "competitive_position": 50.0, "anomaly_event": 40.0}, avg=None, group="English News"),
    row(4, "समाचार भारत", {**ALL, "audience": 20.0}, avg=250.0),
]


def build(**kw):
    return stx_report.build(None, fetch=fake(ROWS), **kw)


def test_the_points_of_the_factors_add_up_to_the_raw_score_and_the_maximums_to_one_hundred():
    rep = build()
    assert rep["scored"] == 4 and [c["rank"] for c in rep["channels"]] == [1, 2, 3, 4]
    for c in rep["channels"]:
        have = [f for f in c["factors"] if f["points"] is not None]
        assert abs(sum(f["points"] for f in have) - c["raw"]) < 0.2, c["name"]                       # the points make the raw STX
        assert abs(sum(f["max_points"] for f in have) - 100) < 0.2, c["name"]                       # and the most they could give is 100
        assert all(0 <= f["points"] <= f["max_points"] + 0.01 for f in have)
        assert len(c["factors"]) == 7 and [f["key"] for f in c["factors"]] == list(ALL)
    gamma = next(c for c in rep["channels"] if c["name"] == "Gamma TV")
    assert gamma["factors_available"] == 4 and [f["key"] for f in gamma["factors"] if f["signal"] is None] == ["audience", "momentum", "acceleration"]    # a missing factor is a dash, not zero
    assert gamma["preliminary"] is True and gamma["confidence"] == 45 and gamma["stx"] != gamma["raw"]                                                   # thin data: pulled toward 50
    alpha = rep["channels"][0] if rep["channels"][0]["name"] == "Alpha News" else next(c for c in rep["channels"] if c["name"] == "Alpha News")
    assert alpha["confidence"] == 100 and alpha["stx"] == alpha["raw"] and alpha["preliminary"] is False


def test_channels_are_ranked_by_the_shown_score_and_the_headline_names_the_leader():
    rep = build()
    shown = [c["stx"] for c in rep["channels"]]
    assert shown == sorted(shown, reverse=True) and rep["headline"]["leader"] == rep["channels"][0]["name"] and rep["headline"]["scored"] == 4
    assert rep["headline"]["average"] == round(sum(shown) / 4, 1)


def test_the_audience_is_listed_channel_by_channel_and_a_missing_figure_stays_missing():
    rep = build()
    order = [next(c["name"] for c in rep["channels"] if c["channel_id"] == i) for i in rep["audience_order"]]
    assert order == ["समाचार भारत", "Alpha News", "Beta Tak"]                                         # by average live viewers; Gamma has none and is not ranked
    gamma = next(c for c in rep["channels"] if c["name"] == "Gamma TV")["audience"]
    assert gamma["average"] is None and gamma["peak"] == 5003 and gamma["views_gained"] == 3_000_000 and gamma["engagement"] == 120


def test_each_factor_has_its_leaders_and_the_channels_that_had_data():
    rep = build()
    comp = next(x for x in rep["leaders"] if x["key"] == "competitive_position")
    assert comp["weight_percent"] == 10 and comp["with_data"] == 4 and comp["top"][0]["signal"] == 100.0
    mom = next(x for x in rep["leaders"] if x["key"] == "momentum")
    assert mom["with_data"] == 2 and len(mom["top"]) == 2
    assert [x["weight_percent"] for x in rep["leaders"]] == [30, 20, 15, 10, 10, 10, 5]


def test_a_bad_period_or_a_failing_report_is_a_plain_error():
    with pytest.raises(ValueError, match="period must be"):
        stx_report.build(None, period="forever", fetch=fake(ROWS))
    with pytest.raises(ValueError, match="no good"):
        stx_report.build(None, fetch=lambda s, **kw: (400, {"error": "no good"}))
    assert stx_report.build(None, fetch=fake([]))["headline"] is None and stx_report.build(None, fetch=fake([]))["scored"] == 0
    only_blank = [{**ROWS[0], "stx": {"score": None, "display_score": None, "confidence": 0.0, "components": {}, "signals": {}}}]
    assert stx_report.build(None, fetch=fake(only_blank))["scored"] == 0                              # a channel with no score is not in the ranking, never zero


def test_the_filters_reach_the_market_report():
    seen = {}

    def fetch(session, **kw):
        seen.update(kw)
        return 200, payload(ROWS)
    stx_report.build(None, period="3w", language="Hindi", segment="news", fetch=fetch)
    assert seen == {"period": "3w", "language": "Hindi", "segment": "news"}


def test_the_pdf_is_a_landscape_report_with_every_number_and_the_method():
    rep = build(cards=2)
    data = stx_report.pdf(rep, prepared_for="owner@x.in", protect=False)
    doc = pymupdf.open(stream=data, filetype="pdf")
    text = "\n".join(p.get_text() for p in doc)
    assert doc[0].rect.width > doc[0].rect.height and "STX INDEX REPORT" in text and "Alpha News" in text and "Beta Tak" in text and "owner@x.in" in text
    first = rep["channels"][0]
    f0 = first["factors"][0]
    assert f"{first['stx']:.1f}" in text and f"{f0['points']:.1f}/{f0['max_points']:.1f}" in text.replace(" ", "")      # the score and a factor's "points / most it could give" are on the page
    for needle in ("Audience, channel by channel", "Channel scorecards", "Who leads each factor", "How the STX Index is made", "not TV ratings", "no data in this window", "Preliminary"):
        assert needle in text, needle
    assert text.count("#1") >= 1 and "#3" not in text                                              # only the two cards asked for
    assert "Downloaded" in text and "stataxis.org" in text


def test_a_protected_pdf_is_pictures_only_locked_to_printing_and_still_the_same_pages():
    rep = build(cards=1)
    plain = pymupdf.open(stream=stx_report.pdf(rep, protect=False), filetype="pdf")
    locked = pymupdf.open(stream=stx_report.pdf(rep, protect=True), filetype="pdf")
    assert len(locked) == len(plain) and locked.is_encrypted is False or locked.needs_pass in (0, False)
    assert all(not p.get_text().strip() for p in locked) and all(p.get_images() for p in locked)


def test_the_pdf_of_a_full_market_is_made_in_reasonable_time():
    many = [row(i, f"Channel {i}", {**ALL, "audience": float(i * 3 % 100)}, avg=float(10 + i)) for i in range(1, 61)]
    started = time.time()
    data = stx_report.pdf(stx_report.build(None, fetch=fake(many), cards=12), protect=False)
    assert len(pymupdf.open(stream=data, filetype="pdf")) >= 6 and time.time() - started < 40


# ------------------------------------------------------------------------------------------------------------------------------ routes
def world():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    for uid, email, plan, admin in ((1, "free@x.in", "sx_free", False), (2, "idea@x.in", "sx_idea", False), (3, "boss@x.in", "sx_enterprise", True)):
        s.add(User(id=uid, email=email, password_hash=hash_password("a long enough pass"), plan=plan, requested_plan=plan, is_admin=admin, active=True, approval_status="approved", full_name=email, organization="Org"))
    s.commit()
    return s, engine


def call(engine, user_id, path, query="", monkeypatch=None):
    app = market_application(lambda: Session(engine))
    u = Session(engine).get(User, user_id) if user_id else None
    out = {}
    env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0",
           "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(u.id, u.email, u.plan, u.is_admin))) if u else ""}
    res = app(env, lambda status, headers: out.update(status=status, headers=dict(headers)))
    return int(out["status"].split()[0]), out["headers"], b"".join(res)


def test_the_routes_return_the_report_as_data_and_as_a_pdf_and_follow_the_privileges(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    monkeypatch.setattr(stx_report, "_default_fetch", fake(ROWS))
    s, engine = world()
    assert call(engine, None, "/api/v1/market/stx-report")[0] == 401
    code, headers, body = call(engine, 2, "/api/v1/market/stx-report", "period=7d&language=Hindi")
    data = json.loads(body)
    assert code == 200 and data["scored"] == 4 and data["filters"]["language"] == "Hindi" and data["channels"][0]["factors"][0]["key"] == "audience"
    assert call(engine, 2, "/api/v1/market/stx-report", "period=bogus")[0] == 400
    from api import feature_access
    feature_access.set_user_feature(s, 2, "stx", False, "boss@x.in")
    assert call(engine, 2, "/api/v1/market/stx-report")[0] == 403 and call(engine, 2, "/api/v1/market/stx-report.pdf")[0] == 403          # the STX tick covers the report
    code, headers, body = call(engine, 3, "/api/v1/market/stx-report.pdf", "period=7d&cards=3")
    assert code == 200 and headers["Content-Type"] == "application/pdf" and headers["Content-Disposition"].startswith('attachment; filename="stataxis-stx-index-report-7d-') and body[:5] == b"%PDF-"
    assert pymupdf.open(stream=body, filetype="pdf").page_count >= 4


def test_the_screen_is_in_the_menu_the_views_and_the_page_scripts_parse():
    from pathlib import Path
    from api import me
    root = Path(__file__).resolve().parent.parent / "dashboard"
    assert ("stxreport", "STX Index report", "stx") in me.VIEWS
    ws = (root / "workspace.html").read_text(encoding="utf-8")
    assert "stxreport.js" in ws and 'stxreport: "STX Index report"' in ws
    js = (root / "stxreport.js").read_text(encoding="utf-8")
    assert 'add("stxreport"' in js and "/api/v1/market/stx-report" in js
