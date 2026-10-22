/* Polls and surveys for the workspace: pick a starter or start blank, build the questions, set who may answer and what is shown afterwards, share the link (or personal invitation links), read the results with
   splits by group, read and clean the individual answers, and export. Loaded by workspace.html after cms.js; it uses the helpers of workspace.html ($, esc, api, post, head, add, isAdmin, adminOnly, token). */
"use strict";
(() => {
  if (typeof add !== "function") return;
  const when = iso => iso ? new Date(iso).toLocaleString("en-IN", {day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata"}) + " IST" : "—";
  const istInput = iso => iso ? new Date(iso).toLocaleString("sv-SE", {timeZone: "Asia/Kolkata"}).slice(0, 16).replace(" ", "T") : "";
  const istIso = v => v ? v + ":00+05:30" : null;
  const fresh = (path, params = {}) => api(path, {...params, _: Date.now()});
  const css = document.createElement("style");
  css.textContent = ".svgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.svgrid label,.svq label{display:block;font-size:13px}.svgrid input:not([type=checkbox]),.svgrid textarea,.svgrid select,.svq input:not([type=checkbox]),.svq textarea,.svq select{width:100%;box-sizing:border-box}"
    + ".svq{border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0;background:#08192a}.svq.arch{opacity:.55}.svq .bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px}.svq .opt{display:grid;grid-template-columns:1fr auto auto auto;gap:6px;align-items:center;margin:5px 0}"
    + ".svtabs{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0}.svtabs button.on{background:var(--blue);color:#021018;border-color:var(--blue)}.svbar{height:10px;border-radius:6px;background:#11283d;overflow:hidden}.svbar i{display:block;height:100%;background:var(--blue)}"
    + ".svres .row{display:grid;grid-template-columns:minmax(120px,1fr) 2fr 90px;gap:10px;align-items:center;margin:7px 0;font-size:14px}.svx td,.svx th{padding:6px 8px;border:1px solid var(--line);font-size:13px}.svwarn{border:1px solid #b08a2e;background:#2a2210;border-radius:10px;padding:12px;margin:12px 0;font-size:13.5px;line-height:1.55}"
    + ".svstarter{display:block;text-align:left;padding:14px;border:1px solid var(--line);border-radius:12px;background:#08192a;color:inherit;cursor:pointer}.svstarter:hover{border-color:var(--blue)}.svstarter b{display:block;margin-bottom:4px}";
  document.head.appendChild(css);
  const TYPE_LABEL = {single: "One choice", multi: "Many choices", dropdown: "Dropdown", rating: "Rating", nps: "Recommend (0 to 10)", number: "Number", text: "Short text", longtext: "Long text", ranking: "Ranking", section: "Heading"};
  const CHOICE = ["single", "multi", "dropdown", "ranking"];
  const CATEGORY = {opinion: "Opinion", political: "Political", brand: "Brand", customer: "Customer", employee: "Employee", media: "Media", other: "Other"};
  const stateTag = s => `<span class="tag ${s.state === "open" ? "green" : s.state === "closed" ? "red" : ""}">${esc(s.state)}</span>`;
  const modal = (title, bodyHtml) => { document.querySelector(".cmsmodal")?.remove(); const m = document.createElement("div"); m.className = "cmsmodal"; m.innerHTML = `<div><header><b>${esc(title)}</b><button class="btn" id="svx">Close</button></header>${bodyHtml}</div>`; document.body.appendChild(m); m.querySelector("#svx").onclick = () => m.remove(); return m; };
  const download = async (path, params, name) => { const q = new URLSearchParams(params); const res = await fetch(path + "?" + q, {headers: {Authorization: "Bearer " + token()}}); if (!res.ok) throw new Error("Could not download."); const url = URL.createObjectURL(await res.blob()); const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 4000); };
  const blankQuestion = type => ({type, text: "", help: "", required: false, ...(CHOICE.includes(type) ? {options: [{text: ""}, {text: ""}]} : {}), ...(type === "rating" ? {scale_max: 5} : {})});

  add("adm-surveys", "Admin", "Polls & surveys", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Polls and surveys"); return; }
    el.innerHTML = head("Polls & surveys", "Run opinion polls, political polls, brand polls and full surveys: build the questions, share a link, and read the results with how many answered and how the answers were collected. Answers are anonymous unless you ask for contact details.") + '<div id="svout"></div>';
    const out = $("#svout", el);
    let data, cur = null, tab = "questions";
    const say = (t, ok) => { const m = $("#svmsg", el); if (!m) return; m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };

    /* ------------------------------------------------------------------ the list */
    const list = async () => {
      cur = null; data = await fresh("/api/v1/surveys/list");
      const starters = data.templates.map(t => `<button class="svstarter" data-tpl="${esc(t.key)}"><b>${esc(t.title)}</b><span class="muted">${esc(t.description)} (${t.questions} question${t.questions === 1 ? "" : "s"})</span></button>`).join("");
      const rows = data.surveys.map(s => `<tr><td><b>${esc(s.title)}</b><div class="muted">/survey/${esc(s.slug)} · ${esc(CATEGORY[s.category] || s.category)} · ${esc(s.kind)}</div></td><td>${stateTag(s)}${s.listed ? ' <span class="tag">on the Polls page</span>' : ""}</td><td>${s.responses}</td><td class="muted">${when(s.updated_at)}</td>
        <td class="btnrow"><button class="btn" data-open="${s.id}">Open</button><button class="btn" data-res="${s.id}">Results</button><button class="btn" data-dup="${s.id}">Copy</button><button class="btn" data-del="${s.id}">Delete</button></td></tr>`).join("");
      out.innerHTML = `<div id="svmsg" class="msg" hidden></div><section class="card"><h2>Start a new one</h2><div class="svgrid"><button class="svstarter" data-tpl=""><b>Blank survey</b><span class="muted">Write your own questions.</span></button>${starters}</div>
        <p class="muted" style="margin-top:8px">A starter is only a draft to edit: the questions, party or brand names and wording are placeholders you change. Nothing is public until you open it.</p></section>
        <section class="card" style="margin-top:14px"><h2>Your polls and surveys (${data.surveys.length})</h2><div style="overflow:auto"><table><thead><tr><th>Name</th><th>State</th><th>Answers</th><th>Changed</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5">None yet. Pick a starter above.</td></tr>'}</tbody></table></div></section>`;
      out.querySelectorAll("[data-tpl]").forEach(b => b.onclick = async () => { try { const t = b.dataset.tpl ? (await api("/api/v1/surveys/template", {key: b.dataset.tpl})).survey : {title: "", kind: "survey", category: "opinion", questions: []}; cur = {status: "draft", language: "en", access: "public", results_mode: "private", sampling: "self_selected", contact_mode: "none", contact_fields: [], min_results: 10, ...t}; tab = "questions"; edit(); } catch (e) { say(e.message); } });
      out.querySelectorAll("[data-open]").forEach(b => b.onclick = async () => { cur = (await fresh("/api/v1/surveys/get", {id: b.dataset.open})).survey; tab = "questions"; edit(); });
      out.querySelectorAll("[data-res]").forEach(b => b.onclick = async () => { cur = (await fresh("/api/v1/surveys/get", {id: b.dataset.res})).survey; tab = "results"; edit(); });
      out.querySelectorAll("[data-dup]").forEach(b => b.onclick = async () => { try { await post("/api/v1/surveys/duplicate", {id: +b.dataset.dup}); await list(); say("Copied as a draft.", true); } catch (e) { say(e.message); } });
      out.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { const s = data.surveys.find(x => x.id === +b.dataset.del); if (!confirm(`Delete "${s.title}"? This cannot be undone.`)) return; try { await post("/api/v1/surveys/delete", {id: s.id}); await list(); say("Deleted.", true); } catch (e) { say(e.message); } });
    };

    /* ------------------------------------------------------------------ one survey */
    const edit = () => {
      const tabs = [["questions", "Questions"], ["settings", "Settings"], ["share", "Share and open"], ["results", "Results"], ["answers", "Answers"]];
      out.innerHTML = `<div id="svmsg" class="msg" hidden></div><div class="btnrow" style="margin:12px 0"><button class="btn" id="svback">← All polls and surveys</button><b style="align-self:center">${esc(cur.title || "New survey")}</b>${cur.id ? stateTag(cur) : '<span class="tag">not saved yet</span>'}<span style="flex:1"></span><button class="btn primary" id="svsave">Save</button><button class="btn" id="svprev">Preview</button></div>
        <div class="svtabs">${tabs.map(([k, l]) => `<button class="btn${tab === k ? " on" : ""}" data-tab="${k}"${(k === "results" || k === "answers" || k === "share") && !cur.id ? " disabled title=\"Save first\"" : ""}>${l}</button>`).join("")}</div><div id="svbody"></div>`;
      $("#svback", out).onclick = list;
      out.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { tab = b.dataset.tab; edit(); });
      $("#svsave", out).onclick = save;
      $("#svprev", out).onclick = async () => { try { const r = await post("/api/v1/surveys/preview", payload()); modal("Preview: " + (cur.title || "survey") + " (nothing is saved or public)", `<iframe srcdoc="${esc(r.html)}" title="Preview"></iframe>`); } catch (e) { say(e.message); } };
      ({questions: drawQuestions, settings: drawSettings, share: drawShare, results: drawResults, answers: drawAnswers})[tab]($("#svbody", out));
    };
    const payload = () => ({...cur, opens_at: cur.opens_at, closes_at: cur.closes_at});
    const save = async () => { try { const r = await post("/api/v1/surveys/save", payload()); cur = r.survey; edit(); say("Saved.", true); } catch (e) { say(e.message); } };

    /* ------------------------------------------------------------------ questions */
    const drawQuestions = body => {
      const locked = !!cur.has_responses;
      const qs = cur.questions = cur.questions || [];
      const earlier = i => qs.slice(0, i).filter(q => q.type !== "section" && q.id);
      body.innerHTML = (locked ? `<div class="svwarn">This survey already has answers. Wording can be corrected, and questions or options can be added, hidden (archive) or reordered, but nothing that holds an answer can be deleted or change its type.</div>` : "")
        + `<div id="svqs"></div><div class="btnrow" style="margin-top:12px">${Object.keys(TYPE_LABEL).map(t => `<button class="btn" data-add="${t}">+ ${TYPE_LABEL[t]}</button>`).join("")}<button class="btn" id="svdemo">+ Age, gender, area and state</button></div>`;
      const box = $("#svqs", body);
      qs.forEach((q, i) => {
        const card = document.createElement("div"); card.className = "svq" + (q.archived ? " arch" : "");
        const isChoice = CHOICE.includes(q.type), canDelete = !(locked && q.id);
        const opts = (q.options || []).map((o, k) => `<div class="opt" data-o="${k}"><input type="text" value="${esc(o.text)}" maxlength="200" placeholder="Option ${k + 1}">
          ${["single", "multi", "dropdown"].includes(q.type) ? `<label title="Respondent writes in their own answer"><input type="checkbox" data-f="other"${o.other ? " checked" : ""}> other</label>` : "<span></span>"}${q.type === "multi" ? `<label title="Cannot be combined with other choices"><input type="checkbox" data-f="exclusive"${o.exclusive ? " checked" : ""}> alone</label>` : "<span></span>"}
          <span class="btnrow"><button class="btn" data-ou>↑</button><button class="btn" data-od>↓</button>${locked && o.id ? `<button class="btn" data-oa>${o.archived ? "Show" : "Hide"}</button>` : '<button class="btn" data-ox>×</button>'}</span></div>`).join("");
        const cond = q.show_if ? q.show_if : null, ref = cond && qs.find(z => z.id === cond.q);
        card.innerHTML = `<div class="bar"><span class="tag">${i + 1}</span><span class="tag">${esc(TYPE_LABEL[q.type])}</span>${q.archived ? '<span class="tag red">hidden from new respondents</span>' : ""}<span style="flex:1"></span>
          <button class="btn" data-qu>↑</button><button class="btn" data-qd>↓</button><button class="btn" data-qc>Copy</button>${locked && q.id ? `<button class="btn" data-qa>${q.archived ? "Show again" : "Archive"}</button>` : ""}${canDelete ? '<button class="btn" data-qx>Delete</button>' : ""}</div>
          <label>${q.type === "section" ? "Heading text" : "Question"}<textarea rows="2" data-f="text" maxlength="400">${esc(q.text)}</textarea></label><label>Help text (optional)<input type="text" data-f="help" maxlength="300" value="${esc(q.help || "")}"></label>
          ${q.type !== "section" ? `<label><input type="checkbox" data-f="required"${q.required ? " checked" : ""}> must be answered</label>` : ""}
          ${isChoice ? `<div style="margin-top:8px"><b style="font-size:13px">Options</b>${opts}<div class="btnrow"><button class="btn" data-oadd>+ Option</button><button class="btn" data-opaste>Paste many (one per line)</button></div>${q.type !== "ranking" ? `<label><input type="checkbox" data-f="randomize"${q.randomize ? " checked" : ""}> show the options in random order (other and alone stay last)</label>` : ""}${q.type === "multi" ? `<label>Most choices allowed (empty = any)<input type="number" min="1" data-f="max_select" value="${q.max_select || ""}"></label>` : ""}</div>` : ""}
          ${q.type === "rating" ? `<div class="svgrid"><label>Scale from 1 to<input type="number" min="3" max="10" data-f="scale_max" value="${q.scale_max || 5}"></label><label>Low end label<input type="text" data-f="label_low" maxlength="40" value="${esc(q.label_low || "")}"></label><label>High end label<input type="text" data-f="label_high" maxlength="40" value="${esc(q.label_high || "")}"></label></div>` : ""}
          ${q.type === "number" ? `<div class="svgrid"><label>Least<input type="number" data-f="min" value="${q.min ?? ""}"></label><label>Most<input type="number" data-f="max" value="${q.max ?? ""}"></label><label>Unit shown<input type="text" data-f="unit" maxlength="20" value="${esc(q.unit || "")}"></label></div>` : ""}
          ${q.type === "text" || q.type === "longtext" ? `<label>Longest answer (characters)<input type="number" min="20" max="2000" data-f="max_length" value="${q.max_length || ""}"></label>` : ""}
          ${q.type !== "section" && i > 0 && earlier(i).length ? `<details style="margin-top:8px"${cond ? " open" : ""}><summary>Show this question only if…</summary><div class="svgrid" style="margin-top:8px"><label>Question<select data-c="q"><option value="">Always show</option>${earlier(i).map(z => `<option value="${esc(z.id)}"${cond && cond.q === z.id ? " selected" : ""}>${esc(z.text.slice(0, 60))}</option>`).join("")}</select></label>
            <label>Answer<select data-c="op"><option value="is"${!cond || cond.op === "is" ? " selected" : ""}>is one of</option><option value="not"${cond && cond.op === "not" ? " selected" : ""}>is not one of</option></select></label>
            <label>Values${ref && ref.options ? "" : " (numbers, comma separated)"}${ref && ref.options ? `<select multiple data-c="values" size="4">${ref.options.map(o => `<option value="${esc(o.id)}"${cond && cond.values.includes(o.id) ? " selected" : ""}>${esc(o.text)}</option>`).join("")}</select>` : `<input type="text" data-c="values" value="${esc(cond ? cond.values.join(",") : "")}">`}</label></div></details>` : ""}`;
        const set = (f, v) => { if (v === "" || v == null) delete q[f]; else q[f] = v; };
        card.querySelectorAll("[data-f]").forEach(inp => { if (inp.closest("[data-o]")) return; inp.onchange = inp.oninput = () => { const f = inp.dataset.f; if (inp.type === "checkbox") q[f] = inp.checked; else if (inp.type === "number") set(f, inp.value === "" ? "" : +inp.value); else q[f] = inp.value; }; });
        card.querySelectorAll("[data-o]").forEach(row => { const k = +row.dataset.o, o = q.options[k];
          row.querySelector("input[type=text]").oninput = e => { o.text = e.target.value; };
          row.querySelectorAll("input[type=checkbox]").forEach(c => c.onchange = () => { o[c.dataset.f] = c.checked; });
          const mv = d => { const j = k + d; if (j >= 0 && j < q.options.length) { [q.options[k], q.options[j]] = [q.options[j], q.options[k]]; drawQuestions(body); } };
          row.querySelector("[data-ou]").onclick = () => mv(-1); row.querySelector("[data-od]").onclick = () => mv(1);
          const x = row.querySelector("[data-ox]"); if (x) x.onclick = () => { q.options.splice(k, 1); drawQuestions(body); };
          const a = row.querySelector("[data-oa]"); if (a) a.onclick = () => { o.archived = !o.archived; drawQuestions(body); }; });
        const addo = card.querySelector("[data-oadd]"); if (addo) addo.onclick = () => { q.options.push({text: ""}); drawQuestions(body); };
        const paste = card.querySelector("[data-opaste]"); if (paste) paste.onclick = () => { const t = prompt("Paste the options, one per line:"); if (t) { t.split("\n").map(x => x.trim()).filter(Boolean).forEach(x => q.options.push({text: x})); q.options = q.options.filter(o => o.text || o.id); drawQuestions(body); } };
        card.querySelectorAll("[data-c]").forEach(c => c.onchange = () => { const g = n => card.querySelector(`[data-c=${n}]`); const qq = g("q").value; if (!qq) { delete q.show_if; return; }
          const raw = g("values"), vals = raw.tagName === "SELECT" ? [...raw.selectedOptions].map(o => o.value) : raw.value.split(",").map(x => x.trim()).filter(Boolean);
          q.show_if = {q: qq, op: g("op").value, values: vals}; if (c.dataset.c === "q") drawQuestions(body); });
        const mvq = d => { const j = i + d; if (j >= 0 && j < qs.length) { [qs[i], qs[j]] = [qs[j], qs[i]]; drawQuestions(body); } };
        card.querySelector("[data-qu]").onclick = () => mvq(-1); card.querySelector("[data-qd]").onclick = () => mvq(1);
        card.querySelector("[data-qc]").onclick = () => { const c = JSON.parse(JSON.stringify(q)); delete c.id; delete c.archived; delete c.show_if; (c.options || []).forEach(o => { delete o.id; delete o.archived; }); qs.splice(i + 1, 0, c); drawQuestions(body); };
        const qa = card.querySelector("[data-qa]"); if (qa) qa.onclick = () => { q.archived = !q.archived; drawQuestions(body); };
        const qx = card.querySelector("[data-qx]"); if (qx) qx.onclick = () => { if (confirm("Delete this question?")) { qs.splice(i, 1); drawQuestions(body); } };
        box.append(card);
      });
      if (!qs.length) box.innerHTML = '<p class="muted">No questions yet. Add one below.</p>';
      body.querySelectorAll("[data-add]").forEach(b => b.onclick = () => { qs.push(blankQuestion(b.dataset.add)); drawQuestions(body); });
      $("#svdemo", body).onclick = async () => { (await api("/api/v1/surveys/demographics")).questions.forEach(q => qs.push(q)); drawQuestions(body); };
    };

    /* ------------------------------------------------------------------ settings */
    const drawSettings = body => {
      const c = cur, sel = (name, opts, val) => `<select data-s="${name}">${opts.map(([v, l]) => `<option value="${v}"${v === val ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
      body.innerHTML = `<section class="card"><h2>About it</h2><div class="svgrid"><label>Name<input data-s="title" maxlength="200" value="${esc(c.title || "")}"></label><label>Web address /survey/<input data-s="slug" maxlength="70" value="${esc(c.slug || "")}" placeholder="made from the name"></label>
          <label>Kind${sel("kind", [["poll", "Poll (1 to 3 questions, quick result)"], ["survey", "Survey (many questions)"]], c.kind)}</label><label>Subject${sel("category", Object.entries(CATEGORY), c.category)}</label><label>Words on buttons${sel("language", [["en", "English"], ["hi", "हिन्दी"]], c.language)}</label></div>
        <label style="display:block;margin-top:10px">Short description (also for search results)<textarea data-s="description" rows="2" maxlength="700">${esc(c.description || "")}</textarea></label>
        <label style="display:block;margin-top:10px">Introduction shown above the questions<textarea data-s="intro" rows="3" maxlength="3000">${esc(c.intro || "")}</textarea></label>
        <label style="display:block;margin-top:10px">Thank-you text (empty = the standard one)<textarea data-s="thank_you" rows="2" maxlength="1000">${esc(c.thank_you || "")}</textarea></label></section>
        <section class="card" style="margin-top:14px"><h2>Who can answer, and when</h2><div class="svgrid"><label>Access${sel("access", [["public", "Anyone with the link"], ["invite", "Invitation links only (one answer per link)"]], c.access)}</label>
          <label>Opens (Indian time)<input type="datetime-local" data-s="opens_at" value="${esc(istInput(c.opens_at))}"></label><label>Closes (Indian time)<input type="datetime-local" data-s="closes_at" value="${esc(istInput(c.closes_at))}"></label><label>Stop after this many answers<input type="number" min="1" data-s="max_responses" value="${c.max_responses || ""}"></label>
          <label>After the last question go to (https address, optional)<input data-s="redirect_url" maxlength="500" value="${esc(c.redirect_url || "")}"></label></div>
          <label style="display:block;margin-top:10px"><input type="checkbox" data-s="allow_repeat"${c.allow_repeat ? " checked" : ""}> allow several answers from one device (a kiosk or a shared phone). Otherwise one answer per browser.</label>
          <label style="display:block"><input type="checkbox" data-s="listed"${c.listed ? " checked" : ""}> show it on the public Polls page (/polls) and let search engines find it</label></section>
        <section class="card" style="margin-top:14px"><h2>Personal details and consent</h2><p class="muted">The default is no personal details at all: answers are anonymous. Ask only when you need to call or e-mail people back, and say why.</p><div class="svgrid"><label>Ask for contact details${sel("contact_mode", [["none", "No (anonymous)"], ["optional", "Optional"], ["required", "Required"]], c.contact_mode)}</label>
          <label>Which details<select multiple size="3" data-s="contact_fields">${[["name", "Name"], ["mobile", "Mobile number"], ["email", "E-mail"]].map(([v, l]) => `<option value="${v}"${(c.contact_fields || []).includes(v) ? " selected" : ""}>${l}</option>`).join("")}</select></label></div>
          <label style="display:block;margin-top:10px">Consent text people agree to (needed when details are asked)<textarea data-s="consent_text" rows="2" maxlength="1000">${esc(c.consent_text || "")}</textarea></label></section>
        <section class="card" style="margin-top:14px"><h2>Method and results</h2>
          ${c.category === "political" ? `<div class="svwarn"><b>Political polls.</b> Indian election law restricts publishing opinion-poll results during the period before polling ends in an election, and exit-poll results until polling has ended (Representation of the People Act, 1951, sections 126 and 126A). Check the Election Commission's current directions before you publish. Keep results private, or switch on "hold all public results" below, during such periods. Always state who paid for the poll, how people were reached, the dates and the number of answers.</div>` : ""}
          <div class="svgrid"><label>Sampling${sel("sampling", [["self_selected", "Self-selected (anyone who chooses to answer)"], ["panel", "Panel (people we recruited, not random)"], ["random_sample", "Random sample (a margin of error is shown)"]], c.sampling)}</label><label>Population size (random sample only, optional)<input type="number" min="2" data-s="population_size" value="${c.population_size || ""}"></label>
            <label>Public results${sel("results_mode", [["private", "Private: only I see them"], ["after_vote", "Shown to each person after they answer"], ["public", "Public page, live"], ["after_close", "Public page, after it closes"]], c.results_mode)}</label><label>Show public results only after this many answers<input type="number" min="0" data-s="min_results" value="${c.min_results ?? 10}"></label>
            <label>Who paid for it (shown with the results)<input data-s="sponsor" maxlength="200" value="${esc(c.sponsor || "")}"></label></div>
          <label style="display:block;margin-top:10px"><input type="checkbox" data-s="results_hold"${c.results_hold ? " checked" : ""}> <b>hold all public results</b> (switches every public result off at once; your own results stay available)</label>
          <label style="display:block;margin-top:10px">Method note shown with public results (how people were reached, dates, who was asked)<textarea data-s="method_note" rows="3" maxlength="1500">${esc(c.method_note || "")}</textarea></label></section>`;
      body.querySelectorAll("[data-s]").forEach(inp => { const k = inp.dataset.s; inp.onchange = inp.oninput = () => {
        if (inp.type === "checkbox") c[k] = inp.checked; else if (inp.multiple) c[k] = [...inp.selectedOptions].map(o => o.value); else if (inp.type === "number") c[k] = inp.value === "" ? null : +inp.value; else if (inp.type === "datetime-local") c[k] = istIso(inp.value); else c[k] = inp.value;
        if (["category"].includes(k)) drawSettings(body); }; });
    };

    /* ------------------------------------------------------------------ share and open */
    const drawShare = async body => {
      const url = `${data.base_url}/survey/${cur.slug}`, inv = cur.access === "invite" ? await fresh("/api/v1/surveys/invites", {id: cur.id}) : null;
      body.innerHTML = `<section class="card"><h2>Status: ${stateTag(cur)}</h2><div class="btnrow">${cur.status !== "live" ? '<button class="btn primary" data-st="live">Open it to answers</button>' : '<button class="btn" data-st="closed">Close it</button>'}${cur.status !== "draft" ? '<button class="btn" data-st="draft">Back to draft</button>' : ""}</div>
        <p class="muted" style="margin-top:8px">Only an open survey takes answers. It also closes by itself at its closing time or when the answer limit is reached.</p></section>
        <section class="card" style="margin-top:14px"><h2>The link</h2><div class="btnrow"><input readonly value="${esc(url)}" style="flex:1;min-width:260px" id="svlink"><button class="btn" id="svcopy">Copy</button><a class="btn" href="${esc(url)}" target="_blank" rel="noopener">Open ↗</a></div>
          <p class="muted" style="margin-top:8px">Share it by WhatsApp, SMS, e-mail, a QR code or a post. ${cur.listed ? "It is also on the public Polls page." : "It is not on the public Polls page (change that under Settings)."} ${cur.results_mode === "public" || cur.results_mode === "after_close" ? `Public results: <a href="${esc(url)}/results" target="_blank" rel="noopener">${esc(url)}/results</a>` : ""}</p></section>
        ${inv ? `<section class="card" style="margin-top:14px"><h2>Invitation links</h2><p class="muted">${inv.used} of ${inv.total} used. Each link works once. The links are shown only when you make them, so download them then.</p>
          <div class="svgrid"><label>One name per line (a link is made for each)<textarea id="svnames" rows="4" placeholder="Asha Rao&#10;Ravi Kumar"></textarea></label><label>Or just a number of links<input id="svcount" type="number" min="1" max="5000"></label></div><div class="btnrow" style="margin-top:8px"><button class="btn primary" id="svmake">Make links</button></div><div id="svlinks"></div></section>` : ""}`;
      $("#svcopy", body).onclick = async () => { try { await navigator.clipboard.writeText(url); say("Link copied.", true); } catch { $("#svlink", body).select(); } };
      body.querySelectorAll("[data-st]").forEach(b => b.onclick = async () => { try { const r = await post("/api/v1/surveys/status", {id: cur.id, status: b.dataset.st}); cur = {...cur, ...r.survey}; edit(); say("Done.", true); } catch (e) { say(e.message); } });
      const make = $("#svmake", body); if (make) make.onclick = async () => { try { const names = $("#svnames", body).value.split("\n").map(x => x.trim()).filter(Boolean), r = await post("/api/v1/surveys/invites/create", {id: cur.id, labels: names.length ? names : undefined, count: names.length ? 0 : +($("#svcount", body).value || 0)});
        const csv = "Name,Link\n" + r.links.map(l => `"${l.label.replace(/"/g, '""')}",${l.url}`).join("\n"); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + csv], {type: "text/csv"})); a.download = cur.slug + "-links.csv";
        $("#svlinks", body).innerHTML = `<div class="msg ok">${esc(r.message)} ${r.links.length} link(s) made.</div>`; $("#svlinks", body).append(Object.assign(document.createElement("button"), {className: "btn primary", textContent: "Download the links (CSV)", onclick: () => a.click()})); } catch (e) { say(e.message); } };
    };

    /* ------------------------------------------------------------------ results */
    const bar = pct => `<div class="svbar"><i style="width:${Math.min(100, pct || 0)}%"></i></div>`;
    const drawResults = async body => {
      let flagged = "1", res;
      const load = async () => { res = await fresh("/api/v1/surveys/results", {id: cur.id, flagged}); show(); };
      const show = () => {
        const t = res.totals, choiceQs = res.questions.filter(q => ["single", "dropdown", "multi"].includes(q.type)), splitQs = res.questions.filter(q => ["single", "dropdown"].includes(q.type));
        body.innerHTML = `<div class="btnrow" style="margin-bottom:10px"><label><input type="checkbox" id="svfl"${flagged === "1" ? " checked" : ""}> include flagged answers</label><span style="flex:1"></span><label><input type="checkbox" id="svct"> include contact details in the file</label>
            <button class="btn" data-ex="csv">Download CSV</button><button class="btn" data-ex="xlsx">Download Excel</button><button class="btn" onclick="window.print()">Print</button></div>
          <div class="grid kpis">${[["Answers counted", t.counted], ["Valid", t.valid], ["Flagged", t.flagged], ["Removed", t.removed], ["Median time", t.median_seconds ? t.median_seconds + " s" : "—"]].map(([l, v]) => `<div class="card kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("")}</div>
          <div class="svwarn" style="${res.scientific ? "border-color:#2f7d5b;background:#0e2a1e" : ""}">${esc(res.note)}${cur.sponsor ? " Commissioned by: " + esc(cur.sponsor) + "." : ""}</div>
          ${res.by_day.length > 1 ? `<section class="card"><b>Answers by day</b>${res.by_day.map(d => `<div class="svres"><div class="row"><span>${esc(d.date)}</span>${bar(100 * d.count / Math.max(...res.by_day.map(x => x.count)))}<b>${d.count}</b></div></div>`).join("")}</section>` : ""}
          ${res.questions.map(q => `<section class="card svres" style="margin-top:14px"><h3 style="margin:0 0 4px">${esc(q.id)}. ${esc(q.text)}${q.archived ? ' <span class="tag red">archived</span>' : ""}</h3><div class="muted">${q.n} answered</div>${renderQ(q)}</section>`).join("") || '<p class="muted">No questions yet.</p>'}
          ${splitQs.length && choiceQs.length ? `<section class="card" style="margin-top:14px"><h3 style="margin:0 0 8px">Split the answers by group</h3><div class="svgrid"><label>Look at<select id="svt">${choiceQs.map(q => `<option value="${q.id}">${esc(q.id)}. ${esc(q.text.slice(0, 60))}</option>`).join("")}</select></label><label>Split by<select id="svb">${splitQs.map(q => `<option value="${q.id}">${esc(q.id)}. ${esc(q.text.slice(0, 60))}</option>`).join("")}</select></label></div><div class="btnrow" style="margin-top:8px"><button class="btn primary" id="svx2">Show the split</button></div><div id="svxout"></div></section>` : ""}`;
        $("#svfl", body).onchange = e => { flagged = e.target.checked ? "1" : "0"; load(); };
        body.querySelectorAll("[data-ex]").forEach(b => b.onclick = async () => { try { await download("/api/v1/surveys/export", {id: cur.id, format: b.dataset.ex, contact: $("#svct", body).checked ? "1" : "0", flagged}, `${cur.slug}.${b.dataset.ex}`); } catch (e) { say(e.message); } });
        const x = $("#svx2", body); if (x) x.onclick = async () => { try { const r = await fresh("/api/v1/surveys/crosstab", {id: cur.id, target: $("#svt", body).value, by: $("#svb", body).value, flagged});
          $("#svxout", body).innerHTML = `<div style="overflow:auto;margin-top:10px"><table class="svx"><thead><tr><th></th>${r.columns.map(c => `<th>${esc(c.text)}<div class="muted">n=${c.n}</div></th>`).join("")}</tr></thead><tbody>${r.rows.map(row => `<tr><td>${esc(row.text)}</td>${row.cells.map(c => `<td>${c.pct == null ? "—" : c.pct + "%"} <span class="muted">(${c.count})</span></td>`).join("")}</tr>`).join("")}</tbody></table></div><p class="muted">Column percentages. ${esc(r.note)}</p>`; } catch (e) { say(e.message); } };
      };
      const renderQ = q => {
        if (["single", "dropdown", "multi"].includes(q.type)) return q.options.map(o => `<div class="row"><span>${esc(o.text)}${o.archived ? " (archived)" : ""}</span>${bar(o.pct)}<b>${o.pct}%${o.moe != null ? ` <span class="muted">±${o.moe}</span>` : ""} <span class="muted">(${o.count})</span></b></div>`).join("") + (q.other_texts && q.other_texts.length ? `<details><summary>Written-in answers (${q.other_texts.length})</summary>${q.other_texts.map(t => `<div class="muted">· ${esc(t)}</div>`).join("")}</details>` : "");
        if (q.type === "ranking") return q.options.map(o => `<div class="row"><span>${esc(o.text)}</span>${bar(o.first_pct)}<b>avg rank ${o.avg_rank ?? "—"} <span class="muted">(${o.first_pct}% first)</span></b></div>`).join("");
        if (q.type === "rating" || q.type === "nps") return `<p>Average <b>${q.mean ?? "—"}</b>, median ${q.median ?? "—"}${q.nps ? `. Recommend score <b>${q.nps.score}</b> (${q.nps.promoters} promoters, ${q.nps.passives} passives, ${q.nps.detractors} detractors)` : ""}</p>` + q.distribution.map(d => `<div class="row"><span>${d.value}</span>${bar(d.pct)}<b>${d.pct}% <span class="muted">(${d.count})</span></b></div>`).join("");
        if (q.type === "number") return `<p>Average <b>${q.mean ?? "—"}</b>, median ${q.median ?? "—"}, from ${q.min ?? "—"} to ${q.max ?? "—"}</p>`;
        return `<details><summary>Answers (${q.texts.length} shown)</summary>${q.texts.map(t => `<div style="border-top:1px solid var(--line);padding:6px 0">${esc(t)}</div>`).join("")}</details>`;
      };
      body.innerHTML = '<p class="muted">Loading…</p>'; try { await load(); } catch (e) { body.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`; }
    };

    /* ------------------------------------------------------------------ the individual answers */
    const drawAnswers = async body => {
      let page = 1, status = "";
      const load = async () => { const r = await fresh("/api/v1/surveys/responses", {id: cur.id, page, status}); const qs = Object.fromEntries((cur.questions || []).map(q => [q.id, q.text]));
        body.innerHTML = `<div class="btnrow" style="margin-bottom:10px"><label>Show<select id="svs"><option value="">All</option><option value="valid"${status === "valid" ? " selected" : ""}>Valid</option><option value="flagged"${status === "flagged" ? " selected" : ""}>Flagged</option><option value="removed"${status === "removed" ? " selected" : ""}>Removed</option></select></label><span class="muted" style="align-self:center">${r.total} answer(s)</span><span style="flex:1"></span><button class="btn" id="svpurge">Delete the removed ones for good</button></div>
          ${r.responses.map(x => `<section class="card" style="margin-top:10px"><div class="btnrow"><b>#${x.id}</b><span class="muted">${esc(x.time)}${x.seconds != null ? " · " + x.seconds + " s" : ""}</span><span class="tag ${x.status === "valid" ? "green" : x.status === "removed" ? "red" : ""}">${esc(x.status)}</span>${x.flags ? `<span class="muted">${esc(x.flags)}</span>` : ""}<span style="flex:1"></span>
            ${x.status !== "valid" ? `<button class="btn" data-set="${x.id}" data-to="valid">Count it</button>` : ""}${x.status !== "removed" ? `<button class="btn" data-set="${x.id}" data-to="removed">Remove</button>` : ""}</div>${Object.entries(x.answers).map(([id, a]) => `<div style="padding:4px 0"><span class="muted">${esc(qs[id] || id)}</span><br>${esc(a)}</div>`).join("")}</section>`).join("") || '<p class="muted">No answers yet.</p>'}
          <div class="btnrow" style="margin-top:12px"><button class="btn" id="svprev2"${page <= 1 ? " disabled" : ""}>← Newer</button><button class="btn" id="svnext2"${page * r.size >= r.total ? " disabled" : ""}>Older →</button></div>`;
        $("#svs", body).onchange = e => { status = e.target.value; page = 1; load(); }; $("#svprev2", body).onclick = () => { page--; load(); }; $("#svnext2", body).onclick = () => { page++; load(); };
        body.querySelectorAll("[data-set]").forEach(b => b.onclick = async () => { try { await post("/api/v1/surveys/response-status", {id: +b.dataset.set, status: b.dataset.to}); load(); } catch (e) { say(e.message); } });
        $("#svpurge", body).onclick = async () => { if (!confirm("Delete the removed answers for good? This cannot be undone.")) return; try { const p = await post("/api/v1/surveys/purge", {id: cur.id}); say(`${p.purged} answer(s) deleted.`, true); load(); } catch (e) { say(e.message); } }; };
      body.innerHTML = '<p class="muted">Loading…</p>'; try { await load(); } catch (e) { body.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`; }
    };

    try { await list(); } catch (e) { out.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`; }
  }, {admin: 1});
})();
