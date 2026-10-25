"""The user manual PDF: made from the web page, in the StatAxis design, with real text, every section, the FAQ last, the worked example, the tables filled in from the code, and no other product named. Also the public route that serves it."""
import io
import json
import re
from types import SimpleNamespace

import pymupdf
import pytest

from api.manual_pdf import filename, manual_pdf
from api.methodology import methodology
from api.public_http import public_application


@pytest.fixture(scope="module")
def pdf():
    return manual_pdf()


@pytest.fixture(scope="module")
def doc(pdf):
    return pymupdf.open(stream=pdf, filetype="pdf")


@pytest.fixture(scope="module")
def text(doc):
    return "\n".join(p.get_text() for p in doc)


def test_it_is_a_pdf_of_a_sensible_length_with_a_title(pdf, doc):
    assert pdf[:5] == b"%PDF-" and 8 <= len(doc) <= 40
    assert doc.metadata["title"] == "StatAxis user manual"


def test_every_section_is_there_in_order_and_the_faq_is_last(text):
    heads = ["1 · WHAT STATAXIS IS", "2 · GETTING STARTED", "3 · THE SCREENS", "4 · WHERE THE DATA COMES FROM", "5 · WHAT EACH FIGURE MEANS", "6 · THE STX INDEX", "7 · THE IFX SCORE", "8 · METHODOLOGY IN SHORT",
             "9 · HOW TO READ THE DATA", "10 · HOW TO USE IT, BY ROLE", "11 · REPORTS AND DOWNLOADS", "12 · WHY STATAXIS IS DIFFERENT", "13 · PRIVACY AND ACCESS", "14 · FAQ"]
    at = [text.rindex(h) for h in heads]            # the last time each appears: the section itself, after the contents page
    assert at == sorted(at)
    assert text.index("Is Instagram, Facebook or X data included") > at[-1]
    assert text.rstrip().endswith("x.com/stataxis") or "Data via YouTube. Processed and evaluated by StatAxis." in text[-400:]


def test_the_contents_page_lists_every_section_with_a_page_number(doc):
    page = doc[1].get_text()
    assert "CONTENTS" in page
    for title in ("WHAT STATAXIS IS", "THE STX INDEX", "THE IFX SCORE", "WHY STATAXIS IS DIFFERENT", "FAQ"):
        assert title in page
    numbers = [int(n) for n in re.findall(r"(?m)\.\s+(\d{1,2})\s*$", page)]
    assert len(numbers) >= 14 and numbers == sorted(numbers) and numbers[0] >= 3 and numbers[-1] <= len(doc)


def test_the_tables_are_filled_in_from_the_code_not_left_empty(text):
    m = methodology()
    for part in m["ifx"]["parts"]:
        assert part["label"] in text
    for name in ("Audience", "Competition", "Anomaly"):
        assert name in text
    assert "Change in concurrent viewers against the previous window" in text
    t = re.sub(r"\s+", " ", text)
    assert t.count("30%") >= 2 and "Impact 35%" in t and "Followership 35%" in t and "eXposure 30%" in t


def test_the_worked_example_and_the_formula_are_in_it(text):
    t = re.sub(r"\s+", " ", text)
    assert "= 18 + 11 + 7.2 + 5 + 7 + 2.5 + 2.6 = 53.3" in t and "Shown = 50 + (53.8 - 50) x 0.85 = 53.2".replace(" x ", " × ") in t
    assert "Shown score = 50 + (STX - 50) × Confidence ÷ 100" in t


def test_the_text_is_real_and_searchable_and_no_other_product_is_named(doc, text):
    assert sum(len(p.get_text()) for p in doc) > 15000
    low = text.lower()
    for name in ("ratingology", "data being", "databeing", "scaleup"):
        assert name not in low


def test_every_page_carries_the_design_the_download_time_and_the_data_note(doc):
    for page in doc:
        t = page.get_text()
        assert "Downloaded" in t and "Data via YouTube. Processed and evaluated by StatAxis." in t and "x.com/stataxis" in t
    pix = doc[2].get_pixmap(matrix=pymupdf.Matrix(0.3, 0.3))
    assert all(abs(a - b) <= 2 for a, b in zip(pix.samples[:3], bytes([1, 5, 9])))   # the near-black page of the reference design, #010509


def test_the_file_name_says_when_it_was_downloaded():
    assert re.fullmatch(r"stataxis-user-manual-downloaded-[0-9T_\-]+\.pdf", filename())


def _call(app, path):
    captured = {}
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "REMOTE_ADDR": "203.0.113.9"}
    body = app(environ, lambda status, headers: captured.update(status=status, headers=dict(headers)))
    return captured["status"], captured["headers"], b"".join(body)


def test_the_public_route_serves_the_pdf_to_anyone_and_is_limited():
    app = public_application(lambda: SimpleNamespace(close=lambda: None))
    status, headers, body = _call(app, "/api/v1/public/manual.pdf")
    assert status == "200 OK" and headers["Content-Type"] == "application/pdf" and body[:5] == b"%PDF-"
    assert headers["Content-Disposition"].startswith('attachment; filename="stataxis-user-manual-downloaded-') and headers["Cache-Control"] == "no-store"
    codes = [_call(app, "/api/v1/public/manual.pdf")[0][:3] for _ in range(10)]
    assert "429" in codes


def test_the_web_page_offers_the_download():
    page = open("dashboard/manual.html", encoding="utf-8").read()
    assert 'href="/api/v1/public/manual.pdf"' in page
