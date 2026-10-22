"""The Services section of the public website, and the small content system behind it.

An administrator writes, orders, publishes and changes every service in the workspace ("Website services"); the website shows the published ones at /services and /services/<address>. Every change is kept
whole (api: ServiceRevision) so an earlier version can be read and put back. The pages are written by the server as plain HTML, so a search engine reads the same words a visitor does; the search side
(title, description, canonical address, Open Graph, structured data, sitemap, robots, llms.txt, moved and removed addresses) lives here too.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from api import services_seed
from collector.storage import AppSetting, Service, ServiceRevision

BASE_URL = os.getenv("STAXIS_PUBLIC_URL", "https://www.stataxis.org").rstrip("/")
CONTACT = "stax9@stataxis.org"
DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PAGE_KEY, SEEDED_KEY = "services_page", "services_seeded"
PAGE_SLUG = "__services_page__"
LISTS = {"audience": (12, 200), "deliverables": (14, 300), "limits": (8, 300)}
STATIC_PAGES = (("/platform", "0.9"), ("/solutions", "0.9"), ("/research", "0.8"), ("/insights", "0.8"), ("/ifx", "0.7"), ("/stx", "0.7"), ("/stx-index", "0.6"), ("/stax9", "0.6"),
                ("/methodology", "0.6"), ("/plans", "0.5"), ("/apply", "0.5"), ("/status", "0.4"), ("/privacy", "0.3"), ("/terms", "0.3"))


# ----------------------------------------------------------------------------------------------- reading and writing
def _now() -> datetime:
    return datetime.now(UTC)


def _load(text: str | None, default: Any) -> Any:
    try:
        value = json.loads(text or "")
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def serialize(row: Service) -> dict[str, Any]:
    return {"id": row.id, "slug": row.slug, "name": row.name, "nav_label": row.nav_label or row.name, "tagline": row.tagline, "intro": row.intro,
            "audience": _load(row.audience_json, []), "deliverables": _load(row.deliverables_json, []), "steps": _load(row.steps_json, []), "limits": _load(row.limits_json, []),
            "faqs": _load(row.faqs_json, []), "related": _load(row.related_json, []), "seo_title": row.seo_title, "seo_description": row.seo_description, "seo_keywords": row.seo_keywords,
            "canonical_url": row.canonical_url or "", "noindex": bool(row.noindex), "status": row.status, "sort_order": row.sort_order,
            "created_at": row.created_at.isoformat() if row.created_at else None, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "updated_by": row.updated_by}


def _text(value: Any, label: str, limit: int, *, required: bool = False) -> str:
    out = re.sub(r"[ \t]+", " ", str(value or "").replace("\r", "")).strip()
    if required and not out:
        raise ValueError(f"{label} cannot be empty")
    if len(out) > limit:
        raise ValueError(f"{label} is too long: {len(out)} characters, the most is {limit}")
    return out


def _line_list(value: Any, label: str, max_items: int, limit: int) -> list[str]:
    items = value.split("\n") if isinstance(value, str) else (value if isinstance(value, list) else [])
    out = [_text(i, f"each point of {label}", limit) for i in items if str(i or "").strip()]
    if len(out) > max_items:
        raise ValueError(f"{label} can have at most {max_items} points")
    return out


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(text or "").lower())).strip("-")[:100]


def clean(payload: dict[str, Any], session: Any, current: Service | None) -> dict[str, Any]:
    """The fields of one service, checked. Raises ValueError, in plain words, for anything a person must fix."""
    name = _text(payload.get("name"), "the name", 160, required=True)
    slug = slugify(payload.get("slug") or name)
    if not SLUG_RE.fullmatch(slug) or len(slug) < 2:
        raise ValueError("the web address can use only small letters, numbers and hyphens")
    other = session.query(Service).filter(Service.slug == slug).first()
    if other is not None and (current is None or other.id != current.id):
        raise ValueError(f'the web address "{slug}" is already used by "{other.name}"')
    out: dict[str, Any] = {"slug": slug, "name": name, "nav_label": _text(payload.get("nav_label"), "the menu name", 80) or name,
                           "tagline": _text(payload.get("tagline"), "the one-line summary", 400), "intro": _text(payload.get("intro"), "the introduction", 6000)}
    for key, (max_items, limit) in LISTS.items():
        out[key] = _line_list(payload.get(key), key, max_items, limit)
    steps = []
    for item in (payload.get("steps") or [])[:8] if isinstance(payload.get("steps"), list) else []:
        if isinstance(item, dict) and (str(item.get("title") or "").strip() or str(item.get("text") or "").strip()):
            steps.append({"title": _text(item.get("title"), "a step title", 80, required=True), "text": _text(item.get("text"), "a step text", 400)})
    if isinstance(payload.get("steps"), list) and len(payload["steps"]) > 8:
        raise ValueError("a service can have at most 8 steps")
    out["steps"] = steps
    faqs = []
    for item in payload.get("faqs") or [] if isinstance(payload.get("faqs"), list) else []:
        if isinstance(item, dict) and (str(item.get("q") or "").strip() or str(item.get("a") or "").strip()):
            faqs.append({"q": _text(item.get("q"), "a question", 200, required=True), "a": _text(item.get("a"), "an answer", 1200, required=True)})
    if len(faqs) > 15:
        raise ValueError("a service can have at most 15 questions")
    out["faqs"] = faqs
    known = {s for (s,) in session.query(Service.slug).all()}
    related = []
    for r in payload.get("related") or [] if isinstance(payload.get("related"), list) else []:
        r = str(r).strip()
        if r and r != slug and r in known and r not in related:
            related.append(r)
    out["related"] = related[:6]
    out["seo_title"] = _text(payload.get("seo_title"), "the search title", 200)
    out["seo_description"] = _text(payload.get("seo_description"), "the search description", 400)
    out["seo_keywords"] = _text(payload.get("seo_keywords"), "the keywords", 300)
    canonical = _text(payload.get("canonical_url"), "the canonical address", 500)
    if canonical:
        parts = urlparse(canonical)
        if parts.scheme != "https" or parts.netloc != urlparse(BASE_URL).netloc:
            raise ValueError(f"the canonical address must be a https address on {urlparse(BASE_URL).netloc}, or empty to use the page's own address")
    out["canonical_url"] = canonical
    out["noindex"] = bool(payload.get("noindex"))
    return out


def _apply(row: Service, data: dict[str, Any]) -> None:
    for key in ("slug", "name", "nav_label", "tagline", "intro", "seo_title", "seo_description", "seo_keywords", "noindex"):
        setattr(row, key, data[key])
    row.canonical_url = data["canonical_url"] or None
    for key in ("audience", "deliverables", "steps", "limits", "faqs", "related"):
        setattr(row, key + "_json", json.dumps(data[key], ensure_ascii=False))


def _revise(session: Any, row: Service | None, action: str, by: str | None, snapshot: dict[str, Any] | None = None, slug: str | None = None) -> None:
    snap = snapshot if snapshot is not None else (serialize(row) if row is not None else {})
    session.add(ServiceRevision(service_id=row.id if row is not None else snap.get("id"), slug=slug or (row.slug if row is not None else snap.get("slug", "")), action=action,
                                snapshot=json.dumps(snap, ensure_ascii=False), by=by, at=_now()))


def _publishable(data: dict[str, Any]) -> None:
    missing = [label for label, ok in (("a name", data["name"]), ("a one-line summary", data["tagline"]), ("an introduction", data["intro"]), ("at least one thing the client receives", data["deliverables"])) if not ok]
    if missing:
        raise ValueError("to publish, the service needs " + ", ".join(missing))


def list_services(session: Any, *, published_only: bool = False) -> list[dict[str, Any]]:
    query = session.query(Service)
    if published_only:
        query = query.filter(Service.status == "published")
    return [serialize(r) for r in query.order_by(Service.sort_order, Service.id).all()]


def get_service(session: Any, service_id: int) -> Service:
    row = session.get(Service, service_id)
    if row is None:
        raise LookupError("that service does not exist")
    return row


def save_service(session: Any, by: str, payload: dict[str, Any], service_id: int | None = None) -> dict[str, Any]:
    row = get_service(session, service_id) if service_id else None
    data = clean(payload, session, row)
    status = str(payload.get("status") or (row.status if row else "draft"))
    if status not in {"draft", "published"}:
        raise ValueError("the state must be draft or published")
    if status == "published":
        _publishable(data)
    created = row is None
    if created:
        row = Service(created_at=_now(), sort_order=(session.query(Service).count() and max(r for (r,) in session.query(Service.sort_order).all()) + 1) or 1)
        session.add(row)
    elif row.slug != data["slug"] and row.status == "published":
        _revise(session, row, "update", by)   # the old address is kept in the history, so visitors and search engines are sent to the new one
    before = row.status if not created else None
    _apply(row, data)
    row.status, row.updated_at, row.updated_by = status, _now(), by
    session.flush()
    _revise(session, row, "create" if created else ("publish" if status == "published" and before != "published" else "unpublish" if before == "published" and status != "published" else "update"), by)
    session.commit()
    invalidate()
    return serialize(row)


def set_status(session: Any, by: str, service_id: int, status: str) -> dict[str, Any]:
    row = get_service(session, service_id)
    if status not in {"draft", "published"}:
        raise ValueError("the state must be draft or published")
    if status == "published":
        _publishable(serialize(row))
    if row.status != status:
        row.status, row.updated_at, row.updated_by = status, _now(), by
        _revise(session, row, "publish" if status == "published" else "unpublish", by)
        session.commit()
        invalidate()
    return serialize(row)


def delete_service(session: Any, by: str, service_id: int) -> dict[str, Any]:
    row = get_service(session, service_id)
    snap = serialize(row)
    _revise(session, row, "delete", by, snap)
    session.delete(row)
    session.commit()
    invalidate()
    return {"deleted": snap["slug"]}


def reorder(session: Any, by: str, ids: list[Any]) -> list[dict[str, Any]]:
    rows = {r.id: r for r in session.query(Service).all()}
    wanted = [int(i) for i in ids if str(i).isdigit() and int(i) in rows]
    rest = [i for i in sorted(rows, key=lambda k: (rows[k].sort_order, k)) if i not in wanted]
    for position, rid in enumerate(wanted + rest, 1):
        rows[rid].sort_order = position
    session.commit()
    invalidate()
    return list_services(session)


def revisions(session: Any, service_id: int) -> list[dict[str, Any]]:
    out = []
    for r in session.query(ServiceRevision).filter(ServiceRevision.service_id == service_id).order_by(ServiceRevision.id.desc()).limit(60).all():
        snap = _load(r.snapshot, {})
        out.append({"id": r.id, "action": r.action, "by": r.by, "at": r.at.isoformat() if r.at else None, "slug": r.slug, "name": snap.get("name"), "status": snap.get("status")})
    return out


def deleted_revisions(session: Any) -> list[dict[str, Any]]:
    live = {s for (s,) in session.query(Service.slug).all()}
    return [{"id": r.id, "slug": r.slug, "by": r.by, "at": r.at.isoformat() if r.at else None, "name": _load(r.snapshot, {}).get("name")}
            for r in session.query(ServiceRevision).filter(ServiceRevision.action == "delete").order_by(ServiceRevision.id.desc()).limit(30).all() if r.slug not in live]


def revision_detail(session: Any, revision_id: int) -> dict[str, Any]:
    r = session.get(ServiceRevision, revision_id)
    if r is None or r.slug == PAGE_SLUG:
        raise LookupError("that version does not exist")
    return {"id": r.id, "action": r.action, "by": r.by, "at": r.at.isoformat() if r.at else None, "snapshot": _load(r.snapshot, {})}


def restore(session: Any, by: str, revision_id: int) -> dict[str, Any]:
    """Put an earlier version back (as a draft, so nothing goes live by surprise). A deleted service comes back as a new one at the same address when that address is free."""
    r = session.get(ServiceRevision, revision_id)
    if r is None or r.slug == PAGE_SLUG:
        raise LookupError("that version does not exist")
    snap = _load(r.snapshot, {})
    if not snap.get("name"):
        raise ValueError("that version holds nothing to restore")
    row = session.get(Service, r.service_id) if r.service_id else None
    if row is None:
        row = session.query(Service).filter(Service.slug == snap.get("slug")).first()
    payload = {**snap, "status": "draft"}
    saved = save_service(session, by, payload, row.id if row else None)
    _revise(session, session.get(Service, saved["id"]), "restore", by)
    session.commit()
    return saved


def restore_starters(session: Any, by: str) -> dict[str, Any]:
    """Add back any starter service that is not there (by its address). Existing services, edited or not, are never touched."""
    have = {s for (s,) in session.query(Service.slug).all()}
    added = []
    for item in services_seed.SERVICES:
        if item["slug"] in have:
            continue
        try:
            added.append(save_service(session, by, {**item, "status": "published"})["slug"])
        except ValueError:
            continue
    return {"added": added}


def ensure_seed(session: Any) -> None:
    """On the first start with this feature, the starter services are written (published, and editable like any other). It happens once: services the administrator deletes do not come back by themselves."""
    if session.get(AppSetting, SEEDED_KEY) is not None:
        return
    if session.query(Service).count() == 0:
        for item in services_seed.SERVICES:
            row = Service(created_at=_now(), sort_order=session.query(Service).count() + 1)
            session.add(row)
            _apply(row, {**item, "canonical_url": "", "noindex": False, "related": item["related"]})
            row.status, row.updated_at, row.updated_by = "published", _now(), "starter"
            session.flush()
            _revise(session, row, "starter", "starter")
    session.add(AppSetting(key=SEEDED_KEY, value="1", updated_by="starter", updated_at=_now()))
    session.commit()


# ----------------------------------------------------------------------------------------------- the page that lists the services
def page_settings(session: Any) -> dict[str, str]:
    row = session.get(AppSetting, PAGE_KEY)
    saved = _load(row.value if row else "", {})
    return {k: str(saved.get(k) or v) for k, v in services_seed.PAGE_DEFAULTS.items()}


def save_page_settings(session: Any, by: str, payload: dict[str, Any]) -> dict[str, str]:
    limits = {"kicker": 60, "heading": 160, "lead": 500, "seo_title": 200, "seo_description": 400}
    values = {k: _text(payload.get(k), k.replace("_", " "), n) or services_seed.PAGE_DEFAULTS[k] for k, n in limits.items()}
    row = session.get(AppSetting, PAGE_KEY)
    if row is None:
        session.add(AppSetting(key=PAGE_KEY, value=json.dumps(values), updated_by=by, updated_at=_now()))
    else:
        row.value, row.updated_by, row.updated_at = json.dumps(values), by, _now()
    session.add(ServiceRevision(service_id=None, slug=PAGE_SLUG, action="update", snapshot=json.dumps(values), by=by, at=_now()))
    session.commit()
    invalidate()
    return values


# ----------------------------------------------------------------------------------------------- the search checks
def _words(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def seo_report(d: dict[str, Any], others: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """What a search engine would make of this page, in words an editor can act on: each check is good, to improve, or a problem."""
    checks: list[dict[str, str]] = []

    def add(level: str, text: str) -> None:
        checks.append({"level": level, "text": text})
    title = d.get("seo_title") or f"{d.get('name', '')} | StatAxis"
    desc = d.get("seo_description") or d.get("tagline") or ""
    n = len(title)
    add("ok" if 30 <= n <= 60 else "warn", f"Search title is {n} characters (30 to 60 shows in full on Google)" + ("" if d.get("seo_title") else ", made from the name because none is written"))
    n = len(desc)
    add("ok" if 70 <= n <= 160 else ("bad" if n == 0 else "warn"), f"Search description is {n} characters (70 to 160 shows in full)" + ("" if d.get("seo_description") else ", taken from the summary because none is written"))
    keyword = (d.get("seo_keywords") or "").split(",")[0].strip().lower()
    if keyword:
        first = (d.get("intro") or "").split("\n")[0].lower()
        for where, text in (("the search title", title), ("the search description", desc), ("the first paragraph", first)):
            add("ok" if keyword in text.lower() else "warn", f'The main keyword "{keyword}" ' + ("is in " if keyword in text.lower() else "is not in ") + where)
    else:
        add("warn", "No keywords are written; the first one is treated as the main one")
    words = _words(d.get("intro", "")) + sum(_words(x) for x in d.get("deliverables", []) + d.get("audience", []) + d.get("limits", [])) + sum(_words(s.get("text", "")) for s in d.get("steps", [])) + sum(_words(f.get("a", "")) for f in d.get("faqs", []))
    add("ok" if words >= 200 else "warn", f"The page has about {words} words (200 or more reads as a full page)")
    add("ok" if len(d.get("faqs", [])) >= 2 else "warn", f"{len(d.get('faqs', []))} question(s) with answers (two or more can show as questions on Google)")
    add("ok" if len(d.get("deliverables", [])) >= 3 else "warn", f"{len(d.get('deliverables', []))} point(s) on what the client receives (three or more reads as concrete)")
    add("ok" if d.get("related") else "warn", "Links to related services: " + (", ".join(d["related"]) if d.get("related") else "none yet (links help visitors and search engines move between pages)"))
    add("ok" if len(d.get("slug", "")) <= 60 else "warn", f"Web address /services/{d.get('slug', '')} is {len(d.get('slug', ''))} characters (short and readable is better)")
    if d.get("noindex"):
        add("bad", "The page is set to stay out of search results")
    for o in others or []:
        if o.get("id") != d.get("id") and o.get("status") == "published":
            if d.get("seo_title") and d["seo_title"].strip().lower() == (o.get("seo_title") or "").strip().lower():
                add("bad", f'The search title is the same as "{o["name"]}"; every page needs its own')
            if d.get("seo_description") and d["seo_description"].strip().lower() == (o.get("seo_description") or "").strip().lower():
                add("bad", f'The search description is the same as "{o["name"]}"; every page needs its own')
    return checks


# ----------------------------------------------------------------------------------------------- HTML
def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _ld(data: Any) -> str:
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{body}</script>'


def _paras(text: str) -> str:
    return "".join(f"<p>{_e(p.strip())}</p>" for p in re.split(r"\n\s*\n|\n", text or "") if p.strip())


ORG = {"@type": "Organization", "name": "StatAxis", "url": BASE_URL + "/", "logo": BASE_URL + "/assets/stataxis-logo.svg", "email": CONTACT}


def _document(*, title: str, description: str, path: str, canonical: str, robots: str, ld: list[Any], body: str, keywords: str = "", og_type: str = "website") -> str:
    meta = f'<meta name="keywords" content="{_e(keywords)}">' if keywords else ""
    return ('<!doctype html><html lang="en-IN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)}</title><meta name="description" content="{_e(description)}">{meta}<meta name="robots" content="{robots}"><meta name="theme-color" content="#05070b">'
            f'<link rel="canonical" href="{_e(canonical)}"><meta property="og:site_name" content="StatAxis"><meta property="og:locale" content="en_IN"><meta property="og:type" content="{og_type}">'
            f'<meta property="og:title" content="{_e(title)}"><meta property="og:description" content="{_e(description)}"><meta property="og:url" content="{_e(canonical)}">'
            f'<meta name="twitter:card" content="summary"><meta name="twitter:site" content="@stataxis"><meta name="twitter:title" content="{_e(title)}"><meta name="twitter:description" content="{_e(description)}">'
            '<link rel="stylesheet" href="/site.css"><link rel="stylesheet" href="/tech.css">' + "".join(_ld(x) for x in ld) + '</head><body class="sx-site"><div id="nav"></div>' + body
            + '<div id="footer"></div><script src="/site.js"></script><script src="/tech.js"></script></body></html>')


def _cta(subject: str) -> str:
    return ('<section class="vx-sec"><div class="vx-wrap"><div class="vx-partner" style="grid-template-columns:1fr"><div style="position:relative"><h2 class="vx-h2" style="font-size:clamp(30px,4vw,56px)">Bring us the question.</h2>'
            '<p class="vx-sub">Name the decision, the people and the date. We write the question back in a form the data can answer.</p><div class="vx-actions"><a class="vx-btn solid" href="/apply">Get early access <span class="arr">→</span></a>'
            f'<a class="vx-btn" href="mailto:{CONTACT}?subject={_e(subject.replace(" ", "%20"))}">{CONTACT}</a></div></div></div></div></section>')


def _card_list(items: list[str]) -> str:
    return '<ul class="sx-list">' + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def render_service(d: dict[str, Any], published: list[dict[str, Any]], *, preview: bool = False) -> str:
    url = f"{BASE_URL}/services/{d['slug']}"
    canonical = d.get("canonical_url") or url
    title = d.get("seo_title") or f"{d['name']} | StatAxis"
    description = d.get("seo_description") or d.get("tagline") or d["name"]
    related = [x for x in published if x["slug"] in d.get("related", []) and x["slug"] != d["slug"]]
    steps = "".join(f'<article class="sx-card"><span class="num">{i:02d}</span><h3>{_e(s["title"])}</h3><p>{_e(s["text"])}</p></article>' for i, s in enumerate(d.get("steps", []), 1))
    faqs = "".join(f'<details><summary><span>{_e(f["q"])}</span><i></i></summary><div class="ans"><p>{_e(f["a"])}</p></div></details>' for f in d.get("faqs", []))
    body = (f'<main class="sx-wrap"><nav class="sx-crumbs" aria-label="Breadcrumb"><a href="/">Home</a><span>/</span><a href="/services">Services</a><span>/</span><b>{_e(d["name"])}</b></nav>'
            f'<section class="sx-hero"><span class="sx-kicker">Service</span><h1>{_e(d["name"])}</h1><p class="sx-lead">{_e(d["tagline"])}</p>'
            f'<div class="sx-actions"><a class="sx-btn" href="mailto:{CONTACT}?subject={_e(("StatAxis%20enquiry%20-%20" + d["name"]).replace(" ", "%20"))}">Discuss this service</a><a class="sx-btn alt" href="/services">All services</a></div></section>'
            f'<section class="sx-section sx-prose">{_paras(d["intro"])}</section>')
    if d.get("audience"):
        body += ('<section class="sx-section"><div class="sx-section-head"><div><span class="sx-kicker">Who it is for</span><h2>Built for teams that need evidence.</h2></div></div><div class="sx-grid four">'
                 + "".join(f'<div class="sx-card"><h3>{_e(a)}</h3></div>' for a in d["audience"]) + "</div></section>")
    if d.get("deliverables"):
        body += f'<section class="sx-section"><div class="sx-section-head"><div><span class="sx-kicker">What you receive</span><h2>Deliverables, named.</h2></div></div><div class="sx-card">{_card_list(d["deliverables"])}</div></section>'
    if steps:
        body += f'<section class="sx-section"><div class="sx-section-head"><div><span class="sx-kicker">How the work runs</span><h2>{len(d["steps"])} steps. No surprises.</h2></div></div><div class="sx-grid">{steps}</div></section>'
    if d.get("limits"):
        body += f'<section class="sx-section"><div class="sx-section-head"><div><span class="sx-kicker">Honest edges</span><h2>What this cannot tell you.</h2></div></div><div class="sx-card">{_card_list(d["limits"])}</div></section>'
    if faqs:
        body += f'<div class="vx-wrap"><div class="vx-sec" style="padding-top:64px"><div class="vx-sec-head"><span>Questions, answered</span></div><h2 class="vx-h2">Straight <em>answers.</em></h2><div class="vx-faq">{faqs}</div></div></div>'
    if related:
        body += ('<section class="sx-section"><div class="sx-section-head"><div><span class="sx-kicker">Related services</span><h2>Often used together.</h2></div></div><div class="sx-grid">'
                 + "".join(f'<a class="sx-card sx-linkcard" href="/services/{_e(r["slug"])}"><h3>{_e(r["name"])}</h3><p>{_e(r["tagline"])}</p><span class="sx-more">Read more →</span></a>' for r in related) + "</div></section>")
    body += f'<p class="sx-note">{_e(services_seed.COVERAGE_NOTE)}</p>' + _cta("StatAxis enquiry - " + d["name"]) + "</main>"
    ld: list[Any] = [
        {"@context": "https://schema.org", "@type": "Service", "name": d["name"], "description": description, "serviceType": d["name"], "url": url, "provider": ORG, "areaServed": {"@type": "Country", "name": "India"},
         "audience": {"@type": "Audience", "audienceType": ", ".join(d.get("audience", []))},
         "hasOfferCatalog": {"@type": "OfferCatalog", "name": f"{d['name']}: what you receive", "itemListElement": [{"@type": "Offer", "itemOffered": {"@type": "Service", "name": x}} for x in d.get("deliverables", [])]}},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": "Home", "item": BASE_URL + "/"},
         {"@type": "ListItem", "position": 2, "name": "Services", "item": BASE_URL + "/services"}, {"@type": "ListItem", "position": 3, "name": d["name"], "item": url}]},
    ]
    if d.get("faqs"):
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in d["faqs"]]})
    robots = "noindex,follow" if (d.get("noindex") or preview) else "index,follow,max-image-preview:large,max-snippet:-1"
    return _document(title=title, description=description, path=f"/services/{d['slug']}", canonical=canonical, robots=robots, ld=ld, body=body, keywords=d.get("seo_keywords", ""))


def render_index(published: list[dict[str, Any]], page: dict[str, str]) -> str:
    cards = "".join(f'<a class="sx-card sx-linkcard" href="/services/{_e(s["slug"])}"><span class="num">{i:02d}</span><h3>{_e(s["name"])}</h3><p>{_e(s["tagline"])}</p><span class="sx-more">Read more →</span></a>'
                    for i, s in enumerate(published, 1))
    body = (f'<main class="sx-wrap"><nav class="sx-crumbs" aria-label="Breadcrumb"><a href="/">Home</a><span>/</span><b>Services</b></nav><section class="sx-hero"><span class="sx-kicker">{_e(page["kicker"])}</span>'
            f'<h1>{_e(page["heading"])}</h1><p class="sx-lead">{_e(page["lead"])}</p><div class="sx-actions"><a class="sx-btn" href="mailto:{CONTACT}?subject=StatAxis%20services%20enquiry">Discuss a requirement</a>'
            f'<a class="sx-btn alt" href="/solutions">Corporate solutions</a></div></section><section class="sx-section"><div class="sx-grid">{cards}</div></section>'
            f'<p class="sx-note">{_e(services_seed.COVERAGE_NOTE)}</p>{_cta("StatAxis services enquiry")}</main>')
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": page["seo_title"], "description": page["seo_description"], "url": BASE_URL + "/services", "publisher": ORG,
           "mainEntity": {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": i, "name": s["name"], "url": f"{BASE_URL}/services/{s['slug']}"} for i, s in enumerate(published, 1)]}},
          {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": "Home", "item": BASE_URL + "/"},
           {"@type": "ListItem", "position": 2, "name": "Services", "item": BASE_URL + "/services"}]}, {"@context": "https://schema.org", **ORG}]
    return _document(title=page["seo_title"], description=page["seo_description"], path="/services", canonical=BASE_URL + "/services", robots="index,follow,max-image-preview:large,max-snippet:-1", ld=ld, body=body)


# ----------------------------------------------------------------------------------------------- sitemap, robots, llms.txt
def sitemap_xml(session: Any) -> str:
    rows = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">', f"<url><loc>{BASE_URL}/</loc><priority>1.0</priority></url>"]
    for path, priority in STATIC_PAGES:
        if (DASHBOARD / (path.lstrip("/") + ".html")).is_file():
            rows.append(f"<url><loc>{BASE_URL}{path}</loc><priority>{priority}</priority></url>")
    published = [s for s in list_services(session, published_only=True) if not s["noindex"]]
    if published:
        latest = max(s["updated_at"] or "" for s in published)[:10]
        rows.append(f"<url><loc>{BASE_URL}/services</loc>{'<lastmod>' + latest + '</lastmod>' if latest else ''}<priority>0.9</priority></url>")
    for s in published:
        if s["canonical_url"] and s["canonical_url"] != f"{BASE_URL}/services/{s['slug']}":
            continue   # a page that points to another address as its canonical is not listed under its own
        rows.append(f"<url><loc>{BASE_URL}/services/{_e(s['slug'])}</loc><lastmod>{(s['updated_at'] or '')[:10]}</lastmod><priority>0.8</priority></url>")
    for f in sorted((DASHBOARD / "blog").glob("*.html")):
        rows.append(f"<url><loc>{BASE_URL}/blog/{f.stem}</loc><priority>0.6</priority></url>")
    from api import blog_cms   # the articles written in the workspace (imported here: blog_cms builds on this module)
    for p in blog_cms.live_posts(session):
        if not p["noindex"] and (not p["canonical_url"] or p["canonical_url"] == f"{BASE_URL}/blog/{p['slug']}"):
            rows.append(f"<url><loc>{BASE_URL}/blog/{_e(p['slug'])}</loc><lastmod>{(p['updated_at'] or '')[:10]}</lastmod><priority>0.6</priority></url>")
    rows.append("</urlset>")
    return "\n".join(rows) + "\n"


def robots_txt() -> str:
    return "\n".join(["User-agent: *", "Allow: /", "Disallow: /workspace", "Disallow: /admin", "Disallow: /login", "Disallow: /forgot", "Disallow: /api/", "Disallow: /demo-api/", "", f"Sitemap: {BASE_URL}/sitemap.xml", ""])


def llms_txt(session: Any) -> str:
    lines = ["# StatAxis", "", "> Digital media market intelligence: measured audiences, the STX Index, the IFX Score, and research and advisory services. Platform data is YouTube today; other platforms follow the published roadmap.", "",
             "## Services", ""]
    for s in list_services(session, published_only=True):
        if not s["noindex"]:
            lines.append(f"- [{s['name']}]({BASE_URL}/services/{s['slug']}): {s['tagline']}")
    from api import blog_cms
    articles = [p for p in blog_cms.live_posts(session) if not p["noindex"]]
    if articles:
        lines += ["", "## Articles", ""] + [f"- [{p['title']}]({BASE_URL}/blog/{p['slug']}): {p['excerpt']}" for p in articles]
    lines += ["", "## Main pages", "", f"- [Platform]({BASE_URL}/platform)", f"- [Solutions]({BASE_URL}/solutions)", f"- [Research]({BASE_URL}/research)", f"- [Methodology]({BASE_URL}/methodology)", f"- [Contact]({CONTACT})", ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------- serving
_CACHE: dict[tuple[int, str], tuple[float, int, str, bytes, str]] = {}
CACHE_SECONDS = 30


def invalidate() -> None:
    _CACHE.clear()


def find_moved(session: Any, slug: str) -> tuple[str, str | None]:
    """What to answer for an address that is not a live service: ('moved', new slug), ('gone', None) for one that was deleted, or ('missing', None)."""
    last = session.query(ServiceRevision).filter(ServiceRevision.slug == slug, ServiceRevision.service_id.isnot(None)).order_by(ServiceRevision.id.desc()).first()
    if last is None:
        return "missing", None
    if last.action == "delete":
        return "gone", None
    row = session.get(Service, last.service_id)
    if row is None:
        return "gone", None   # it moved once and was deleted later: the old address is gone too
    if row.status == "published" and row.slug != slug:
        return "moved", row.slug
    return "missing", None


def respond(session: Any, key: int, path: str) -> tuple[int, str, bytes, str, str | None] | None:
    """The answer for one public address: (status, content type, body, etag, redirect target) or None when the path is not one of ours."""
    if path not in {"/services", "/sitemap.xml", "/robots.txt", "/llms.txt"} and not path.startswith("/services/"):
        return None
    hit = _CACHE.get((key, path))
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2], hit[3], hit[4], None
    status, ctype, location = 200, "text/html; charset=utf-8", None
    if path == "/robots.txt":
        text, ctype = robots_txt(), "text/plain; charset=utf-8"
    elif path == "/sitemap.xml":
        text, ctype = sitemap_xml(session), "application/xml; charset=utf-8"
    elif path == "/llms.txt":
        text, ctype = llms_txt(session), "text/plain; charset=utf-8"
    elif path == "/services":
        text = render_index(list_services(session, published_only=True), page_settings(session))
    else:
        slug = path[len("/services/"):]
        if slug.endswith("/") and slug.strip("/"):
            return 301, "text/plain; charset=utf-8", b"", "", "/services/" + slug.strip("/")
        published = list_services(session, published_only=True)
        found = next((s for s in published if s["slug"] == slug), None)
        if found is not None:
            text = render_service(found, published)
        else:
            kind, target = find_moved(session, slug)
            if kind == "moved":
                return 301, "text/plain; charset=utf-8", b"", "", f"/services/{target}"
            status, text = (410, "<!doctype html><title>Gone</title><p>This service page was removed.</p>") if kind == "gone" else (404, "<!doctype html><title>Not found</title><p>Not found.</p>")
    body = text.encode("utf-8")
    etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
    if status == 200:
        _CACHE[(key, path)] = (time.monotonic(), status, ctype, body, etag)
    return status, ctype, body, etag, location


def public_list(session: Any) -> dict[str, Any]:
    return {"services": [{"slug": s["slug"], "name": s["nav_label"], "tagline": s["tagline"]} for s in list_services(session, published_only=True)]}
