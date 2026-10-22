/* Website services for the workspace: the administrator writes, orders, publishes and changes the pages of the public Services section, with the search side (title, description, keywords, canonical address,
   index or not) beside each page and a check of what a search engine would make of it. Loaded by workspace.html after social.js; it uses the helpers of workspace.html ($, esc, api, post, head, add, isAdmin, state, adminOnly). */
"use strict";
(() => {
  if (typeof add !== "function") return;
  const when = iso => iso ? new Date(iso).toLocaleString("en-IN", {day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata"}) + " IST" : "—";
  const lines = v => (v || []).join("\n");
  const levelTag = c => `<li class="cmschk ${c.level}">${c.level === "ok" ? "✓" : c.level === "bad" ? "✕" : "!"} ${esc(c.text)}</li>`;
  const checkList = checks => `<ul class="cmschecks">${(checks || []).map(levelTag).join("")}</ul>`;
  const css = document.createElement("style");
  css.textContent = ".cmschecks{list-style:none;margin:8px 0 0;padding:0}.cmschk{padding:4px 0;font-size:13px}.cmschk.ok{color:var(--green)}.cmschk.warn{color:#e3b341}.cmschk.bad{color:var(--red)}"
    + ".cmsgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.cmsgrid label,.cmsrow label{display:block;font-size:13px}.cmsgrid input,.cmsgrid textarea,.cmsrow input,.cmsrow textarea{width:100%;box-sizing:border-box}"
    + ".cmsrow{display:grid;grid-template-columns:1fr 2fr auto;gap:8px;align-items:start;margin:6px 0}.cmssnip{background:#fff;color:#202124;border-radius:8px;padding:12px 14px;max-width:640px;font-family:Arial,sans-serif}"
    + ".cmssnip .t{color:#1a0dab;font-size:19px;line-height:1.3}.cmssnip .u{color:#006621;font-size:13px}.cmssnip .d{color:#545454;font-size:13.5px;line-height:1.5}.cmscount{font-size:12px;color:var(--muted)}"
    + "#cmsform textarea,#blgform textarea,#cmsform input:not([type=checkbox]),#blgform input:not([type=checkbox]){width:100%;box-sizing:border-box}#cmsform label,#blgform label{display:block}"
    + ".cmsmodal{position:fixed;inset:0;z-index:300;background:rgba(3,5,9,.85);display:flex;align-items:center;justify-content:center;padding:20px}.cmsmodal>div{background:#0d121a;border:1px solid #26324a;border-radius:14px;width:min(1100px,100%);height:min(86vh,100%);display:flex;flex-direction:column}"
    + ".cmsmodal header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #26324a}.cmsmodal iframe{flex:1;border:0;background:#05070b;border-radius:0 0 14px 14px}.cmsmodal .body{overflow:auto;padding:14px 16px}";
  document.head.appendChild(css);

  add("adm-services", "Admin", "Website services", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Website services"); return; }
    el.innerHTML = head("Website services", "Write, order and publish the pages of the Services section of the public website. Each page has its own search title, description and address, and every change is kept so an earlier version can be put back.")
      + '<div id="cmsout"></div>';
    const out = $("#cmsout", el);
    const say = (t, ok) => { const m = $("#cmsmsg", el); if (!m) return; m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    let data;

    const draw = async () => {
      data = await api("/api/v1/cms/services");
      const rows = data.services.map((s, i) => `<tr><td>${i + 1}</td><td><b>${esc(s.name)}</b><div class="muted">/services/${esc(s.slug)}</div></td>
        <td>${s.status === "published" ? '<span class="tag green">published</span>' : '<span class="tag">draft</span>'}${s.noindex ? ' <span class="tag red">hidden from Google</span>' : ""}</td>
        <td>${s.seo_problems ? `<span class="tag red">${s.seo_problems} problem${s.seo_problems > 1 ? "s" : ""}</span> ` : ""}${s.seo_warnings ? `<span class="tag">${s.seo_warnings} to improve</span>` : (s.seo_problems ? "" : '<span class="tag green">good</span>')}</td>
        <td class="muted">${when(s.updated_at)}</td>
        <td class="btnrow"><button class="btn" data-up="${s.id}" title="Move up"${i ? "" : " disabled"}>↑</button><button class="btn" data-down="${s.id}" title="Move down"${i < data.services.length - 1 ? "" : " disabled"}>↓</button>
          <button class="btn" data-edit="${s.id}">Edit</button><button class="btn" data-toggle="${s.id}" data-to="${s.status === "published" ? "draft" : "published"}">${s.status === "published" ? "Unpublish" : "Publish"}</button>
          ${s.status === "published" ? `<a class="btn" href="/services/${esc(s.slug)}" target="_blank" rel="noopener">View ↗</a>` : ""}<button class="btn" data-del="${s.id}">Delete</button></td></tr>`).join("");
      const p = data.page, deleted = data.deleted.map(d => `<li>${esc(d.name || d.slug)} <span class="muted">/services/${esc(d.slug)} · deleted ${when(d.at)} by ${esc(d.by || "")}</span> <button class="btn" data-undelete="${d.id}">Bring back as a draft</button></li>`).join("");
      out.innerHTML = `<div id="cmsmsg" class="msg" hidden></div>
        <div class="btnrow" style="margin:12px 0"><button class="btn primary" id="cmsnew">New service</button><button class="btn" id="cmsstart">Add back any starter service that is missing</button><a class="btn" href="/services" target="_blank" rel="noopener">Open the public Services page ↗</a></div>
        <section class="card"><h2>Services (${data.services.length})</h2><div style="overflow:auto"><table><thead><tr><th>#</th><th>Service</th><th>State</th><th>Search</th><th>Changed</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="6">No service yet.</td></tr>'}</tbody></table></div>
          <p class="muted" style="margin-top:8px">The order here is the order on the website and in the menu. Only published services appear on the website, in the menu, in the sitemap and in llms.txt. Search engines learn of a change within the day; the sitemap is at <a href="/sitemap.xml" target="_blank" rel="noopener">/sitemap.xml</a>.</p></section>
        <section class="card" style="margin-top:14px"><h2>The Services page itself</h2><form id="cmspage" class="cmsgrid">
          <label>Small line above the heading<input name="kicker" maxlength="60" value="${esc(p.kicker)}"></label><label>Heading<input name="heading" maxlength="160" value="${esc(p.heading)}"></label>
          <label style="grid-column:1/-1">Introduction under the heading<textarea name="lead" rows="2" maxlength="500">${esc(p.lead)}</textarea></label>
          <label>Search title <span class="cmscount"></span><input name="seo_title" maxlength="200" value="${esc(p.seo_title)}"></label><label>Search description <span class="cmscount"></span><textarea name="seo_description" rows="2" maxlength="400">${esc(p.seo_description)}</textarea></label>
          <div><button class="btn primary" type="submit">Save the page</button></div></form></section>
        ${deleted ? `<section class="card" style="margin-top:14px"><h2>Deleted services</h2><ul>${deleted}</ul><p class="muted">Their old addresses answer "gone" to search engines until a service is brought back.</p></section>` : ""}
        <div id="cmsedit"></div>`;
      wire();
    };
    const run = async (fn, okText) => { try { await fn(); await draw(); say(okText, true); } catch (e) { say(e.message); } };
    const wire = () => {
      $("#cmsnew", out).onclick = () => edit(null);
      $("#cmsstart", out).onclick = () => run(async () => { const r = await post("/api/v1/cms/services/starters", {}); wire.last = r.added.length; }, "Starter services that were missing have been added back (existing ones are never changed).");
      $("#cmspage", out).onsubmit = ev => { ev.preventDefault(); run(() => post("/api/v1/cms/services/page", Object.fromEntries(new FormData(ev.target))), "Saved."); };
      out.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => edit(+b.dataset.edit));
      out.querySelectorAll("[data-up],[data-down]").forEach(b => b.onclick = () => { const ids = data.services.map(s => s.id), id = +(b.dataset.up || b.dataset.down), i = ids.indexOf(id), j = b.dataset.up ? i - 1 : i + 1;
        [ids[i], ids[j]] = [ids[j], ids[i]]; run(() => post("/api/v1/cms/services/order", {ids}), "Order saved."); });
      out.querySelectorAll("[data-toggle]").forEach(b => b.onclick = () => run(() => post("/api/v1/cms/services/status", {id: +b.dataset.toggle, status: b.dataset.to}), b.dataset.to === "published" ? "Published." : "Unpublished: it is off the website, the menu and the sitemap."));
      out.querySelectorAll("[data-del]").forEach(b => b.onclick = () => { const s = data.services.find(x => x.id === +b.dataset.del);
        if (confirm(`Delete "${s.name}"? Its address will answer "gone" to search engines. The text is kept in the history and can be brought back.`)) run(() => post("/api/v1/cms/services/delete", {id: s.id}), "Deleted."); });
      out.querySelectorAll("[data-undelete]").forEach(b => b.onclick = () => run(() => post("/api/v1/cms/services/restore", {revision_id: +b.dataset.undelete}), "Brought back as a draft."));
      $("#cmspage", out).querySelectorAll("input[name^=seo],textarea[name^=seo]").forEach(i => counter(i, i.name === "seo_title" ? [30, 60] : [70, 160]));
    };
    const counter = (input, [lo, hi]) => { const c = input.parentElement.querySelector(".cmscount"); const f = () => { const n = input.value.length; c.textContent = `${n} characters`; c.style.color = n >= lo && n <= hi ? "var(--green)" : "#e3b341"; }; input.oninput = f; f(); };

    const stepRow = (s = {}) => `<div class="cmsrow" data-step><input placeholder="Step title" maxlength="80" value="${esc(s.title || "")}"><textarea rows="2" placeholder="What happens in this step" maxlength="400">${esc(s.text || "")}</textarea><button type="button" class="btn" data-rm>×</button></div>`;
    const faqRow = (f = {}) => `<div class="cmsrow" data-faq><input placeholder="Question" maxlength="200" value="${esc(f.q || "")}"><textarea rows="2" placeholder="Answer" maxlength="1200">${esc(f.a || "")}</textarea><button type="button" class="btn" data-rm>×</button></div>`;
    const edit = async id => {
      const box = $("#cmsedit", out);
      const got = id ? await api("/api/v1/cms/services/get", {id}) : {service: {name: "", nav_label: "", slug: "", tagline: "", intro: "", audience: [], deliverables: [], steps: [], limits: [], faqs: [], related: [], seo_title: "", seo_description: "", seo_keywords: "", canonical_url: "", noindex: false, status: "draft"}, checks: []};
      const s = got.service, others = data.services.filter(x => x.id !== s.id);
      box.innerHTML = `<section class="card" style="margin-top:14px" id="cmsform"><h2>${id ? "Edit: " + esc(s.name) : "New service"}</h2>
        <div class="cmsgrid"><label>Name<input name="name" maxlength="160" value="${esc(s.name)}"></label><label>Name in the menu (short; empty = the name)<input name="nav_label" maxlength="80" value="${esc(s.nav_label === s.name ? "" : s.nav_label)}"></label>
          <label>Web address /services/<input name="slug" maxlength="100" value="${esc(s.slug)}" placeholder="made from the name"></label></div>
        <label style="display:block;margin-top:10px">One-line summary<textarea name="tagline" rows="2" maxlength="400">${esc(s.tagline)}</textarea></label>
        <label style="display:block;margin-top:10px">Introduction (a blank line starts a new paragraph)<textarea name="intro" rows="7" maxlength="6000">${esc(s.intro)}</textarea></label>
        <div class="cmsgrid" style="margin-top:10px"><label>Who it is for (one per line)<textarea name="audience" rows="5">${esc(lines(s.audience))}</textarea></label><label>What the client receives (one per line)<textarea name="deliverables" rows="5">${esc(lines(s.deliverables))}</textarea></label>
          <label>What it cannot tell you (one per line)<textarea name="limits" rows="5">${esc(lines(s.limits))}</textarea></label></div>
        <h3 style="margin-top:14px">How the work runs (up to 8 steps)</h3><div id="cmssteps">${(s.steps || []).map(stepRow).join("")}</div><button type="button" class="btn" id="cmsaddstep">Add a step</button>
        <h3 style="margin-top:14px">Questions and answers (up to 15)</h3><div id="cmsfaqs">${(s.faqs || []).map(faqRow).join("")}</div><button type="button" class="btn" id="cmsaddfaq">Add a question</button>
        <h3 style="margin-top:14px">Related services</h3><div>${others.map(o => `<label style="display:inline-block;margin-right:14px"><input type="checkbox" name="related" value="${esc(o.slug)}"${(s.related || []).includes(o.slug) ? " checked" : ""}> ${esc(o.name)}</label>`).join("") || '<span class="muted">Add more services to link them.</span>'}</div>
        <h3 style="margin-top:14px">Search (Google and other search engines)</h3>
        <div class="cmsgrid"><label>Search title <span class="cmscount"></span><input name="seo_title" maxlength="200" value="${esc(s.seo_title)}"></label><label>Search description <span class="cmscount"></span><textarea name="seo_description" rows="3" maxlength="400">${esc(s.seo_description)}</textarea></label>
          <label>Keywords (comma separated; the first is the main one)<input name="keywords" maxlength="300" value="${esc(s.seo_keywords)}"></label><label>Canonical address (leave empty for the page's own address)<input name="canonical_url" maxlength="500" value="${esc(s.canonical_url)}"></label>
          <label style="align-self:end"><input type="checkbox" name="noindex"${s.noindex ? " checked" : ""}> keep this page out of search results</label></div>
        <div class="cmssnip" style="margin-top:12px"><div class="u" id="snu"></div><div class="t" id="snt"></div><div class="d" id="snd"></div></div><div id="cmschecks">${checkList(got.checks)}</div>
        <div class="btnrow" style="margin-top:14px"><button class="btn primary" id="cmssave">${s.status === "published" ? "Save changes" : "Save as draft"}</button>${s.status === "published" ? "" : '<button class="btn primary" id="cmspub">Save and publish</button>'}
          <button class="btn" id="cmscheck">Check the search side</button><button class="btn" id="cmsprev">Preview the page</button>${id ? '<button class="btn" id="cmshist">History</button>' : ""}<button class="btn" id="cmscancel">Close</button></div>
        <div id="cmseditmsg" class="msg" hidden></div></section>`;
      const f = box.querySelector("#cmsform"), q = n => f.querySelector(`[name=${n}]`);
      const emsg = (t, ok) => { const m = $("#cmseditmsg", box); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
      const collect = status => ({id: id || undefined, status, name: q("name").value, nav_label: q("nav_label").value, slug: q("slug").value, tagline: q("tagline").value, intro: q("intro").value,
        audience: q("audience").value, deliverables: q("deliverables").value, limits: q("limits").value, seo_title: q("seo_title").value, seo_description: q("seo_description").value, seo_keywords: q("keywords").value,
        canonical_url: q("canonical_url").value, noindex: q("noindex").checked, related: [...f.querySelectorAll("[name=related]:checked")].map(i => i.value),
        steps: [...f.querySelectorAll("[data-step]")].map(r => ({title: r.querySelector("input").value, text: r.querySelector("textarea").value})), faqs: [...f.querySelectorAll("[data-faq]")].map(r => ({q: r.querySelector("input").value, a: r.querySelector("textarea").value}))});
      const snippet = () => { const name = q("name").value, slug = q("slug").value || name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
        $("#snu", f).textContent = `${data.base_url.replace("https://", "")} › services › ${slug}`; $("#snt", f).textContent = q("seo_title").value || `${name} | StatAxis`; $("#snd", f).textContent = q("seo_description").value || q("tagline").value; };
      ["seo_title", "seo_description", "name", "slug", "tagline"].forEach(n => q(n).addEventListener("input", snippet)); snippet();
      counter(q("seo_title"), [30, 60]); counter(q("seo_description"), [70, 160]);
      f.addEventListener("click", ev => { if (ev.target.matches("[data-rm]")) ev.target.closest(".cmsrow").remove(); });
      $("#cmsaddstep", f).onclick = () => { if (f.querySelectorAll("[data-step]").length < 8) $("#cmssteps", f).insertAdjacentHTML("beforeend", stepRow()); };
      $("#cmsaddfaq", f).onclick = () => { if (f.querySelectorAll("[data-faq]").length < 15) $("#cmsfaqs", f).insertAdjacentHTML("beforeend", faqRow()); };
      const save = async status => { try { const r = await post("/api/v1/cms/services/save", collect(status)); await draw(); say(status === "published" ? "Saved and published." : "Saved.", true); edit(r.service.id); } catch (e) { emsg(e.message); } };
      $("#cmssave", f).onclick = () => save(s.status === "published" ? "published" : "draft");
      if ($("#cmspub", f)) $("#cmspub", f).onclick = () => save("published");
      $("#cmscheck", f).onclick = async () => { try { const r = await post("/api/v1/cms/services/preview", collect(s.status)); $("#cmschecks", f).innerHTML = checkList(r.checks); emsg("", true); } catch (e) { emsg(e.message); } };
      $("#cmsprev", f).onclick = async () => { try { const r = await post("/api/v1/cms/services/preview", collect(s.status)); $("#cmschecks", f).innerHTML = checkList(r.checks); modal("Preview: " + (q("name").value || "new service") + " (nothing is saved or public)", `<iframe srcdoc="${esc(r.html)}" title="Preview"></iframe>`); } catch (e) { emsg(e.message); } };
      $("#cmscancel", f).onclick = () => { box.innerHTML = ""; };
      if ($("#cmshist", f)) $("#cmshist", f).onclick = async () => { const h = await api("/api/v1/cms/services/history", {id});
        modal("History of " + s.name, `<div class="body"><table><thead><tr><th>When</th><th>What</th><th>By</th><th></th></tr></thead><tbody>${h.revisions.map(r => `<tr><td>${when(r.at)}</td><td>${esc(r.action)}${r.slug && r.slug !== s.slug ? ` (address /services/${esc(r.slug)})` : ""}</td><td>${esc(r.by || "")}</td><td><button class="btn" data-restore="${r.id}">Put this version back as a draft</button></td></tr>`).join("")}</tbody></table></div>`);
        document.querySelectorAll("[data-restore]").forEach(b => b.onclick = async () => { try { await post("/api/v1/cms/services/restore", {revision_id: +b.dataset.restore}); document.querySelector(".cmsmodal").remove(); await draw(); say("Put back as a draft.", true); } catch (e) { alert(e.message); } }); };
      f.scrollIntoView({behavior: "smooth", block: "start"});
    };
    const modal = (title, bodyHtml) => { document.querySelector(".cmsmodal")?.remove(); const m = document.createElement("div"); m.className = "cmsmodal"; m.innerHTML = `<div><header><b>${esc(title)}</b><button class="btn" id="cmsx">Close</button></header>${bodyHtml}</div>`; document.body.appendChild(m); $("#cmsx", m).onclick = () => m.remove(); };
    try { await draw(); } catch (e) { out.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`; }
  }, {admin: 1});

  /* ---------------------------------------------------------------------------------------------------- the blog */
  const istInput = iso => iso ? new Date(iso).toLocaleString("sv-SE", {timeZone: "Asia/Kolkata"}).slice(0, 16).replace(" ", "T") : "";
  const istIso = v => v ? v + ":00+05:30" : null;
  const stateTag = p => p.state === "published" ? '<span class="tag green">published</span>' : p.state === "scheduled" ? `<span class="tag">scheduled ${when(p.publish_at)}</span>` : '<span class="tag">draft</span>';
  const modal = (title, bodyHtml) => { document.querySelector(".cmsmodal")?.remove(); const m = document.createElement("div"); m.className = "cmsmodal"; m.innerHTML = `<div><header><b>${esc(title)}</b><button class="btn" id="cmsx">Close</button></header>${bodyHtml}</div>`; document.body.appendChild(m); $("#cmsx", m).onclick = () => m.remove(); };
  /* the small buttons above the article text: [text put before the selection, placeholder, text put after, put on a line of its own] */
  const INSERTS = {heading: ["## ", "Section heading", "", true], sub: ["### ", "Smaller heading", "", true], bold: ["**", "bold words", "**", false], italic: ["*", "italic words", "*", false], list: ["- ", "A point", "", true], quote: ["> ", "A quote", "", true], link: ["[", "link words", "](/platform)", false]};

  add("adm-blog", "Admin", "Website blog", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Website blog"); return; }
    el.innerHTML = head("Website blog", "Write, schedule and publish articles for the Insights page. Each article has its own search title, description and address; every change is kept so an earlier version can be put back. The six articles built into the site are shown for reference and are not changed here.") + '<div id="blgout"></div>';
    const out = $("#blgout", el);
    const say = (t, ok) => { const m = $("#blgmsg", el); if (!m) return; m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    let data;
    const draw = async () => {
      data = await api("/api/v1/cms/posts");
      const rows = data.posts.map(p => `<tr><td><b>${esc(p.title)}</b><div class="muted">/blog/${esc(p.slug)} · ${esc(p.category || "no category")} · ${p.words} words</div></td><td>${stateTag(p)}${p.noindex ? ' <span class="tag red">hidden from Google</span>' : ""}</td><td class="muted">${when(p.updated_at)}</td>
        <td class="btnrow"><button class="btn" data-edit="${p.id}">Edit</button>${p.live ? `<a class="btn" href="/blog/${esc(p.slug)}" target="_blank" rel="noopener">View ↗</a><button class="btn" data-draft="${p.id}">Unpublish</button>` : `<button class="btn" data-pub="${p.id}">Publish now</button>`}<button class="btn" data-del="${p.id}">Delete</button></td></tr>`).join("");
      const built = data.builtin.map(b => `<li><a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.title)}</a> <span class="muted">${esc(b.url)}</span></li>`).join("");
      const deleted = data.deleted.map(d => `<li>${esc(d.title || d.slug)} <span class="muted">/blog/${esc(d.slug)} · deleted ${when(d.at)} by ${esc(d.by || "")}</span> <button class="btn" data-undelete="${d.id}">Bring back as a draft</button></li>`).join("");
      out.innerHTML = `<div id="blgmsg" class="msg" hidden></div><div class="btnrow" style="margin:12px 0"><button class="btn primary" id="blgnew">New article</button><a class="btn" href="/insights" target="_blank" rel="noopener">Open the Insights page ↗</a></div>
        <section class="card"><h2>Articles written here (${data.posts.length})</h2><div style="overflow:auto"><table><thead><tr><th>Article</th><th>State</th><th>Changed</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="4">No article yet. Press New article.</td></tr>'}</tbody></table></div>
          <p class="muted" style="margin-top:8px">Live articles appear on /insights (newest first), in the sitemap at <a href="/sitemap.xml" target="_blank" rel="noopener">/sitemap.xml</a> and in llms.txt. A scheduled article goes live at its time without anyone pressing anything (within a minute).</p></section>
        <section class="card" style="margin-top:14px"><h2>Built into the site (${data.builtin.length})</h2><ul>${built}</ul><p class="muted">These stay exactly as they are, so search engines keep what they already know. Their addresses cannot be used for a new article.</p></section>
        ${deleted ? `<section class="card" style="margin-top:14px"><h2>Deleted articles</h2><ul>${deleted}</ul></section>` : ""}<div id="blgedit"></div>`;
      wire();
    };
    const run = async (fn, okText) => { try { await fn(); await draw(); say(okText, true); } catch (e) { say(e.message); } };
    const wire = () => {
      $("#blgnew", out).onclick = () => edit(null);
      out.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => edit(+b.dataset.edit));
      out.querySelectorAll("[data-pub]").forEach(b => b.onclick = () => run(() => post("/api/v1/cms/posts/status", {id: +b.dataset.pub, status: "published"}), "Published."));
      out.querySelectorAll("[data-draft]").forEach(b => b.onclick = () => run(() => post("/api/v1/cms/posts/status", {id: +b.dataset.draft, status: "draft"}), "Unpublished: it is off the website, the Insights list and the sitemap."));
      out.querySelectorAll("[data-del]").forEach(b => b.onclick = () => { const p = data.posts.find(x => x.id === +b.dataset.del); if (confirm(`Delete "${p.title}"? Its address will answer "gone" to search engines. The text is kept in the history and can be brought back.`)) run(() => post("/api/v1/cms/posts/delete", {id: p.id}), "Deleted."); });
      out.querySelectorAll("[data-undelete]").forEach(b => b.onclick = () => run(() => post("/api/v1/cms/posts/restore", {revision_id: +b.dataset.undelete}), "Brought back as a draft."));
    };
    const edit = async id => {
      const box = $("#blgedit", out);
      const got = id ? await api("/api/v1/cms/posts/get", {id}) : {post: {title: "", slug: "", excerpt: "", category: "", author: "StatAxis", body: "", related: [], seo_title: "", seo_description: "", seo_keywords: "", canonical_url: "", noindex: false, status: "draft", state: "draft", publish_at: null}, checks: []};
      const p = got.post, others = [...data.posts.filter(x => x.id !== p.id).map(x => [x.slug, x.title]), ...data.builtin.map(b => [b.slug, b.title])];
      box.innerHTML = `<section class="card" style="margin-top:14px" id="blgform"><h2>${id ? "Edit: " + esc(p.title) : "New article"}</h2>
        <div class="cmsgrid"><label>Title<input name="title" maxlength="200" value="${esc(p.title)}"></label><label>Web address /blog/<input name="slug" maxlength="100" value="${esc(p.slug)}" placeholder="made from the title"></label>
          <label>Category<input name="category" maxlength="60" list="blgcats" value="${esc(p.category)}"><datalist id="blgcats">${data.categories.map(c => `<option value="${esc(c)}">`).join("")}</datalist></label><label>Author<input name="author" maxlength="120" value="${esc(p.author)}"></label></div>
        <label style="display:block;margin-top:10px">Short summary (shows under the title and on the Insights list)<textarea name="excerpt" rows="2" maxlength="400">${esc(p.excerpt)}</textarea></label>
        <div class="btnrow" style="margin-top:10px">${[["heading", "Heading"], ["sub", "Sub-heading"], ["bold", "Bold"], ["italic", "Italic"], ["list", "List"], ["quote", "Quote"], ["link", "Link"]].map(([k, l]) => `<button type="button" class="btn" data-ins="${k}">${l}</button>`).join("")}</div>
        <label style="display:block;margin-top:6px">Article text <span class="cmscount" id="blgwords"></span><textarea name="body" rows="18" style="font-family:inherit">${esc(p.body)}</textarea></label>
        <p class="muted">A blank line starts a new paragraph. <code>## Heading</code>, <code>### Smaller heading</code>, lines starting with <code>- </code> or <code>1. </code> make lists, <code>&gt; </code> a quote, <code>**bold**</code>, <code>*italic*</code>, <code>[words](/page)</code> a link.</p>
        <h3 style="margin-top:14px">Keep reading (related articles)</h3><div>${others.map(([s, t]) => `<label style="display:inline-block;margin-right:14px"><input type="checkbox" name="related" value="${esc(s)}"${(p.related || []).includes(s) ? " checked" : ""}> ${esc(t)}</label>`).join("") || '<span class="muted">No other article yet.</span>'}</div>
        <h3 style="margin-top:14px">Search (Google and other search engines)</h3>
        <div class="cmsgrid"><label>Search title <span class="cmscount"></span><input name="seo_title" maxlength="200" value="${esc(p.seo_title)}"></label><label>Search description <span class="cmscount"></span><textarea name="seo_description" rows="3" maxlength="400">${esc(p.seo_description)}</textarea></label>
          <label>Keywords (comma separated; the first is the main one)<input name="keywords" maxlength="300" value="${esc(p.seo_keywords)}"></label><label>Canonical address (empty = the article's own address)<input name="canonical_url" maxlength="500" value="${esc(p.canonical_url)}"></label>
          <label style="align-self:end"><input type="checkbox" name="noindex"${p.noindex ? " checked" : ""}> keep this article out of search results</label></div>
        <div class="cmssnip" style="margin-top:12px"><div class="u" id="snu"></div><div class="t" id="snt"></div><div class="d" id="snd"></div></div><div id="blgchecks">${checkList(got.checks)}</div>
        <h3 style="margin-top:14px">When</h3><div class="cmsgrid"><label>Publish at (Indian time), used by "Schedule"<input type="datetime-local" name="publish_at" value="${esc(istInput(p.publish_at))}"></label><div class="muted" style="align-self:end">Now: <b>${esc(p.state)}</b></div></div>
        <div class="btnrow" style="margin-top:14px"><button class="btn primary" id="blgsave">${p.live ? "Save changes" : "Save as draft"}</button>${p.live ? "" : '<button class="btn primary" id="blgpub">Publish now</button><button class="btn" id="blgsched">Schedule</button>'}${p.live ? '<button class="btn" id="blgunpub">Unpublish (back to draft)</button>' : ""}
          <button class="btn" id="blgcheck">Check the search side</button><button class="btn" id="blgprev">Preview</button>${id ? '<button class="btn" id="blghist">History</button>' : ""}<button class="btn" id="blgcancel">Close</button></div><div id="blgeditmsg" class="msg" hidden></div></section>`;
      const f = box.querySelector("#blgform"), q = n => f.querySelector(`[name=${n}]`);
      const emsg = (t, ok) => { const m = $("#blgeditmsg", box); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
      const collect = status => ({id: id || undefined, status, title: q("title").value, slug: q("slug").value, category: q("category").value, author: q("author").value, excerpt: q("excerpt").value, body: q("body").value, seo_title: q("seo_title").value,
        seo_description: q("seo_description").value, seo_keywords: q("keywords").value, canonical_url: q("canonical_url").value, noindex: q("noindex").checked, publish_at: istIso(q("publish_at").value), related: [...f.querySelectorAll("[name=related]:checked")].map(i => i.value)});
      const snippet = () => { const t = q("title").value, slug = q("slug").value || t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); $("#snu", f).textContent = `${data.base_url.replace("https://", "")} › blog › ${slug}`; $("#snt", f).textContent = q("seo_title").value || `${t} — StatAxis`; $("#snd", f).textContent = q("seo_description").value || q("excerpt").value; };
      const wc = () => { $("#blgwords", f).textContent = `${(q("body").value.match(/\w+/g) || []).length} words`; };
      ["seo_title", "seo_description", "title", "slug", "excerpt"].forEach(n => q(n).addEventListener("input", snippet)); q("body").addEventListener("input", wc); snippet(); wc();
      const count = (input, [lo, hi]) => { const c = input.parentElement.querySelector(".cmscount"); const g = () => { const n = input.value.length; c.textContent = `${n} characters`; c.style.color = n >= lo && n <= hi ? "var(--green)" : "#e3b341"; }; input.addEventListener("input", g); g(); };
      count(q("seo_title"), [30, 60]); count(q("seo_description"), [70, 160]);
      f.querySelectorAll("[data-ins]").forEach(b => b.onclick = () => {
        const [pre, placeholder, post_, ownLine] = INSERTS[b.dataset.ins], t = q("body"), a = t.selectionStart, z = t.selectionEnd, chosen = t.value.slice(a, z) || placeholder;
        const lead = ownLine && a > 0 && t.value[a - 1] !== "\n" ? "\n\n" : "";
        t.setRangeText(lead + pre + chosen + post_, a, z, "end"); t.focus(); wc(); });
      const save = async (status, okText) => { try { const r = await post("/api/v1/cms/posts/save", collect(status)); await draw(); say(okText, true); edit(r.post.id); } catch (e) { emsg(e.message); } };
      $("#blgsave", f).onclick = () => save(p.live ? "published" : "draft", "Saved.");
      if ($("#blgpub", f)) $("#blgpub", f).onclick = () => save("published", "Published.");
      if ($("#blgsched", f)) $("#blgsched", f).onclick = () => save("scheduled", "Scheduled: it goes live at that time.");
      if ($("#blgunpub", f)) $("#blgunpub", f).onclick = () => save("draft", "Unpublished.");
      $("#blgcheck", f).onclick = async () => { try { const r = await post("/api/v1/cms/posts/preview", collect("draft")); $("#blgchecks", f).innerHTML = checkList(r.checks); emsg("", true); } catch (e) { emsg(e.message); } };
      $("#blgprev", f).onclick = async () => { try { const r = await post("/api/v1/cms/posts/preview", collect("draft")); $("#blgchecks", f).innerHTML = checkList(r.checks); modal("Preview: " + (q("title").value || "new article") + " (nothing is saved or public)", `<iframe srcdoc="${esc(r.html)}" title="Preview"></iframe>`); } catch (e) { emsg(e.message); } };
      $("#blgcancel", f).onclick = () => { box.innerHTML = ""; };
      if ($("#blghist", f)) $("#blghist", f).onclick = async () => { const h = await api("/api/v1/cms/posts/history", {id});
        modal("History of " + p.title, `<div class="body"><table><thead><tr><th>When</th><th>What</th><th>By</th><th></th></tr></thead><tbody>${h.revisions.map(r => `<tr><td>${when(r.at)}</td><td>${esc(r.action)}${r.slug && r.slug !== p.slug ? ` (address /blog/${esc(r.slug)})` : ""} · ${r.words ?? ""} words</td><td>${esc(r.by || "")}</td><td><button class="btn" data-restore="${r.id}">Put this version back as a draft</button></td></tr>`).join("")}</tbody></table></div>`);
        document.querySelectorAll("[data-restore]").forEach(b => b.onclick = async () => { try { await post("/api/v1/cms/posts/restore", {revision_id: +b.dataset.restore}); document.querySelector(".cmsmodal").remove(); await draw(); say("Put back as a draft.", true); } catch (e) { alert(e.message); } }); };
      f.scrollIntoView({behavior: "smooth", block: "start"});
    };
    try { await draw(); } catch (e) { out.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`; }
  }, {admin: 1});
})();
