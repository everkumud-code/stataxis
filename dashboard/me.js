/* My account: what I see and who I am. Loaded by workspace.html after market.js, so it can use that script's helpers ($, esc, api, post, add, head, state, VIEWS ...).
   - the first-sign-in choice: who I am in the market, which screens I want, my languages and groups, where to land
   - the Profile screen: my details, my view, my password
   What a person MAY see is decided by their package and what an administrator ticked (the server enforces it); this file only lets them narrow that to what is relevant to them. */
"use strict";
(() => {
  const GROUPS = [["Intelligence", ["overview", "market", "channel", "dashboard", "stream", "content", "competition", "trends", "live", "stx", "changed", "research", "evaluate"]],
    ["Reports and tools", ["briefing", "weekly", "primetime", "builder", "creators", "planner", "authenticity", "audience", "liveevent"]]];

  /* the choice dialog; resolves when the person has saved (or, on the first sign-in, chosen to see everything they may use) */
  const choose = (me, first) => new Promise(resolve => {
    const prefs = me.preferences, may = me.views.filter(v => v.allowed), label = Object.fromEntries(me.views.map(v => [v.id, v.label]));
    const persona = prefs.persona || "";
    const chosen = new Set(prefs.views || (persona ? me.personas.find(p => p.id === persona).views : may.map(v => v.id)));
    const dlg = document.createElement("dialog"); dlg.className = "pwdlg"; dlg.style.cssText = "max-width:760px;width:calc(100vw - 32px);padding:22px;border:1px solid #159de8;border-radius:14px;background:#071a2b;color:#e8f0f8";
    const ROW = "display:flex;flex-direction:row;gap:9px;align-items:center;justify-content:flex-start;text-align:left";   /* the workspace stacks labels; a choice is a box and its words on one line */
    const NOFILL = "width:auto;flex:none;margin:0";
    const box = (name, id, text, on) => `<label style="${ROW};margin:4px 0"><input type="checkbox" style="${NOFILL}" name="${name}" value="${esc(id)}"${on ? " checked" : ""}> <span>${esc(text)}</span></label>`;
    dlg.innerHTML = `<form method="dialog" id="obf"><h2 style="margin:0 0 6px">${first ? "Welcome. What would you like to see?" : "What I see"}</h2>
      <p class="muted" style="margin:0 0 14px">${first ? "Pick who you are and StatAxis will show you only what is useful to you. You can change this any time under Profile." : "Change who you are and which screens you see."}</p>
      <h3 style="margin:10px 0 6px">1. Who are you?</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px">${me.personas.map(p => `<label class="card" style="cursor:pointer;${ROW}"><input type="radio" style="${NOFILL}" name="persona" value="${esc(p.id)}"${persona === p.id ? " checked" : ""}> <b>${esc(p.label)}</b></label>`).join("")}</div>
      <h3 style="margin:14px 0 6px">2. Screens I want in my menu</h3><p class="muted" style="margin:0 0 6px">Screens your package does not include are not listed.</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px">${GROUPS.map(([g, ids]) => `<div><div class="muted" style="margin-bottom:4px">${esc(g)}</div>${ids.filter(i => may.some(v => v.id === i)).map(i => box("views", i, label[i], chosen.has(i))).join("") || '<span class="muted">Nothing here for your package.</span>'}</div>`).join("")}</div>
      <h3 style="margin:14px 0 6px">3. My languages and groups <span class="muted" style="font-weight:400">(optional: used as the starting filter)</span></h3>
      <div style="display:flex;gap:26px;flex-wrap:wrap"><div>${me.languages.map(l => box("languages", l, l, (prefs.languages || []).includes(l))).join("")}</div><div>${me.segments.map(s => box("segments", s.id, s.label, (prefs.segments || []).includes(s.id))).join("")}</div></div>
      <h3 style="margin:14px 0 6px">4. Where should I land?</h3><select name="start_view" id="obstart"></select>
      <div id="obmsg" class="msg bad" hidden style="margin-top:10px"></div>
      <div class="btnrow" style="margin-top:16px">${first ? '<button class="btn" type="button" id="oball">Show me everything I may use</button>' : '<button class="btn" type="button" id="obno">Cancel</button>'}<button class="btn primary" type="submit" id="obsave">Save and continue</button></div></form>`;
    document.body.appendChild(dlg);
    const form = dlg.querySelector("#obf"), startSel = dlg.querySelector("#obstart"), msg = dlg.querySelector("#obmsg");
    const picked = () => [...form.querySelectorAll('input[name="views"]:checked')].map(i => i.value);
    const fillStart = () => { const cur = startSel.value || prefs.start_view || ""; startSel.innerHTML = [...picked(), "mychannels", "profile"].map(i => `<option value="${i}"${i === cur ? " selected" : ""}>${esc(label[i] || (i === "profile" ? "Profile" : "My channels"))}</option>`).join(""); };
    fillStart();
    form.addEventListener("change", ev => {
      if (ev.target.name === "persona") { const set = new Set(me.personas.find(p => p.id === ev.target.value).views); form.querySelectorAll('input[name="views"]').forEach(i => { i.checked = set.has(i.value); }); }
      fillStart();
    });
    const save = async everything => {
      const f = new FormData(form), body = {persona: everything ? null : (f.get("persona") || null), views: everything ? null : picked(), languages: everything ? [] : f.getAll("languages"), segments: everything ? [] : f.getAll("segments"), start_view: everything ? null : (f.get("start_view") || null)};
      if (!everything && !body.views.length) { msg.hidden = false; msg.textContent = "Keep at least one screen."; return; }
      try { const d = await post("/api/v1/me/preferences", body); dlg.close(); dlg.remove(); resolve(d); }
      catch (e) { msg.hidden = false; msg.textContent = e.message; }
    };
    form.onsubmit = ev => { ev.preventDefault(); save(false); };
    if (first) { dlg.addEventListener("cancel", ev => ev.preventDefault()); dlg.querySelector("#oball").onclick = () => save(true); }
    else { dlg.addEventListener("cancel", () => { dlg.remove(); resolve(null); }); dlg.querySelector("#obno").onclick = () => { dlg.close(); dlg.remove(); resolve(null); }; }
    dlg.showModal();
  });

  /* what the workspace calls at sign-in */
  window.runOnboarding = me => choose(me, true);
  window.applyPreferenceDefaults = me => {
    const p = me.preferences, m = window.__sxMarket;
    if (!sessionStorage.getItem("sx_ws_filters") && p.languages.length === 1) { F.language = p.languages[0]; saveF(); }
    if (m && !m.SP.brief && p.persona) m.keep("brief", {persona: p.persona, days: "7", segment: p.segments.length === 1 ? p.segments[0] : "", language: p.languages.length === 1 ? p.languages[0] : ""});
  };

  add("profile", "My account", "Profile", async el => {
    cache.clear();
    const me = await api("/api/v1/me"); ME = me;
    const a = me.account, p = me.preferences, persona = (me.personas.find(x => x.id === p.persona) || {}).label;
    const plan = (a.plan || "").replace(/^sx_/, "SX ").replace(/\b\w/g, c => c.toUpperCase());
    el.innerHTML = head("Profile", "Your details, what you see in the workspace, and your password.") + `<div id="pfmsg" class="msg" hidden></div>
      <section class="card"><h2>About me</h2><form id="pff" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;align-items:end">
        <label>Name<br><input type="text" name="full_name" maxlength="255" required value="${esc(a.full_name || "")}"></label>
        <label>Job title<br><input type="text" name="job_title" maxlength="120" value="${esc(a.job_title || "")}"></label>
        <label>Mobile<br><input type="text" name="mobile" maxlength="32" value="${esc(a.mobile || "")}"></label>
        <label>Login ID<br><input type="text" value="${esc(a.email)}" disabled></label>
        <label>Organisation<br><input type="text" value="${esc(a.organization || "")}" disabled></label>
        <label>Package<br><input type="text" value="${esc(a.is_admin ? "Administrator" : plan)}" disabled></label>
        <button class="btn primary" type="submit">Save my details</button></form>
        <p class="muted" style="margin-top:8px">Your login ID, organisation and package are changed by an administrator.</p></section>
      <section class="card" style="margin-top:14px"><h2>What I see</h2>
        <p>${persona ? `<b>${esc(persona)}</b> · ` : ""}${me.nav.length} screen${me.nav.length === 1 ? "" : "s"} in my menu${p.languages.length ? " · languages: " + esc(p.languages.join(", ")) : ""}${p.segments.length ? " · groups: " + esc(p.segments.map(s => (me.segments.find(x => x.id === s) || {}).label || s).join(", ")) : ""}</p>
        <p class="muted">${me.nav.map(i => esc((me.views.find(v => v.id === i) || {}).label || i)).join(" · ")}</p>${me.menu_choices_on ? "" : `<p class="muted">Right now every screen you may use is shown to everyone. Your choices are saved and will apply again when packages are switched back on.</p>`}
        <div class="btnrow"><button class="btn primary" type="button" id="pfview">Change what I see</button></div></section>
      <section class="card" style="margin-top:14px"><h2>Security</h2><p class="muted">Use at least 12 characters. Nobody at StatAxis can read your password.</p><div class="btnrow"><button class="btn" type="button" id="pfpw">Change my password</button></div></section>`;
    const say = (t, ok) => { const m = el.querySelector("#pfmsg"); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    el.querySelector("#pff").onsubmit = async ev => { ev.preventDefault(); try { const d = await post("/api/v1/me/profile", Object.fromEntries(new FormData(ev.target))); ME = d; $("#who").innerHTML = `<b>${esc(d.account.full_name || d.account.email)}</b>${esc(d.account.organization || "")}`; say("Saved.", true); } catch (e) { say(e.message); } };
    el.querySelector("#pfpw").onclick = () => $("#chpw").click();
    el.querySelector("#pfview").onclick = async () => { const d = await choose(me, false); if (d) { ME = d; NAV = d.nav; applyPreferenceDefaults(d); buildNav("profile"); render(); } };
  });
})();
