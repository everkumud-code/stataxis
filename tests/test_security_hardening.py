"""Hiding what must stay hidden: no secret in a served file or a log, no source or data file reachable, hardened response headers, and the copy guard."""
import logging
import re
from pathlib import Path

import pytest

import web

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "dashboard"


def get(path):
    out = {}
    res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status, headers=dict(headers)))
    return out["status"], out["headers"], b"".join(res)


@pytest.mark.parametrize("path", ["/.env", "/.git/config", "/web.py", "/dashboard/api.py", "/api.py", "/intelligence.py", "/launch-notes.md", "/../web.py", "/%2e%2e/web.py",
                                  "/config/channels.json", "/config/live_news_feeds.json", "/stataxis.db", "/requirements.txt", "/Dockerfile", "/docker-compose.yml", "/pyproject.toml", "/sample-report.csv",
                                  "/tests/test_security_hardening.py", "/collector/service.py"])
def test_source_data_and_configuration_files_are_not_reachable(path):
    status, _headers, body = get(path)
    assert status.startswith("404") and body == b"Not found", path


def test_nothing_served_to_a_browser_contains_a_secret():
    patterns = {"a Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "a private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a live payment key": re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{10,}"),
                "a long token": re.compile(r"\beyJ[A-Za-z0-9_\-]{30,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}")}
    for path in DASH.rglob("*"):
        if path.is_file() and path.suffix.lower() in web.STATIC_EXTENSIONS and path.stat().st_size < 3_000_000:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for what, rx in patterns.items():
                assert not rx.search(text), f"{path.name} contains {what}"


def test_every_response_carries_the_hardening_headers():
    for path in ("/", "/ifx.html", "/api/v1/market/weekly"):
        _status, headers, _body = get(path)
        assert headers["X-Content-Type-Options"] == "nosniff" and headers["X-Frame-Options"] == "DENY" and headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert "camera=()" in headers["Permissions-Policy"] and headers["Cross-Origin-Resource-Policy"] == "same-site" and headers["Referrer-Policy"]
        assert "object-src 'none'" in headers["Content-Security-Policy"] and "frame-ancestors 'none'" in headers["Content-Security-Policy"] and "default-src 'self'" in headers["Content-Security-Policy"]


def test_the_youtube_key_cannot_reach_a_log_because_request_urls_are_not_logged():
    import collector.youtube.client  # noqa: F401  (importing it sets the log levels)

    for name in ("httpx", "httpcore"):
        assert not logging.getLogger(name).isEnabledFor(logging.INFO), name


def test_the_copy_guard_is_loaded_everywhere_a_visitor_or_a_member_looks_and_leaves_typing_and_secrets_alone():
    guard = (DASH / "guard.js").read_text(encoding="utf-8")
    assert "guard.js" in (DASH / "site.js").read_text(encoding="utf-8") and "guard.js" in (DASH / "workspace.html").read_text(encoding="utf-8")
    for needed in ("contextmenu", "copy", "cut", "dragstart", "selectstart", "F12", "allow-copy", "is_admin", "input,textarea,select", "mailto:"):
        assert needed in guard, needed
    market = (DASH / "market.js").read_text(encoding="utf-8")
    assert market.count('class="allow-copy"') >= 2   # the temporary password and the verification code stay copyable


def test_the_demo_page_and_its_api_also_get_the_guard_and_the_headers():
    status, headers, body = get("/demo.html")
    assert status.startswith("200") and b"guard.js" in body and headers["Cache-Control"] == "no-store" and "Permissions-Policy" in headers
