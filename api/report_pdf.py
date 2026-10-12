"""Turns a built report (api/report_builder.py) into a PDF a person can download and share straight away."""

from __future__ import annotations

import base64
import binascii
import re
import secrets
from datetime import datetime
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from api.stamps import file_stamp, ist_stamp

NAVY = colors.HexColor("#061322")
BLUE = colors.HexColor("#159de8")
GOLD = colors.HexColor("#b8923a")
GREY = colors.HexColor("#5b6b7b")
LINE = colors.HexColor("#d5dde5")
BAND = colors.HexColor("#eef3f7")


# ---------------------------------------------------------------------------------------------- brand: the logo, drawn on every page as a watermark
_MARK = ('<circle cx="68" cy="58" r="48" fill="none" stroke="{ring}" stroke-width="18"/><path d="M38 74l27-27 17 15 35-35" fill="none" stroke="{ink}" stroke-width="12" stroke-linecap="square"/>'
         '<path d="M103 26h20v20" fill="none" stroke="{ink}" stroke-width="12"/><line x1="139" y1="10" x2="139" y2="112" stroke="{gold}" stroke-width="2"/>')
_WORD = '<text x="164" y="66" font-family="Helvetica,Arial,sans-serif" font-size="52" font-weight="700" letter-spacing="3" fill="{ink}">STATAXIS</text>'
_LOGO_CACHE: dict[str, bytes] = {}


def _mupdf() -> Any:
    try:
        import pymupdf  # the current name of the module
        return pymupdf
    except ImportError:  # older releases call it fitz
        import fitz
        return fitz


def logo_png(ring: str = "#5f7f9c", ink: str = "#061322", gold: str = "#b8923a", words: bool = True, scale: float = 3.0) -> bytes:
    """The StatAxis mark (and name) as a transparent PNG in the given colours; drawn from the same shapes as the site logo."""
    key = f"{ring}{ink}{gold}{words}{scale}"
    if key not in _LOGO_CACHE:
        fitz = _mupdf()  # PyMuPDF renders the SVG to pixels
        width = 520 if words else 150
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 124" width="{width}" height="124">' + _MARK.format(ring=ring, ink=ink, gold=gold) + (_WORD.format(ink=ink) if words else "") + "</svg>"
        doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
        _LOGO_CACHE[key] = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True).tobytes("png")
    return _LOGO_CACHE[key]


def _watermark(canvas: Any, size: tuple[float, float] = A4) -> None:
    """The logo, faint and tilted, repeated over the whole page so a screenshot or a crop still carries it."""
    img = ImageReader(BytesIO(logo_png()))
    canvas.saveState()
    canvas.setFillAlpha(0.075)
    canvas.translate(size[0] / 2, size[1] / 2)
    canvas.rotate(32)
    w, h = 70 * mm, 70 * mm * 124 / 520
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


def _hours(r: dict[str, Any]) -> str:
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


def filename(r: dict[str, Any]) -> str:
    stamp = file_stamp()   # the download time is part of the name, so two downloads never overwrite each other
    if r.get("kind") == "briefing":
        return f"stataxis-briefing-{r['persona']}-{r['from']}-to-{r['to']}-downloaded-{stamp}.pdf"
    return f"stataxis-{r['scope']}-{r['from']}-to-{r['to']}-{r['start_hour']:02d}-{r['end_hour']:02d}-downloaded-{stamp}.pdf"


def _bars(rows: list[dict[str, Any]], key: str, width: float, label: str) -> Drawing:
    rows = rows[:10]
    row_h, left = 15, 120
    d = Drawing(width, 18 + row_h * len(rows))
    top = max((r[key] for r in rows), default=0) or 1
    d.add(String(0, 6 + row_h * len(rows), label, fontName="Helvetica-Bold", fontSize=8, fillColor=GREY))
    for i, r in enumerate(rows):
        y = row_h * (len(rows) - 1 - i)
        w = (width - left - 60) * r[key] / top
        d.add(String(0, y + 4, str(r["name"])[:24], fontName="Helvetica", fontSize=8, fillColor=NAVY))
        d.add(Rect(left, y + 1, max(w, 1), 10, fillColor=BLUE if i else GOLD, strokeColor=None))
        d.add(String(left + w + 4, y + 3, _n(r[key]), fontName="Helvetica-Bold", fontSize=8, fillColor=NAVY))
    return d


def _table(data: list[list[str]], widths: list[float], right_from: int = 2) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5), ("ALIGN", (right_from, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]), ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _decorate(canvas: Any, document: Any, downloaded: str, data_note: str, who: str) -> None:
    """The look every page of every report shares: watermark, the navy band with the mark, and a footer that says when it was downloaded."""
    pw, ph = document.pagesize
    _watermark(canvas, (pw, ph))
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, ph - 16 * mm, pw, 16 * mm, stroke=0, fill=1)
    canvas.drawImage(ImageReader(BytesIO(logo_png(ring="#e8f0f8", ink="#e8f0f8", gold="#e1b94f", words=False, scale=2))), 16 * mm, ph - 14 * mm, 12 * mm, 12 * 124 / 150 * mm, mask="auto")
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(31 * mm, ph - 10.5 * mm, "STATAXIS")
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(pw - 16 * mm, ph - 7.5 * mm, "Digital Media Intelligence")
    canvas.setFillColor(colors.HexColor("#e1b94f"))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawRightString(pw - 16 * mm, ph - 12 * mm, f"Downloaded {downloaded}")
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(16 * mm, 9 * mm, f"Downloaded {downloaded}{who}" + (f"  |  {data_note}" if data_note else "") + "  |  STATAXIS - Stat the View. Axis the Viewpoint.")
    canvas.drawRightString(pw - 16 * mm, 9 * mm, f"Page {document.page}")
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.6)
    canvas.line(16 * mm, 13 * mm, pw - 16 * mm, 13 * mm)
    canvas.restoreState()


def report_pdf(r: dict[str, Any], protect: bool = True) -> bytes:
    buf = BytesIO()
    downloaded = ist_stamp()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=26 * mm, bottomMargin=18 * mm, title=report_title(r), author="STAXIS")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=NAVY, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=GREY)
    story: list[Any] = []
    filters = r.get("filters") or {}
    story.append(Paragraph(escape(report_title(r)), h1))
    story.append(Paragraph(escape(f"{_dates(r)}  |  Indian time  |  " + ("" if r.get("kind") == "briefing" else f"Genre: {r['genre'] or 'all genres'}  |  ") + f"Language: {filters.get('language') or 'all'}  |  Group: {filters.get('segment') or 'all'}"), body))
    try:
        as_of = ist_stamp(datetime.fromisoformat(r["generated_at"]))
    except (KeyError, TypeError, ValueError):
        as_of = downloaded
    story.append(Paragraph(f"<font color='#b8923a'><b>Downloaded {escape(downloaded)}</b></font>  |  Data as of {escape(as_of)}", body))
    story.append(Spacer(1, 8))
    width = A4[0] - 32 * mm
    rows = r["rows"]
    if r.get("kind") == "briefing":
        b = r["briefing"]
        kp = [[Paragraph(f"<font size=15 color='#061322'><b>{escape(str(k['value']))}</b></font><br/><font size=7.5 color='#5b6b7b'>{escape(k['label'])}<br/>{escape(k['detail'])}</font>", body) for k in b["kpis"]]]
        if kp[0]:
            t = Table(kp, colWidths=[width / len(kp[0])] * len(kp[0]))
            t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, -1), BAND), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
            story.append(t)
        story.append(Paragraph("What the data shows, and what it means for you", h2))
        if not b["findings"]:
            story.append(Paragraph(escape(b.get("note") or "No findings."), body))
        small = ParagraphStyle("sm", parent=body, fontSize=7.8, leading=10, textColor=GREY)
        head3 = ParagraphStyle("h3", parent=body, fontName="Helvetica-Bold", fontSize=10.2, leading=13, textColor=NAVY, spaceBefore=6)
        for n, f in enumerate(b["findings"], start=1):
            ev = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in f["evidence"].items() if isinstance(v, (int, float, str)) and v not in ("", None))[:230]
            story.append(Paragraph(escape(f"{n}. {f['headline']}"), head3))
            story.append(Paragraph(escape(f["detail"]), body))
            story.append(Paragraph(f"<font color='#b8923a'><b>For you:</b></font> {escape(f['so_what'])}", body))
            story.append(Paragraph(escape(f"Confidence: {f['confidence']}  |  Evidence: {ev}"), small))
        story.append(Paragraph("Where to look next", h2))
        story.append(Paragraph(escape("  |  ".join(x["label"] for x in b["recommended"])), body))
    elif not rows:
        story.append(Paragraph("No channel was measured in these hours on these days with these filters. Nothing is estimated, so there is nothing to show.", body))
    elif r["kind"] == "audience":
        story.append(_bars(rows, "average", width, "Average concurrent viewers (top 10)"))
        story.append(Spacer(1, 8))
        data = [["#", "Channel", "Average", "Peak", "Share %", "Days seen"]] + [[str(x["rank"]), x["name"][:34], _n(x["average"]), _n(x["peak"]), _n(x["share_percent"]), str(x["days_seen"])] for x in rows]
        story.append(_table(data, [10 * mm, 70 * mm, 24 * mm, 24 * mm, 20 * mm, 20 * mm]))
    else:
        story.append(_bars(rows, "views", width, "Views gained in the chosen hours (top 10)"))
        story.append(Spacer(1, 8))
        data = [["#", "Channel", "Views gained", "Share %", "Videos", "New uploads"]] + [[str(x["rank"]), x["name"][:34], _n(x["views"]), _n(x["share_percent"]), _n(x["videos"]), _n(x["uploads"])] for x in rows]
        story.append(_table(data, [10 * mm, 70 * mm, 28 * mm, 20 * mm, 20 * mm, 20 * mm]))
    for g in r.get("by_genre") or []:
        story.append(Paragraph(escape(f"Genre: {g['genre']}"), h2))
        if r["kind"] == "audience":
            data = [["#", "Channel", "Average", "Peak"]] + [[str(x["rank"]), x["name"][:34], _n(x["average"]), _n(x["peak"])] for x in g["rows"][:5]]
            story.append(_table(data, [10 * mm, 90 * mm, 30 * mm, 30 * mm]))
        else:
            data = [["#", "Channel", "Views gained", "Share %"]] + [[str(x["rank"]), x["name"][:34], _n(x["views"]), _n(x["share_percent"])] for x in g["rows"][:5]]
            story.append(_table(data, [10 * mm, 90 * mm, 30 * mm, 30 * mm]))
    story.append(Paragraph("How these numbers were worked out", h2))
    story.append(Paragraph(escape(r["method"]), body))
    cov = r.get("coverage") or {}
    if r["kind"] == "briefing":
        pass
    elif r["kind"] == "views" and cov.get("videos_matching"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(escape(f"Coverage: {cov['videos_measured_at_both_ends']} of {cov['videos_matching']} matching videos were measured at both ends of the window ({cov['percent_measured']}%); {cov['videos_left_out']} were left out."), body))
    elif r["kind"] == "audience":
        story.append(Spacer(1, 4))
        story.append(Paragraph(escape(f"Coverage: {cov.get('channels_seen_live', 0)} channels were seen live in these hours over {cov.get('days_requested', 0)} day(s)."), body))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Measured by STAXIS from public YouTube data. This is not TV ratings and not a statement about who watched; audiences of different channels overlap by an amount that is not visible here.", body))

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
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=26 * mm, bottomMargin=18 * mm, title=screen["title"], author="STAXIS")
    width = size[0] - 32 * mm
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=NAVY, spaceBefore=10, spaceAfter=4, keepWithNext=1)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12, textColor=colors.HexColor("#2b3a49"), spaceAfter=2)
    muted = ParagraphStyle("m", parent=body, fontSize=8, leading=10.5, textColor=GREY)
    cell = ParagraphStyle("c", parent=body, fontSize=7.6, leading=9.4, spaceAfter=0)
    cellh = ParagraphStyle("ch", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    story: list[Any] = [Paragraph(escape(screen["title"]), h1),
                        Paragraph(f"<font color='#b8923a'><b>Downloaded {escape(downloaded)}</b></font>" + (f"  |  {escape(screen['filters'])}" if screen["filters"] else ""), muted), Spacer(1, 8)]
    for b in screen["blocks"]:
        if b["t"] == "h":
            story.append(Paragraph(escape(b["text"]), h2))
        elif b["t"] == "p":
            story.append(Paragraph(escape(b["text"]), body))
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
            data = [[Paragraph(escape(c), cellh) for c in b["head"]]] + [[Paragraph(escape(c), cell) for c in r] for r in b["rows"]]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
                                   ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
            story.append(Spacer(1, 3))
            story.append(t)
            if b.get("cut"):
                story.append(Paragraph(f"The first {MAX_ROWS} rows are shown here; the screen has more.", muted))
            story.append(Spacer(1, 4))
    story.append(Spacer(1, 8))
    story.append(Paragraph(escape("This report shows the screen as it was on the screen when it was downloaded. Measured by STAXIS from public YouTube data. This is not TV ratings and not a statement about who watched."), muted))
    who = f" for {prepared_for}" if prepared_for else ""

    def page(canvas: Any, document: Any) -> None:
        _decorate(canvas, document, downloaded, "Screen report", who)

    doc.build(story, onFirstPage=page, onLaterPages=page)
    data = buf.getvalue()
    return protect_pdf(data, screen["title"]) if protect else data
