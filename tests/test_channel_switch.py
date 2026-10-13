"""The On/Off switch of a channel: an off channel is not collected and not shown, keeps its history, and can be found and switched on again."""
import io
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.admin import list_all_channels, set_channel_active
from api.admin_http import admin_application
from api.auth import AuthIdentity, issue_token
from api.market_common import pick_channels
from collector import service
from collector.storage import Base, Channel, ChannelLanguageOverride
from collector.youtube.collector import ChannelTarget

ADMIN = AuthIdentity(1, "boss@x.com", "sx_enterprise", True)
NOBODY = AuthIdentity(2, "n@x.com", "sx_free", False)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


@pytest.fixture
def world():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    for key, name, lang, region in (("a", "Hindi India", "Hindi", "India"), ("b", "Tamil India", "Tamil", "India"), ("c", "English UK", "English", "UK")):
        s.add(Channel(youtube_channel_id="UC" + key * 22, name=name, network="n", language=lang, region=region, segment="news", active=True))
    s.commit()
    return s, engine


def test_switching_a_channel_off_and_on(world):
    s, _ = world
    a = s.query(Channel).filter_by(name="Hindi India").one()
    assert set_channel_active(s, ADMIN, a.id, False) == {"channel_id": a.id, "name": "Hindi India", "active": False}
    assert "Hindi India" not in [c.name for c in pick_channels(s, segment=None, language=None)[0]]     # off: not shown anywhere that lists channels
    assert [c["name"] for c in list_all_channels(s, ADMIN) if not c["active"]] == ["Hindi India"]       # but still listed for the admin, so it can be found again
    assert set_channel_active(s, ADMIN, a.id, True)["active"] is True and "Hindi India" in [c.name for c in pick_channels(s, segment=None, language=None)[0]]
    with pytest.raises(PermissionError):
        set_channel_active(s, NOBODY, a.id, False)
    with pytest.raises(LookupError):
        set_channel_active(s, ADMIN, 9999, False)


def test_the_full_list_shows_the_language_an_administrator_set(world):
    s, _ = world
    b = s.query(Channel).filter_by(name="Tamil India").one()
    s.add(ChannelLanguageOverride(channel_id=b.id, language="Hindi"))
    s.commit()
    assert {c["name"]: c["language"] for c in list_all_channels(s, ADMIN)}["Tamil India"] == "Hindi"


def test_the_worker_does_not_collect_a_channel_that_is_off_even_if_the_config_file_lists_it(world):
    s, _ = world
    configured = [ChannelTarget(channel_id="UC" + "a" * 22, name="Hindi India", language="Hindi", network="n", segment="news"), ChannelTarget(channel_id="UC" + "z" * 22, name="Only in the file", language="Hindi", network="n", segment="news")]
    assert [t.name for t in service._with_database_channels(s, configured)] == ["Hindi India", "Only in the file", "Tamil India", "English UK"]
    set_channel_active(s, ADMIN, s.query(Channel).filter_by(name="Hindi India").one().id, False)
    set_channel_active(s, ADMIN, s.query(Channel).filter_by(name="Tamil India").one().id, False)
    assert [t.name for t in service._with_database_channels(s, configured)] == ["Only in the file", "English UK"]


def test_the_admin_routes_for_the_switch(world):
    s, engine = world
    app = admin_application(lambda: Session(engine))

    def call(path, who, body):
        raw = json.dumps(body).encode()
        out = {}
        environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path, "QUERY_STRING": "", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)), "HTTP_AUTHORIZATION": "Bearer " + issue_token(who)}
        res = app(environ, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(b"".join(res))

    status, body = call("/api/v1/admin/channels/all", ADMIN, {})
    assert status == 200 and len(body["channels"]) == 3 and all(c["active"] for c in body["channels"])
    cid = body["channels"][0]["id"]
    assert call("/api/v1/admin/channels/active", ADMIN, {"channel_id": cid, "active": False})[1]["active"] is False
    assert call("/api/v1/admin/channels/active", ADMIN, {"channel_id": cid, "active": "no"})[0] == 400
    assert call("/api/v1/admin/channels/active", NOBODY, {"channel_id": cid, "active": True})[0] in (401, 403)
    assert call("/api/v1/admin/channels/all", NOBODY, {})[0] in (401, 403)
    assert sum(1 for c in call("/api/v1/admin/channels/all", ADMIN, {})[1]["channels"] if not c["active"]) == 1
