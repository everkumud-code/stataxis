"""Polls and surveys for clients: the tick-only privileges, what each tick allows, that a client sees only its own polls, the approval step before a client's poll goes public, and that clients never reach the
home page or the public Polls page. Invented data in a scratch database."""
import base64
import io
import json

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import feature_access, me
from api import survey_core as core
from api.auth import AuthIdentity, hash_password, issue_token
from api.rate_limit import limiter
from api.survey_http import inject_home_polls, survey_admin_application, survey_site_response
from collector.storage import Base, User

ALL = ["survey_publish", "survey_export", "survey_invites", "survey_pictures", "survey_contact", "survey_public_results", "survey_political"]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    limiter.reset()
    from api import survey_http
    survey_http._HOME.clear()


def world():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    users = {}
    for key, email, admin in (("boss", "boss@x.in", True), ("a", "a@client.in", False), ("b", "b@client.in", False), ("nobody", "nobody@client.in", False)):
        u = User(email=email, password_hash=hash_password("a long enough pass"), plan="sx_enterprise", requested_plan="sx_enterprise", is_admin=admin, active=True, approval_status="approved", full_name=key, organization="Org")
        s.add(u)
        s.commit()
        users[key] = u
    return s, engine, users


def tick(s, who, *features, by="boss@x.in"):
    for f in features:
        feature_access.set_user_feature(s, who.id, f, True, by)


def caller(engine):
    app = survey_admin_application(lambda: Session(engine))

    def call(who, method, route, body=None, query=""):
        raw = json.dumps(body).encode() if body is not None else b""
        out = {}
        env = {"REQUEST_METHOD": method, "PATH_INFO": "/api/v1/surveys/" + route, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
               "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else ""}
        res = app(env, lambda status, headers: out.update(status=status, headers=dict(headers)))
        data = b"".join(res)
        return int(out["status"].split()[0]), (json.loads(data) if out["headers"].get("Content-Type", "").startswith("application/json") else data)
    return call


def poll(**over):
    base = {"title": "Client poll", "kind": "poll", "questions": [{"type": "single", "text": "Pick one", "required": True, "options": [{"text": "A"}, {"text": "B"}]}]}
    return {**base, **over}


def png_b64():
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (10, 100, 200)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------------------------------------------------------------------------------------ the ticks
def test_every_survey_tool_needs_a_tick_whatever_the_package_and_even_when_packages_are_off():
    s, _, u = world()
    for f in ["surveys", *ALL]:
        assert f in feature_access.OPT_IN and feature_access.FEATURES[f][0] and feature_access.DESCRIPTIONS[f] and feature_access.group_of(f) == "Polls and surveys"
        assert feature_access.allowed(s, f, "sx_enterprise", False, u["a"].id) is False and feature_access.allowed(s, f, "sx_enterprise", True, u["boss"].id) is True
    feature_access.set_packages_enabled(s, False, "boss@x.in")
    assert feature_access.allowed(s, "surveys", "sx_enterprise", False, u["a"].id) is False and feature_access.allowed(s, "market", "sx_free", False, u["a"].id) is True       # packages off opens the others, not these
    tick(s, u["a"], "surveys")
    assert feature_access.allowed(s, "surveys", "sx_free", False, u["a"].id) and not feature_access.allowed(s, "survey_export", "sx_enterprise", False, u["a"].id)
    feature_access.set_user_feature(s, u["a"].id, "surveys", False, "boss@x.in")
    assert not feature_access.allowed(s, "surveys", "sx_enterprise", False, u["a"].id)
    assert "not switched on" in feature_access.explain_denied(s, "surveys", "sx_enterprise", u["a"].id)
    with pytest.raises(ValueError, match="not part of any package"):
        feature_access.set_min_plan(s, "surveys", "sx_idea", "boss@x.in")


def test_the_privilege_list_of_a_person_shows_groups_and_which_tools_need_a_tick():
    s, _, u = world()
    rows = {r["feature"]: r for r in feature_access.user_matrix(s, u["a"])}
    assert rows["surveys"]["opt_in"] is True and rows["surveys"]["allowed"] is False and rows["surveys"]["by_package"] is False and rows["surveys"]["group"] == "Polls and surveys"
    assert rows["market"]["opt_in"] is False and rows["market"]["group"] == "Market and channels" and set(rows) == set(feature_access.FEATURES) and all(r["group"] != "Other" for r in rows.values())
    assert {r["group"] for r in rows.values()} == {name for name, _ in feature_access.GROUPS}
    assert {m["feature"] for m in feature_access.matrix(s) if m["opt_in"]} == feature_access.OPT_IN
    from api import public_http
    assert not {f["feature"] for f in public_http.packages(s)["features"]} & feature_access.OPT_IN                         # not offered as part of any package
    ticked = {r["feature"]: r for r in feature_access.set_user_feature(s, u["a"].id, "survey_export", True, "boss@x.in")}
    assert ticked["survey_export"]["allowed"] and ticked["survey_export"]["source"] == "admin" and ticked["survey_export"]["set_by"] == "boss@x.in"


def test_the_screen_appears_in_a_clients_menu_only_after_the_tick():
    s, _, u = world()
    feature_access.set_packages_enabled(s, False, "boss@x.in")
    assert "surveys" not in me.nav_views(s, u["a"]) and "surveys" in me.nav_views(s, u["boss"]) and "market" in me.nav_views(s, u["a"])
    tick(s, u["a"], "surveys")
    assert "surveys" in me.nav_views(s, u["a"]) and "surveys" not in me.nav_views(s, u["b"])
    assert next(v for v in me.me_payload(s, u["a"])["views"] if v["id"] == "surveys")["allowed"] is True


# ------------------------------------------------------------------------------------------------------------------------------ what a client may do
def test_a_person_without_the_tick_gets_a_plain_refusal_on_every_route():
    s, engine, u = world()
    call = caller(engine)
    for method, route, body in (("GET", "list", None), ("POST", "save", poll()), ("GET", "get", None), ("POST", "images/upload", {"data": png_b64()})):
        code, out = call(u["nobody"], method, route, body)
        assert code == 403 and "not switched on" in out["error"], route
    assert call(None, "GET", "list")[0] == 401
    assert call(u["boss"], "GET", "list")[0] == 200


def test_a_client_sees_and_changes_only_its_own_polls_and_the_administrator_sees_all_with_the_owner():
    s, engine, u = world()
    tick(s, u["a"], "surveys")
    tick(s, u["b"], "surveys")
    call = caller(engine)
    mine = call(u["a"], "POST", "save", poll(title="A poll", slug="a-poll"))[1]["survey"]
    theirs = call(u["b"], "POST", "save", poll(title="B poll", slug="b-poll"))[1]["survey"]
    boss_own = call(u["boss"], "POST", "save", poll(title="Boss poll", slug="boss-poll"))[1]["survey"]
    assert [x["title"] for x in call(u["a"], "GET", "list")[1]["surveys"]] == ["A poll"] and [x["title"] for x in call(u["b"], "GET", "list")[1]["surveys"]] == ["B poll"]
    listing = call(u["boss"], "GET", "list")[1]
    assert {x["title"]: x["owner"] for x in listing["surveys"]} == {"A poll": "a@client.in", "B poll": "b@client.in", "Boss poll": "boss@x.in"} and listing["is_admin"] is True
    for method, route, body, query in (("GET", "get", None, f"id={theirs['id']}"), ("GET", "results", None, f"id={theirs['id']}"), ("GET", "responses", None, f"id={theirs['id']}"), ("POST", "delete", {"id": theirs["id"]}, ""),
                                       ("POST", "duplicate", {"id": theirs["id"]}, ""), ("POST", "status", {"id": theirs["id"], "status": "closed"}, ""), ("POST", "save", {**poll(title="Hijack"), "id": theirs["id"]}, ""),
                                       ("GET", "history", None, f"id={theirs['id']}"), ("POST", "purge", {"id": theirs["id"]}, "")):
        code, out = call(u["a"], method, route, body, query)
        assert code == 404 and "does not exist" in out["error"], route                                                    # somebody else's poll is not even said to exist
    assert call(u["a"], "GET", "get", query=f"id={mine['id']}")[0] == 200 and call(u["boss"], "GET", "get", query=f"id={theirs['id']}")[0] == 200
    copy = call(u["a"], "POST", "duplicate", {"id": mine["id"]})[1]["survey"]
    assert core.get_survey(s, copy["id"]).owner_id == u["a"].id and boss_own["id"]
    resp_survey = core.get_survey(s, theirs["id"])
    resp_survey.status = "live"
    s.commit()
    core.submit_response(s, resp_survey, {"q1": {"o": "o1"}}, token="t" * 20)
    rid = s.query(__import__("collector.storage", fromlist=["SurveyResponse"]).SurveyResponse).first().id
    assert call(u["a"], "POST", "response-status", {"id": rid, "status": "removed"})[0] == 404 and call(u["b"], "POST", "response-status", {"id": rid, "status": "removed"})[0] == 200


def test_each_tick_unlocks_exactly_its_own_part():
    s, engine, u = world()
    tick(s, u["a"], "surveys")
    call = caller(engine)
    sid = call(u["a"], "POST", "save", poll(title="Plain poll", slug="plain-poll"))[1]["survey"]["id"]
    refusals = [
        ("POST", "images/upload", {"data": png_b64()}, "pictures"), ("GET", "export", None, "downloading"), ("POST", "invites/create", {"id": sid, "count": 2}, "invitation"),
        ("POST", "save", poll(title="Contact poll", contact_mode="optional", contact_fields=["mobile"], consent_text="I agree"), "personal details"), ("POST", "save", poll(title="Public results", results_mode="public"), "results to others"),
        ("POST", "save", poll(title="Political poll", category="political"), "Political"), ("GET", "template", None, "Political")]
    for method, route, body, word in refusals:
        query = f"id={sid}&format=csv" if route == "export" else ("key=political-poll" if route == "template" else "")
        code, out = call(u["a"], method, route, body, query)
        assert code == 403 and word.lower() in out["error"].lower(), (route, out)
    assert [t["key"] for t in call(u["a"], "GET", "list")[1]["templates"]] == ["quick-poll", "brand-tracker", "customer-satisfaction", "team-pulse", "media-habits"]        # no political starter
    assert "political" not in call(u["a"], "GET", "list")[1]["categories"]
    for key in ("quick-poll", "brand-tracker", "customer-satisfaction", "team-pulse", "media-habits"):                                  # every starter saves cleanly for a client with only the first tick
        draft = call(u["a"], "GET", "template", query=f"key={key}")[1]["survey"]
        assert draft["results_mode"] == "private" and call(u["a"], "POST", "save", {**draft, "slug": f"s-{key}"})[0] == 200, key
    tick(s, u["a"], "survey_pictures", "survey_export", "survey_political")
    assert call(u["a"], "POST", "images/upload", {"data": png_b64()})[0] == 200 and call(u["a"], "GET", "export", query=f"id={sid}&format=csv")[0] == 200
    assert call(u["a"], "POST", "save", poll(title="Political poll", category="political"))[0] == 200 and call(u["a"], "GET", "template", query="key=political-poll")[0] == 200
    tick(s, u["a"], "survey_contact", "survey_public_results", "survey_invites")
    assert call(u["a"], "POST", "save", poll(title="Contact poll", contact_mode="optional", contact_fields=["mobile"], consent_text="I agree"))[0] == 200
    assert call(u["a"], "POST", "save", poll(title="Public results", results_mode="public"))[0] == 200
    assert call(u["a"], "POST", "save", poll(title="Invited poll", access="invite"))[0] == 200


def test_contact_details_stay_out_of_exports_and_answer_lists_without_their_tick():
    s, engine, u = world()
    tick(s, u["a"], "surveys", "survey_export", "survey_contact")
    call = caller(engine)
    sid = call(u["a"], "POST", "save", poll(title="With details", contact_mode="required", contact_fields=["mobile"], consent_text="I agree to a call"))[1]["survey"]["id"]
    row = core.get_survey(s, sid)
    row.status = "live"
    s.commit()
    core.submit_response(s, row, {"q1": {"o": "o1"}}, contact={"mobile": "9876543210"}, consent=True, token="c" * 20)
    assert b"9876543210" in call(u["a"], "GET", "export", query=f"id={sid}&format=csv&contact=1")[1] and call(u["a"], "GET", "responses", query=f"id={sid}&contact=1")[1]["responses"][0]["contact"] == {"mobile": "9876543210"}
    feature_access.set_user_feature(s, u["a"].id, "survey_contact", False, "boss@x.in")
    assert b"9876543210" not in call(u["a"], "GET", "export", query=f"id={sid}&format=csv&contact=1")[1] and "contact" not in call(u["a"], "GET", "responses", query=f"id={sid}&contact=1")[1]["responses"][0]


def test_a_client_cannot_use_a_picture_another_account_uploaded():
    s, engine, u = world()
    tick(s, u["a"], "surveys", "survey_pictures")
    tick(s, u["b"], "surveys", "survey_pictures")
    call = caller(engine)
    mine = call(u["a"], "POST", "images/upload", {"data": png_b64()})[1]["key"]
    q = [{"type": "single", "text": "Pick", "options": [{"text": "A", "image": mine}, {"text": "B"}]}]
    assert call(u["a"], "POST", "save", poll(title="Picture poll", questions=q))[0] == 200
    code, out = call(u["b"], "POST", "save", poll(title="Copycat", questions=q))
    assert code == 400 and "missing" in out["error"]                                                                          # not even by guessing a key


# ------------------------------------------------------------------------------------------------------------------------------ approval and the public side
def page(engine, path):
    out = {}
    res = survey_site_response(lambda: Session(engine), {"REQUEST_METHOD": "GET", "PATH_INFO": path}, lambda status, headers: out.update(status=status), [])
    return (None, b"") if res is None else (int(out["status"].split()[0]), b"".join(res))


def test_a_clients_poll_waits_for_approval_unless_it_has_the_publish_tick():
    s, engine, u = world()
    tick(s, u["a"], "surveys")
    call = caller(engine)
    saved = call(u["a"], "POST", "save", poll(title="Needs approval", slug="needs-approval", status="live"))[1]["survey"]
    assert saved["status"] == "review" and saved["state"] == "review" and page(engine, "/survey/needs-approval")[0] == 404           # asked to open: waiting, not public
    assert call(u["a"], "POST", "save", {**poll(title="Needs approval", slug="needs-approval"), "id": saved["id"], "status": "draft"})[0] == 200
    assert call(u["a"], "POST", "status", {"id": saved["id"], "status": "live"})[1]["survey"]["state"] == "review"
    assert call(u["a"], "POST", "review/reject", {"id": saved["id"], "note": "Please add who paid for it."})[0] == 403               # a client cannot approve or reject
    rejected = call(u["boss"], "POST", "review/reject", {"id": saved["id"], "note": "Please add who paid for it."})[1]["survey"]
    assert rejected["status"] == "draft" and rejected["review_note"] == "Please add who paid for it." and call(u["boss"], "POST", "review/reject", {"id": saved["id"], "note": "x"})[0] == 400
    assert call(u["a"], "POST", "status", {"id": saved["id"], "status": "live"})[1]["survey"]["state"] == "review"
    approved = call(u["boss"], "POST", "status", {"id": saved["id"], "status": "live"})[1]["survey"]
    assert approved["state"] == "open" and approved["review_note"] == "" and page(engine, "/survey/needs-approval")[0] == 200
    code, out = call(u["a"], "POST", "save", {**poll(title="Needs approval", slug="needs-approval", description="Changed after approval"), "id": saved["id"], "status": "live"})
    assert code == 403 and "cannot be changed" in out["error"]                                                              # an approved poll cannot be quietly changed
    assert call(u["a"], "POST", "status", {"id": saved["id"], "status": "closed"})[1]["survey"]["state"] == "closed"
    tick(s, u["a"], "survey_publish")
    direct = call(u["a"], "POST", "save", poll(title="Straight live", slug="straight-live", status="live"))[1]["survey"]
    assert direct["state"] == "open" and page(engine, "/survey/straight-live")[0] == 200


def test_a_client_poll_never_reaches_the_home_page_or_the_polls_list_unless_an_administrator_says_so():
    s, engine, u = world()
    tick(s, u["a"], "surveys", "survey_publish")
    call = caller(engine)
    saved = call(u["a"], "POST", "save", poll(title="Client live", slug="client-live", status="live", promote=True, listed=True))[1]["survey"]
    assert saved["state"] == "open" and saved["promote"] is False and saved["listed"] is False                                      # asked for, ignored
    index = b"<html><body><main><section class=\"vx-hero\">h</section><section>x</section></main></body></html>"
    assert inject_home_polls(lambda: Session(engine), index) == index and b"client-live" not in page(engine, "/polls")[1]
    admin_edit = call(u["boss"], "POST", "save", {**saved, "promote": True, "listed": True})[1]["survey"]
    assert admin_edit["promote"] is True and admin_edit["listed"] is True and b"client-live" in inject_home_polls(lambda: Session(engine), index) and b"client-live" in page(engine, "/polls")[1]
    again = call(u["a"], "POST", "save", {**admin_edit, "status": "closed"})[1]["survey"]
    assert again["promote"] is False and again["listed"] is False                                                                    # the client's own save takes it off again


def test_a_client_can_withdraw_its_own_poll_from_review_and_delete_a_draft():
    s, engine, u = world()
    tick(s, u["a"], "surveys")
    call = caller(engine)
    sid = call(u["a"], "POST", "save", poll(title="Withdraw me", slug="withdraw-me", status="live"))[1]["survey"]["id"]
    assert call(u["a"], "POST", "status", {"id": sid, "status": "draft"})[1]["survey"]["state"] == "draft"
    assert call(u["a"], "POST", "delete", {"id": sid})[0] == 200 and call(u["a"], "GET", "list")[1]["surveys"] == []
