"""The one-tap report under every screen, and the download time that every report, workbook, sheet and picture carries."""
import base64
import io
import json
import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.auth import AuthIdentity, issue_token
from api.market_http import market_application
from collector.storage import Base, User

pytest.importorskip("reportlab")
pytest.importorskip("fitz")


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


# a 1x1 png
PIXEL = "data:image/png;base64," + base64.b64encode(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082")).decode()


def screen(**extra):
    base = {"view": "market", "title": "Market", "filters": "Language: Hindi  |  From: 2026-10-05", "blocks": [
        {"t": "p", "text": "Every channel ranked by views gained."},
        {"t": "h", "text": "Ranking"},
        {"t": "table", "head": ["Rank", "Channel", "Views gained"], "rows": [["1", "Alpha News", "1,20,000"], ["2", "Beta TV", "90,000"]]},
    ]}
    base.update(extra)
    return base


def test_the_download_time_is_in_indian_time_in_words_and_in_file_names():
    from api.stamps import file_stamp, ist_stamp
    moment = datetime(2026, 10, 12, 10, 12, tzinfo=UTC)          # 3:42 pm in India
    assert ist_stamp(moment) == "12 Oct 2026, 3:42 PM IST"
    assert ist_stamp(datetime(2026, 10, 11, 18, 31, tzinfo=UTC)) == "12 Oct 2026, 12:01 AM IST"
    assert file_stamp(moment) == "20261012-1542"


def test_a_screen_report_is_a_branded_protected_pdf_that_says_when_it_was_downloaded():
    from api.report_pdf import _mupdf, clean_screen, screen_filename, screen_pdf
    fitz = _mupdf()
    s = clean_screen(screen())
    assert re.fullmatch(r"stataxis-market-downloaded-\d{8}-\d{4}\.pdf", screen_filename(s))
    plain = fitz.open(stream=screen_pdf(s, "owner@x.com (Org)", protect=False), filetype="pdf")
    text = " ".join(p.get_text() for p in plain)
    assert "Market" in text and "Alpha News" in text and "1,20,000" in text and "Language: Hindi" in text
    assert text.count("Downloaded ") >= 2 and " IST" in text and "owner@x.com" in text and "STATAXIS" in text     # header band and footer both carry it
    protected = fitz.open(stream=screen_pdf(s, "owner@x.com"), filetype="pdf")
    assert all(p.get_text().strip() == "" for p in protected) and all(p.get_images() for p in protected)         # a picture of the page, nothing to lift


def test_a_screen_report_keeps_what_a_report_can_hold_and_refuses_the_rest():
    from api.report_pdf import MAX_COLS, MAX_ROWS, clean_screen, screen_pdf
    for bad in ({}, {"blocks": []}, {"blocks": "x"}, {"blocks": [{"t": "script", "text": "x"}, {"t": "p", "text": "   "}, 5]}):
        with pytest.raises(ValueError):
            clean_screen(bad)
    big = clean_screen(screen(blocks=[{"t": "table", "head": [f"c{i}" for i in range(30)], "rows": [[str(j)] * 30 for j in range(MAX_ROWS + 50)]}]))
    t = big["blocks"][0]
    assert len(t["head"]) == MAX_COLS and len(t["rows"]) == MAX_ROWS and t["cut"] and all(len(r) == MAX_COLS for r in t["rows"])
    odd = clean_screen(screen(blocks=[{"t": "table", "head": ["a"], "rows": [["x", "y", "z"], ["only"]]}, {"t": "img", "data": "data:image/svg+xml;base64,AAAA"}, {"t": "img", "data": "data:image/png;base64,@@@"}]))
    assert odd["blocks"][0]["head"] == ["a", "", ""] and odd["blocks"][0]["rows"] == [["x", "y", "z"], ["only", "", ""]] and len(odd["blocks"]) == 1      # no pictures pass unless they are real png data
    assert screen_pdf(big, None, protect=False)[:5] == b"%PDF-"                                                                                              # a wide table makes a landscape page and still builds
    pic = clean_screen(screen(blocks=[{"t": "img", "data": PIXEL}, {"t": "p", "text": "<b>not markup</b> & more"}]))
    assert screen_pdf(pic, "a@b.c", protect=False)[:5] == b"%PDF-"


def test_the_endpoint_gives_any_signed_in_person_a_pdf_and_nobody_else():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(User(id=1, email="free@x.com", password_hash="x", plan="sx_free", is_admin=False, active=True, approval_status="approved", organization="Org"))
        s.commit()
    app = market_application(lambda: Session(engine))

    def call(body, token=True, raw=None):
        raw = raw if raw is not None else json.dumps(body).encode()
        out = {}
        environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/market/screen-report.pdf", "QUERY_STRING": "", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
                   "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(1, "free@x.com", "sx_free", False))) if token else ""}
        res = app(environ, lambda status, headers: out.update(status=status, headers=dict(headers)))
        return int(out["status"].split()[0]), b"".join(res), out.get("headers", {})

    status, body, headers = call(screen())
    assert status == 200 and body[:5] == b"%PDF-" and headers["Content-Type"] == "application/pdf" and "-downloaded-" in headers["Content-Disposition"] and headers["Cache-Control"] == "no-store"
    assert call(screen(), token=False)[0] == 401
    assert call({"blocks": []})[0] == 400
    assert call(None, raw=b"x" * 1_700_000)[0] == 400


def test_workbooks_say_when_they_were_downloaded():
    from openpyxl import Workbook

    from api.export import _add_notice_sheet
    wb = Workbook()
    _add_notice_sheet(wb)
    notes = wb["Notes"]
    assert notes["A1"].value == "Downloaded at" and str(notes["B1"].value).endswith(" IST")


def test_the_workspace_puts_the_report_bar_under_every_screen_and_stamps_csv_and_pictures():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "dashboard"
    html, bar, market = (root / "workspace.html").read_text(encoding="utf-8"), (root / "reportbar.js").read_text(encoding="utf-8"), (root / "market.js").read_text(encoding="utf-8")
    assert '<script src="reportbar.js"></script>' in html and "window.addReportBar(host, el, v)" in html
    assert "Downloaded at (Indian time)" in html and "-downloaded-" in html
    assert "/api/v1/market/screen-report.pdf" in bar and "sxDownloadedAt" in bar and "sxFileStamp" in bar
    assert 'x.fillText("Downloaded " + window.sxDownloadedAt()' in market and "-downloaded-" in market


def test_every_block_has_its_own_pdf_and_post_image_and_nothing_says_branded_download():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "dashboard"
    bar, market, html = (root / "reportbar.js").read_text(encoding="utf-8"), (root / "market.js").read_text(encoding="utf-8"), (root / "workspace.html").read_text(encoding="utf-8")
    assert "function addUnitBars(view, screen)" in bar and "MutationObserver" in bar and 'className = "unitbar"' in bar          # each card (each channel, slot, group) gets its own buttons as it appears
    assert "async function postPng(" in bar and "image/png" in bar and "-post-downloaded-" in bar                        # an image to post, with the time of download in the file name
    assert "Download post image" in bar and "Download PDF" in bar
    for text in (bar, market, html):
        assert "branded download" not in text.lower() and "Download branded" not in text and "Take this screen with you" not in text
    assert ".unitbar{" in html


def test_downloads_carry_the_tagline_and_say_where_the_data_comes_from_without_claiming_an_endorsement():
    from pathlib import Path

    from api.report_pdf import YOUTUBE_NOTE, _mupdf, clean_screen, screen_pdf
    assert YOUTUBE_NOTE == "Data via YouTube. Processed and evaluated by StatAxis." and "authoris" not in YOUTUBE_NOTE.lower() and "endorse" not in YOUTUBE_NOTE.lower()
    doc = _mupdf().open(stream=screen_pdf(clean_screen(screen()), "a@b.c", protect=False), filetype="pdf")
    text = " ".join(p.get_text() for p in doc)
    assert "Stat the View. Axis the Viewpoint." in text and "Data via YouTube. Processed and evaluated by StatAxis." in text and "Digital Media Intelligence" not in text
    root = Path(__file__).resolve().parent.parent / "dashboard"
    for name in ("reportbar.js", "market.js"):
        js = (root / name).read_text(encoding="utf-8")
        assert "Stat the View. Axis the Viewpoint." in js and "Digital Media Intelligence" not in js and "Processed and evaluated by StatAxis." in js
    bar = (root / "reportbar.js").read_text(encoding="utf-8")
    assert "roundRect" not in bar and "(?![a-z])" in bar       # the risk label pill is gone from the post image, and so are the radar's risk words
