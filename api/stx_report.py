"""The STX Index report: for every channel, the STX Index out of 100, what each of the seven factors gave it, and its audience.

The numbers are the ones the STX Index screen already shows (api/media_intelligence.market_report, kept ready by the warm-up loop); this module only arranges them:
  * STX shown: the 0-100 score every other screen shows (pulled toward 50 when data is thin) and the raw 0-100 score under it;
  * the factors: audience, growth, momentum, acceleration, consistency, competition, event. Each factor is a 0-100 signal; its points are signal x weight, so the points of all factors add up to the
    raw STX. A factor with no data in the window is left out and the others share its weight (never counted as zero), so the maximum points of the factors that exist always add up to 100;
  * the audience, channel by channel: average and peak concurrent viewers, views gained, share of its group, uploads, likes and comments gained.
Nothing is estimated here and nothing is filled in: a channel without a figure shows a dash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Callable
from xml.sax.saxutils import escape

from metrics.stx_index import WEIGHTS

FACTORS: list[tuple[str, str, str, str]] = [
    ("audience", "Audience", "Aud", "How many people were watching live, against the window before: 50 + the percent change, kept between 0 and 100."),
    ("growth", "Growth", "Gro", "How many views were gained, against the window before: 50 + the percent change, kept between 0 and 100."),
    ("momentum", "Momentum", "Mom", "Viewers gained or lost per minute at the latest reading: 50 + half the change per minute."),
    ("acceleration", "Acceleration", "Acc", "How that rate of change itself moved at the latest reading."),
    ("consistency", "Consistency", "Con", "How often recent readings moved the same way as the latest one."),
    ("competitive_position", "Competition", "Cmp", "100 divided by the channel's rank among the channels compared: first place is 100."),
    ("anomaly_event", "Event", "Evt", "How unusual the latest view count is against the channel's own history: 50 + 10 times a robust z-score."),
]
PERIODS = {"today": "today so far", "7d": "the last 7 days", "3w": "the last 3 weeks", "month": "the last month"}
NOTE = ("The STX Index is StatAxis's own 0-100 score, measured on YouTube. It is not TV ratings and not a statement about any channel's quality or truthfulness. A dash means there was not enough data "
        "in the window; it is never read as zero.")


def _r(value: Any, places: int = 1) -> float | None:
    return None if value is None else round(float(value), places)


def _default_fetch(session: Any, **kw: Any) -> tuple[int, dict[str, Any]]:
    from api.http import get_market_report
    return get_market_report(session, stream_scope="all", limit=200, **kw)


def build(session: Any, *, period: str = "7d", language: str | None = None, segment: str | None = None, cards: int = 12, fetch: Callable[..., tuple[int, dict[str, Any]]] | None = None) -> dict[str, Any]:
    """The report as plain data. Raises ValueError (with a sentence) for a period or filter that is not valid."""
    if period not in PERIODS:
        raise ValueError("period must be one of: " + ", ".join(PERIODS))
    status, payload = (fetch or _default_fetch)(session, period=period, language=language or None, segment=segment or None)
    if status != 200:
        raise ValueError(str(payload.get("error") or "the market report could not be made"))
    channels = []
    for row in payload["channels"]:
        stx = row.get("stx") or {}
        raw = stx.get("score")
        shown = stx.get("display_score") if stx.get("display_score") is not None else raw
        if shown is None:
            continue
        comps, signals = stx.get("components") or {}, stx.get("signals") or {}
        available_weight = sum(WEIGHTS[k] for k in comps if k in WEIGHTS) or 1.0
        factors = []
        for key, label, short, meaning in FACTORS:
            if key in comps and signals.get(key) is not None:
                factors.append({"key": key, "label": label, "short": short, "weight_percent": round(WEIGHTS[key] * 100), "signal": _r(signals[key]), "points": _r(comps[key]), "max_points": _r(WEIGHTS[key] / available_weight * 100)})
            else:
                factors.append({"key": key, "label": label, "short": short, "weight_percent": round(WEIGHTS[key] * 100), "signal": None, "points": None, "max_points": None})
        channels.append({
            "channel_id": row["channel_id"], "name": row["channel"], "group": row.get("market_label") or "", "stx": _r(shown), "raw": _r(raw), "confidence": _r(stx.get("confidence"), 0), "preliminary": bool(stx.get("preliminary")),
            "factors_available": sum(1 for f in factors if f["points"] is not None), "factors": factors,
            "audience": {"average": _r(row.get("average_concurrent"), 0), "peak": row.get("peak_concurrent"), "now": row.get("current_concurrent"), "views_gained": row.get("view_delta"), "share_percent": row.get("share_percent"),
                         "share_basis": row.get("share_basis"), "uploads": row.get("uploads_in_window"),
                         "engagement": (row.get("like_delta") or 0) + (row.get("comment_delta") or 0) if (row.get("like_delta") is not None or row.get("comment_delta") is not None) else None},
        })
    channels.sort(key=lambda c: (c["stx"], c["raw"] or 0), reverse=True)
    for i, c in enumerate(channels, 1):
        c["rank"] = i
    leaders = []
    for key, label, _short, meaning in FACTORS:
        have = sorted((c for c in channels if next(f for f in c["factors"] if f["key"] == key)["signal"] is not None), key=lambda c: next(f for f in c["factors"] if f["key"] == key)["signal"], reverse=True)
        leaders.append({"key": key, "label": label, "meaning": meaning, "weight_percent": round(WEIGHTS[key] * 100), "with_data": len(have),
                        "top": [{"name": c["name"], "signal": next(f for f in c["factors"] if f["key"] == key)["signal"]} for c in have[:3]]})
    scored = len(channels)
    by_audience = sorted((c for c in channels if c["audience"]["average"] is not None), key=lambda c: c["audience"]["average"], reverse=True)
    return {
        "title": "STX Index report", "period": period, "period_label": PERIODS[period], "as_of": payload.get("as_of"), "start_at": payload.get("start_at"), "end_at": payload.get("end_at"),
        "filters": {"language": language or None, "segment": segment or None}, "channels_in_window": len(payload["channels"]), "scored": scored,
        "headline": ({"leader": channels[0]["name"], "leader_score": channels[0]["stx"], "average": _r(sum(c["stx"] for c in channels) / scored), "average_raw": _r(sum(c["raw"] for c in channels if c["raw"] is not None) / max(1, sum(1 for c in channels if c["raw"] is not None))), "scored": scored} if scored else None),
        "channels": channels, "audience_order": [c["channel_id"] for c in by_audience], "leaders": leaders, "cards": max(0, min(int(cards), 60)), "note": NOTE,
        "weights": [{"key": k, "label": label, "weight_percent": round(WEIGHTS[k] * 100), "meaning": m} for k, label, _s, m in FACTORS],
    }


def filename(report: dict[str, Any]) -> str:
    from api.stamps import file_stamp
    return f"stataxis-stx-index-report-{report['period']}-{file_stamp()}.pdf"


# ---------------------------------------------------------------------------------------------- the PDF
def _n(value: Any) -> str:
    return "-" if value is None else f"{value:,.0f}"


def _p(value: Any, places: int = 1) -> str:
    return "-" if value is None else f"{value:.{places}f}"


def pdf(report: dict[str, Any], prepared_for: str | None = None, protect: bool = True) -> bytes:
    """A branded landscape report in the StatAxis design (api/report_pdf.py). With ``protect`` every page is a picture and the file is locked to printing, like every other StatAxis report."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Flowable, KeepTogether, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle

    from api import report_pdf as R
    from api.stamps import ist_stamp

    downloaded = ist_stamp()
    size = (A4[1], A4[0])
    width = size[0] - 32 * mm
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=28 * mm, bottomMargin=18 * mm, title="STX Index report", author="STAXIS")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=R.WHITE, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=R.BLUE, spaceBefore=12, spaceAfter=5)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12, textColor=R.TEXT, spaceAfter=3)
    muted = ParagraphStyle("m", parent=body, fontSize=8, leading=10.5, textColor=R.MUTE)

    f = report["filters"]
    dates = ""
    try:
        s, e = datetime.fromisoformat(report["start_at"]), datetime.fromisoformat(report["end_at"])
        dates = f"{ist_stamp(s)} to {ist_stamp(e)}  |  "
    except (TypeError, ValueError, KeyError):
        pass
    subtitle = f"{dates}Indian time  |  {report['period_label'].capitalize()}  |  Language: {f['language'] or 'all'}  |  Group: {f['segment'] or 'all'}"
    story: list[Any] = [R._para("STX INDEX REPORT", h1), R._para(escape(subtitle), muted),
                        R._para(f"<font color='#0b8ded'><b>Downloaded {escape(downloaded)}</b></font>  |  {report['scored']} channels scored of {report['channels_in_window']} with data in the window", body), Spacer(1, 8)]
    if report["headline"]:
        story += [R._stx_banner(report["headline"], width, report["period_label"]), Spacer(1, 8)]
    story.append(R._para("<b>How to read this report.</b> Every channel gets an <b>STX Index out of 100</b>. It is built from seven factors; each factor is a 0-100 signal, and the <b>points</b> it gives are its signal times its weight "
                         "(audience 30%, growth 20%, momentum 15%, acceleration 10%, consistency 10%, competition 10%, event 5%). The points add up to the <b>Raw</b> STX. The <b>STX</b> column is the score every StatAxis screen shows: "
                         "the raw score pulled toward 50 when data is thin (the <b>Conf.</b> column says how much of the weight had data). A factor with no data is left out and the others share its weight, so the maximums "
                         "shown beside the points always add up to 100. A dash means no data, never zero.", body))
    story.append(Spacer(1, 4))

    # ---- 1. the league
    story.append(R._para("1. STX Index by channel: the score out of 100 and what each factor gave", h2))
    head = ["#", "Channel", "Group", "STX", "Raw", "Conf."] + [f"{label}" for _k, label, _s, _m in FACTORS]
    rows = [head]
    for c in report["channels"]:
        cells = [str(c["rank"]), c["name"][:34] + (" *" if c["preliminary"] else ""), c["group"][:22], _p(c["stx"]), _p(c["raw"]), "-" if c["confidence"] is None else f"{c['confidence']:.0f}%"]
        cells += ["-" if x["points"] is None else f"{x['points']:.1f}/{x['max_points']:.1f}" for x in c["factors"]]
        rows.append(cells)
    widths = [8, 54, 32, 14, 13, 13] + [18.2] * 7
    story.append(R._table(rows, [w * mm for w in widths], right_from=3))
    story.append(R._para("* Preliminary: less than half of the weight had data, so the shown score stays close to 50. Each factor cell reads points earned / most points that factor could give this channel.", muted))

    # ---- 2. audience
    story.append(PageBreak())
    story.append(R._para("2. Audience, channel by channel", h2))
    by_id = {c["channel_id"]: c for c in report["channels"]}
    arows = [["#", "Channel", "Group", "Average live viewers", "Peak viewers", "Now", "Views gained", "Share of its group", "Uploads", "Likes + comments"]]
    for i, cid in enumerate(report["audience_order"], 1):
        c = by_id[cid]
        a = c["audience"]
        arows.append([str(i), c["name"][:34], c["group"][:24], _n(a["average"]), _n(a["peak"]), _n(a["now"]), _n(a["views_gained"]), "-" if a["share_percent"] is None else f"{a['share_percent']:.1f}%", _n(a["uploads"]), _n(a["engagement"])])
    for c in report["channels"]:
        if c["channel_id"] not in report["audience_order"]:
            a = c["audience"]
            arows.append(["-", c["name"][:34], c["group"][:24], "-", _n(a["peak"]), _n(a["now"]), _n(a["views_gained"]), "-" if a["share_percent"] is None else f"{a['share_percent']:.1f}%", _n(a["uploads"]), _n(a["engagement"])])
    story.append(R._table(arows, [w * mm for w in (8, 56, 36, 28, 22, 17, 30, 24, 18, 26)], right_from=3))
    story.append(R._para("Average live viewers: the average of the viewers watching the channel's live streams over the minutes it was live in the window (all feeds). Views gained: new views on the videos observed in the window. "
                         "Share of its group: the channel's part of its language and category group's total (by views gained, or by average viewers when views are not available).", muted))

    # ---- 3. scorecards
    class Scorecard(Flowable):
        """One channel: its STX and seven bars, one for each factor, with the points beside each bar."""
        height_mm = 37

        def __init__(self, c: dict[str, Any]) -> None:
            super().__init__()
            self.c = c

        def wrap(self, aw: float, ah: float) -> tuple[float, float]:
            self.w = aw
            return aw, self.height_mm * mm

        def draw(self) -> None:
            cv, c, h = self.canv, self.c, self.height_mm * mm
            cv.saveState()
            cv.setFillColor(R.PANEL)
            cv.setStrokeColor(R.LINE)
            cv.roundRect(0, 0, self.w, h - 2 * mm, 3 * mm, stroke=1, fill=1)
            R._put(cv, 5 * mm, h - 9 * mm, f"#{c['rank']}", "Courier", 8, R.MUTE)
            R._put(cv, 14 * mm, h - 9 * mm, c["name"][:36], "Helvetica-Bold", 11.5, R.WHITE)
            R._put(cv, 5 * mm, h - 15 * mm, c["group"][:40], "Helvetica", 7.8, R.MUTE)
            R._put(cv, 5 * mm, h - 28 * mm, _p(c["stx"]), "Helvetica-Bold", 28, R.BLUE)
            R._put(cv, 5 * mm, h - 33 * mm, f"STX out of 100{' (preliminary)' if c['preliminary'] else ''}", "Helvetica", 7.2, R.MUTE)
            R._put(cv, 52 * mm, h - 24 * mm, f"Raw {_p(c['raw'])}", "Helvetica-Bold", 8.5, R.TEXT)
            R._put(cv, 52 * mm, h - 29 * mm, f"Conf. {'-' if c['confidence'] is None else str(int(c['confidence'])) + '%'}", "Helvetica", 8, R.MUTE)
            R._put(cv, 52 * mm, h - 33.5 * mm, f"{c['factors_available']} of 7 factors", "Helvetica", 7.5, R.MUTE)
            x0, bw, row = 88 * mm, 78 * mm, 4.2 * mm
            for i, fct in enumerate(c["factors"]):
                y = h - 8 * mm - i * row
                R._put(cv, x0 - 3 * mm, y - 0.3 * mm, fct["label"], "Helvetica", 7.8, R.TEXT, right=True)
                cv.setFillColor(colors.HexColor("#0b1a2b"))
                cv.rect(x0, y - 1.2 * mm, bw, 2.8 * mm, stroke=0, fill=1)
                if fct["signal"] is None:
                    R._put(cv, x0 + 2 * mm, y - 0.4 * mm, "no data in this window", "Helvetica", 6.8, R.MUTE)
                    continue
                cv.setFillColor(R.BLUE if i else R.BLUE_LIGHT)
                cv.rect(x0, y - 1.2 * mm, max(bw * fct["signal"] / 100, 0.6 * mm), 2.8 * mm, stroke=0, fill=1)
                R._put(cv, x0 + bw + 3 * mm, y - 0.4 * mm, f"signal {fct['signal']:.0f}", "Helvetica", 7, R.MUTE)
                R._put(cv, self.w - 4 * mm, y - 0.4 * mm, f"{fct['points']:.1f} / {fct['max_points']:.1f}", "Helvetica-Bold", 7.8, R.WHITE, right=True)
            cv.restoreState()

    cards = report["channels"][: report["cards"]]
    if cards:
        story.append(PageBreak())
        story.append(R._para(f"3. Channel scorecards: the top {len(cards)} by STX", h2))
        story.append(R._para("Each bar is the factor's 0-100 signal; the figure on the right is the points it gave out of the most it could give.", muted))
        for c in cards:
            story += [KeepTogether([Scorecard(c)]), Spacer(1, 2)]

    # ---- 4. who leads each factor
    story.append(PageBreak())
    story.append(R._para("4. Who leads each factor", h2))
    lrows = [["Factor", "Weight", "Channels with data", "First", "Second", "Third"]]
    for x in report["leaders"]:
        lrows.append([x["label"], f"{x['weight_percent']}%", str(x["with_data"])] + [f"{t['name'][:30]} ({t['signal']:.0f})" for t in x["top"]] + [""] * (3 - len(x["top"])))
    story.append(R._table(lrows, [w * mm for w in (34, 18, 30, 61, 61, 61)], right_from=1))
    story.append(R._para("The number in brackets is the factor's 0-100 signal.", muted))

    # ---- 5. method
    story.append(R._para("5. How the STX Index is made, and what it does not say", h2))
    mrows = [["Factor", "Weight", "What it measures"]] + [[x["label"], f"{x['weight_percent']}%", x["meaning"]] for x in report["weights"]]
    story.append(R._table(mrows, [w * mm for w in (34, 18, 213)], right_from=1))
    story.append(Spacer(1, 6))
    for line in ("STX = the sum of (signal x weight) over the factors that have data, divided by their total weight. Confidence = the weight of the factors that have data, out of 100. The shown score = 50 + (STX - 50) x confidence / 100.",
                 "Momentum and acceleration need minute-by-minute live readings; a channel that had no live stream in the window has none, and its other factors share their weight.",
                 "Audience and growth compare the window with the one of equal length before it, so they say whether a channel is rising or falling, not how big it is. Size is in section 2.",
                 "All figures are measured on YouTube from public data. " + report["note"]):
        story.append(R._para(escape(line), body))
    who = f" for {prepared_for}" if prepared_for else ""

    def page(canvas: Any, document: Any) -> None:
        R._decorate(canvas, document, downloaded, "STX Index report", who)

    doc.build(story, onFirstPage=page, onLaterPages=page)
    data = buf.getvalue()
    return R.protect_pdf(data, "STX Index report") if protect else data
