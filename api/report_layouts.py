"""The two layouts a client can choose for a periodic report, in the StatAxis design (design/reference.png): a ONE-PAGER and a BOOKLET.

Both are drawn from one content dictionary (``content``), so a daily, weekly, fortnightly, monthly, quarterly, half-yearly or yearly report differs only in its content:

  title, period, interval, kicker   what and when
  stx                               {"leader", "leader_score", "average", "scored", "of"}: the STX Index headline, always first
  kpis                              [{"label", "value", "detail"}] the big numbers
  ranking                           [{"rank", "name", "stx", "views", "share"}] the channels, with STX beside each
  trend                             {"title", "unit", "points": [(label, value)]} one small chart
  highlights, findings, observations, viewpoint
                                    the highlighted things, the detailed findings ({"headline", "detail", "so_what"}), our observations and the StatAxis viewpoint
  sample                            True when the figures are illustrative: every page then says so

``sample_content(interval)`` builds illustrative content (fictional channels, invented figures) so a client can see each layout before any report is real.
"""

from __future__ import annotations

import random
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle

from api.report_pdf import BLUE, BLUE_LIGHT, HANDLE, LINE, MUTE, PANEL, TEXT, WHITE, _decorate, _para, _stx_banner, _table
from api.stamps import ist_stamp

INTERVALS = {
    "daily": {"label": "Daily report", "days": 1, "unit": "day", "period": "13 Oct 2026", "chart": ("Audience through the day", "average viewers, all channels", [f"{h:02d}h" for h in range(0, 24, 2)])},
    "weekly": {"label": "Weekly report", "days": 7, "unit": "week", "period": "7 – 13 Oct 2026", "chart": ("Views day by day", "million views of new videos", ["7 Oct", "8", "9", "10", "11", "12", "13"])},
    "fortnightly": {"label": "Fortnightly report", "days": 14, "unit": "fortnight", "period": "30 Sep – 13 Oct 2026", "chart": ("Views day by day", "million views of new videos", [str(d) for d in range(30, 31)] + [str(d) for d in range(1, 14)])},
    "monthly": {"label": "Monthly report", "days": 30, "unit": "month", "period": "September 2026", "chart": ("Views week by week", "million views of new videos", ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"])},
    "quarterly": {"label": "Quarterly report", "days": 91, "unit": "quarter", "period": "Jul – Sep 2026 (Q3)", "chart": ("Views month by month", "million views of new videos", ["Jul", "Aug", "Sep"])},
    "half-yearly": {"label": "Half-yearly report", "days": 183, "unit": "half-year", "period": "Apr – Sep 2026 (H1, FY 2026-27)", "chart": ("Views month by month", "million views of new videos", ["Apr", "May", "Jun", "Jul", "Aug", "Sep"])},
    "yearly": {"label": "Yearly report", "days": 365, "unit": "year", "period": "Apr 2025 – Mar 2026 (FY 2025-26)", "chart": ("Views month by month", "million views of new videos", ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"])},
}
CHANNELS = [("Sample News A", 162.9, 72.4), ("Sample News B", 152.3, 68.1), ("Sample News C", 151.5, 61.0), ("Sample News D", 108.0, 58.2), ("Sample News E", 101.0, 55.0),
            ("Sample News F", 73.8, 49.5), ("Sample News G", 40.1, 44.3), ("Sample News H", 22.3, 41.0)]   # fictional: weekly million views and an STX Index each


def sample_content(interval: str) -> dict[str, Any]:
    """Illustrative content for one interval: fictional channels, invented figures, deterministic, and marked as a sample on every page."""
    spec = INTERVALS[interval]
    rnd = random.Random(interval)
    days = spec["days"]
    rows = []
    for name, weekly, stx in CHANNELS:
        views = weekly * days / 7 * rnd.uniform(0.92, 1.08)
        rows.append({"name": name, "views": views, "stx": round(max(30.0, min(90.0, stx + rnd.uniform(-3.5, 3.5))), 1)})
    rows.sort(key=lambda r: r["views"], reverse=True)
    total = sum(r["views"] for r in rows)
    for i, r in enumerate(rows, start=1):
        r["rank"], r["share"] = i, round(100 * r["views"] / total, 1)
    best = max(rows, key=lambda r: r["stx"])
    top, second, third = rows[0], rows[1], rows[2]
    stx = {"leader": best["name"], "leader_score": best["stx"], "average": round(sum(r["stx"] for r in rows) / len(rows), 1), "scored": len(rows), "of": len(rows)}
    labels = spec["chart"][2]
    weights = [rnd.uniform(0.7, 1.3) for _ in labels]
    scale = (total / sum(weights)) if interval != "daily" else 1
    points = [(lab, round(w * scale, 1)) for lab, w in zip(labels, weights)] if interval != "daily" else [(lab, int(rnd.uniform(6_000, 52_000))) for lab in labels]
    unit = spec["unit"]
    top3 = round(sum(r["share"] for r in rows[:3]), 1)
    mover = rows[rnd.randint(3, 6)]
    peak_audience = int(rnd.uniform(48_000, 61_000))
    content: dict[str, Any] = {
        "interval": interval, "title": f"Hindi news · {spec['label']}", "period": spec["period"], "kicker": spec["label"].upper(), "sample": True, "stx": stx,
        "kpis": [{"label": "Total views", "value": f"{total:,.1f}M", "detail": "videos uploaded in the period"}, {"label": "Highest STX Index", "value": f"{best['stx']:.1f}", "detail": best["name"]},
                 {"label": "Peak audience", "value": f"{peak_audience:,}", "detail": "concurrent viewers, all streams"}, {"label": "Channels measured", "value": str(len(rows)), "detail": "all with an STX Index"}],
        "ranking": rows,
        "trend": {"title": spec["chart"][0], "unit": spec["chart"][1], "points": points},
        "highlights": [f"{best['name']} has the highest STX Index: {best['stx']:.1f}.", f"{top['name']} leads on views with {top['views']:,.1f}M ({top['share']}% of the total).",
                       f"{mover['name']} moved up {(places := rnd.randint(1, 3))} place{'s' if places > 1 else ''} against the previous {unit}.",
                       f"The top three channels hold {top3}% of all views."],
        "findings": [
            {"headline": f"{top['name']} leads on views, {best['name']} leads on STX" if top["name"] != best["name"] else f"{top['name']} leads on both views and STX",
             "detail": f"{top['name']} collected {top['views']:,.1f}M views, {top['views'] / second['views']:.2f} times {second['name']}. The STX Index, which also weighs audience, momentum and consistency, is highest for {best['name']} at {best['stx']:.1f}.",
             "so_what": "Views show who was watched; STX shows who is strongest overall. Read the two together before choosing where to place a campaign."},
            {"headline": f"The top three hold {top3}% of all views", "detail": f"{top['name']}, {second['name']} and {third['name']} together hold {top3}% of the {total:,.1f}M views; the other {len(rows) - 3} share the rest.",
             "so_what": "A crowded top means rankings can change with one big story; a wide gap means the lead is safer."},
            {"headline": f"{mover['name']} is the mover of the {unit}", "detail": f"{mover['name']} now stands at number {mover['rank']} with an STX Index of {mover['stx']:.1f}, up on the previous {unit}.",
             "so_what": "A channel that climbs on STX before it climbs on views is often the one to watch next."},
            {"headline": f"The gap between {top['name']} and {second['name']} is {top['views'] - second['views']:,.1f}M views", "detail": f"That is {100 * (top['views'] - second['views']) / second['views']:.1f}% more than the runner-up. The channels at the bottom, {rows[-2]['name']} and {rows[-1]['name']}, hold {rows[-2]['share'] + rows[-1]['share']:.1f}% between them.",
             "so_what": "A wide gap at the top is a safer lead; a narrow one can change in a single news cycle."},
            {"headline": f"STX is spread from {min(r['stx'] for r in rows):.1f} to {max(r['stx'] for r in rows):.1f}", "detail": f"The average STX Index of the {len(rows)} channels is {stx['average']:.1f}. {best['name']} is {best['stx'] - stx['average']:.1f} points above the average.",
             "so_what": "STX separates channels that look alike on views: use it to choose between two channels that draw similar audiences."},
        ],
        "observations": [f"Views are measured on YouTube for the videos uploaded in this {unit}, as last measured; STX is each channel's score over the same period.",
                         f"This {unit} covers {days} day{'s' if days != 1 else ''}; a short window can be moved by a single event.",
                         "Channels with little data carry a lower confidence and are pulled toward 50 so they cannot look more certain than they are.",
                         "The ranking is by views; the STX column beside it ranks the same channels by overall strength, so the two orders can differ."],
        "viewpoint": (f"STX Index: {best['name']} is highest at {best['stx']:.1f}; the average of the {len(rows)} scored channels is {stx['average']:.1f}. "
                      f"{top['name']} and {second['name']} lead on views, and the audience is {'spread widely' if top['share'] < 30 else 'concentrated in a few channels'}. "
                      "Read the figures with the period in mind: they are measured on YouTube, not on television."),
    }
    return content


# ------------------------------------------------------------------------------------------------ pieces
def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Helvetica", fontSize=8.8, leading=12, textColor=TEXT)
    return {
        "body": ParagraphStyle("body", **base), "small": ParagraphStyle("small", **{**base, "fontSize": 7.6, "leading": 10, "textColor": MUTE}),
        "kicker": ParagraphStyle("kicker", fontName="Courier", fontSize=8.5, leading=11, textColor=MUTE),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=25, leading=27, textColor=WHITE, spaceAfter=2),
        "period": ParagraphStyle("period", fontName="Helvetica", fontSize=10.5, leading=14, textColor=BLUE),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=BLUE, spaceBefore=8, spaceAfter=3, keepWithNext=1),
        "num": ParagraphStyle("num", fontName="Helvetica-Bold", fontSize=21, leading=22, textColor=BLUE),
        "find_h": ParagraphStyle("find_h", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=WHITE),
        "serif": ParagraphStyle("serif", fontName="Times-Italic", fontSize=12.5, leading=17, textColor=BLUE),
        "kpi_v": ParagraphStyle("kpi_v", fontName="Helvetica-Bold", fontSize=19, leading=21, textColor=BLUE),
        "kpi_l": ParagraphStyle("kpi_l", fontName="Helvetica", fontSize=7.4, leading=9.5, textColor=MUTE),
    }


def _kicker(c: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    return [_para(f"<font color='#0b8ded'>&#8226;</font>  FIG. 00 - {escape(c['kicker'])}" + ("  |  SAMPLE: ILLUSTRATIVE FIGURES" if c.get("sample") else ""), st["kicker"]), Spacer(1, 3),
            _para(escape(c["title"].upper()), st["title"]), _para(escape(c["period"]), st["period"]), Spacer(1, 6)]


def _kpi_row(c: dict[str, Any], st: dict[str, ParagraphStyle], width: float) -> Table:
    data = [[_para(escape(k["value"]), st["kpi_v"]) for k in c["kpis"]], [_para(escape(k["label"].upper()) + "<br/>" + escape(k["detail"]), st["kpi_l"]) for k in c["kpis"]]]
    t = Table(data, colWidths=[width / len(c["kpis"])] * len(c["kpis"]))
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, 0), 0)]))
    return t


def _ranking(c: dict[str, Any], width: float, rows: int | None = None) -> Table:
    data = [["#", "Channel", "STX Index", "Views (M)", "Share %"]] + [[f"{r['rank']:02d}", r["name"], f"{r['stx']:.1f}", f"{r['views']:,.1f}", f"{r['share']:.1f}"] for r in c["ranking"][:rows]]
    return _table(data, [12 * mm, width - 12 * mm - 3 * 26 * mm, 26 * mm, 26 * mm, 26 * mm], right_from=2)


def _chart(c: dict[str, Any], width: float, height: float = 78) -> Drawing:
    t = c["trend"]
    d = Drawing(width, height + 34)
    d.add(String(0, height + 22, f"{t['title'].upper()}", fontName="Helvetica-Bold", fontSize=8, fillColor=WHITE))
    d.add(String(0, height + 11, t["unit"], fontName="Helvetica", fontSize=7, fillColor=MUTE))
    pts = t["points"]
    top = max(v for _l, v in pts) or 1
    slot = width / len(pts)
    bw = min(34, slot * 0.62)
    d.add(Line(0, 16, width, 16, strokeColor=LINE, strokeWidth=0.6))
    for i, (lab, v) in enumerate(pts):
        h = max(1.5, (height - 22) * v / top)
        x = i * slot + (slot - bw) / 2
        d.add(Rect(x, 16, bw, h, fillColor=BLUE_LIGHT if v == top else BLUE, strokeColor=None))
        d.add(String(x + bw / 2, 18 + h + 2, f"{v:,.0f}" if v >= 1000 else f"{v:,.1f}", fontName="Helvetica-Bold", fontSize=6.6 if len(pts) > 8 else 7.4, fillColor=WHITE, textAnchor="middle"))
        d.add(String(x + bw / 2, 5, str(lab), fontName="Helvetica", fontSize=6.4 if len(pts) > 8 else 7, fillColor=MUTE, textAnchor="middle"))
    return d


def _bullets(items: list[str], st: dict[str, ParagraphStyle]) -> list[Any]:
    return [_para("<font color='#0b8ded'>&#8226;</font>&nbsp;&nbsp;" + escape(t), st["body"]) for t in items]


def _finding(n: int, f: dict[str, str], st: dict[str, ParagraphStyle], width: float) -> Table:
    body = [_para(escape(f["headline"]), st["find_h"]), _para(escape(f["detail"]), st["body"]), _para("<font color='#0b8ded'><b>For you:</b></font> " + escape(f["so_what"]), st["body"])]
    t = Table([[_para(f"{n:02d}", st["num"]), body]], colWidths=[16 * mm, width - 16 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    return t


def _doc(buf: BytesIO, title: str, top: float = 28 * mm) -> SimpleDocTemplate:
    return SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=top, bottomMargin=18 * mm, title=title, author="STAXIS")


def _page_fn(c: dict[str, Any], downloaded: str, who: str):
    def page(canvas: Any, document: Any) -> None:
        _decorate(canvas, document, downloaded, "SAMPLE: illustrative figures" if c.get("sample") else c["period"], who)
        if c.get("sample"):
            canvas.saveState()
            canvas.setFillColor(BLUE)
            canvas.setFillAlpha(0.085)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.setFont("Helvetica-Bold", 120)
            canvas.drawCentredString(0, 0, "SAMPLE")
            canvas.restoreState()
    return page


# ------------------------------------------------------------------------------------------------ the one-pager
def one_pager(c: dict[str, Any], prepared_for: str | None = None) -> bytes:
    """Everything that matters on one page: STX first, the numbers, the ranking, the trend, what stands out and our viewpoint."""
    st, width, buf, downloaded = _styles(), A4[0] - 32 * mm, BytesIO(), ist_stamp()
    story: list[Any] = _kicker(c, st)
    story += [_stx_banner(c["stx"], width, "this period"), Spacer(1, 7), _kpi_row(c, st, width), Spacer(1, 6), _ranking(c, width, rows=8), Spacer(1, 4), _chart(c, width, 62)]
    story += [_para("WHAT STANDS OUT", st["h2"])] + _bullets(c["highlights"], st)
    story += [_para("STATAXIS VIEWPOINT", st["h2"]), _para(escape(c["viewpoint"]), st["serif"])]
    page = _page_fn(c, downloaded, f" for {prepared_for}" if prepared_for else "")
    _doc(buf, c["title"], 27 * mm).build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ the booklet
def booklet(c: dict[str, Any], prepared_for: str | None = None) -> bytes:
    """A cover, an at-a-glance page, the STX ranking and trend, every finding in detail, the full data, and our observations, method and viewpoint."""
    st, width, buf, downloaded = _styles(), A4[0] - 32 * mm, BytesIO(), ist_stamp()
    cover_title = ParagraphStyle("cover", fontName="Helvetica-Bold", fontSize=40, leading=42, textColor=WHITE)
    story: list[Any] = [Spacer(1, 38 * mm), _para(f"<font color='#0b8ded'>&#8226;</font>  FIG. 00 - {escape(c['kicker'])}" + ("  |  SAMPLE" if c.get("sample") else ""), st["kicker"]), Spacer(1, 8),
                        _para(escape(c["title"].upper()), cover_title), Spacer(1, 8), _para(escape(c["period"]), ParagraphStyle("cp", parent=st["period"], fontSize=15, leading=19)), Spacer(1, 16),
                        _para("Detailed findings, data, observations and the StatAxis viewpoint." + (f" Prepared for {escape(prepared_for)}." if prepared_for else ""), st["body"]), Spacer(1, 22),
                        _stx_banner(c["stx"], width, "this period"), Spacer(1, 22), _para("INSIDE", st["h2"])] + _bullets(["At a glance: the numbers, what stands out, our viewpoint", "The STX Index, channel by channel, and the trend", "Detailed findings, one by one",
                                                                                                               "The data: every figure, period by period", "Observations, method and our closing viewpoint"], st) + [PageBreak()]
    story += [_para("AT A GLANCE", st["h2"]), _kpi_row(c, st, width), Spacer(1, 8), _para("WHAT STANDS OUT", st["h2"])] + _bullets(c["highlights"], st) + [Spacer(1, 6), _para("STATAXIS VIEWPOINT", st["h2"]), _para(escape(c["viewpoint"]), st["serif"]), PageBreak()]
    story += [_para("THE STX INDEX, CHANNEL BY CHANNEL", st["h2"]), _para("STX is StatAxis's own 0-100 score for a channel: audience, momentum, consistency and more, in one number, with a confidence beside it.", st["small"]), Spacer(1, 5),
              _ranking(c, width), Spacer(1, 10), _chart(c, width, 110), PageBreak()]
    story += [_para("DETAILED FINDINGS", st["h2"])] + [KeepTogether(_finding(i, f, st, width)) for i, f in enumerate(c["findings"], start=1)] + [PageBreak()]
    pts = c["trend"]["points"]
    story += [_para("THE DATA, PERIOD BY PERIOD", st["h2"]), _para(escape(c["trend"]["title"] + ": " + c["trend"]["unit"]), st["small"]), Spacer(1, 5),
              _table([["Period", "Value", "Against the average"]] + [[str(lab), f"{v:,.1f}" if v < 1000 else f"{v:,.0f}", f"{100 * (v / (sum(x for _l, x in pts) / len(pts)) - 1):+.0f}%"] for lab, v in pts], [60 * mm, 40 * mm, 40 * mm], right_from=1),
              Spacer(1, 12), _para("EVERY CHANNEL", st["h2"]), _ranking(c, width), PageBreak()]
    story += [_para("OBSERVATIONS", st["h2"])] + _bullets(c["observations"], st) + [Spacer(1, 10), _para("HOW THESE NUMBERS WERE WORKED OUT", st["h2"]),
              _para("Views are what YouTube reports for videos uploaded in the period, as last measured by StatAxis. The STX Index is StatAxis's own score and is pulled toward 50 when data is thin. "
                    "Nothing is estimated; a dash means not enough data. Measured from public YouTube data: this is not TV ratings and not a statement about who watched.", st["body"]),
              Spacer(1, 14), _para("STATAXIS VIEWPOINT", st["h2"]), _para(escape(c["viewpoint"]), st["serif"]), Spacer(1, 12), _para(f"stataxis.org  |  x.com/stataxis  |  {escape(HANDLE.split('|')[0].strip())}", st["small"])]
    page = _page_fn(c, downloaded, f" for {prepared_for}" if prepared_for else "")
    _doc(buf, c["title"]).build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()

