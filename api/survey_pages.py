"""The pages of the polls and surveys that anyone may open: the page where a respondent answers, the page of public results, and the list of open polls.

The page is written by the server (title, description, canonical address, robots) and the form is drawn by a small script from the survey's definition, which is embedded in the page. Every text the administrator
wrote reaches the page through `textContent`, never as markup, so nothing typed into a survey can run as code.
"""

from __future__ import annotations

import html
import json
from typing import Any

from api import services_cms as sc

CSS = """:root{--bg:#061322;--panel:#0b1b2b;--line:#20394e;--blue:#159de8;--gold:#e1b94f;--text:#e8f0f8;--muted:#8ba3b9;--red:#f2b3b3;--green:#8fdcb4}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 Manrope,Inter,system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:28px 18px 60px}.brand{display:flex;align-items:center;gap:10px;margin-bottom:22px}.brand img{height:30px}.brand span{color:var(--muted);font-size:13px}h1{font-size:clamp(26px,5vw,36px);line-height:1.2;margin:0 0 10px}
.lead{color:#c4d2e1;margin:0 0 6px}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px;margin:16px 0}.q h3{font-size:18px;margin:0 0 4px}.q .help{color:var(--muted);font-size:14px;margin:0 0 12px}.q.err{border-color:#b65b5b}.errmsg{color:var(--red);font-size:14px;margin-top:8px}
.opt{display:flex;gap:10px;align-items:flex-start;padding:11px 12px;border:1px solid var(--line);border-radius:10px;margin:8px 0;cursor:pointer;background:#071727}.opt:hover{border-color:var(--blue)}.opt input{margin-top:4px;accent-color:var(--blue)}.opt.on{border-color:var(--blue);background:#0b2740}
.scale{display:flex;flex-wrap:wrap;gap:8px}.scale button{min-width:46px;padding:11px 0;border-radius:10px;border:1px solid var(--line);background:#071727;color:var(--text);font:inherit;cursor:pointer}.scale button.on{background:var(--blue);border-color:var(--blue);color:#021018;font-weight:800}.lbls{display:flex;justify-content:space-between;color:var(--muted);font-size:13px;margin-top:6px}
input[type=text],input[type=number],input[type=tel],input[type=email],textarea,select{width:100%;padding:12px 13px;border-radius:10px;border:1px solid var(--line);background:#071727;color:var(--text);font:inherit}textarea{min-height:110px}
.btn{display:inline-block;padding:13px 22px;border-radius:10px;border:0;background:var(--blue);color:#021018;font:inherit;font-weight:800;cursor:pointer}.btn.alt{background:transparent;border:1px solid var(--line);color:var(--text);font-weight:600}.btn:disabled{opacity:.6;cursor:wait}
.rank{display:flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;margin:8px 0;background:#071727}.rank b{width:24px;color:var(--gold)}.rank span{flex:1}.rank button{padding:4px 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--text);cursor:pointer}
.msg{padding:14px;border-radius:12px;margin:16px 0;border:1px solid var(--line)}.msg.ok{border-color:#2f7d5b;color:var(--green)}.note{color:var(--muted);font-size:13px;margin-top:22px}.bar{height:10px;border-radius:6px;background:#11283d;overflow:hidden;margin:6px 0 2px}.bar i{display:block;height:100%;background:var(--blue)}
.res .row{margin:12px 0}.res .row div.t{display:flex;justify-content:space-between;gap:12px}.hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}.chip{display:inline-block;padding:2px 10px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:12px;margin-right:6px}
a{color:var(--blue)}.list a.card{display:block;text-decoration:none;color:inherit}.list a.card:hover{border-color:var(--blue)}.list h3{margin:6px 0}.list p{margin:0;color:#b7c3d4}"""

JS_COMMON = r"""
const $ = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
function resultsView(res) { const w = $("div", "res"); w.append($("p", "note", res.n + (res.n === 1 ? " answer. " : " answers. ") + res.note));
  for (const q of res.questions) { const c = $("div", "card"); c.append($("h3", "", q.text)); if (q.options) for (const o of q.options) { const r = $("div", "row"), t = $("div", "t"); t.append($("span", "", o.text), $("b", "", o.pct + "%")); const b = $("div", "bar"), i = $("i"); i.style.width = Math.min(100, o.pct) + "%"; b.append(i); r.append(t, b); c.append(r); }
    else if (q.mean != null) c.append($("p", "", "Average: " + q.mean + (q.nps ? ". NPS: " + q.nps.score : ""))); w.append(c); } return w; }
"""

JS = "(() => {" + JS_COMMON + r"""
const D = JSON.parse(document.getElementById("def").textContent), S = D.strings, root = document.getElementById("form");
const ans = {}, touched = {}, errs = {}, key = "sxs_" + D.slug;
let token = ""; try { token = localStorage.getItem(key) || ""; if (!token) { token = Array.from(crypto.getRandomValues(new Uint8Array(18)), b => b.toString(16).padStart(2, "0")).join(""); localStorage.setItem(key, token); } } catch (e) { token = Array.from({length: 36}, () => Math.floor(Math.random() * 16).toString(16)).join(""); }
const started = Date.now(), invite = new URLSearchParams(location.search).get("i") || "", qs = D.questions, shuffle = a => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const vals = id => { const a = ans[id]; if (!a) return []; if (a.o != null) return [].concat(a.o).map(String); if (a.n != null) return [String(a.n)]; return []; };
const shown = q => !q.show_if || ((v) => q.show_if.op === "is" ? v : !v)(vals(q.show_if.q).some(x => q.show_if.values.includes(x)));
const nodes = {};
const fix = o => o.other || o.exclusive;
function opts(q) { const list = q.options.slice(); if (!q.randomize) return list; const fixed = list.filter(fix), free = shuffle(list.filter(o => !fix(o))); return free.concat(fixed); }
function setA(q, v) { if (v == null || (Array.isArray(v.o) && !v.o.length)) delete ans[q.id]; else ans[q.id] = v; delete errs[q.id]; refresh(); }
function build(q) {
  const box = $("div", "card q"); nodes[q.id] = box;
  if (q.type === "section") { box.className = "q"; box.append($("h2", "", q.text)); if (q.help) box.append($("p", "help", q.help)); return box; }
  box.append($("h3", "", q.text + (q.required ? " *" : ""))); if (q.help) box.append($("p", "help", q.help));
  const body = $("div"); box.append(body); const err = $("div", "errmsg"); err.hidden = true; box.append(err); box._err = err;
  if (q.type === "single" || q.type === "multi") {
    const multi = q.type === "multi", labels = [], other = $("input"); other.type = "text"; other.placeholder = S.other; other.maxLength = 300; other.hidden = true; other.oninput = () => { const cur = ans[q.id]; if (cur) cur.t = other.value; };
    for (const o of opts(q)) { const l = $("label", "opt"), i = $("input"); i.type = multi ? "checkbox" : "radio"; i.name = q.id; i.value = o.id; l.append(i, $("span", "", o.text)); labels.push([l, i, o]); body.append(l);
      i.onchange = () => { let cur = [].concat((ans[q.id] || {}).o || []).filter(x => x !== undefined);
        if (multi) { if (i.checked) { cur = o.exclusive ? [o.id] : cur.filter(x => !(q.options.find(z => z.id === x) || {}).exclusive).concat(o.id); if (q.max_select && cur.length > q.max_select) { i.checked = false; cur = cur.filter(x => x !== o.id); showErr(q, S.select_up_to + " " + q.max_select + "."); } } else cur = cur.filter(x => x !== o.id); } else cur = [o.id];
        const hasOther = cur.some(x => (q.options.find(z => z.id === x) || {}).other); other.hidden = !hasOther;
        labels.forEach(([ll, ii]) => { ii.checked = cur.includes(ii.value); ll.classList.toggle("on", ii.checked); });
        setA(q, cur.length ? Object.assign({o: multi ? cur : cur[0]}, hasOther ? {t: other.value} : {}) : null); }; }
    body.append(other);
  } else if (q.type === "dropdown") {
    const s = $("select"), other = $("input"); s.append(Object.assign($("option", "", S.choose), {value: ""})); for (const o of opts(q)) s.append(Object.assign($("option", "", o.text), {value: o.id}));
    other.type = "text"; other.placeholder = S.other; other.hidden = true; other.maxLength = 300; other.oninput = () => { if (ans[q.id]) ans[q.id].t = other.value; };
    s.onchange = () => { const o = q.options.find(z => z.id === s.value); other.hidden = !(o && o.other); setA(q, s.value ? Object.assign({o: s.value}, o && o.other ? {t: other.value} : {}) : null); }; body.append(s, other);
  } else if (q.type === "rating" || q.type === "nps") {
    const lo = q.type === "nps" ? 0 : 1, hi = q.type === "nps" ? 10 : q.scale_max, row = $("div", "scale");
    for (let v = lo; v <= hi; v++) { const b = $("button", "", String(v)); b.type = "button"; b.onclick = () => { row.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); setA(q, {n: v}); }; row.append(b); }
    body.append(row); if (q.label_low || q.label_high) { const l = $("div", "lbls"); l.append($("span", "", q.label_low || ""), $("span", "", q.label_high || "")); body.append(l); }
  } else if (q.type === "number") { const i = $("input"); i.type = "number"; i.step = "any"; if (q.min != null) i.min = q.min; if (q.max != null) i.max = q.max; i.oninput = () => setA(q, i.value === "" ? null : {n: Number(i.value)}); body.append(i); if (q.unit) body.append($("div", "help", q.unit));
  } else if (q.type === "text" || q.type === "longtext") { const i = $(q.type === "text" ? "input" : "textarea"); if (q.type === "text") i.type = "text"; i.maxLength = q.max_length || 300; i.oninput = () => setA(q, i.value.trim() ? {t: i.value} : null); body.append(i);
  } else if (q.type === "ranking") {
    let order = opts(q).map(o => o.id); const list = $("div"); const draw = () => { list.textContent = ""; order.forEach((id, n) => { const o = q.options.find(z => z.id === id), r = $("div", "rank"), up = $("button", "", "↑"), dn = $("button", "", "↓"); up.type = dn.type = "button"; r.append($("b", "", String(n + 1)), $("span", "", o.text), up, dn);
      up.onclick = () => { if (n) { [order[n - 1], order[n]] = [order[n], order[n - 1]]; touched[q.id] = 1; setA(q, {o: order.slice()}); draw(); } }; dn.onclick = () => { if (n < order.length - 1) { [order[n + 1], order[n]] = [order[n], order[n + 1]]; touched[q.id] = 1; setA(q, {o: order.slice()}); draw(); } }; list.append(r); }); };
    draw(); const first = $("button", "btn alt", S.one_per_rank); first.type = "button"; first.onclick = () => { touched[q.id] = 1; setA(q, {o: order.slice()}); first.hidden = true; }; body.append(list, first);
  }
  return box;
}
function showErr(q, m) { const b = nodes[q.id]; if (!b) return; b.classList.add("err"); b._err.hidden = false; b._err.textContent = m; }
function refresh() { for (const q of qs) { const b = nodes[q.id]; if (!b) continue; const s = shown(q); b.hidden = !s; if (!s && ans[q.id]) delete ans[q.id]; if (s && !errs[q.id]) { b.classList.remove("err"); if (b._err) b._err.hidden = true; } } }
const contact = {};
function render() {
  const head = $("div"); head.append($("h1", "", D.title)); for (const p of (D.intro || D.description || "").split(/\n+/).filter(Boolean)) head.append($("p", "lead", p)); root.append(head);
  if (D.closed) { const m = $("div", "msg", D.closed); root.append(m); return; }
  const hp = $("div", "hp"), hpi = $("input"); hpi.type = "text"; hpi.tabIndex = -1; hpi.autocomplete = "off"; hpi.name = "website"; hp.append(hpi); root.append(hp);
  for (const q of qs) root.append(build(q));
  let consent = null;
  if (D.contact.mode !== "none") { const c = $("div", "card q"); c.append($("h3", "", D.contact.mode === "required" ? "*" : "")); c.firstChild.textContent = ""; const labels = {name: S.name, mobile: S.mobile, email: S.email};
    for (const f of D.contact.fields) { const i = $("input"); i.type = f === "email" ? "email" : f === "mobile" ? "tel" : "text"; i.placeholder = labels[f]; i.maxLength = 160; i.style.marginBottom = "10px"; i.oninput = () => { contact[f] = i.value; }; c.append(i); }
    const l = $("label", "opt"); consent = $("input"); consent.type = "checkbox"; l.append(consent, $("span", "", D.contact.consent || S.consent)); c.append(l); const e = $("div", "errmsg"); e.hidden = true; c._err = e; c.append(e); nodes.__contact = c; root.append(c); }
  const go = $("button", "btn", S.submit); go.type = "button"; root.append(go); const top = $("div", "errmsg"); top.hidden = true; root.append(top);
  go.onclick = async () => {
    for (const q of qs) { delete errs[q.id]; if (nodes[q.id] && nodes[q.id]._err) { nodes[q.id]._err.hidden = true; nodes[q.id].classList.remove("err"); } }
    let bad = null; for (const q of qs) { if (q.type === "section" || !shown(q)) continue; const a = ans[q.id]; if (q.required && (!a || (q.type === "ranking" && !touched[q.id]))) { showErr(q, S.required); errs[q.id] = 1; bad = bad || q; } }
    if (bad) { nodes[bad.id].scrollIntoView({behavior: "smooth", block: "center"}); return; }
    go.disabled = true; top.hidden = true;
    try {
      const r = await fetch("/api/v1/public/survey/" + encodeURIComponent(D.slug) + "/respond", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({answers: ans, contact: D.contact.mode !== "none" ? contact : undefined, consent: consent ? consent.checked : false, token, started_ms: started, invite, hp: hpi.value})});
      let d = {}; try { d = await r.json(); } catch (e) {}
      if (!r.ok) { if (d.errors) { for (const [id, m] of Object.entries(d.errors)) { if (id === "contact" && nodes.__contact) { nodes.__contact._err.hidden = false; nodes.__contact._err.textContent = m; } else { const q = qs.find(z => z.id === id); if (q) showErr(q, m); } } } top.hidden = false; top.textContent = d.error || "Something went wrong."; go.disabled = false; return; }
      root.textContent = ""; root.append($("h1", "", D.title), Object.assign($("div", "msg ok"), {textContent: D.thank_you}));
      if (D.results_mode === "after_vote") { const rr = await fetch("/api/v1/public/survey/" + encodeURIComponent(D.slug) + "/results"); if (rr.ok) { const res = await rr.json(); if (!res.waiting) root.append(resultsView(res)); } }
      if (D.redirect_url) { const a = $("a", "btn alt", "Continue"); a.href = D.redirect_url; root.append(a); }
    } catch (e) { top.hidden = false; top.textContent = "Could not reach the server. Please try again."; go.disabled = false; }
  };
  refresh();
}
render();
})();"""


def _json_script(element_id: str, data: Any) -> str:
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/json" id="{element_id}">{body}</script>'


def _shell(title: str, description: str, path: str, robots: str, body: str, extra_head: str = "") -> str:
    e = sc._e
    canonical = sc.BASE_URL + path
    return ('<!doctype html><html lang="en-IN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><meta name="description" content="{e(description)}"><meta name="robots" content="{robots}"><meta name="theme-color" content="#061322"><link rel="canonical" href="{e(canonical)}">'
            f'<meta property="og:site_name" content="StatAxis"><meta property="og:type" content="website"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(description)}"><meta property="og:url" content="{e(canonical)}">'
            f'<meta name="twitter:card" content="summary"><link rel="icon" href="/assets/stataxis-favicon.svg"><style>{CSS}</style>{extra_head}</head><body><main>'
            '<div class="brand"><a href="/"><img src="/assets/stataxis-logo.svg" alt="StatAxis"></a></div>' + body + "</main></body></html>")


def survey_page(defn: dict[str, Any], closed_text: str | None, *, indexable: bool) -> str:
    e = sc._e
    data = {**defn, "closed": closed_text}
    title = f"{defn['title']} | StatAxis"
    desc = defn["description"] or defn["intro"][:150] or f"{defn['title']}: a short {defn['kind']} by StatAxis."
    strings = defn["strings"]
    body = (f'<div id="form"></div><p class="note">{e(strings["private_note"] if defn["contact"]["mode"] == "none" else "")}</p>'
            + (f'<p class="note">{e(defn["sponsor"])}</p>' if defn["sponsor"] else "")
            + f'<p class="note">{e(strings["powered"])}</p>' + _json_script("def", data) + f"<script>{JS}</script>")
    return _shell(title, desc, f"/survey/{defn['slug']}", "index,follow" if indexable else "noindex,nofollow", body)


def results_page(row_title: str, slug: str, res: dict[str, Any] | None, lang_results: str) -> str:
    e = sc._e
    if res is None:
        body = f'<h1>{e(row_title)}</h1><div class="msg">The results of this poll are not public.</div><p><a href="/survey/{e(slug)}">Back to the poll</a></p>'
        return _shell(f"{row_title} | StatAxis", "Results are not public.", f"/survey/{slug}/results", "noindex,nofollow", body)
    if res.get("waiting"):
        body = f'<h1>{e(row_title)}</h1><div class="msg">The results will show after {res["needed"]} answers. So far: {res["have"]}.</div><p><a href="/survey/{e(slug)}">Back to the poll</a></p>'
        return _shell(f"{row_title} | StatAxis", "Results are not ready.", f"/survey/{slug}/results", "noindex,nofollow", body)
    facts = []
    if res.get("sponsor"):
        facts.append(f"Commissioned by: {res['sponsor']}.")
    if res.get("first") and res.get("last"):
        facts.append(f"Answers collected between {res['first'][:10]} and {res['last'][:10]}.")
    if res.get("method_note"):
        facts.append(res["method_note"])
    body = (f'<h1>{e(row_title)}: results</h1><div id="results" class="res"></div><div class="card"><b>About these results</b><p class="note" style="margin-top:6px">{e(res["note"])} '
            + e(" ".join(facts)) + f'</p></div><p><a href="/survey/{e(slug)}">Back to the poll</a></p>' + _json_script("resdata", res))
    script = "(() => {" + JS_COMMON + "document.getElementById('results').append(resultsView(JSON.parse(document.getElementById('resdata').textContent)));})();"
    return _shell(f"{row_title}: results | StatAxis", f"Results of the poll {row_title}, with how many answered and how the poll was run.", f"/survey/{slug}/results", "noindex,follow",
                  body + f"<script>{script}</script>")


def polls_index(items: list[dict[str, Any]]) -> str:
    e = sc._e
    cards = "".join(f'<a class="card" href="/survey/{e(i["slug"])}"><span class="chip">{e(i["category"])}</span><span class="chip">{e(i["kind"])}</span><h3>{e(i["title"])}</h3><p>{e(i["description"])}</p></a>' for i in items)
    body = ('<h1>Polls and surveys</h1><p class="lead">Open polls and surveys run by StatAxis. Your answers are anonymous unless a survey asks for contact details and tells you why.</p>'
            f'<div class="list">{cards or "<div class=msg>No poll is open right now.</div>"}</div><p class="note">Polls collect the answers of people who choose to take part. Unless a poll says it uses a random sample, its results describe those who answered, not everyone.</p>')
    return _shell("Polls and surveys | StatAxis", "Open polls and surveys run by StatAxis. Anonymous unless a survey says otherwise.", "/polls", "index,follow" if items else "noindex,follow", body)
