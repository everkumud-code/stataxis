"""The blog (Insights) of the public website, and the small content system behind it.

An administrator writes, schedules, publishes and changes articles in the workspace ("Website blog"); the website shows the live ones at /blog/<address> and in the list on /insights. The six articles that were
built into the site as files are left exactly as they are (search engines already know them): they are listed in the editor, read-only, and their addresses can never be taken by a new article.
Every change is kept whole so an earlier version can be put back. As with the Services, the server writes plain HTML (title, description, canonical address, Open Graph, Article structured data, breadcrumbs,
sitemap, llms.txt, and the right answer for an address that moved, was removed or is not live yet).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from api import services_cms as sc
from collector.storage import Post, PostRevision

RESERVED = {"index", "new", "admin"}
CATEGORY_SUGGESTIONS = ["Media buying", "Audience", "Authenticity", "Creators", "Live", "Method", "Market", "Research", "Product", "Roadmap"]
BULLET, NUMBER = re.compile(r"^[-*]\s+"), re.compile(r"^\d+[.)]\s+")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def is_live(row: Post, now: datetime | None = None) -> bool:
    now = now or _now()
    if row.status == "published":
        return True
    return row.status == "scheduled" and row.publish_at is not None and _aware(row.publish_at) <= now


def builtin_posts() -> list[dict[str, str]]:
    """The articles that live as files in the site: the address and the title the page itself carries."""
    out = []
    for f in sorted((sc.DASHBOARD / "blog").glob("*.html")):
        m = re.search(r"<title>([^<]+)</title>", f.read_text(encoding="utf-8"))
        title = re.sub(r"\s*[—|-]\s*StatAxis\s*$", "", html.unescape(m.group(1))) if m else f.stem
        out.append({"slug": f.stem, "title": title, "url": f"/blog/{f.stem}"})
    return out


def words(text: str) -> int:
    return len(re.findall(r"\w+", re.sub(r"[#>*\[\]()`-]", " ", text or "")))


def minutes(text: str) -> int:
    return max(1, round(words(text) / 200))


def serialize(row: Post, *, now: datetime | None = None) -> dict[str, Any]:
    live = is_live(row, now)
    state = "published" if live else ("scheduled" if row.status == "scheduled" else "draft")
    return {"id": row.id, "slug": row.slug, "title": row.title, "excerpt": row.excerpt, "category": row.category, "author": row.author, "body": row.body, "related": sc._load(row.related_json, []),
            "seo_title": row.seo_title, "seo_description": row.seo_description, "seo_keywords": row.seo_keywords, "canonical_url": row.canonical_url or "", "noindex": bool(row.noindex),
            "status": row.status, "state": state, "live": live, "publish_at": row.publish_at.isoformat() if row.publish_at else None, "published_at": row.published_at.isoformat() if row.published_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "updated_by": row.updated_by,
            "words": words(row.body), "minutes": minutes(row.body)}


# ----------------------------------------------------------------------------------------------- writing
def clean(payload: dict[str, Any], session: Any, current: Post | None) -> dict[str, Any]:
    title = sc._text(payload.get("title"), "the title", 200, required=True)
    slug = sc.slugify(payload.get("slug") or title)
    if not sc.SLUG_RE.fullmatch(slug) or len(slug) < 2:
        raise ValueError("the web address can use only small letters, numbers and hyphens")
    if slug in RESERVED or (sc.DASHBOARD / "blog" / f"{slug}.html").is_file():
        raise ValueError(f'the web address "{slug}" belongs to an article built into the site; choose another')
    other = session.query(Post).filter(Post.slug == slug).first()
    if other is not None and (current is None or other.id != current.id):
        raise ValueError(f'the web address "{slug}" is already used by "{other.title}"')
    body = str(payload.get("body") or "").replace("\r", "").strip()
    if len(body) > 60000:
        raise ValueError(f"the article is too long: {len(body)} characters, the most is 60000")
    known = {s for (s,) in session.query(Post.slug).all()} | {b["slug"] for b in builtin_posts()}
    related = []
    for r in (payload.get("related") or []) if isinstance(payload.get("related"), list) else []:
        r = str(r).strip()
        if r and r != slug and r in known and r not in related:
            related.append(r)
    canonical = sc._text(payload.get("canonical_url"), "the canonical address", 500)
    if canonical:
        parts = urlparse(canonical)
        if parts.scheme != "https" or parts.netloc != urlparse(sc.BASE_URL).netloc:
            raise ValueError(f"the canonical address must be a https address on {urlparse(sc.BASE_URL).netloc}, or empty to use the article's own address")
    return {"slug": slug, "title": title, "excerpt": sc._text(payload.get("excerpt"), "the short summary", 400), "category": sc._text(payload.get("category"), "the category", 60),
            "author": sc._text(payload.get("author"), "the author", 120) or "StatAxis", "body": body, "related": related[:6], "seo_title": sc._text(payload.get("seo_title"), "the search title", 200),
            "seo_description": sc._text(payload.get("seo_description"), "the search description", 400), "seo_keywords": sc._text(payload.get("seo_keywords"), "the keywords", 300),
            "canonical_url": canonical, "noindex": bool(payload.get("noindex"))}


def _parse_when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("the publishing time is not a valid date and time") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _apply(row: Post, data: dict[str, Any]) -> None:
    for key in ("slug", "title", "excerpt", "category", "author", "body", "seo_title", "seo_description", "seo_keywords", "noindex"):
        setattr(row, key, data[key])
    row.canonical_url = data["canonical_url"] or None
    row.related_json = json.dumps(data["related"], ensure_ascii=False)


def _revise(session: Any, row: Post | None, action: str, by: str | None, snapshot: dict[str, Any] | None = None) -> None:
    snap = snapshot if snapshot is not None else serialize(row)
    session.add(PostRevision(post_id=row.id if row is not None else snap.get("id"), slug=row.slug if row is not None else snap.get("slug", ""), action=action, snapshot=json.dumps(snap, ensure_ascii=False), by=by, at=_now()))


def _publishable(data: dict[str, Any]) -> None:
    missing = [label for label, ok in (("a title", data["title"]), ("a short summary", data["excerpt"]), ("the article text (at least 50 words)", words(data["body"]) >= 50)) if not ok]
    if missing:
        raise ValueError("to publish or schedule, the article needs " + ", ".join(missing))


def list_posts(session: Any) -> list[dict[str, Any]]:
    now = _now()
    return [serialize(r, now=now) for r in session.query(Post).order_by(Post.created_at.desc(), Post.id.desc()).all()]


def get_post(session: Any, post_id: int) -> Post:
    row = session.get(Post, post_id)
    if row is None:
        raise LookupError("that article does not exist")
    return row


def save_post(session: Any, by: str, payload: dict[str, Any], post_id: int | None = None) -> dict[str, Any]:
    row = get_post(session, post_id) if post_id else None
    data = clean(payload, session, row)
    status = str(payload.get("status") or (row.status if row else "draft"))
    if status not in {"draft", "published", "scheduled"}:
        raise ValueError("the state must be draft, scheduled or published")
    when = _parse_when(payload.get("publish_at")) if "publish_at" in payload else (_aware(row.publish_at) if row else None)
    if status != "draft":
        _publishable(data)
    if status == "scheduled" and when is None:
        raise ValueError("choose the date and time to publish")
    created = row is None
    if created:
        row = Post(created_at=_now())
        session.add(row)
    elif row.slug != data["slug"] and is_live(row):
        _revise(session, row, "update", by)   # the old address stays in the history, so visitors and search engines are sent to the new one
    before = None if created else row.status
    was_live = False if created else is_live(row)
    _apply(row, data)
    row.status, row.publish_at, row.updated_at, row.updated_by = status, (when if status == "scheduled" else None), _now(), by
    if status == "published":
        row.published_at = row.published_at or _now()
    elif status == "scheduled":
        row.published_at = when
    elif not was_live:
        row.published_at = None
    session.flush()
    if created:
        action = "create"
    elif status == "published" and not was_live:
        action = "publish"
    elif status == "scheduled" and before != "scheduled":
        action = "schedule"
    elif status == "draft" and was_live:
        action = "unpublish"
    else:
        action = "update"
    _revise(session, row, action, by)
    session.commit()
    invalidate()
    sc.invalidate()
    return serialize(row)


def set_status(session: Any, by: str, post_id: int, status: str, publish_at: Any = None) -> dict[str, Any]:
    row = get_post(session, post_id)
    current = serialize(row)
    return save_post(session, by, {**current, "status": status, "publish_at": publish_at or current["publish_at"]}, post_id)


def delete_post(session: Any, by: str, post_id: int) -> dict[str, Any]:
    row = get_post(session, post_id)
    snap = serialize(row)
    _revise(session, row, "delete", by, snap)
    session.delete(row)
    session.commit()
    invalidate()
    sc.invalidate()
    return {"deleted": snap["slug"]}


def revisions(session: Any, post_id: int) -> list[dict[str, Any]]:
    out = []
    for r in session.query(PostRevision).filter(PostRevision.post_id == post_id).order_by(PostRevision.id.desc()).limit(60).all():
        snap = sc._load(r.snapshot, {})
        out.append({"id": r.id, "action": r.action, "by": r.by, "at": r.at.isoformat() if r.at else None, "slug": r.slug, "title": snap.get("title"), "words": snap.get("words")})
    return out


def deleted_revisions(session: Any) -> list[dict[str, Any]]:
    live = {s for (s,) in session.query(Post.slug).all()}
    return [{"id": r.id, "slug": r.slug, "by": r.by, "at": r.at.isoformat() if r.at else None, "title": sc._load(r.snapshot, {}).get("title")}
            for r in session.query(PostRevision).filter(PostRevision.action == "delete").order_by(PostRevision.id.desc()).limit(30).all() if r.slug not in live]


def restore(session: Any, by: str, revision_id: int) -> dict[str, Any]:
    """Put an earlier version back as a draft (nothing goes live by surprise). A deleted article returns as a new one at the same address when it is free."""
    r = session.get(PostRevision, revision_id)
    if r is None:
        raise LookupError("that version does not exist")
    snap = sc._load(r.snapshot, {})
    if not snap.get("title"):
        raise ValueError("that version holds nothing to restore")
    row = session.get(Post, r.post_id) if r.post_id else None
    if row is None:
        row = session.query(Post).filter(Post.slug == snap.get("slug")).first()
    saved = save_post(session, by, {**snap, "status": "draft", "publish_at": None}, row.id if row else None)
    _revise(session, session.get(Post, saved["id"]), "restore", by)
    session.commit()
    return saved


# ----------------------------------------------------------------------------------------------- the search checks
def seo_report(d: dict[str, Any], others: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(level: str, text: str) -> None:
        checks.append({"level": level, "text": text})
    title = d.get("seo_title") or f"{d.get('title', '')} — StatAxis"
    desc = d.get("seo_description") or d.get("excerpt") or ""
    n = len(title)
    add("ok" if 30 <= n <= 60 else "warn", f"Search title is {n} characters (30 to 60 shows in full on Google)" + ("" if d.get("seo_title") else ", made from the title because none is written"))
    n = len(desc)
    add("ok" if 70 <= n <= 160 else ("bad" if n == 0 else "warn"), f"Search description is {n} characters (70 to 160 shows in full)" + ("" if d.get("seo_description") else ", taken from the short summary because none is written"))
    keyword = (d.get("seo_keywords") or "").split(",")[0].strip().lower()
    body = d.get("body", "")
    if keyword:
        first = next((b for b in re.split(r"\n\s*\n", body) if b.strip() and not b.lstrip().startswith("#")), "").lower()
        for where, text in (("the search title", title), ("the search description", desc), ("the first paragraph", first)):
            add("ok" if keyword in text.lower() else "warn", f'The main keyword "{keyword}" ' + ("is in " if keyword in text.lower() else "is not in ") + where)
        density = body.lower().count(keyword)
        add("ok" if density >= 2 else "warn", f"The main keyword appears {density} time(s) in the text (two or more, used naturally)")
    else:
        add("warn", "No keywords are written; the first one is treated as the main one")
    w = words(body)
    add("ok" if w >= 600 else ("bad" if w < 150 else "warn"), f"The article has about {w} words (600 or more ranks best for an explainer; under 150 is too thin)")
    headings = len(re.findall(r"(?m)^##\s+\S", body))
    add("ok" if headings >= 2 else "warn", f"{headings} section heading(s) (two or more make an article easy to scan and to quote)")
    links = len(re.findall(r"\]\(/[^/)]", body))
    add("ok" if links >= 1 else "warn", f"{links} link(s) to other pages of the site (one or more helps readers and search engines move on)")
    add("ok" if d.get("excerpt") else "warn", "A short summary is written (it shows on the Insights list)" if d.get("excerpt") else "No short summary yet (it shows on the Insights list)")
    add("ok" if d.get("category") else "warn", "A category is set" if d.get("category") else "No category is set")
    add("ok" if len(d.get("slug", "")) <= 60 else "warn", f"Web address /blog/{d.get('slug', '')} is {len(d.get('slug', ''))} characters (short and readable is better)")
    if d.get("noindex"):
        add("bad", "The article is set to stay out of search results")
    for o in others or []:
        if o.get("id") != d.get("id") and o.get("live"):
            if d.get("seo_title") and d["seo_title"].strip().lower() == (o.get("seo_title") or "").strip().lower():
                add("bad", f'The search title is the same as "{o["title"]}"; every page needs its own')
            if d.get("seo_description") and d["seo_description"].strip().lower() == (o.get("seo_description") or "").strip().lower():
                add("bad", f'The search description is the same as "{o["title"]}"; every page needs its own')
    return checks


# ----------------------------------------------------------------------------------------------- HTML
_E = sc._e


def _inline(text: str) -> str:
    t = html.escape(text, quote=True)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)

    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if re.match(r"^(https?://|mailto:|/(?!/))", url):
            external = url.startswith(("http://", "https://")) and not url.startswith(sc.BASE_URL)
            return f'<a href="{url}"' + (' rel="noopener noreferrer" target="_blank"' if external else "") + f">{label}</a>"
        return m.group(0)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)


def render_body(text: str) -> str:
    """The article text as HTML: blank lines separate blocks; '## ' and '### ' are headings; '- ' lists; '1. ' numbered lists; '> ' quotes; **bold**, *italic* and [text](address) inside lines. Everything is escaped first."""
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [ln.rstrip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        head = re.match(r"^(#{2,3})\s+(.*)$", lines[0])
        if head:
            level = len(head.group(1))
            out.append(f"<h{level}>{_inline(head.group(2))}</h{level}>")
            lines = lines[1:]
            if not lines:
                continue
        if all(BULLET.match(ln) for ln in lines):
            out.append("<ul>" + "".join("<li>" + _inline(BULLET.sub("", ln)) + "</li>" for ln in lines) + "</ul>")
        elif all(NUMBER.match(ln) for ln in lines):
            out.append("<ol>" + "".join("<li>" + _inline(NUMBER.sub("", ln)) + "</li>" for ln in lines) + "</ol>")
        elif lines[0].startswith(">"):
            out.append("<blockquote>" + _inline(" ".join(re.sub(r"^>\s?", "", ln) for ln in lines)) + "</blockquote>")
        else:
            out.append("<p>" + _inline(" ".join(lines)) + "</p>")
    return "\n".join(out)


def _date(d: dict[str, Any]) -> str:
    return (d.get("published_at") or d.get("updated_at") or "")[:10]


def render_post(d: dict[str, Any], live: list[dict[str, Any]], *, preview: bool = False) -> str:
    url = f"{sc.BASE_URL}/blog/{d['slug']}"
    canonical = d.get("canonical_url") or url
    title = d.get("seo_title") or f"{d['title']} — StatAxis"
    description = d.get("seo_description") or d.get("excerpt") or d["title"]
    published, modified = d.get("published_at") or d.get("updated_at") or "", d.get("updated_at") or d.get("published_at") or ""
    category = d.get("category") or "Insights"
    builtin = {b["slug"]: b for b in builtin_posts()}
    more = []
    for r in d.get("related", []):
        match = next((x for x in live if x["slug"] == r), None)
        if match:
            more.append((f"/blog/{r}", match["title"], match.get("excerpt", "")))
        elif r in builtin:
            more.append((f"/blog/{r}", builtin[r]["title"], ""))
    related = ""
    if more:
        related = ('<section class="vx-wrap" style="padding:10px 0 40px"><div class="vx-sec-head"><span>Keep reading</span></div><div class="vx-posts">'
                   + "".join(f'<a class="vx-post" href="{_E(u)}"><h3>{_E(t)}</h3><p>{_E(x)}</p><span class="more">Read →</span></a>' for u, t, x in more) + "</div></section>")
    body = (f'<main><section class="vx-art-head"><div class="vx-wrap"><div class="vx-eyebrow"><a href="/insights">Insights</a> &nbsp;/&nbsp; {_E(category)}</div><h1 class="vx-h1">{_E(d["title"])}</h1>'
            f'<p class="vx-lead">{_E(d.get("excerpt", ""))}</p><p class="vx-mono" style="margin-top:20px">{_E(d.get("author") or "StatAxis")} · {_E(_date(d))} · {minutes(d.get("body", ""))} min read</p></div></section>'
            f'<article class="vx-prose">{render_body(d.get("body", ""))}</article>{related}'
            '<div class="vx-cta"><div><h3>See it on your own question.</h3><p style="color:#b3bfce;margin:0 0 18px">Tell us the audience, the channels and the date.</p>'
            '<a class="vx-btn solid" href="/apply">Get early access <span class="arr">→</span></a></div></div></main>')
    author = {"@type": "Organization", "name": "StatAxis"} if (d.get("author") or "StatAxis") == "StatAxis" else {"@type": "Person", "name": d["author"]}
    article = {"@context": "https://schema.org", "@type": "Article", "headline": d["title"][:110], "description": description, "datePublished": published[:10], "dateModified": modified[:10], "author": author,
               "publisher": {"@type": "Organization", "name": "StatAxis", "logo": {"@type": "ImageObject", "url": sc.BASE_URL + "/assets/stataxis-logo.svg"}}, "mainEntityOfPage": canonical, "wordCount": words(d.get("body", "")),
               "articleSection": category, "inLanguage": "en-IN"}
    if d.get("seo_keywords"):
        article["keywords"] = d["seo_keywords"]
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": "Home", "item": sc.BASE_URL + "/"},
              {"@type": "ListItem", "position": 2, "name": "Insights", "item": sc.BASE_URL + "/insights"}, {"@type": "ListItem", "position": 3, "name": d["title"], "item": url}]}
    robots = "noindex,follow" if (d.get("noindex") or preview) else "index,follow,max-image-preview:large,max-snippet:-1"
    doc = sc._document(title=title, description=description, path=f"/blog/{d['slug']}", canonical=canonical, robots=robots, ld=[article, crumbs], body=body, keywords=d.get("seo_keywords", ""), og_type="article")
    meta = f'<meta property="article:published_time" content="{_E(published)}"><meta property="article:modified_time" content="{_E(modified)}"><meta property="article:section" content="{_E(category)}">'
    return doc.replace('<link rel="stylesheet" href="/site.css">', meta + '<link rel="stylesheet" href="/site.css">', 1)


def cards(live: list[dict[str, Any]]) -> str:
    """The Insights list entries for the live articles, newest first, in the same look as the built-in ones."""
    return "".join(f'<a class="vx-post rv" href="/blog/{_E(p["slug"])}"><span class="t">{_E(p["category"] or "Insights")}</span><h3>{_E(p["title"])}</h3><p>{_E(p["excerpt"])}</p>'
                   f'<span class="more">{_E(_date(p))} · {p["minutes"]} min read →</span></a>' for p in live)


def live_posts(session: Any) -> list[dict[str, Any]]:
    now = _now()
    rows = [serialize(r, now=now) for r in session.query(Post).all()]
    return sorted((r for r in rows if r["live"]), key=lambda r: (r["published_at"] or "", r["id"]), reverse=True)


def inject_cards(session_factory: Any, body: bytes) -> bytes:
    """The Insights page with the live CMS articles ahead of the built-in ones. Any failure leaves the page exactly as it is."""
    marker = b'<div class="vx-posts">'
    try:
        if marker not in body:
            return body
        session = session_factory()
        try:
            live = live_posts(session)
        finally:
            session.close()
        return body.replace(marker, marker + cards(live).encode("utf-8"), 1) if live else body
    except Exception:
        return body


# ----------------------------------------------------------------------------------------------- serving
_CACHE: dict[tuple[int, str], tuple[float, bytes, str]] = {}


def invalidate() -> None:
    _CACHE.clear()


def respond(session: Any, key: int, path: str) -> tuple[int, str, bytes, str, str | None] | None:
    """The answer for /blog/<address> when the address belongs to a CMS article: (status, content type, body, etag, redirect target); None leaves it to the built-in articles and the 404 page."""
    slug = path[len("/blog/"):]
    if not slug or "/" in slug:
        return None
    hit = _CACHE.get((key, slug))
    if hit and time.monotonic() - hit[0] < sc.CACHE_SECONDS:
        return 200, "text/html; charset=utf-8", hit[1], hit[2], None
    now = _now()
    row = session.query(Post).filter(Post.slug == slug).first()
    if row is not None:
        if not is_live(row, now):
            return 404, "text/html; charset=utf-8", b"<!doctype html><title>Not found</title><p>Not found.</p>", "", None
        live = live_posts(session)
        body = render_post(serialize(row, now=now), [p for p in live if p["slug"] != slug]).encode("utf-8")
        etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
        _CACHE[(key, slug)] = (time.monotonic(), body, etag)
        return 200, "text/html; charset=utf-8", body, etag, None
    last = session.query(PostRevision).filter(PostRevision.slug == slug, PostRevision.post_id.isnot(None)).order_by(PostRevision.id.desc()).first()
    if last is None:
        return None
    current = session.get(Post, last.post_id)
    if current is None:
        return 410, "text/html; charset=utf-8", b"<!doctype html><title>Gone</title><p>This article was removed.</p>", "", None
    if is_live(current, now) and current.slug != slug:
        return 301, "text/plain; charset=utf-8", b"", "", f"/blog/{current.slug}"
    return None
