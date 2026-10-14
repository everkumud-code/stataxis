"""Turns a built report (api/report_builder.py) into a PDF a person can download and share straight away."""

from __future__ import annotations

import base64
import binascii
import re
import secrets
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from html import unescape
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from api.stamps import file_stamp, ist_stamp

# The StatAxis design (design/reference.png): a near-black page, white headlines, electric blue for numbers and accents, grey-white text, and the blue-and-gold logo.
BG = colors.HexColor("#010509")
PANEL = colors.HexColor("#050d17")
WHITE = colors.HexColor("#fdfdfd")
TEXT = colors.HexColor("#ccd5dd")
MUTE = colors.HexColor("#9ba0a6")
BLUE = colors.HexColor("#0b8ded")
BLUE_LIGHT = colors.HexColor("#5fb4ff")
DEEP = colors.HexColor("#0b52b1")
LINE = colors.HexColor("#255073")
STXBG = colors.HexColor("#071a30")
YOUTUBE_NOTE = "Data via YouTube. Processed and evaluated by StatAxis."
HANDLE = "stataxis.org  |  x.com/stataxis"


# ---------------------------------------------------------------------------------------------- brand: the logo, drawn on every page as a watermark
LOGO_SVG = Path(__file__).resolve().parent.parent / "dashboard" / "assets" / "stataxis-logo-dark.svg"
LOGO_RATIO = 200 / 760
_LOGO_CACHE: dict[str, bytes] = {}


def _mupdf() -> Any:
    try:
        import pymupdf  # the current name of the module
        return pymupdf
    except ImportError:  # older releases call it fitz
        import fitz
        return fitz


def logo_png(*_ignored: Any, scale: float = 3.0, **_ignored_kw: Any) -> bytes:
    """The blue-and-gold StatAxis logo as a transparent PNG, drawn from the same SVG the workspace uses for its pictures."""
    key = f"{scale}"
    if key not in _LOGO_CACHE:
        fitz = _mupdf()  # PyMuPDF renders the SVG to pixels
        svg = LOGO_SVG.read_text(encoding="utf-8")   # MuPDF draws flat colours more reliably than gradients, so the gradients are replaced by the colour they average to
        for ref, flat in (("url(#ring)", "#1470d8"), ("url(#word)", "#1a85ec"), ("url(#arrow)", "#edc461")):
            svg = svg.replace(ref, flat)
        doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
        _LOGO_CACHE[key] = doc[0].get_pixmap(matrix=fitz.Matrix(scale * 760 / doc[0].rect.width, scale * 760 / doc[0].rect.width), alpha=True).tobytes("png")
    return _LOGO_CACHE[key]


def _watermark(canvas: Any, size: tuple[float, float] = A4) -> None:
    """The logo, faint and tilted, repeated over the whole page so a screenshot or a crop still carries it."""
    img = ImageReader(BytesIO(logo_png()))
    canvas.saveState()
    canvas.setFillAlpha(0.075)
    canvas.translate(size[0] / 2, size[1] / 2)
    canvas.rotate(32)
    w, h = 70 * mm, 70 * mm * LOGO_RATIO
    for row in range(-6, 7):
        for col in range(-5, 6):
            x = col * 105 * mm + (row % 2) * 52 * mm - w / 2
            y = row * 36 * mm - h / 2
            canvas.drawImage(img, x, y, w, h, mask="auto")
    canvas.restoreState()


def protect_pdf(pdf: bytes, title: str, owner_password: str | None = None, dpi: int = 170) -> bytes:
    """Make the report unreadable by machines: every page becomes a picture (there is no text to copy, search or parse), the file is encrypted so that only printing is allowed,
    and the properties say who made it. A person can still read, print and share it; a script cannot lift the numbers out of it."""
    fitz = _mupdf()
    src = fitz.open(stream=pdf, filetype="pdf")
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=pix.tobytes("jpeg", jpg_quality=84))
    out.set_metadata({"title": title, "author": "STATAXIS", "producer": "STATAXIS", "creator": "STATAXIS", "subject": "Branded report. Not for machine reading.", "keywords": ""})
    data = out.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=owner_password or secrets.token_urlsafe(24), user_pw="", permissions=fitz.PDF_PERM_PRINT, garbage=3, deflate=True)
    out.close()
    src.close()
    return data


def _n(value: Any) -> str:
    return "-" if value is None else f"{value:,.0f}" if isinstance(value, (int, float)) else str(value)


# ---------------------------------------------------------------------------------------------- Hindi and every other script
# reportlab's own fonts hold Western letters only; Devanagari (and Tamil, Arabic, emoji, arrows...) would print as black boxes. Text that Helvetica cannot write is therefore set by MuPDF, which shapes it
# correctly with its built-in Noto fonts, and placed on the page as a transparent picture. (The finished report is a set of page pictures anyway, so nothing readable is lost.)
def _plain_ok(text: str) -> bool:
    try:
        text.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _markup_text(markup: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", markup.replace("<br/>", " ")))


def _html(markup: str) -> str:
    """reportlab paragraph markup (<font color size>, <b>, <br/>) as the HTML MuPDF sets."""
    def font(m: re.Match[str]) -> str:
        attrs = m.group(1)
        color, size = re.search(r"color\s*=\s*['\"]?(#[0-9a-fA-F]{3,8})", attrs), re.search(r"size\s*=\s*['\"]?([0-9.]+)", attrs)
        return "<span style=\"" + (f"color:{color.group(1)};" if color else "") + (f"font-size:{size.group(1)}pt;" if size else "") + "\">"
    return re.sub(r"</font>", "</span>", re.sub(r"<font([^>]*)>", font, markup))


@lru_cache(maxsize=512)
def _shaped(html: str, size: float, leading: float, color: str, bold: bool, align: str, width: float | None) -> tuple[bytes, float, float]:
    """(PNG, width, height in points) of ``html`` set at ``size``; ``width`` None means as wide as the text is (up to 560 points)."""
    fitz = _mupdf()
    css = f"body{{margin:0;padding:0}}p{{margin:0;padding:0;font-family:sans-serif;font-size:{size}pt;line-height:{leading}pt;color:{color};text-align:{align};font-weight:{'700' if bold else '400'}}}"
    source = f"<p>{html}</p>"
    probe = fitz.Story(source, user_css=css)
    _more, filled_box = probe.place(fitz.Rect(0, 0, width or 560, 3000))
    filled = fitz.Rect(filled_box)
    w, h = float(width or max(2.0, filled.x1 + 1)), float(filled.y1 + 2)
    out = BytesIO()
    writer = fitz.DocumentWriter(out)
    story = fitz.Story(source, user_css=css)
    device = writer.begin_page(fitz.Rect(0, 0, w, h))
    story.place(fitz.Rect(0, 0, w, h))
    story.draw(device)
    writer.end_page()
    writer.close()
    page = fitz.open(stream=out.getvalue(), filetype="pdf")[0]
    return page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=True).tobytes("png"), w, h


def _hex(color: Any) -> str:
    return "#" + color.hexval()[2:]


class Shaped(Flowable):
    """Text that Helvetica cannot write, set by MuPDF and drawn as a picture that wraps to the width it is given."""

    def __init__(self, html: str, style: ParagraphStyle) -> None:
        super().__init__()
        self.html, self.style = html, style
        self.spaceBefore, self.spaceAfter, self.keepWithNext = style.spaceBefore, style.spaceAfter, getattr(style, "keepWithNext", 0)
        self._png, self._w, self._h = b"", 0.0, 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        st = self.style
        self._png, self._w, self._h = _shaped(self.html, st.fontSize, st.leading, _hex(st.textColor), "Bold" in st.fontName, ("right", "center", "left", "justify")[st.alignment] if st.alignment in (1, 2) else "left", float(avail_width))
        return self._w, self._h

    def draw(self) -> None:
        self.canv.drawImage(ImageReader(BytesIO(self._png)), 0, 0, self._w, self._h, mask="auto")


def _para(markup: str, style: ParagraphStyle) -> Any:
    """A paragraph that always shows every letter: a normal one when Helvetica can write the text, a shaped one when it cannot."""
    return Paragraph(markup, style) if _plain_ok(_markup_text(markup)) else Shaped(_html(markup), style)


def _cell(text: str, align: str = "left") -> Any:
    """A table cell: the plain string when Helvetica can write it (the table's own font is used), otherwise a shaped picture."""
    if _plain_ok(text):
        return text
    return Shaped(escape(text), ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10.5, textColor=TEXT, alignment=2 if align == "right" else 0))


def _put(canvas: Any, x: float, y: float, text: str, font: str, size: float, color: Any, right: bool = False) -> None:
    """canvas.drawString / drawRightString that also copes with text Helvetica cannot write."""
    canvas.setFillColor(color)
    if _plain_ok(text):
        canvas.setFont(font, size)
        (canvas.drawRightString if right else canvas.drawString)(x, y, text)
        return
    png, w, h = _shaped(escape(text), size, size * 1.2, _hex(color), "Bold" in font, "left", None)
    canvas.drawImage(ImageReader(BytesIO(png)), x - w if right else x, y - size * 0.3, w, h, mask="auto")


def _hours(r: dict[str, Any]) -> str:
    if r.get("whole_day"):
        return "Entire day (00:00-24:00) IST"
    if r.get("start_time"):
        return f"{r['start_time']}-{r['end_time']} IST"
    return f"{r['start_hour']:02d}:00-{r['end_hour']:02d}:00 IST"


def _dates(r: dict[str, Any]) -> str:
    def f(s: str) -> str:
        return datetime.fromisoformat(s).strftime("%d %b %Y").lstrip("0")
    return f(r["from"]) if r["from"] == r["to"] else f"{f(r['from'])} to {f(r['to'])}"


def report_title(r: dict[str, Any]) -> str:
    if r.get("kind") == "briefing":
        return r["title"]
    what = r["scope_label"] + (f" ({r['feed']} feeds)" if r.get("feed") else "")
    return f"{what}, {_hours(r)}"


def _clock_part(text: str) -> str:
    """09:00 -> 09, 09:30 -> 0930: a file name that stays short for whole hours and exact for minutes."""
    return text[:2] if text.endswith(":00") else text.replace(":", "")


def filename(r: dict[str, Any]) -> str:
    stamp = file_stamp()   # the download time is part of the name, so two downloads never overwrite each other
    if r.get("kind") == "briefing":
        return f"stataxis-briefing-{r['persona']}-{r['from']}-to-{r['to']}-downloaded-{stamp}.pdf"
    return f"stataxis-{r['scope']}-{r['from']}-to-{r['to']}-{_clock_part(r.get('start_time', f"{r['start_hour']:02d}:00"))}-{_clock_part(r.get('end_time', f"{r['end_hour']:02d}:00"))}-downloaded-{stamp}.pdf"


def _bars(rows: list[dict[str, Any]], key: str, width: float, label: str) -> Drawing:
    rows = rows[:10]
    row_h, left = 15, 120
    d = Drawing(width, 18 + row_h * len(rows))
    top = max((r[key] for r in rows), default=0) or 1
    d.add(String(0, 6 + row_h * len(rows), label, fontName="Helvetica-Bold", fontSize=8, fillColor=MUTE))
    for i, r in enumerate(rows):
        y = row_h * (len(rows) - 1 - i)
        w = (width - left - 60) * r[key] / top
        d.add(String(0, y + 4, str(r["name"])[:24].encode("cp1252", "replace").decode("cp1252"), fontName="Helvetica", fontSize=8, fillColor=TEXT))
        d.add(Rect(left, y + 1, max(w, 1), 10, fillColor=BLUE if i else BLUE_LIGHT, strokeColor=None))
        d.add(String(left + w + 4, y + 3, _n(r[key]), fontName="Helvetica-Bold", fontSize=8, fillColor=WHITE))
    return d


def _stx(x: Any) -> str:
    return "-" if not x else f"{x['score']:.1f}"


def _stx_banner(h: dict[str, Any] | None, width: float, period: str = "the last 7 days") -> Any:
    """The STX Index strip every report opens with: who leads, the average, how many channels have a score."""
    if not h:
        return Spacer(1, 0)
    big = ParagraphStyle("stxb", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=WHITE)
    small = ParagraphStyle("stxs", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTE)
    left = _para("<font color='#0b8ded'><b>STX INDEX</b></font>", big)
    mid = _para(f"Highest: <b>{escape(str(h['leader']))} - {h['leader_score']:.1f}</b>  |  Average of {h['scored']} scored channels: <b>{h['average']:.1f}</b>", big)
    note = _para(escape(f"STX is StatAxis's own 0-100 score for a channel, over {period}. A dash means not enough data."), small)
    t = Table([[left, mid], [note, ""]], colWidths=[28 * mm, width - 28 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, BLUE), ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("SPAN", (0, 1), (1, 1)), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _table(data: list[list[str]], widths: list[float], right_from: int = 2) -> Table:
    data = [[c if i == 0 else _cell(c, "right" if j >= right_from else "left") for j, c in enumerate(row)] for i, row in enumerate(data)]
    t = Table(data, colWidths=widths, repeatRows=1)
    stx_col = [i for i, h in enumerate(data[0]) if str(h).startswith("STX")]
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BG, PANEL]), ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        *[("BACKGROUND", (i, 1), (i, -1), STXBG) for i in stx_col], *[("FONT", (i, 1), (i, -1), "Helvetica-Bold", 10) for i in stx_col], *[("TEXTCOLOR", (i, 1), (i, -1), BLUE) for i in stx_col],
        ("BACKGROUND", (0, 0), (-1, 0), DEEP), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5), ("ALIGN", (right_from, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _decorate(canvas: Any, document: Any, downloaded: str, data_note: str, who: str) -> None:
    """The look every page of every report shares: the near-black page with the faint logo, the logo at the top, and a footer with the download time, the site and the X handle."""
    pw, ph = document.pagesize
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, pw, ph, stroke=0, fill=1)
    canvas.restoreState()
    _watermark(canvas, (pw, ph))
    canvas.saveState()
    lw = 52 * mm
    canvas.drawImage(ImageReader(BytesIO(logo_png(scale=2))), 16 * mm, ph - 6 * mm - lw * LOGO_RATIO, lw, lw * LOGO_RATIO, mask="auto")
    _put(canvas, pw - 16 * mm, ph - 11 * mm, "STAT THE VIEW. AXIS THE VIEWPOINT.", "Courier", 7.5, MUTE, right=True)
    _put(canvas, pw - 16 * mm, ph - 16 * mm, f"Downloaded {downloaded}", "Helvetica-Bold", 8, BLUE, right=True)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(16 * mm, ph - 20 * mm, pw - 16 * mm, ph - 20 * mm)
    _put(canvas, 16 * mm, 9 * mm, f"Downloaded {downloaded}{who}" + (f"  |  {data_note}" if data_note else ""), "Helvetica", 7.5, MUTE)
    _put(canvas, 16 * mm, 5.5 * mm, YOUTUBE_NOTE + "  |  " + HANDLE, "Helvetica", 6.8, MUTE)
    _put(canvas, pw - 16 * mm, 9 * mm, f"Page {document.page}", "Helvetica", 7.5, BLUE, right=True)
    canvas.line(16 * mm, 13 * mm, pw - 16 * mm, 13 * mm)
    canvas.restoreState()


def _nm(x: dict[str, Any], with_group: bool) -> str:
    return (x["name"][:34] + (f" ({x['group']})" if with_group and x.get("group") else ""))[:60]


def report_pdf(r: dict[str, Any], protect: bool = True) -> bytes:
    buf = BytesIO()
    downloaded = ist_stamp()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=28 * mm, bottomMargin=18 * mm, title=report_title(r), author="STAXIS")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=WHITE, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=BLUE, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=TEXT)
    story: list[Any] = []
    filters = r.get("filters") or {}
    story.append(_para(escape(report_title(r).upper()), h1))
    story.append(_para(escape(f"{_dates(r)}  |  Indian time  |  " + ("" if r.get("kind") == "briefing" else f"Genre: {r['genre'] or 'all genres'}  |  ") + f"Language: {filters.get('language') or 'all'}  |  Group: {filters.get('segment') or 'all'}"), body))
    try:
        as_of = ist_stamp(datetime.fromisoformat(r["generated_at"]))
    except (KeyError, TypeError, ValueError):
        as_of = downloaded
    story.append(_para(f"<font color='#0b8ded'><b>Downloaded {escape(downloaded)}</b></font>  |  Data as of {escape(as_of)}", body))
    story.append(Spacer(1, 8))
    width = A4[0] - 32 * mm
    rows = r["rows"]
    groups = not (r.get("filters") or {}).get("segment")   # with every category chosen, a channel is shown with its group (language and category)
    if r.get("stx"):
        story.append(_stx_banner(r["stx"], width))
        story.append(Spacer(1, 8))
    if r.get("kind") == "briefing":
        b = r["briefing"]
        kp = [[_para(f"<font size=15 color='#fdfdfd'><b>{escape(str(k['value']))}</b></font><br/><font size=7.5 color='#9ba0a6'>{escape(k['label'])}<br/>{escape(k['detail'])}</font>", body) for k in b["kpis"]]]
        if kp[0]:
            t = Table(kp, colWidths=[width / len(kp[0])] * len(kp[0]))
            t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
            story.append(t)
        story.append(_para("What the data shows, and what it means for you", h2))
        if not b["findings"]:
            story.append(_para(escape(b.get("note") or "No findings."), body))
        small = ParagraphStyle("sm", parent=body, fontSize=7.8, leading=10, textColor=MUTE)
        head3 = ParagraphStyle("h3", parent=body, fontName="Helvetica-Bold", fontSize=10.2, leading=13, textColor=WHITE, spaceBefore=6)
        for n, f in enumerate(b["findings"], start=1):
            ev = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in f["evidence"].items() if isinstance(v, (int, float, str)) and v not in ("", None))[:230]
            story.append(_para(escape(f"{n}. {f['headline']}"), head3))
            story.append(_para(escape(f["detail"]), body))
            story.append(_para(f"<font color='#0b8ded'><b>For you:</b></font> {escape(f['so_what'])}", body))
            story.append(_para(escape(f"Confidence: {f['confidence']}  |  Evidence: {ev}"), small))
        story.append(_para("Where to look next", h2))
        story.append(_para(escape("  |  ".join(x["label"] for x in b["recommended"])), body))
    elif not rows:
        story.append(_para("No channel was measured in these hours on these days with these filters. Nothing is estimated, so there is nothing to show.", body))
    elif r["kind"] == "audience":
        story.append(_bars(rows, "average", width, "Average concurrent viewers (top 10)"))
        story.append(Spacer(1, 8))
        data = [["#", "Channel", "STX Index", "Average", "Peak", "Share %", "Days seen"]] + [[str(x["rank"]), _nm(x, groups), _stx(x.get("stx")), _n(x["average"]), _n(x["peak"]), _n(x["share_percent"]), str(x["days_seen"])] for x in rows]
        story.append(_table(data, [9 * mm, 58 * mm, 22 * mm, 22 * mm, 22 * mm, 20 * mm, 20 * mm], right_from=2))
    else:
        story.append(_bars(rows, "views", width, "Views gained in the chosen hours (top 10)"))
        story.append(Spacer(1, 8))
        data = [["#", "Channel", "STX Index", "Views gained", "Share %", "Videos", "New uploads"]] + [[str(x["rank"]), _nm(x, groups), _stx(x.get("stx")), _n(x["views"]), _n(x["share_percent"]), _n(x["videos"]), _n(x["uploads"])] for x in rows]
        story.append(_table(data, [9 * mm, 58 * mm, 22 * mm, 26 * mm, 20 * mm, 18 * mm, 21 * mm], right_from=2))
    for d in r.get("by_day") or []:
        label = datetime.fromisoformat(d["date"]).strftime("%A, %d %b %Y").replace(" 0", " ")
        story.append(_para(escape(f"{label}, {d['from_time']}-{d['to_time']} IST" + (" (so far)" if d.get("partial") else "")), h2))
        if not d["rows"]:
            story.append(_para("No channel was measured on this day.", body))
        elif r["kind"] == "audience":
            data = [["#", "Channel", "STX Index", "Average", "Peak", "Share %"]] + [[str(x["rank"]), _nm(x, groups), _stx(x.get("stx")), _n(x["average"]), _n(x["peak"]), _n(x["share_percent"])] for x in d["rows"][:20]]
            story.append(_table(data, [10 * mm, 66 * mm, 24 * mm, 26 * mm, 26 * mm, 22 * mm]))
        else:
            data = [["#", "Channel", "STX Index", "Views gained", "Share %"]] + [[str(x["rank"]), _nm(x, groups), _stx(x.get("stx")), _n(x["views"]), _n(x["share_percent"])] for x in d["rows"][:20]]
            story.append(_table(data, [10 * mm, 76 * mm, 26 * mm, 30 * mm, 24 * mm]))
    for g in r.get("by_genre") or []:
        story.append(_para(escape(f"Genre: {g['genre']}"), h2))
        if r["kind"] == "audience":
            data = [["#", "Channel", "Average", "Peak"]] + [[str(x["rank"]), _nm(x, groups), _n(x["average"]), _n(x["peak"])] for x in g["rows"][:5]]
            story.append(_table(data, [10 * mm, 90 * mm, 30 * mm, 30 * mm]))
        else:
            data = [["#", "Channel", "Views gained", "Share %"]] + [[str(x["rank"]), _nm(x, groups), _n(x["views"]), _n(x["share_percent"])] for x in g["rows"][:5]]
            story.append(_table(data, [10 * mm, 90 * mm, 30 * mm, 30 * mm]))
    story.append(_para("How these numbers were worked out", h2))
    story.append(_para(escape(r["method"]), body))
    cov = r.get("coverage") or {}
    if r["kind"] == "briefing":
        pass
    elif r["kind"] == "views" and cov.get("videos_matching"):
        story.append(Spacer(1, 4))
        story.append(_para(escape(f"Coverage: {cov['videos_measured_at_both_ends']} of {cov['videos_matching']} matching videos were measured at both ends of the window ({cov['percent_measured']}%); {cov['videos_left_out']} were left out."), body))
    elif r["kind"] == "audience":
        story.append(Spacer(1, 4))
        story.append(_para(escape(f"Coverage: {cov.get('channels_seen_live', 0)} channels were seen live in these hours over {cov.get('days_requested', 0)} day(s)."), body))
    story.append(Spacer(1, 4))
    story.append(_para("Measured by STAXIS from public YouTube data. This is not TV ratings and not a statement about who watched; audiences of different channels overlap by an amount that is not visible here.", body))

    who = f" for {r['prepared_for']}" if r.get("prepared_for") else ""

    def page(canvas: Any, document: Any) -> None:
        _decorate(canvas, document, downloaded, f"Data as of {as_of}", who)

    doc.build(story, onFirstPage=page, onLaterPages=page)
    data = buf.getvalue()
    return protect_pdf(data, report_title(r)) if protect else data


# ---------------------------------------------------------------------------------------------- a report of any screen
MAX_BLOCKS, MAX_ROWS, MAX_COLS, MAX_IMAGES = 700, 500, 14, 4
_FREE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _txt(value: Any, limit: int) -> str:
    return _FREE.sub("", value if isinstance(value, str) else ("" if value is None else str(value))).strip()[:limit]


def clean_screen(payload: dict[str, Any]) -> dict[str, Any]:
    """Check what the browser sent for a screen report and keep only what a report can hold: headings, text, tables and pictures, with sizes capped."""
    blocks_in = payload.get("blocks")
    if not isinstance(blocks_in, list) or not blocks_in:
        raise ValueError("there is nothing on this screen to put in a report yet")
    blocks: list[dict[str, Any]] = []
    images = 0
    for b in blocks_in[:MAX_BLOCKS]:
        if not isinstance(b, dict):
            continue
        kind = b.get("t")
        if kind in ("h", "p"):
            text = _txt(b.get("text"), 1400)
            if text:
                blocks.append({"t": kind, "text": text})
        elif kind == "table":
            head = [_txt(c, 60) for c in (b.get("head") or [])[:MAX_COLS]] if isinstance(b.get("head"), list) else []
            rows = []
            for row in (b.get("rows") or [])[:MAX_ROWS] if isinstance(b.get("rows"), list) else []:
                if isinstance(row, list):
                    rows.append([_txt(c, 160) for c in row[:MAX_COLS]])
            width = max([len(head)] + [len(r) for r in rows] or [0])
            if width:
                head = (head + [""] * width)[:width]
                blocks.append({"t": "table", "head": head, "rows": [(r + [""] * width)[:width] for r in rows], "cut": bool(b.get("cut")) or len(b.get("rows") or []) > MAX_ROWS})
        elif kind == "img" and images < MAX_IMAGES:
            raw = b.get("data")
            if isinstance(raw, str) and raw.startswith("data:image/png;base64,") and len(raw) < 700_000:
                try:
                    blocks.append({"t": "img", "bytes": base64.b64decode(raw.split(",", 1)[1], validate=True), "alt": _txt(b.get("alt"), 120)})
                    images += 1
                except (binascii.Error, ValueError):
                    continue
    if not blocks:
        raise ValueError("there is nothing on this screen to put in a report yet")
    return {"title": _txt(payload.get("title"), 140) or "Workspace screen", "filters": _txt(payload.get("filters"), 400), "view": re.sub(r"[^a-z0-9-]", "", _txt(payload.get("view"), 40).lower()) or "screen", "blocks": blocks}


def screen_filename(screen: dict[str, Any]) -> str:
    return f"stataxis-{screen['view']}-downloaded-{file_stamp()}.pdf"


def screen_pdf(screen: dict[str, Any], prepared_for: str | None = None, protect: bool = True) -> bytes:
    """A branded report of the screen a person is looking at: what they see (headings, figures, tables, pictures) on the StatAxis letterhead, with the time it was downloaded on every page."""
    downloaded = ist_stamp()
    wide = any(b["t"] == "table" and len(b["head"]) > 7 for b in screen["blocks"])
    size = (A4[1], A4[0]) if wide else A4
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=28 * mm, bottomMargin=18 * mm, title=screen["title"], author="STAXIS")
    width = size[0] - 32 * mm
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=WHITE, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=BLUE, spaceBefore=10, spaceAfter=4, keepWithNext=1)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12, textColor=TEXT, spaceAfter=2)
    muted = ParagraphStyle("m", parent=body, fontSize=8, leading=10.5, textColor=MUTE)
    cell = ParagraphStyle("c", parent=body, fontSize=7.6, leading=9.4, spaceAfter=0)
    cellh = ParagraphStyle("ch", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    story: list[Any] = [_para(escape(screen["title"].upper()), h1),
                        _para(f"<font color='#0b8ded'><b>Downloaded {escape(downloaded)}</b></font>" + (f"  |  {escape(screen['filters'])}" if screen["filters"] else ""), muted), Spacer(1, 8)]
    for b in screen["blocks"]:
        if b["t"] == "h":
            story.append(_para(escape(b["text"]), h2))
        elif b["t"] == "p":
            story.append(_para(escape(b["text"]), body))
        elif b["t"] == "img":
            try:
                img = ImageReader(BytesIO(b["bytes"]))
                iw, ih = img.getSize()
                w = min(width, iw * 0.264583 * mm / 1.0)   # 96 dpi picture pixels to millimetres
                story.append(Spacer(1, 4))
                story.append(Image(BytesIO(b["bytes"]), width=w, height=w * ih / iw))
            except Exception:   # a picture that cannot be read is left out; the figures stay
                continue
        else:
            cols = len(b["head"])
            weight = [max(4, min(34, max([len(b["head"][i])] + [len(r[i]) for r in b["rows"][:60]]))) for i in range(cols)]
            total = float(sum(weight))
            widths = [width * w / total for w in weight]
            data = [[_para(escape(c), cellh) for c in b["head"]]] + [[_para(escape(c), cell) for c in r] for r in b["rows"]]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DEEP), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BG, PANEL]),
                                   ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
            story.append(Spacer(1, 3))
            story.append(t)
            if b.get("cut"):
                story.append(_para(f"The first {MAX_ROWS} rows are shown here; the screen has more.", muted))
            story.append(Spacer(1, 4))
    story.append(Spacer(1, 8))
    story.append(_para(escape("This report shows the screen as it was on the screen when it was downloaded. Measured by STAXIS from public YouTube data. This is not TV ratings and not a statement about who watched."), muted))
    who = f" for {prepared_for}" if prepared_for else ""

    def page(canvas: Any, document: Any) -> None:
        _decorate(canvas, document, downloaded, "Screen report", who)

    doc.build(story, onFirstPage=page, onLaterPages=page)
    data = buf.getvalue()
    return protect_pdf(data, screen["title"]) if protect else data
