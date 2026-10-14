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
    assert "market" in text.lower() and "Alpha News" in text and "1,20,000" in text and "Language: Hindi" in text
    assert text.count("Downloaded ") >= 2 and " IST" in text and "owner@x.com" in text and "stataxis" in text.lower()     # the header and the footer both carry it
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
    assert '"Downloaded " + window.sxDownloadedAt()' in market and "-downloaded-" in market


def test_every_block_has_its_own_pdf_and_post_image_and_nothing_says_branded_download():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "dashboard"
    bar, market, html = (root / "reportbar.js").read_text(encoding="utf-8"), (root / "market.js").read_text(encoding="utf-8"), (root / "workspace.html").read_text(encoding="utf-8")
    assert "function addUnitBars(view, screen)" in bar and "MutationObserver" in bar and 'className = "unitbar"' in bar          # each card (each channel, slot, group) gets its own buttons as it appears
    assert "async function postPng(" in bar and "image/png" in bar and "-post${pages > 1" in bar and "-downloaded-${stamp}.png" in bar                        # an image to post, with the time of download in the file name
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
    assert "stat the view. axis the viewpoint." in text.lower() and "Data via YouTube. Processed and evaluated by StatAxis." in text and "Digital Media Intelligence" not in text
    root = Path(__file__).resolve().parent.parent / "dashboard"
    for name in ("reportbar.js", "market.js"):
        js = (root / name).read_text(encoding="utf-8")
        assert "Digital Media Intelligence" not in js and "Processed and evaluated by StatAxis." in js
    design = (root / "sxdesign.js").read_text(encoding="utf-8")
    assert "Stat the View. " in design and "Axis the Viewpoint." in design and "x.com/stataxis" in design                       # every picture ends with the tagline, the site and the X handle
    bar = (root / "reportbar.js").read_text(encoding="utf-8")
    assert "(?![a-z])" in bar and "Weights and points are the method" in bar       # the radar's risk words stay out of a post, and so does the method (weights, points)


def test_a_post_explains_itself_to_a_stranger_shows_the_result_and_leaves_the_method_out():
    from pathlib import Path
    bar = (Path(__file__).resolve().parent.parent / "dashboard" / "reportbar.js").read_text(encoding="utf-8")
    assert "const PLAIN = {" in bar and "STX is a score out of 100" in bar and "plainOf(view)" in bar                    # one plain sentence on what the screen is
    assert 'classList.contains("kpi")' in bar and "kpi: {l, v, s: note}" in bar and "out[k].m = 1" in bar                  # headline numbers kept, method text marked and left out of a post
    assert "About this report: " in bar and "!/weight|points/i.test(b.head[c])" in bar                                      # the PDF opens with it too; weights are never the bars


def test_reports_say_what_stands_out_from_the_figures_alone():
    from pathlib import Path
    bar = (Path(__file__).resolve().parent.parent / "dashboard" / "reportbar.js").read_text(encoding="utf-8")
    assert "function findingsOf(chart)" in bar and "WHAT STANDS OUT" in bar and '"What stands out"' in bar          # in the post image and at the top of the PDF
    assert "leads with" in bar and "times" in bar and "holds" in bar and "do not have enough data yet" in bar          # who leads, by how much, the share, what is thin
    assert "r.value == null" in bar and "show 0 in this period" in bar                                                # a zero is a zero, not missing data


def test_a_long_result_is_split_into_numbered_posts_and_every_report_carries_our_viewpoint():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "dashboard"
    bar = (root / "reportbar.js").read_text(encoding="utf-8")
    assert "ROWS_PER = 8" in bar and "LINES_PER = 12" in bar and "-${n}-of-${pages}" in bar and "`${n} of ${pages}`" in bar        # 1 of 3, 2 of 3, 3 of 3
    assert "b.rows.slice(0, 24)" in bar and "first && kpis.length" in bar and "last && finds.length" in bar and "last && vp" in bar                     # the introduction on the first post, our reading on the last
    assert "function viewpointOf(chart, viewId, stx = \"\")" in bar and '"StatAxis viewpoint"' in bar and "STATAXIS VIEWPOINT" in bar            # in the PDF and on the post
    assert "not proof of anything" in bar                                                                                          # the radar's reading describes, it does not accuse


def test_the_report_builder_draws_one_date_and_one_time_interval_as_all_streams_beside_the_primary_stream():
    from pathlib import Path
    market = (Path(__file__).resolve().parent.parent / "dashboard" / "market.js").read_text(encoding="utf-8")
    assert 'id="bcmp"' in market and "async function comparisonPng(all, prim, v)" in market and 'feed: "all"' in market and 'feed: "primary"' in market
    assert '"All Streams"' in market and '"Primary Stream"' in market and "Avrg Concurrent" in market and "Peak Concurrent" in market and "Hrs | " in market   # the layout of the reference chart
    assert "STATAXIS VIEWPOINT" in market and "sxDownloadedAt" in market


def test_the_radar_describes_a_missing_dip_pattern_as_worth_a_look_not_as_a_finding_of_wrongdoing():
    from api import authenticity
    assert "no_ad_dips" in authenticity.SIGNALS and "not proof" in authenticity.METHOD


def test_hindi_and_other_scripts_are_drawn_as_letters_not_as_black_boxes():
    import fitz

    from api.report_pdf import _plain_ok, _shaped, clean_screen, screen_pdf

    assert _plain_ok("Aaj Tak - 12,000 viewers") and not _plain_ok("आज तक")
    png, w, h = _shaped("आज तक लाइव — ज्ञानेश कुमार", 9.0, 11.0, "#061322", False, "left", 200.0)
    pixmap = fitz.Pixmap(png)
    assert pixmap.alpha and w == 200.0 and h > 9
    assert any(pixmap.samples[i] for i in range(3, len(pixmap.samples), 4))                                  # something was drawn (alpha > 0), so it is not an empty picture

    hindi = screen(title="Spikes", blocks=[{"t": "p", "text": "Stream that carried it: आज तक लाइव"},
                                           {"t": "table", "head": ["Channel", "Stream that carried it", "Gained"], "rows": [["Aaj Tak", "आज की ताज़ा खबर लाइव", "8,913"], ["Beta TV", "Plain English title", "1,200"]]}])
    plain = screen(title="Spikes", blocks=[hindi["blocks"][0] | {"text": "Stream that carried it: Aaj Tak live"},
                                           {"t": "table", "head": ["Channel", "Stream that carried it", "Gained"], "rows": [["Aaj Tak", "Aaj ki taaza khabar live", "8,913"], ["Beta TV", "Plain English title", "1,200"]]}])
    pdf = screen_pdf(clean_screen(hindi), protect=False)
    doc = fitz.open(stream=pdf, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    assert "Plain English title" in text and "8,913" in text                                                 # ordinary text stays text
    assert "आज" not in text and "■" not in text                                                              # Hindi is not written with a font that lacks it
    base = fitz.open(stream=screen_pdf(clean_screen(plain), protect=False), filetype="pdf")
    assert sum(len(page.get_images()) for page in doc) > sum(len(page.get_images()) for page in base)       # the Hindi cells and line are pictures of real letters
    assert screen_pdf(clean_screen(hindi))[:4] == b"%PDF"   # the protected download works too


def test_every_picture_and_pdf_uses_the_one_design_of_the_reference():
    from pathlib import Path
    from api import report_pdf as rp
    root = Path(__file__).resolve().parent.parent
    assert (root / "design" / "reference.png").is_file() and (root / "dashboard" / "assets" / "stataxis-logo-dark.svg").is_file()
    design = (root / "dashboard" / "sxdesign.js").read_text(encoding="utf-8")
    for token in ("#010509", "#0b8ded", "#fdfdfd", "#ccd5dd", "Anton", "Instrument Serif", "FIG." if False else "background(x, W, H)"):
        assert token in design, token
    market, bar = ((root / "dashboard" / n).read_text(encoding="utf-8") for n in ("market.js", "reportbar.js"))
    for js in (market, bar):
        assert "SXD" in js and "D.background(x, W, H)" in js and "D.footer(x, W, H, P" in js        # the picture cards, the table card, the comparison chart and the posts all draw through the design
    assert market.count("D.background(x, W, H)") == 3 and bar.count("D.background(x, W, H)") == 1
    assert "#061322" not in market[market.index("async function cardPng"):market.index("/* ---------- report builder")] and "#e1b94f" not in bar[bar.index("async function postPng"):bar.index("async function makePost")]
    assert str(rp.BG) .lower().endswith("010509") or rp.BG.hexval().lower().endswith("010509")           # the PDF page is the same black
    assert rp.BLUE.hexval().lower().endswith("0b8ded") and rp.HANDLE.endswith("x.com/stataxis")
    png = rp.logo_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 5_000                                         # the blue-and-gold logo renders


def test_text_in_pictures_is_made_to_fit_never_cut_and_pages_are_not_cached():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    design, market, bar = ((root / "dashboard" / n).read_text(encoding="utf-8") for n in ("sxdesign.js", "market.js", "reportbar.js"))
    assert "function fit(x, text, maxW, weight, px, family)" in design and "fit," in design
    for js in (market, bar):
        assert js.count("D.fit(") >= 5
    for cut in ("String(r.label).slice(0, 18)", "String(r.label).slice(0, 17)", "String(k.v).slice(0, 12)", "String(r.text).slice(0, 14)", "nm.slice(0, 16)"):
        assert cut not in market and cut not in bar, cut                        # no label, value or legend is chopped to a fixed length any more
    web = (root / "web.py").read_text(encoding="utf-8")
    assert '("Cache-Control", "no-cache")' in web and '".js", ".html", ".css", ".svg"' in web


def test_the_date_and_other_filters_sit_above_the_result_on_every_screen():
    from pathlib import Path
    market = (Path(__file__).resolve().parent.parent / "dashboard" / "market.js").read_text(encoding="utf-8")
    for name in ("weekly", "primetime"):
        block = market[market.index(f'add("{name}"'):]
        block = block[:block.index("\n  });")]
        assert f'run(dateFilters(el, "{name}", "", run)); el.append(out);' in block                      # the filters are put on the page first, the result after them
        assert 'const out = document.createElement("div"); el.append(out);' not in block


def test_live_event_compare_lets_the_reader_pick_the_feed():
    from pathlib import Path
    market = (Path(__file__).resolve().parent.parent / "dashboard" / "market.js").read_text(encoding="utf-8")
    assert '<label>Feed<br><select name="feed">' in market and '"Primary stream"' in market and '"Secondary streams"' in market and "feed: v.feed" in market
