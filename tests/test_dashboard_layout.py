"""Each person's dashboard: six sections, the second always the STX Index, kept with the login."""
import io
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import dashboard_layout as dl
from api.auth import AuthIdentity, issue_token
from api.me_http import me_application
from collector.storage import Base, User


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    ann, bob = (User(email=e, password_hash="x", plan="sx_free", active=True, approval_status="approved") for e in ("ann@x.com", "bob@x.com"))
    s.add_all([ann, bob])
    s.commit()
    return s, engine, ann, bob


def layout(widgets, language="", segment="news"):
    return {"slots": [{"widget": w, "language": language, "segment": segment} for w in widgets]}


def test_the_default_has_six_sections_with_the_stx_index_second():
    s, _, ann, _ = make()
    out = dl.get_layout(s, ann)
    assert len(out["slots"]) == 6 and out["customised"] is False and out["slots"][1]["widget"] == "stx" and out["fixed"] == {"slot": 1, "widget": "stx"}
    assert all(sl["segment"] == "news" for sl in out["slots"])                                                 # starts on Main stream: business news is never counted with Hindi news
    assert {w["id"] for w in out["widgets"]} >= {"stx", "views", "audience", "movers", "live", "spikes", "forecasts", "weekly", "alerts", "numbers"} and "Hindi (Regional)" in out["languages"]
    assert [x["id"] for x in out["segments"]][:5] == ["news", "business", "entertainment", "commentator", "journalist"]


def test_a_person_picks_their_own_data_and_the_second_section_stays_the_stx_index():
    s, _, ann, bob = make()
    out = dl.save_layout(s, ann, layout(["weekly", "forecasts", "live", "alerts", "numbers", "spikes"], language="Tamil", segment="business"))
    assert out["customised"] is True and out["slots"][0]["widget"] == "weekly" and out["slots"][1]["widget"] == "stx"          # asked for forecasts second: it is the STX Index anyway
    assert out["slots"][1]["language"] == "Tamil" and out["slots"][1]["segment"] == "business"                                  # but it may be narrowed to a language and a category
    assert dl.get_layout(s, bob)["customised"] is False and dl.get_layout(s, ann)["slots"][2]["widget"] == "live"             # kept per login
    for bad in ({"slots": layout(["views"] * 5)["slots"]}, {"slots": "x"}, layout(["views", "stx", "nonsense", "views", "views", "views"]), layout(["views"] * 6, language="Klingon"), layout(["views"] * 6, segment="sports")):
        with pytest.raises(ValueError):
            dl.save_layout(s, ann, bad)
    assert dl.save_layout(s, ann, {"reset": True})["customised"] is False


def test_the_dashboard_is_read_and_saved_through_the_account_api():
    s, engine, ann, _ = make()
    app = me_application(lambda: Session(engine))
    token = issue_token(AuthIdentity(ann.id, ann.email, ann.plan, False))

    def call(method, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        out = {}
        env = {"REQUEST_METHOD": method, "PATH_INFO": "/api/v1/me/dashboard", "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "HTTP_AUTHORIZATION": "Bearer " + token}
        res = app(env, lambda status, headers, *a: out.update(status=int(status.split()[0])))
        return out["status"], json.loads(b"".join(res))

    assert call("GET")[0] == 200 and call("GET")[1]["slots"][1]["widget"] == "stx"
    status, body = call("POST", layout(["audience", "stx", "views", "movers", "live", "numbers"], language="Hindi"))
    assert status == 200 and body["slots"][0]["widget"] == "audience" and call("GET")[1]["slots"][0]["language"] == "Hindi"
    assert call("POST", {"slots": []})[0] == 400
