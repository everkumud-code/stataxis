"""The public demo: the real workspace, running on invented data, read-only.

/demo.html is the workspace page with a small script added. The script gets a session for the demo visitor and sends the page's API calls to /demo-api/..., which answers from a separate in-memory
database (api/demo_data.py) with the same code as the real API. The demo can look at everything and change nothing: only reading is allowed, plus the media planner, which only calculates.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import demo_data
from api.auth import AuthIdentity, issue_token
from api.rate_limit import client_ip, limiter
from collector.storage import Base, User

REBUILD_SECONDS = 1800          # the invented numbers are rebuilt around the current time every half hour
READ_ONLY_MESSAGE = "The demo is read-only. Apply for access to use this with your own data."
ALLOWED_POST = {"/api/v1/market/planner", "/api/v1/market/screen-report.pdf"}   # they only calculate or draw a PDF; nothing is stored

INJECT = r"""<script>/* STAXIS demo: this page runs the real workspace on invented data and cannot change anything */
(function () {
  try {
    var x = new XMLHttpRequest(); x.open("GET", "/demo-api/session", false); x.send();
    var d = JSON.parse(x.responseText);
    sessionStorage.setItem("stataxis_token", d.token); sessionStorage.setItem("stataxis_account", JSON.stringify(d.account));
  } catch (e) { /* the page will show its own sign-in message */ }
  var f = window.fetch;
  window.fetch = function (u, o) { return f.call(this, (typeof u === "string" && u.indexOf("/api/") === 0) ? "/demo-api/" + u.slice(5) : u, o); };
  document.addEventListener("DOMContentLoaded", function () {
    document.title = "Demo — StatAxis workspace";
    var b = document.createElement("div");
    b.style.cssText = "background:#0b2a44;border-bottom:1px solid #159de8;color:#dff1ff;padding:10px 18px;font:14px/1.45 system-ui,sans-serif;display:flex;gap:14px;flex-wrap:wrap;align-items:center;justify-content:space-between";
    b.innerHTML = '<span><b>DEMO</b> · This is the real StatAxis workspace running on <b>invented sample channels</b>. Nothing here is a real channel or a real measurement, and nothing can be changed.</span><a href="/apply" style="color:#021018;background:#159de8;padding:8px 14px;border-radius:6px;text-decoration:none;font-weight:600">Apply for access</a>';
    document.body.insertBefore(b, document.body.firstChild);
    var out = document.getElementById("signout"); if (out) { out.textContent = "Apply for access"; out.onclick = function () { location.href = "/apply"; }; }
    var pw = document.getElementById("chpw"); if (pw) pw.hidden = true;
    window.signOut = function () { sessionStorage.removeItem("stataxis_token"); location.reload(); };
  });
})();</script>"""


def demo_page(workspace_html: str) -> bytes:
    """The workspace page with the demo script added right after <head>."""
    return workspace_html.replace("<head>", "<head>" + INJECT, 1).encode("utf-8")


class DemoSite:
    def __init__(self, build_dispatch: Callable[[Callable[[], Session]], Callable[..., Any]]):
        self._build_dispatch = build_dispatch
        self._lock = threading.Lock()
        self._state: dict[str, Any] | None = None

    def _ensure(self) -> dict[str, Any]:
        state = self._state
        if state is not None and time.monotonic() - state["built"] < REBUILD_SECONDS:
            return state
        with self._lock:
            state = self._state
            if state is not None and time.monotonic() - state["built"] < REBUILD_SECONDS:
                return state
            engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
            Base.metadata.create_all(engine)
            with Session(engine) as s:
                demo_data.seed(s)
                user = s.query(User).filter_by(email=demo_data.DEMO_LOGIN).one()
                account = {"id": user.id, "email": user.email, "full_name": user.full_name, "organization": user.organization, "plan": user.plan, "is_admin": False, "approval_status": "approved"}
            self._state = {"built": time.monotonic(), "dispatch": self._build_dispatch(lambda: Session(engine)), "account": account}
            return self._state

    def application(self, environ: dict[str, Any], start_response: Callable[..., Any]):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")

        def reply(status: str, payload: dict[str, Any]):
            body = json.dumps(payload).encode("utf-8")
            start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
            return [body]

        if limiter.check(f"demo:{client_ip(environ)}", 300, 60):
            return reply("429 Too Many Requests", {"error": "The demo is busy; try again in a minute."})
        state = self._ensure()
        if path == "/demo-api/session" and method == "GET":
            acct = state["account"]
            return reply("200 OK", {"token": issue_token(AuthIdentity(acct["id"], acct["email"], acct["plan"], False)), "account": acct})
        real = "/api/" + path[len("/demo-api/"):]
        if method not in ("GET", "HEAD") and not (method == "POST" and real in ALLOWED_POST):
            return reply("403 Forbidden", {"error": READ_ONLY_MESSAGE})
        environ = dict(environ, PATH_INFO=real)
        result = state["dispatch"](environ, start_response)
        if result is None:
            return reply("404 Not Found", {"error": "not found"})
        return result
