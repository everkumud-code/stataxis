"""Mapping a login to its own channels: the proof, the limits, the administrator's hand, and that nobody can touch anyone else's claim."""
import io
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import my_channels
from api.admin_http import admin_application
from api.auth import AuthIdentity, hash_password, issue_token
from api.my_channels_http import my_channels_application
from collector.storage import Base, Channel, User, UserChannel

UC_A = "UC" + "A" * 22
UC_NEW = "UC" + "N" * 22


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


@pytest.fixture
def world():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    users = {}
    for key, admin in (("a", False), ("b", False), ("boss", True)):
        u = User(email=f"{key}@x.com", password_hash=hash_password("x" * 14), plan="sx_free", is_admin=admin, active=True, approval_status="approved", full_name=key.upper(), organization="Org " + key)
        s.add(u)
        users[key] = u
    chans = {}
    for i, (key, name, handle, active) in enumerate((("one", "Alpha News", "@alphanews", True), ("two", "Beta Voice", "@betavoice", True), ("off", "Gamma Off", "@gammaoff", False))):
        c = Channel(youtube_channel_id="UC" + "BCD"[i] * 22, name=name, network="n", language="Hindi", region="India", segment="news", active=active, handle=handle)
        s.add(c)
        chans[key] = c
    s.commit()
    return s, engine, users, chans


class FakeYT:
    def __init__(self, descriptions=None, known=None):
        self.descriptions, self.known, self.closed = descriptions or {}, known or {}, 0

    def resolve_channel_url(self, url):
        ref = url.rsplit("/", 1)[-1]
        if ref not in self.known:
            raise RuntimeError("Channel not found for handle")
        cid, title = self.known[ref]
        return {"id": cid, "snippet": {"title": title}}

    def get_channel(self, channel_id):
        return {"id": channel_id, "snippet": {"description": self.descriptions.get(channel_id, "")}}

    def close(self):
        self.closed += 1


def test_the_code_belongs_to_one_person_and_one_channel():
    a, b = my_channels.code_for(1, 10), my_channels.code_for(2, 10)
    assert a == my_channels.code_for(1, 10) and a != b and a != my_channels.code_for(1, 11) and a.startswith("stataxis-") and len(a) == len("stataxis-") + 10


@pytest.mark.parametrize("text,url", [("@alphanews", "https://www.youtube.com/@alphanews"), ("alphanews", "https://www.youtube.com/@alphanews"), ("https://youtube.com/@AlphaNews", "https://www.youtube.com/@AlphaNews"),
                                       ("youtube.com/@alphanews/streams", "https://www.youtube.com/@alphanews"), ("https://www.youtube.com/channel/" + UC_A, "https://www.youtube.com/channel/" + UC_A), (UC_A, "https://www.youtube.com/channel/" + UC_A)])
def test_a_handle_or_link_becomes_one_exact_lookup(text, url):
    assert my_channels.normalize_ref(text) == url


@pytest.mark.parametrize("bad", ["", "ab", "https://example.com/@x", "https://www.youtube.com/c/OldName", "https://www.youtube.com/user/old", "two words here", "x" * 300])
def test_name_searches_and_old_style_links_are_refused_because_they_cost_100_units(bad):
    with pytest.raises(ValueError):
        my_channels.normalize_ref(bad)


def test_a_tracked_channel_is_claimed_then_proved_with_its_own_description(world):
    s, _, users, chans = world
    c = my_channels.claim_tracked(s, users["a"], chans["one"].id)
    assert c["status"] == "pending" and c["code"] == my_channels.code_for(users["a"].id, chans["one"].id)
    assert my_channels.approved_channel_ids(s, users["a"].id) == []
    yt = FakeYT({chans["one"].youtube_channel_id: "News from Alpha. no code here"})
    assert my_channels.verify(s, users["a"], c["id"], client=yt)["found"] is False and my_channels.approved_channel_ids(s, users["a"].id) == []
    yt.descriptions[chans["one"].youtube_channel_id] = "News from Alpha. " + c["code"].upper()
    done = my_channels.verify(s, users["a"], c["id"], client=yt)
    assert done["found"] is True and done["status"] == "approved" and done["method"] == "code" and done["code"] is None
    assert my_channels.approved_channel_ids(s, users["a"].id) == [chans["one"].id]


def test_someone_elses_code_does_not_prove_your_claim(world):
    s, _, users, chans = world
    mine = my_channels.claim_tracked(s, users["a"], chans["one"].id)
    theirs = my_channels.claim_tracked(s, users["b"], chans["one"].id)
    assert mine["code"] != theirs["code"]
    yt = FakeYT({chans["one"].youtube_channel_id: "owner put " + theirs["code"]})
    assert my_channels.verify(s, users["a"], mine["id"], client=yt)["found"] is False
    assert my_channels.verify(s, users["b"], theirs["id"], client=yt)["found"] is True
    with pytest.raises(LookupError):
        my_channels.verify(s, users["a"], theirs["id"], client=yt)
    with pytest.raises(LookupError):
        my_channels.remove(s, users["a"], theirs["id"])


def test_a_pasted_handle_stores_an_unknown_channel_switched_off_and_never_a_second_copy(world):
    s, _, users, chans = world
    yt = FakeYT(known={"@brandnew": (UC_NEW, "Brand New Channel"), "@alphanews": (chans["one"].youtube_channel_id, "Alpha News")})
    c = my_channels.claim_by_ref(s, users["a"], "@brandnew", client=yt)
    row = s.query(Channel).filter_by(youtube_channel_id=UC_NEW).one()
    assert c["channel"]["tracked"] is False and row.active is False and row.segment == "creator" and row.handle == "@brandnew" and yt.closed == 0
    same = my_channels.claim_by_ref(s, users["a"], "@alphanews", client=yt)
    assert same["channel"]["id"] == chans["one"].id and s.query(Channel).count() == 4
    with pytest.raises(RuntimeError):
        my_channels.claim_by_ref(s, users["a"], "@nobody", client=yt)


def test_claiming_twice_is_one_claim_and_the_number_of_claims_is_limited(world, monkeypatch):
    s, _, users, chans = world
    first = my_channels.claim_tracked(s, users["a"], chans["one"].id)
    assert my_channels.claim_tracked(s, users["a"], chans["one"].id)["id"] == first["id"]
    monkeypatch.setattr(my_channels, "MAX_CLAIMS", 2)
    my_channels.claim_tracked(s, users["a"], chans["two"].id)
    with pytest.raises(ValueError, match="up to 2"):
        my_channels.claim_tracked(s, users["a"], chans["off"].id)


def test_search_finds_tracked_channels_not_already_taken(world):
    s, _, users, chans = world
    assert [c["name"] for c in my_channels.search_tracked(s, users["a"].id, "alpha")] == ["Alpha News"]
    assert [c["name"] for c in my_channels.search_tracked(s, users["a"].id, "@beta")] == ["Beta Voice"]
    assert my_channels.search_tracked(s, users["a"].id, "gamma") == [] and my_channels.search_tracked(s, users["a"].id, "a") == []
    my_channels.claim_tracked(s, users["a"], chans["one"].id)
    assert my_channels.search_tracked(s, users["a"].id, "alpha") == []


def test_the_administrator_approves_declines_assigns_and_can_switch_tracking_on(world):
    s, _, users, chans = world
    c = my_channels.claim_tracked(s, users["a"], chans["off"].id)
    ok = my_channels.decide(s, c["id"], "approve", by="boss@x.com", track=True)
    assert ok["status"] == "approved" and ok["method"] == "admin" and ok["channel"]["tracked"] is True and ok["user"]["login"] == "a@x.com"
    d = my_channels.claim_tracked(s, users["b"], chans["two"].id)
    no = my_channels.decide(s, d["id"], "reject", by="boss@x.com", note="not the owner")
    assert no["status"] == "rejected" and no["note"] == "not the owner"
    with pytest.raises(PermissionError):
        my_channels.verify(s, users["b"], d["id"], client=FakeYT({chans["two"].youtube_channel_id: d["code"]}))
    again = my_channels.claim_tracked(s, users["b"], chans["two"].id)
    assert again["status"] == "pending" and again["id"] == d["id"]
    given = my_channels.assign(s, users["b"].id, chans["one"].id, by="boss@x.com")
    assert given["status"] == "approved" and my_channels.approved_channel_ids(s, users["b"].id) == [chans["one"].id]
    assert {x["status"] for x in my_channels.list_claims(s)} == {"approved", "pending"}
    assert [x["user"]["login"] for x in my_channels.list_claims(s, "pending")] == ["b@x.com"]
    with pytest.raises(ValueError):
        my_channels.decide(s, c["id"], "maybe", by="x")
    with pytest.raises(ValueError):
        my_channels.list_claims(s, "weird")
    assert my_channels.admin_remove(s, given["id"]) == {"removed": True}


def _call(app, method, path, who, body=None, query=""):
    raw = json.dumps(body or {}).encode()
    out = {}
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)) if method == "POST" else "0",
               "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else "", "REMOTE_ADDR": "127.0.0.1"}
    res = app(environ, lambda status, headers: out.update(status=status))
    return int(out["status"].split()[0]), json.loads(b"".join(res))


def test_the_http_routes_keep_each_login_to_its_own_claims_and_the_admin_routes_to_admins(world):
    s, engine, users, chans = world
    mine, admin = my_channels_application(lambda: Session(engine)), admin_application(lambda: Session(engine))
    assert _call(mine, "GET", "/api/v1/my/channels", None)[0] == 401
    status, body = _call(mine, "POST", "/api/v1/my/channels/claim", users["a"], {"channel_id": chans["one"].id})
    assert status == 200 and body["claim"]["status"] == "pending" and "description" in body["help"]
    claim_id = body["claim"]["id"]
    status, body = _call(mine, "GET", "/api/v1/my/channels", users["a"])
    assert status == 200 and [c["id"] for c in body["claims"]] == [claim_id] and body["channel_ids"] == []
    assert _call(mine, "GET", "/api/v1/my/channels", users["b"])[1]["claims"] == []
    assert _call(mine, "POST", "/api/v1/my/channels/remove", users["b"], {"claim_id": claim_id})[0] == 404
    assert _call(mine, "POST", "/api/v1/my/channels/verify", users["b"], {"claim_id": claim_id})[0] == 404
    status, body = _call(mine, "GET", "/api/v1/my/channels/search", users["b"], query="q=alpha")
    assert status == 200 and [c["name"] for c in body["channels"]] == ["Alpha News"]
    assert _call(mine, "POST", "/api/v1/my/channels/claim", users["a"], {"ref": "https://example.com/@x"})[0] == 400
    assert _call(admin, "POST", "/api/v1/admin/channel-claims/list", users["a"], {})[0] == 403
    status, body = _call(admin, "POST", "/api/v1/admin/channel-claims/list", users["boss"], {"status": "pending"})
    assert status == 200 and [c["id"] for c in body["claims"]] == [claim_id]
    status, body = _call(admin, "POST", "/api/v1/admin/channel-claims/decide", users["boss"], {"claim_id": claim_id, "decision": "approve", "track": True})
    assert status == 200 and body["status"] == "approved"
    assert _call(mine, "GET", "/api/v1/my/channels", users["a"])[1]["channel_ids"] == [chans["one"].id]
    status, body = _call(admin, "POST", "/api/v1/admin/channel-claims/assign", users["boss"], {"user_id": users["b"].id, "channel_id": chans["two"].id})
    assert status == 200 and body["user"]["login"] == "b@x.com"
    assert _call(admin, "POST", "/api/v1/admin/channel-claims/decide", users["boss"], {"claim_id": 999, "decision": "approve"})[0] == 404
    assert _call(admin, "POST", "/api/v1/admin/channel-claims/remove", users["boss"], {"claim_id": body["id"]})[0] == 200
    assert s.query(UserChannel).count() == 1
