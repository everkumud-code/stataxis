"""The user manual as a PDF, in the StatAxis design (design/reference.png), made from the very page people read on the site (dashboard/manual.html) so the two cannot say different things.
The parts of the page that the browser fills in from the methodology (the STX and IFX tables and bars) are filled in here from the same code. The calculator stays on the web page.
Unlike the report PDFs this one keeps real, selectable text: it is a document to read and search, not a set of figures."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents

from api.methodology import VERSION, methodology
from api.report_pdf import BG, BLUE, BLUE_LIGHT, DEEP, HANDLE, LINE, MUTE, PANEL, TEXT, WHITE, YOUTUBE_NOTE, _decorate, _para
from api.stamps import file_stamp, ist_stamp

PAGE = Path(__file__).resolve().parent.parent / "dashboard" / "manual.html"
BASE = "https://www.stataxis.org"
STX_NAMES = {"audience": "Audience", "growth": "Growth", "momentum": "Momentum", "acceleration": "Acceleration", "consistency": "Consistency", "competitive_position": "Competition", "anomaly_event": "Anomaly or event"}
IFX_PILLARS = {"impact": "Impact", "followership": "Followership", "exposure": "eXposure"}
VOID = {"br", "hr", "img", "input", "meta", "link"}


class Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None") -> None:
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []   # kids: Node or str

    def cls(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag: str, attrs: list) -> None:
        n = Node(tag, {k: v or "" for k, v in attrs}, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag: str) -> None:
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data: str) -> None:
        self.cur.kids.append(data)


def _find(node: Node, pred) -> "Node | None":
    for k in node.kids:
        if isinstance(k, Node):
            if pred(k):
                return k
            hit = _find(k, pred)
            if hit:
                return hit
    return None


def _inline(node: Node) -> str:
    """The text of a node as reportlab paragraph markup: bold stays bold, a link keeps its words, everything else is plain text."""
    out = []
    for k in node.kids:
        if isinstance(k, str):
            out.append(escape(re.sub(r"\s+", " ", k)))
        elif k.tag in ("b", "strong"):
            out.append("<b><font color='#fdfdfd'>" + _inline(k) + "</font></b>")
        elif k.tag in ("i", "em"):
            out.append("<i>" + _inline(k) + "</i>")
        elif k.tag == "a":
            href = k.attrs.get("href", "")
            inner = _inline(k)
            out.append(f"<a href='{escape(BASE + href if href.startswith('/') else href)}'><font color='#5fb4ff'><u>{inner}</u></font></a>" if href and not href.startswith("#") else inner)
        elif k.tag == "br":
            out.append("<br/>")
        elif k.tag in ("button",):
            continue
        else:
            out.append(_inline(k))
    return "".join(out).replace("−", "-")


def _plain(node: Node) -> str:
    return re.sub(r"\s+", " ", unescape("".join(k if isinstance(k, str) else _plain(k) for k in node.kids))).strip().replace("−", "-")


class ManualDoc(SimpleDocTemplate):
    def afterFlowable(self, flowable: Any) -> None:
        if isinstance(flowable, Paragraph) and flowable.style.name == "h2":
            text = re.sub(r"<[^>]+>", "", flowable.text)
            self.notify("TOCEntry", (0, text, self.page))


def _styles() -> dict[str, ParagraphStyle]:
    ss = getSampleStyleSheet()
    return {
        "label": ParagraphStyle("label", fontName="Courier", fontSize=8, leading=11, textColor=MUTE, spaceAfter=6),
        "title": ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=34, leading=38, textColor=WHITE, alignment=0, spaceAfter=8),
        "serif": ParagraphStyle("serif", fontName="Times-Italic", fontSize=15, leading=20, textColor=BLUE_LIGHT, spaceAfter=10),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=BLUE, spaceBefore=16, spaceAfter=6, keepWithNext=1),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=13.5, textColor=WHITE, spaceBefore=9, spaceAfter=3, keepWithNext=1),
        "p": ParagraphStyle("p", fontName="Helvetica", fontSize=9, leading=13, textColor=TEXT, spaceAfter=5),
        "li": ParagraphStyle("li", fontName="Helvetica", fontSize=9, leading=13, textColor=TEXT, leftIndent=12, bulletIndent=2, spaceAfter=2.5),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10.4, textColor=TEXT),
        "cellh": ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=8, leading=10.4, textColor=WHITE),
        "mono": ParagraphStyle("mono", fontName="Courier", fontSize=8.2, leading=11, textColor=WHITE),
        "q": ParagraphStyle("q", fontName="Helvetica-Bold", fontSize=9.2, leading=12.5, textColor=WHITE, spaceBefore=7, spaceAfter=1.5, keepWithNext=1),
        "toc0": ParagraphStyle("toc0", fontName="Helvetica", fontSize=10, leading=17, textColor=TEXT, leftIndent=0, rightIndent=0),
    }


def _panel(inner: list[Any], width: float, bar: bool = False) -> Table:
    t = Table([[inner]], colWidths=[width])
    style = [("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9)]
    if bar:
        style.append(("LINEBEFORE", (0, 0), (0, -1), 2.2, colors.HexColor("#c9a227")))
    t.setStyle(TableStyle(style))
    return t


def _bars(rows: list[tuple[str, float]], width: float, scale: float) -> Drawing:
    h = 15 * len(rows) + 4
    d = Drawing(width, h)
    for i, (name, value) in enumerate(rows):
        y = h - 15 * (i + 1)
        d.add(String(0, y + 3, name, fontName="Helvetica", fontSize=8, fillColor=TEXT))
        d.add(Rect(95, y + 1, (width - 150) * min(1, value / scale), 8, fillColor=BLUE, strokeColor=None))
        d.add(String(width - 4, y + 3, f"{round(value * 100)}%", fontName="Helvetica-Bold", fontSize=8, fillColor=WHITE, textAnchor="end"))
    return d


def _table(node: Node, st: dict[str, ParagraphStyle], width: float, fill: list[list[str]] | None = None) -> Any:
    rows: list[list[Any]] = []
    carry: dict[int, int] = {}
    for tr in [k for k in _all(node, "tr")]:
        cells = [c for c in tr.kids if isinstance(c, Node) and c.tag in ("td", "th")]
        row, col, ci = [], 0, 0
        while ci < len(cells) or col in carry:
            if col in carry:
                carry[col] -= 1
                if carry[col] <= 0:
                    del carry[col]
                row.append("")
                col += 1
                continue
            c = cells[ci]
            ci += 1
            span = int(c.attrs.get("rowspan") or 1)
            if span > 1:
                carry[col] = span - 1
            row.append(Paragraph(_inline(c), st["cellh"] if c.tag == "th" else st["cell"]))
            col += 1
        rows.append(row)
    if fill is not None:
        rows = rows[:1] + [[Paragraph(escape(str(x)), st["cellh"] if j == 0 else st["cell"]) for j, x in enumerate(r)] for r in fill]
    if not rows:
        return Spacer(1, 1)
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lens = [max(8, min(60, sum(len(re.sub(r"<[^>]+>", "", c.text if isinstance(c, Paragraph) else str(c))) for c in col) / max(1, len(col)))) for col in zip(*rows)]
    total = sum(lens)
    t = Table(rows, colWidths=[width * x / total for x in lens], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), STXBG_), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    return t


STXBG_ = colors.HexColor("#071a30")


def _all(node: Node, tag: str) -> list[Node]:
    out = []
    for k in node.kids:
        if isinstance(k, Node):
            if k.tag == tag:
                out.append(k)
            elif k.tag not in ("table",) or tag == "table":
                out.extend(_all(k, tag))
    return out


def _list(node: Node, st: dict[str, ParagraphStyle]) -> list[Any]:
    items = []
    ordered = node.tag == "ol"
    for n, li in enumerate([k for k in node.kids if isinstance(k, Node) and k.tag == "li"], 1):
        items.append(Paragraph(_inline(li), st["li"], bulletText=f"{n}." if ordered else "•"))
    return items


def _blocks(node: Node, st: dict[str, ParagraphStyle], width: float, m: dict[str, Any]) -> list[Any]:
    out: list[Any] = []
    for k in node.kids:
        if not isinstance(k, Node):
            continue
        c = k.cls()
        if k.tag == "nav" or "btnrow" in c or "calc" in c or k.tag == "button":
            if "calc" in c:
                out.append(_panel([Paragraph("<font color='#5fb4ff'><b>Try it yourself.</b></font> The web version of this manual has a calculator: type the signals you have, leave a box empty if it could not be worked out, and it shows the STX, the confidence and the shown score. Open <font color='#5fb4ff'><u>stataxis.org/manual</u></font>.", st["p"])], width, bar=True))
            continue
        if k.tag == "span" and "sx-kicker" in c:
            continue
        if k.tag == "h1":
            continue
        if k.tag == "h2":
            out.append(Paragraph(_inline(k).upper(), st["h2"]))
        elif k.tag == "h3":
            out.append(Paragraph(_inline(k), st["h3"]))
        elif k.tag == "p":
            out.append(Paragraph(_inline(k), st["p"]))
        elif k.tag in ("ul", "ol"):
            out.extend(_list(k, st))
            out.append(Spacer(1, 3))
        elif k.tag == "div" and "callout" in c:
            out.append(_panel([Paragraph(_inline(p), st["p"]) for p in k.kids if isinstance(p, Node) and p.tag == "p"], width, bar=True))
            out.append(Spacer(1, 6))
        elif k.tag == "div" and "formula" in c:
            raw = "".join(x if isinstance(x, str) else _plain(x) for x in k.kids).replace("−", "-")
            lines = [escape(l).replace(" ", "&nbsp;") for l in raw.strip("\n").split("\n")]
            out.append(_panel([Paragraph("<br/>".join(lines), st["mono"])], width))
            out.append(Spacer(1, 6))
        elif k.tag == "div" and "cards" in c:
            cards = [[Paragraph(_inline(x), st["p"]) for x in [card]] for card in k.kids if isinstance(card, Node)]
            flat = [c_[0] for c_ in cards]
            rows = [flat[i:i + 2] + [""] * (2 - len(flat[i:i + 2])) for i in range(0, len(flat), 2)]
            t = Table(rows, colWidths=[width / 2] * 2)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.4, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            out.append(t)
            out.append(Spacer(1, 6))
        elif k.tag == "div" and "bars" in c:
            ident = k.attrs.get("id")
            if ident == "stxbars":
                out.append(_bars([(STX_NAMES.get(a, a), b) for a, b in m["stx"]["weights"].items()], width, 0.35))
            elif ident == "ifxbars":
                out.append(_bars([(IFX_PILLARS.get(a, a), b) for a, b in m["ifx"]["pillar_weights"].items()], width, 0.4))
        elif k.tag == "div" and "tw" in c:
            tbl = _find(k, lambda n: n.tag == "table")
            if tbl:
                fill = None
                if tbl.attrs.get("id") == "stxtable":
                    defs = {s["name"]: s["definition"] for s in m["stx"]["signals"]}
                    fill = [[STX_NAMES.get(a, a), f"{round(b * 100)}%", defs.get(a, "")] for a, b in m["stx"]["weights"].items()]
                elif tbl.attrs.get("id") == "ifxtable":
                    fill = [[IFX_PILLARS.get(p["pillar"], p["pillar"]), p["label"], f"{round(p['weight'] * 100)}%"] for p in m["ifx"]["parts"]]
                out.append(_table(tbl, st, width, fill))
                out.append(Spacer(1, 6))
        elif k.tag == "details":
            q = _find(k, lambda n: n.tag == "summary")
            a = _find(k, lambda n: n.tag == "p")
            out.append(Paragraph(_inline(q) if q else "", st["q"]))
            if a:
                out.append(Paragraph(_inline(a), st["p"]))
        elif k.tag in ("div", "section", "article", "main"):
            out.extend(_blocks(k, st, width, m))
    return out


def manual_pdf() -> bytes:
    tree = Tree()
    tree.feed(PAGE.read_text(encoding="utf-8"))
    article = _find(tree.root, lambda n: n.tag == "article")
    m = methodology()
    st = _styles()
    width = A4[0] - 32 * mm
    downloaded = ist_stamp()
    buf = BytesIO()
    doc = ManualDoc(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=28 * mm, bottomMargin=18 * mm, title="StatAxis user manual", author="STAXIS", subject=f"How to use StatAxis, the STX Index and the IFX Score ({VERSION})")
    intro = next((x for x in article.kids if isinstance(x, Node) and x.tag == "p"), None)
    toc = TableOfContents()
    toc.levelStyles = [st["toc0"]]
    toc.dotsMinLevel = 0
    story: list[Any] = [
        Spacer(1, 38 * mm),
        Paragraph("●&nbsp;FIG. 00 - USER MANUAL", ParagraphStyle("l2", parent=st["label"], textColor=BLUE)),
        Paragraph("HOW TO USE<br/>STATAXIS", st["title"]),
        Paragraph("Stat the View. Axis the Viewpoint.", st["serif"]),
        Spacer(1, 6),
        Paragraph(_inline(intro) if intro else "", st["p"]),
        Spacer(1, 10),
        Paragraph(f"<font color='#0b8ded'><b>Methodology version {escape(VERSION)}</b></font>  |  Downloaded {escape(downloaded)}", st["p"]),
        Paragraph("The live version of this manual, with a calculator for the STX Index, is at <font color='#5fb4ff'><u>stataxis.org/manual</u></font>.", st["p"]),
        PageBreak(),
        Paragraph("CONTENTS", ParagraphStyle("contents", parent=st["h2"])),
        toc,
        PageBreak(),
    ]
    story.extend(_blocks(article, st, width, m))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"{escape(YOUTUBE_NOTE)}  |  {escape(HANDLE)}", ParagraphStyle("end", parent=st["p"], textColor=MUTE, fontSize=8)))
    doc.multiBuild(story, onFirstPage=lambda c, d: _decorate(c, d, downloaded, "StatAxis user manual", ""), onLaterPages=lambda c, d: _decorate(c, d, downloaded, "StatAxis user manual", ""))
    return buf.getvalue()


def filename() -> str:
    return f"stataxis-user-manual-downloaded-{file_stamp()}.pdf"
