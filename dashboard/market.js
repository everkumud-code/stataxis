/* Market tools for the workspace: weekly report, prime time, report builder (PDF), IFX Score, media planner, authenticity radar,
   and the admin screens for users, package access, channel groups and the YouTube quota. Loaded by workspace.html after its own script,
   so it can use that script's helpers ($, esc, api, post, table, head, state, add, token, isAdmin ...). */
"use strict";
(() => {
  const SEGMENTS = [["", "All groups"], ["news", "News"], ["business", "Business news"], ["print", "Print media"], ["party", "Political parties"], ["leader", "Political leaders"],
    ["commentator", "Political commentators"], ["creator", "Creators & influencers"], ["journalist", "Independent journalists"], ["brand", "Brands & entertainment"]];
  const GENRES = ["Politics", "Sports", "Entertainment", "Business", "Current Affairs", "Other"];
  const LANGS = [["", "All languages"], ["Hindi", "Hindi"], ["English", "English"], ["Regional", "Regional"]];
  const opt = (list, cur) => list.map(([v, l]) => `<option value="${esc(v)}"${String(cur ?? "") === v ? " selected" : ""}>${esc(l)}</option>`).join("");
  const istDay = off => new Date(Date.now() + off * 864e5).toLocaleDateString("en-CA", {timeZone: "Asia/Kolkata"});
  const qs = o => Object.entries(o).filter(([, v]) => v !== "" && v != null && v !== false).map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v === true ? "1" : v)).join("&");
  const fdate = s => { const d = new Date(s + "T00:00:00"); return isNaN(d) ? s : d.toLocaleDateString("en-IN", {day: "numeric", month: "short", year: "numeric"}); };
  const AGES = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"];
  const STATES = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"];
  const SOURCES = [["youtube_analytics", "YouTube Studio analytics shown by the channel"], ["channel_media_kit", "Channel's media kit"], ["third_party_study", "Named third-party study"], ["admin_entered", "Entered by the STAXIS team"]];
  let MINE = []; /* ids of the channels mapped to this login (approved claims) */
  const loadMine = async () => { try { MINE = (await api("/api/v1/my/channels")).channel_ids || []; } catch { MINE = []; } };
  loadMine();
  const SP = JSON.parse(sessionStorage.getItem("sx_market") || "{}");
  const keep = (k, v) => { SP[k] = v; try { sessionStorage.setItem("sx_market", JSON.stringify(SP)); } catch { /* storage blocked */ } };
  window.__sxMarket = {SP, keep};   /* used by me.js to start the briefing on the person's own role */
  const num = v => v == null || v === "" ? "—" : Number(v).toLocaleString("en-IN", {maximumFractionDigits: 1});
  const MULTI = new Set(["channels", "states", "ages"]);
  /* The values of a form, with the choose-several fields (channels, places, age groups) joined with commas so the API gets one value for each */
  const formValues = form => {
    const fd = new FormData(form), out = {};
    for (const [k, v] of fd.entries()) out[k] = MULTI.has(k) ? (out[k] ? out[k] + "," : "") + v : v;
    return out;
  };
  const has = (csv, v) => String(csv || "").split(",").includes(v);
  /* Category, language and time are in each screen's own form; this is the rest of the common filters: an individual channel, place, age group and gender. */
  const filterFields = (f, {place = true, age = true, channel = true, known = true} = {}) => `<details style="grid-column:1/-1" ${(f.channels || f.states || f.ages || f.gender) ? "open" : ""}><summary class="muted">More filters: ${[channel && "individual channel", place && "place", age && "age group"].filter(Boolean).join(", ")}</summary>
    <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:start;margin-top:10px">
    ${channel ? `<label>Channel(s)<br><select name="channels" multiple size="6" style="min-width:220px">${optsByLanguage(typeof channels !== "undefined" ? channels : [], c => has(f.channels, String(c.id)))}</select><br><span class="muted">None chosen means all</span>${MINE.length ? `<br><button class="btn" type="button" data-mine style="margin-top:6px">Select my channels</button>` : ""}</label>` : ""}
    ${place ? `<label>Place (states)<br><select name="states" multiple size="6" style="min-width:200px">${STATES.map(s => `<option${has(f.states, s) ? " selected" : ""}>${esc(s)}</option>`).join("")}</select></label>` : ""}
    ${age ? `<div><div class="muted">Age group</div>${AGES.map(a => `<label style="display:block"><input type="checkbox" name="ages" value="${a}"${has(f.ages, a) ? " checked" : ""}> ${a}</label>`).join("")}
      <label style="display:block;margin-top:8px">Gender<br><select name="gender">${opt([["", "Any"], ["male", "Male"], ["female", "Female"]], f.gender || "")}</select></label></div>` : ""}
    ${known && (place || age) ? `<label style="max-width:240px"><input type="checkbox" name="known_only"${f.known_only ? " checked" : ""}> Only channels whose audience is known<br><span class="muted">Place and age work only where the channel or a study supplied its audience; other channels show "no audience data".</span></label>` : ""}</div></details>`;
  const method = text => `<details class="card" style="margin-top:14px"><summary>How these numbers were worked out</summary><p class="muted" style="margin-top:8px">${esc(text)}</p></details>`;

  /* ---------- a picture card to post (PNG): branded, with the logo tiled faintly over it ---------- */
  let logoImg = null;
  const logo = () => logoImg || (logoImg = new Promise(res => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = "/assets/stataxis-logo.svg"; }));
  async function cardPng(title, subtitle, rows, {unit = "", footer = ""} = {}) {
    const W = 1080, rowH = 74, top = 220, H = top + rows.length * rowH + 130;
    const c = document.createElement("canvas"); c.width = W; c.height = H; const x = c.getContext("2d");
    x.fillStyle = "#061322"; x.fillRect(0, 0, W, H);
    const lg = await logo();
    if (lg) {
      x.save(); x.globalAlpha = 0.06; x.translate(W / 2, H / 2); x.rotate(-0.55);
      for (let r = -9; r <= 9; r++) for (let k = -4; k <= 4; k++) x.drawImage(lg, k * 420 + (r % 2) * 210 - 150, r * 150 - 38, 300, 75);
      x.restore();
      x.drawImage(lg, 44, 28, 300, 75);
    } else { x.fillStyle = "#e1b94f"; x.font = "800 34px Manrope, Inter, system-ui, sans-serif"; x.fillText("STATAXIS", 50, 70); }
    x.fillStyle = "#7f9ab2"; x.font = "500 20px Manrope, Inter, system-ui, sans-serif"; x.textAlign = "right"; x.fillText("Stat the View. Axis the Viewpoint.", W - 50, 66); x.textAlign = "left";
    x.fillStyle = "#e8f1f8"; x.font = "800 38px Manrope, Inter, system-ui, sans-serif"; x.fillText(title.slice(0, 48), 50, 150);
    x.fillStyle = "#9db3c6"; x.font = "500 22px Manrope, Inter, system-ui, sans-serif"; x.fillText(subtitle.slice(0, 80), 50, 188);
    const max = Math.max(...rows.map(r => r.value), 1), left = 330, bar = W - left - 190;
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      x.fillStyle = "#e8f1f8"; x.font = "700 26px Manrope, Inter, system-ui, sans-serif"; x.fillText(String(r.label).slice(0, 20), 50, y + 40);
      x.fillStyle = i === 0 ? "#e1b94f" : "#159de8"; x.fillRect(left, y + 14, Math.max(4, bar * r.value / max), 36);
      x.fillStyle = "#e8f1f8"; x.font = "800 26px Manrope, Inter, system-ui, sans-serif"; x.fillText(r.text || (compact(r.value) + unit), left + Math.max(4, bar * r.value / max) + 14, y + 42);
    });
    x.fillStyle = "#e1b94f"; x.fillRect(50, H - 92, W - 100, 2);
    x.fillStyle = "#7f9ab2"; x.font = "500 18px Manrope, Inter, system-ui, sans-serif"; x.fillText(footer.slice(0, 80), 50, H - 62);
    x.textAlign = "right"; x.fillStyle = "#e1b94f"; x.fillText("Downloaded " + window.sxDownloadedAt(), W - 50, H - 62); x.textAlign = "left"; x.fillStyle = "#7f9ab2";
    x.fillText("Data via YouTube API Services. Not endorsed by YouTube. Not TV ratings.   stataxis.org", 50, H - 32);
    return c;
  }
  function saveCanvas(canvas, name) { canvas.toBlob(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = name.replace(/\.png$/, "") + "-downloaded-" + window.sxFileStamp() + ".png"; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }, "image/png"); }
  const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  async function downloadFile(path, params, fallbackName, msgEl) {
    try {
      const res = await fetch(path + "?" + qs(params), {headers: {Authorization: "Bearer " + token()}});
      if (!res.ok) { let m = "Could not make the file."; try { m = (await res.json()).error || m; } catch { /* not JSON */ } throw new Error(m); }
      const cd = res.headers.get("Content-Disposition") || "", name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName;
      const blob = await res.blob(), a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      if (msgEl) { msgEl.className = "msg ok"; msgEl.textContent = "Downloaded " + name; }
    } catch (e) { if (msgEl) { msgEl.className = "msg bad"; msgEl.textContent = e.message; } }
  }
  const dateFilters = (el, id, extra, onGo) => {
    const f = SP[id] || {from: istDay(-7), to: istDay(-1), segment: "", language: ""};
    el.insertAdjacentHTML("beforeend", `<form class="card" id="${id}-f" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0">
      <label>Category<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label><label>Language<br><select name="language">${opt(LANGS, f.language)}</select></label>
      <label>From<br><input type="date" name="from" value="${esc(f.from)}"></label><label>To<br><input type="date" name="to" value="${esc(f.to)}"></label>${extra || ""}
      ${filterFields(f)}<button class="btn primary" type="submit">Show</button></form>`);
    $("#" + id + "-f", el).onsubmit = ev => { ev.preventDefault(); const v = formValues(ev.target); keep(id, v); onGo(v); };
    return f;
  };
  const cardsBtn = (label, attrs) => `<button class="btn" type="button" ${attrs}>${esc(label)}</button>`;

  /* ---------- weekly views ---------- */
  add("weekly", "Market tools", "Weekly report", async el => {
    el.innerHTML = head("Weekly report", "Views of every video uploaded in the chosen dates, per channel, with each channel's share of its group. Download a picture card to post.");
    const out = document.createElement("div"); el.append(out);
    const run = async v => {
      out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/market/weekly", v);
        if (!d.groups.length) { out.innerHTML = state("Nothing in these dates", "No uploads were measured with these filters. Nothing is estimated."); return; }
        out.innerHTML = d.groups.map((g, gi) => `<section class="card" style="margin-top:14px"><div class="head"><h2>${esc(g.label)} <span class="muted">· ${esc(whole(g.total_views))} views</span></h2></div>${table([
          {h: "#", v: r => r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.name)}</strong>`}, {h: "Views (million)", n: 1, v: r => dec(r.views / 1e6, 1)}, {h: "Share", n: 1, v: r => r.share_percent == null ? "—" : r.share_percent + "%"},
          {h: "Videos", n: 1, v: r => r.videos}, {h: "Measured", n: 1, v: r => r.coverage_percent == null ? "—" : r.coverage_percent + "%"}, {h: "Stale", n: 1, v: r => r.stale_videos}], g.channels)}
          <div class="btnrow" style="margin-top:10px">${cardsBtn("Download picture card (PNG)", `data-png="${gi}"`)}</div></section>`).join("") + method(d.method);
        out.querySelectorAll("[data-png]").forEach(b => b.onclick = async () => { const g = d.groups[+b.dataset.png];
          saveCanvas(await cardPng(g.label + " YouTube weekly", `Views of videos uploaded ${fdate(d.from)} – ${fdate(d.to)}`, g.channels.slice(0, 10).map(r => ({label: r.name, value: r.views, text: dec(r.views / 1e6, 1) + "M  ·  " + (r.share_percent ?? "—") + "%"})), {footer: `Share of ${g.label}. Views as last measured by STAXIS.`}), `stataxis-weekly-${slug(g.label)}-${d.from}.png`); });
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    run(dateFilters(el, "weekly", "", run));
  });

  /* ---------- prime time ---------- */
  add("primetime", "Market tools", "Prime time", async el => {
    el.innerHTML = head("Prime time", "Average live viewers for every evening hour, 5 PM to 11 PM Indian time, averaged over the chosen days. Top 5 channels per hour.");
    const out = document.createElement("div"); el.append(out);
    const run = async v => {
      out.innerHTML = `<p class="muted">Working it out (this reads several days of live samples)…</p>`;
      try {
        const d = await api("/api/v1/market/prime-time", v);
        out.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-top:14px">${d.slots.map((s, i) => `<section class="card"><h2>${esc(s.slot.replace("-", " – "))}</h2>${
          s.top.length ? table([{h: "#", v: r => r.rank}, {h: "Channel", v: r => r.name}, {h: "Average", n: 1, v: r => whole(r.average_concurrent)}, {h: "Peak", n: 1, v: r => whole(r.peak_concurrent)}], s.top) : `<p class="muted">Nobody was live in this hour on these days.</p>`}
          ${s.top.length ? `<div class="btnrow" style="margin-top:8px">${cardsBtn("Picture card (PNG)", `data-png="${i}"`)}</div>` : ""}</section>`).join("")}</div>` + method(d.method);
        out.querySelectorAll("[data-png]").forEach(b => b.onclick = async () => { const s = d.slots[+b.dataset.png];
          saveCanvas(await cardPng("Live viewers " + s.slot.replace("-", " – "), `Average over ${fdate(d.from)} – ${fdate(d.to)}, Indian time`, s.top.map(r => ({label: r.name, value: r.average_concurrent, text: whole(r.average_concurrent)})), {footer: "Average concurrent viewers across the live streams of each channel."}), `stataxis-primetime-${s.start_hour}-${s.end_hour}-${d.from}.png`); });
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    run(dateFilters(el, "primetime", "", run));
  });

  /* ---------- report builder ---------- */
  add("builder", "Market tools", "Report builder", async el => {
    const f = SP.builder || {from: istDay(-7), to: istDay(-1), start_hour: 9, end_hour: 12, scope: "live", feed: "all", genre: "", segment: "", language: "", by_genre: false};
    f.from = f.from || istDay(-7); f.to = f.to || istDay(-1);
    const hours = sel => Array.from({length: 25}, (_, h) => [String(h), String(h).padStart(2, "0") + ":00"]).map(([v, l]) => `<option value="${v}"${String(sel) === v ? " selected" : ""}>${l}</option>`).join("");
    el.innerHTML = head("Report builder", "Choose the days, the hours, what to count and the genre. See the ranking, then download it as a PDF.") + `<form class="card" id="bf" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;align-items:end">
      <label>From<br><input type="date" name="from" value="${esc(f.from)}"></label><label>To<br><input type="date" name="to" value="${esc(f.to)}"></label>
      <label>Hours from (IST)<br><select name="start_hour">${hours(f.start_hour)}</select></label><label>Hours to (IST)<br><select name="end_hour">${hours(f.end_hour)}</select></label>
      <label>What to count<br><select name="scope">${opt([["live", "Live streams (viewers)"], ["video", "Videos (views gained)"], ["shorts", "Shorts (views gained)"], ["replay", "Live replays (views gained)"]], f.scope)}</select></label>
      <label>Feed (live only)<br><select name="feed">${opt([["all", "All feeds"], ["primary", "Primary feed"], ["secondary", "Secondary feeds"]], f.feed)}</select></label>
      <label>Genre<br><select name="genre">${opt([["", "All genres"], ...GENRES.map(g => [g, g])], f.genre)}</select></label>
      <label>Category<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label><label>Language<br><select name="language">${opt(LANGS, f.language)}</select></label>
      <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" name="by_genre"${f.by_genre ? " checked" : ""}> Also split by genre</label>
      ${filterFields(f)}
      <div class="btnrow"><button class="btn primary" type="submit">Show ranking</button><button class="btn" type="button" id="bpdf">Download PDF</button></div></form><div id="bmsg" class="msg" hidden></div><div id="bout"></div>`;
    const read = () => { const form = $("#bf", el), v = formValues(form); v.by_genre = new FormData(form).has("by_genre"); v.known_only = new FormData(form).has("known_only"); keep("builder", v); return v; };
    const feedState = () => { $("#bf", el).elements.feed.disabled = $("#bf", el).elements.scope.value !== "live"; };
    $("#bf", el).elements.scope.onchange = feedState; feedState();
    const show = async () => {
      const v = read(), out = $("#bout", el); out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/market/report", {...v, by_genre: v.by_genre ? 1 : "", known_only: v.known_only ? 1 : ""});
        const live = d.kind === "audience";
        out.innerHTML = `<section class="card" style="margin-top:14px"><h2>${esc(d.scope_label)}${d.feed ? " · " + esc(d.feed) + " feeds" : ""} · ${String(d.start_hour).padStart(2, "0")}:00–${String(d.end_hour).padStart(2, "0")}:00 IST</h2><p class="muted">${esc(fdate(d.from))} – ${esc(fdate(d.to))} · genre: ${esc(d.genre || "all")}</p>${
          d.rows.length ? table(live ? [{h: "#", v: r => r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.name)}</strong>`}, {h: "Average viewers", n: 1, v: r => whole(r.average)}, {h: "Peak", n: 1, v: r => whole(r.peak)}, {h: "Share", n: 1, v: r => r.share_percent == null ? "—" : r.share_percent + "%"}, {h: "Days seen", n: 1, v: r => r.days_seen}]
            : [{h: "#", v: r => r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.name)}</strong>`}, {h: "Views gained", n: 1, v: r => whole(r.views)}, {h: "Share", n: 1, v: r => r.share_percent == null ? "—" : r.share_percent + "%"}, {h: "Videos", n: 1, v: r => r.videos}, {h: "New uploads", n: 1, v: r => r.uploads}], d.rows)
          : `<p class="muted">Nothing was measured in these hours with these filters. Nothing is estimated.</p>`}</section>${(d.by_genre || []).map(g => `<section class="card" style="margin-top:14px"><h2>Genre: ${esc(g.genre)}</h2>${table([{h: "#", v: r => r.rank}, {h: "Channel", v: r => r.name}, {h: live ? "Average" : "Views gained", n: 1, v: r => whole(live ? r.average : r.views)}], g.rows.slice(0, 5))}</section>`).join("")}
          ${!live ? `<p class="muted" style="margin-top:8px">Coverage: ${whole(d.coverage.videos_measured_at_both_ends)} of ${whole(d.coverage.videos_matching)} matching videos measured at both ends of the hours.</p>` : ""}${method(d.method)}`;
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#bf", el).onsubmit = ev => { ev.preventDefault(); show(); };
    $("#bpdf", el).onclick = () => { const v = read(), m = $("#bmsg", el); m.hidden = false; m.className = "msg"; m.textContent = "Making the PDF…"; downloadFile("/api/v1/market/report.pdf", {...v, by_genre: v.by_genre ? 1 : "", known_only: v.known_only ? 1 : ""}, "stataxis-report.pdf", m); };
  });

  /* ---------- IFX Score ---------- */
  const riskTag = r => r === "high" ? `<span class="tag red" title="Open high-risk flags in the authenticity radar">Under review</span>` : r === "review" ? `<span class="tag" title="Something unusual was flagged">Check</span>` : "";
  add("creators", "Market tools", "IFX Score", async el => {
    const f = SP.creators || {segment: "creator", days: "30"};
    el.innerHTML = head("IFX Score", "Impact · Followership · eXposure. A score for people who publish videos and Shorts instead of going live: influencers, independent journalists and commentators. Each is ranked against the others in the group.") +
      `<form class="card" id="cf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0"><label>Category<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label>
      <label>Language<br><select name="language">${opt(LANGS, f.language || "")}</select></label><label>Window<br><select name="days">${opt([["14", "14 days"], ["30", "30 days"], ["60", "60 days"], ["90", "90 days"]], f.days)}</select></label>
      ${filterFields(f, {place: false, age: false, known: false})}<button class="btn primary" type="submit">Show</button></form><div id="cout"></div>`;
    const bar = (v, color) => v == null ? `<span class="muted">—</span>` : `<span title="${v}" style="display:inline-flex;align-items:center;gap:6px"><span style="display:inline-block;width:54px;height:8px;background:#0b2032;border-radius:4px"><span style="display:block;height:8px;border-radius:4px;background:${color};width:${v}%"></span></span>${Math.round(v)}</span>`;
    const run = async () => {
      const v = formValues($("#cf", el)); keep("creators", v); const out = $("#cout", el); out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/market/creator-index", v);
        out.innerHTML = (d.note ? `<p class="msg">${esc(d.note)}</p>` : "") + `<section class="card">${table([
          {h: "#", v: r => r.rank ?? "—"}, {h: "Creator", html: 1, v: r => `<strong>${esc(r.name)}</strong> ${riskTag(r.authenticity_risk)}<br><span class="muted">${esc(r.profile)}</span>`},
          {h: "IFX", n: 1, html: 1, v: r => r.index_score == null ? `<span class="muted" title="${esc(r.withheld_reason || "Not enough peers or data")}">Not scored</span>` : `<strong style="font-size:1.1em">${dec(r.index_score)}</strong>${r.preliminary ? ' <span class="tag" title="Little data: the score is pulled toward 50">Preliminary</span>' : ""}`},
          {h: "Impact", html: 1, v: r => bar(r.pillars.impact, "#e1b94f")}, {h: "Followership", html: 1, v: r => bar(r.pillars.followership, "#159de8")}, {h: "eXposure", html: 1, v: r => bar(r.pillars.exposure, "#35d399")},
          {h: "Confidence", n: 1, v: r => r.confidence + "% " + r.confidence_label}, {h: "Strong on", v: r => r.strengths.join(", ") || "—"}, {h: "Watch", v: r => r.watch.join(", ") || "—"},
          {h: "Uploads", n: 1, v: r => `${r.uploads} (${r.uploads_video} video, ${r.uploads_shorts} Shorts)`}, {h: "Views per subscriber", n: 1, v: r => r.pull_percent == null ? "—" : r.pull_percent + "%"},
          {h: "Comments per 1,000 views", n: 1, v: r => r.comments_per_1000_views == null ? "—" : r.comments_per_1000_views}, {h: "Hit rate", n: 1, v: r => r.hit_rate_percent == null ? "—" : r.hit_rate_percent + "%"},
          {h: "Live turnout (median peak)", n: 1, v: r => r.live_streams ? `${whole(r.live_peak_median)} (${r.live_streams} live)` : "—"}, {h: "Last upload", n: 1, v: r => r.days_since_last_upload == null ? "—" : (r.days_since_last_upload < 1 ? "today" : Math.round(r.days_since_last_upload) + " d ago")},
          {h: "Best format", v: r => r.best_format || "—"}], d.channels, "No creators in this group yet. Admins can put channels in the Creators or Independent journalists group under Channel groups.", {group: r => r.language})}</section>
          <section class="card" style="margin-top:14px"><h2>What the three pillars are</h2><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px">
            <div><strong style="color:#e1b94f">Impact</strong> (${Math.round(d.pillar_weights.impact * 100)}%)<p class="muted">How strongly the content lands: depth of reaction, conversation in the comments and staying power. Saves, shares and conversions are not public on YouTube, so they are not counted.</p></div>
            <div><strong style="color:#159de8">Followership</strong> (${Math.round(d.pillar_weights.followership * 100)}%)<p class="muted">The audience behind the creator: its size, its loyalty (views per subscriber), its growth and, for creators who go live, the turnout at a live stream.</p></div>
            <div><strong style="color:#35d399">eXposure</strong> (${Math.round(d.pillar_weights.exposure * 100)}%)<p class="muted">How far and how often the creator is seen: reach per upload, regular publishing, steady results, hit rate and fresh uploads. YouTube only for now.</p></div></div>
            <p class="muted" style="margin-top:8px">Not measured: ${esc(d.not_measured.join("; "))}.</p></section>${method(d.method)}`;
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#cf", el).onsubmit = ev => { ev.preventDefault(); run(); }; run();
  });

  /* ---------- media planner ---------- */
  add("planner", "Market tools", "Media planner", async el => {
    const f = SP.planner || {start_hour: 20, end_hour: 22, days: 7, segment: "news", language: "", budget: "", max_share_percent: 40};
    const rates = SP.plannerRates || {};
    const hours = sel => Array.from({length: 25}, (_, h) => `<option value="${h}"${String(sel) === String(h) ? " selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("");
    el.innerHTML = head("Media planner", "Where to place your spots. Type your own rate for one spot on each channel; STAXIS shows the audience, the cost per 1,000 live viewers and a suggested split of your budget.") +
      `<form class="card" id="pf" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;align-items:end"><label>Spot time from (IST)<br><select name="start_hour">${hours(f.start_hour)}</select></label>
      <label>to<br><select name="end_hour">${hours(f.end_hour)}</select></label><label>Look at the last<br><select name="days">${opt([["3", "3 days"], ["7", "7 days"], ["14", "14 days"], ["28", "28 days"]], String(f.days))}</select></label>
      <label>Group<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label><label>Language<br><select name="language">${opt(LANGS, f.language)}</select></label>
      <label>Budget (₹, optional)<br><input type="number" name="budget" min="0" value="${esc(f.budget)}"></label><label>Most on one channel (%)<br><input type="number" name="max_share_percent" min="10" max="100" value="${esc(f.max_share_percent)}"></label>
      <fieldset style="grid-column:1/-1;border:1px solid var(--line);border-radius:10px;padding:10px 14px"><legend class="muted">Target audience (optional, only channels whose audience is known can be matched)</legend>
        <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:start"><div><div class="muted">Age</div>${AGES.map(a => `<label style="margin-right:10px"><input type="checkbox" name="t_age" value="${a}"${(f.t_age || []).includes(a) ? " checked" : ""}> ${a}</label>`).join("")}</div>
        <label>States<br><select name="t_states" multiple size="5" style="min-width:220px">${STATES.map(s => `<option${(f.t_states || []).includes(s) ? " selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
        <label>Gender<br><select name="t_gender">${opt([["", "Any"], ["male", "Male"], ["female", "Female"]], f.t_gender || "")}</select></label></div></fieldset>
      ${filterFields(f, {place: false, age: false, known: false})}<button class="btn primary" type="submit">Compare</button></form><div id="pout"></div>`;
    const run = async () => {
      const form = new FormData($("#pf", el)), fd = formValues($("#pf", el));
      const target = {ages: form.getAll("t_age"), states: form.getAll("t_states"), gender: form.get("t_gender") || ""};
      keep("planner", {...fd, t_age: target.ages, t_states: target.states, t_gender: target.gender}); const out = $("#pout", el); out.innerHTML = `<p class="muted">Working it out (reads several days of live samples)…</p>`;
      const typed = {...rates}; out.querySelectorAll?.("[data-rate]").forEach(i => { if (i.value) typed[i.dataset.rate] = Number(i.value); });
      try {
        const body = {start_hour: +fd.start_hour, end_hour: +fd.end_hour, days: +fd.days, segment: fd.segment, language: fd.language, budget: fd.budget ? +fd.budget : null, max_share_percent: +fd.max_share_percent || 40, rates: SP.plannerRates || {}, channels: fd.channels || "",
          target: (target.ages.length || target.states.length || target.gender) ? target : null};
        const tg = target.ages.length || target.states.length || target.gender;
        const d = await post("/api/v1/market/planner", body);
        const rk = {high: '<span class="tag red">High risk</span>', review: '<span class="tag">Check</span>', low: "", not_checked: ""};
        out.innerHTML = `<section class="card" style="margin-top:14px">${table([
          {h: "#", v: r => r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.name)}</strong> ${rk[r.authenticity_risk] || ""}`}, {h: "Average viewers", n: 1, v: r => whole(r.average_concurrent)}, {h: "Peak", n: 1, v: r => whole(r.peak_concurrent)},
          {h: "Share of audience", n: 1, v: r => r.audience_share_percent == null ? "—" : r.audience_share_percent + "%"}, {h: "Steadiness", n: 1, v: r => r.stability == null ? "—" : r.stability + "/100"}, {h: "Trend", n: 1, v: r => r.trend_percent == null ? "—" : (r.trend_percent > 0 ? "+" : "") + r.trend_percent + "%"},
          {h: "Days seen", n: 1, v: r => `${r.days_seen}/${r.days_in_range}`}, {h: "Your rate for one spot (₹)", n: 1, html: 1, v: r => `<input type="number" min="0" style="width:110px" data-rate="${esc(r.channel_id)}" value="${esc((SP.plannerRates || {})[r.channel_id] ?? "")}">`},
          {h: "Cost per 1,000 viewers", n: 1, v: r => r.cost_per_1000 == null ? "—" : "₹" + whole(r.cost_per_1000)},
          ...(tg ? [{h: "Audience match", n: 1, html: 1, v: r => r.audience_match ? Math.round(r.audience_match.share * 100) + "%" + (r.audience_match.missing.length ? ` <span class="tag" title="Profile has no ${esc(r.audience_match.missing.join(", "))}">partial</span>` : "") : '<span class="tag" title="Nobody has told STAXIS who watches this channel">no audience data</span>'},
            {h: "Matched viewers", n: 1, v: r => r.matched_audience == null ? "—" : whole(r.matched_audience)}, {h: "Cost per 1,000 matched", n: 1, v: r => r.cost_per_1000_matched == null ? "—" : "₹" + whole(r.cost_per_1000_matched)}] : []),
          {h: "Value index", n: 1, v: r => r.value_index == null ? "—" : r.value_index}], d.channels, d.note || "Nobody was live in these hours on these days.", {group: r => r.language})}
          <div class="btnrow" style="margin-top:10px"><button class="btn primary" type="button" id="precalc">Recalculate with my rates</button></div></section>${planBlock(d.plan)}
          <p class="muted" style="margin-top:8px">Value index: 100 is the middle of the channels you gave a rate for; higher is more audience per rupee. High-risk channels are never bought.</p>${method(d.method)}`;
        $("#precalc", out).onclick = () => { const r = {}; out.querySelectorAll("[data-rate]").forEach(i => { if (i.value) r[i.dataset.rate] = Number(i.value); }); keep("plannerRates", r); run(); };
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    const planBlock = p => !p ? "" : `<section class="card" style="margin-top:14px"><h2>Suggested split of ₹${whole(p.budget)}</h2>${p.lines.length ? table([{h: "Channel", v: l => l.name}, {h: "Spots", n: 1, v: l => l.spots}, {h: "Rate", n: 1, v: l => "₹" + whole(l.rate)}, {h: "Spend", n: 1, v: l => "₹" + whole(l.spend)}, {h: "Average viewers per spot", n: 1, v: l => whole(l.average_concurrent)}], p.lines) : `<p class="muted">Not enough budget for one spot at these rates.</p>`}
      <p style="margin-top:8px">Spent ₹${whole(p.spent)} · left ₹${whole(p.left)} · ${p.total_spots} spots · about ₹${p.blended_cost_per_1000 == null ? "—" : whole(p.blended_cost_per_1000)} per 1,000 live viewers${p.skipped_high_risk.length ? " · skipped (high risk): " + esc(p.skipped_high_risk.join(", ")) : ""}${p.skipped_no_audience_data.length ? " · not bought, audience not known: " + esc(p.skipped_no_audience_data.join(", ")) : ""}</p>${p.counts_matched_audience_only ? '<p class="muted">Only the part of each audience that matches your target is counted.</p>' : ""}<p class="muted">${esc(p.note)}</p></section>`;
    $("#pf", el).onsubmit = ev => { ev.preventDefault(); run(); }; run();
  });

  /* ---------- authenticity radar ---------- */
  add("authenticity", "Market tools", "Authenticity radar", async el => {
    el.innerHTML = head("Authenticity radar", "Finds viewership that looks unusual so a person can look at it. A flag is a pattern, not proof: public numbers cannot show who watched.") +
      `<form class="card" id="af" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0"><label>Group<br><select name="segment">${opt(SEGMENTS, (SP.auth || {}).segment || "")}</select></label>
      <label>Language<br><select name="language">${opt(LANGS, (SP.auth || {}).language || "")}</select></label><label>Look back<br><select name="days">${opt([["3", "3 days"], ["7", "7 days"], ["14", "14 days"], ["28", "28 days"]], (SP.auth || {}).days || "7")}</select></label>
      ${filterFields((SP.auth || {}), {place: false, age: false, known: false})}<button class="btn primary" type="submit">Scan</button></form><div id="aout"></div>`;
    const colors = {high: "red", review: "", low: "green"}, words = {high: "Review now", review: "Check", low: "Nothing unusual"};
    const run = async () => {
      const v = formValues($("#af", el)); keep("auth", v); const out = $("#aout", el); out.innerHTML = `<p class="muted">Scanning…</p>`;
      try {
        const d = await api("/api/v1/market/authenticity", v);
        out.innerHTML = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">${kpi("Review now", d.summary.high, "channels", d.summary.high ? "red" : "")}${kpi("Check", d.summary.review, "channels")}${kpi("Nothing unusual", d.summary.low, "channels", "green")}</div>` +
          d.channels.filter(c => c.signals.length).map(c => `<section class="card" style="margin-top:12px"><h2>${esc(c.name)} <span class="tag ${colors[c.risk]}">${words[c.risk]}</span></h2>${c.signals.map(s => `<div style="padding:8px 0;border-top:1px solid #152c40"><strong>${esc(s.title)}</strong>${s.occurrences > 1 ? ` <span class="muted">(seen ${s.occurrences} times)</span>` : ""}
            <p class="muted">${esc(s.detail)}</p>${s.review ? `<p><span class="tag">${esc(s.review.status)}</span> <span class="muted">${esc(s.review.by || "")} ${s.review.note ? "· " + esc(s.review.note) : ""}</span></p>` : ""}
            ${isAdmin ? `<div class="btnrow">${["cleared", "watching", "confirmed"].map(st => `<button class="btn" type="button" data-rev="${esc(st)}" data-ch="${esc(c.channel_id)}" data-sig="${esc(s.code)}">Mark ${st}</button>`).join("")}</div>` : ""}</div>`).join("")}</section>`).join("") +
          (d.channels.some(c => c.signals.length) ? "" : state("Nothing unusual found", "No channel shows an unusual pattern in these days.")) + method(d.method);
        out.querySelectorAll("[data-rev]").forEach(b => b.onclick = async () => {
          const note = prompt("Note for the record (what you checked):", ""); if (note === null) return;
          try { await post("/api/v1/market/authenticity/review", {channel_id: +b.dataset.ch, signal: b.dataset.sig, status: b.dataset.rev, note}); run(); } catch (e) { alert(e.message); }
        });
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#af", el).onsubmit = ev => { ev.preventDefault(); run(); }; run();
  });

  /* ---------- audience: geography and age ---------- */
  const bars = (obj, {limit = 8, color = "#159de8"} = {}) => {
    const items = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]).slice(0, limit), max = Math.max(...items.map(i => i[1]), 1);
    return items.length ? items.map(([k, v]) => `<div style="display:grid;grid-template-columns:150px 1fr 48px;gap:8px;align-items:center;margin:4px 0"><span>${esc(k)}</span><span style="background:#0b2032;border-radius:4px;height:12px"><span style="display:block;height:12px;border-radius:4px;background:${color};width:${(v / max * 100).toFixed(1)}%"></span></span><span class="muted" style="text-align:right">${num(v)}%</span></div>`).join("") : `<p class="muted">Not given.</p>`;
  };
  const ageBars = obj => bars(Object.fromEntries(AGES.filter(a => (obj || {})[a] != null).map(a => [a, obj[a]])), {limit: 7, color: "#e1b94f"});
  add("audience", "Market tools", "Audience (geography and age)", async el => {
    el.innerHTML = head("Audience: geography and age", "Who watches, where they live and how old they are. YouTube does not publish another channel's audience, so this shows only what a channel or a named study has supplied, with the source and date. Anything else says: not known.");
    const d = await api("/api/v1/market/audience");
    const known = d.channels.filter(c => c.profile);
    el.insertAdjacentHTML("beforeend", `<p class="muted">${d.with_profile} of ${d.total} channels have an audience profile.</p>` + (known.length ? known.map(c => { const p = c.profile; return `<section class="card" style="margin-top:14px"><div class="head"><h2>${esc(c.name)}</h2></div>
      <p class="muted"><span class="tag">${esc(p.source_label)}</span> as of ${esc(fdate(p.as_of))} · ${esc(p.source_note || "")}</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px"><div><h3>Age</h3>${ageBars(p.age)}</div><div><h3>Gender</h3>${bars(p.gender, {color: "#35d399"})}</div><div><h3>Top states</h3>${bars(p.states)}</div><div><h3>Countries</h3>${bars(p.countries, {color: "#b18cff"})}</div></div></section>`; }).join("")
      : state("No audience profile yet", "Nobody has supplied an audience profile for any channel. Ask a channel for its YouTube Studio audience screens or media kit; an admin enters them under Audience profiles, with the source.")));
    const none = d.channels.filter(c => !c.profile);
    if (none.length) el.insertAdjacentHTML("beforeend", `<section class="card" style="margin-top:14px"><h2>Audience not known</h2><p class="muted">${esc(none.map(c => c.name).join(", "))}</p></section>`);
  });

  add("adm-audience", "Admin", "Audience profiles", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Audience profiles"); return; }
    el.innerHTML = head("Audience profiles", "Enter the audience of a channel exactly as the channel or a study gave it, with where it came from. Never fill this in from a guess.") + `<div id="amsg" class="msg" hidden></div><div id="aout"><p class="muted">Loading…</p></div><div id="aform"></div>`;
    const say = (t, ok) => { const m = $("#amsg", el); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    const lines = o => Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
    const parse = s => Object.fromEntries(String(s || "").split("\n").map(l => l.trim()).filter(Boolean).map(l => { const i = l.lastIndexOf(":"); return [l.slice(0, i).trim(), Number(l.slice(i + 1))]; }));
    const load = async () => {
      const d = await api("/api/v1/market/audience");
      $("#aout", el).innerHTML = `<section class="card">${table([{h: "Channel", html: 1, v: c => `<strong>${esc(c.name)}</strong>`}, {h: "Profile", v: c => c.profile ? `${c.profile.source_label}, as of ${c.profile.as_of}` : "None"},
        {h: "", html: 1, v: c => `<div class="btnrow"><button class="btn" type="button" data-edit="${esc(c.channel_id)}">${c.profile ? "Change" : "Add"}</button>${c.profile ? `<button class="btn" type="button" data-rm="${esc(c.channel_id)}">Remove</button>` : ""}</div>`}], d.channels)}</section>`;
      $("#aout", el).querySelectorAll("[data-edit]").forEach(b => b.onclick = () => edit(d.channels.find(c => c.channel_id === +b.dataset.edit)));
      $("#aout", el).querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => { if (!confirm("Remove this audience profile?")) return; try { await post("/api/v1/admin/audience/remove", {channel_id: +b.dataset.rm}); cache.clear(); say("Removed.", true); load(); } catch (e) { say(e.message); } });
    };
    const edit = c => {
      const p = c.profile || {};
      $("#aform", el).innerHTML = `<section class="card" style="margin-top:14px"><h2>${esc(c.name)}</h2><form id="apf" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px">
        <label>Where did this come from?<br><select name="source">${opt(SOURCES, p.source || "")}</select></label><label>As of (date)<br><input type="date" name="as_of" value="${esc(p.as_of || "")}" required></label>
        <label style="grid-column:1/-1">Source note (who gave it, which document or screen)<br><input type="text" name="source_note" value="${esc(p.source_note || "")}" style="width:100%" required></label>
        <label>Age, one band per line like "25-34: 35" (bands ${AGES.join(", ")}; should add to about 100)<br><textarea name="age" rows="7" style="width:100%">${esc(lines(p.age))}</textarea></label>
        <label>Gender: male, female, other<br><textarea name="gender" rows="7" style="width:100%">${esc(lines(p.gender))}</textarea></label>
        <label>States (Indian states, one per line like "Bihar: 14")<br><textarea name="states" rows="7" style="width:100%">${esc(lines(p.states))}</textarea></label>
        <label>Countries (one per line like "India: 93")<br><textarea name="countries" rows="7" style="width:100%">${esc(lines(p.countries))}</textarea></label>
        <div class="btnrow" style="grid-column:1/-1"><button class="btn primary" type="submit">Save profile</button><button class="btn" type="button" id="apc">Cancel</button></div></form></section>`;
      $("#apc", el).onclick = () => { $("#aform", el).innerHTML = ""; };
      $("#apf", el).onsubmit = async ev => { ev.preventDefault(); const f = Object.fromEntries(new FormData(ev.target));
        try { await post("/api/v1/admin/audience/set", {channel_id: c.channel_id, source: f.source, source_note: f.source_note, as_of: f.as_of, age: parse(f.age), gender: parse(f.gender), states: parse(f.states), countries: parse(f.countries)});
          cache.clear(); $("#aform", el).innerHTML = ""; say("Saved.", true); load(); } catch (e) { say(e.message); } };
      $("#aform", el).scrollIntoView({behavior: "smooth"});
    };
    await load();
  }, {admin: 1});


  /* ---------- a tool the package does not include: say so, and let the person ask for it ---------- */
  const PLAN_CODES = {"SX Idea": "sx_idea", "SX Intelligence": "sx_intelligence", "SX Analyst": "sx_analyst", "SX Pro": "sx_pro", "SX Corporate": "sx_corporate", "SX Enterprise": "sx_enterprise"};
  const upsell = message => { const m = String(message).match(/part of (SX [A-Za-z]+)/), code = m && PLAN_CODES[m[1]];
    return `<section class="card" style="margin-top:14px;border-color:#8b7131"><h2>This tool is part of a higher package</h2><p>${esc(message)}</p>${code ? `<div class="btnrow"><button class="btn primary" type="button" data-upgrade="${code}">Request ${esc(m[1])}</button></div>` : ""}<div class="upmsg msg" hidden></div></section>`; };
  const fail = e => e && e.status === 403 && /part of SX/.test(e.message) ? upsell(e.message) : errCard(e);
  const wireUpgrade = root => root.querySelectorAll("[data-upgrade]").forEach(b => b.onclick = async () => {
    const m = b.closest("section").querySelector(".upmsg");
    try { const d = await post("/api/v1/market/upgrade-request", {plan: b.dataset.upgrade}); m.hidden = false; m.className = "upmsg msg ok"; m.textContent = d.message; b.disabled = true; }
    catch (e) { m.hidden = false; m.className = "upmsg msg bad"; m.textContent = e.message; } });
  const miniSpark = (series, color = "#159de8") => {
    const pts = (series || []).map((v, i) => [i, v]).filter(p => p[1] != null);
    if (pts.length < 2) return `<span class="muted">—</span>`;
    const max = Math.max(...pts.map(p => p[1])), min = Math.min(...pts.map(p => p[1])), rng = Math.max(max - min, 1), n = series.length - 1;
    return `<svg width="96" height="26" viewBox="0 0 96 26" role="img" aria-label="viewers over the last ${n} minutes"><polyline fill="none" stroke="${color}" stroke-width="1.8" points="${pts.map(([i, v]) => (i / n * 94 + 1).toFixed(1) + "," + (24 - (v - min) / rng * 22).toFixed(1)).join(" ")}"/></svg>`;
  };
  const TOOL_VIEW = {weekly: "weekly", primetime: "primetime", builder: "builder", planner: "planner", audience: "audience", authenticity: "authenticity", creators: "creators"};

  /* ---------- briefing: the findings, for your role ---------- */
  const PERSONAS = [["buyer", "Media buyer / advertiser"], ["media", "Media company"], ["politician", "Politician / campaign"], ["influencer", "Influencer / journalist"], ["audience", "Audience"]];
  add("briefing", "Briefing", "Briefing", async el => {
    const f = SP.brief || {persona: "buyer", days: "7", segment: "", language: ""};
    el.innerHTML = head("Briefing", "What the data shows this week, and what it means for you. Every finding carries its numbers, how sure we are, and where to act on it.") +
      `<div class="btnrow" id="bp" style="margin:10px 0">${PERSONAS.map(([k, l]) => `<button class="btn${f.persona === k ? " primary" : ""}" type="button" data-p="${k}">${esc(l)}</button>`).join("")}</div>
      <form class="card" id="bf2" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"><label>Period<br><select name="days">${opt([["7", "Last 7 days"], ["14", "Last 14 days"], ["28", "Last 28 days"]], f.days)}</select></label>
      <label>Category<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label><label>Language<br><select name="language">${opt(LANGS, f.language)}</select></label>
      ${filterFields(f, {place: false, age: false, known: false})}<button class="btn primary" type="submit">Update</button><button class="btn" type="button" id="bpdf">Download this brief (PDF)</button></form><div id="bmsg2" class="msg" hidden></div><div id="bout2"></div>`;
    const read = () => { const v = formValues($("#bf2", el)); v.persona = f.persona; Object.assign(f, v); keep("brief", f); return v; };
    const run = async () => {
      const v = read(), out = $("#bout2", el); out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/market/briefing", v);
        const conf = {high: "green", medium: "", low: "red"};
        out.innerHTML = `<p class="muted" style="margin-top:12px">${esc(d.persona_label)} · ${esc(fdate(d.window.from))} – ${esc(fdate(d.window.to))} (Indian time), compared with the ${d.days} days before.</p>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:10px 0">${d.kpis.map(k => kpi(k.label, k.value, k.detail)).join("")}</div>
          ${d.locked ? `<section class="card" style="border-color:#8b7131"><strong>${esc(d.upgrade)}</strong><div class="btnrow" style="margin-top:8px"><button class="btn primary" type="button" data-upgrade="sx_idea">Request SX Idea</button></div><div class="upmsg msg" hidden></div></section>` : ""}
          ${d.findings.length ? d.findings.map((x, i) => `<section class="card" style="margin-top:12px"><div class="head"><h2>${i + 1}. ${esc(x.headline)}</h2></div>
            ${x.detail ? `<p>${esc(x.detail)}</p>` : ""}${x.so_what ? `<p style="border-left:3px solid #e1b94f;padding-left:12px;margin:10px 0"><strong style="color:#e1b94f">For you:</strong> ${esc(x.so_what)}</p>` : ""}
            <p class="muted"><span class="tag ${conf[x.confidence] || ""}">Confidence: ${esc(x.confidence)}</span> ${TOOL_VIEW[x.tool] ? `<a class="btn" style="margin-left:8px" href="#/${TOOL_VIEW[x.tool]}">${esc(x.tool_label)}</a>` : ""}</p>
            ${Object.keys(x.evidence || {}).length ? `<details><summary class="muted">The numbers behind it</summary><pre class="muted" style="white-space:pre-wrap">${esc(JSON.stringify(x.evidence, null, 1))}</pre></details>` : ""}</section>`).join("") : state("Not enough data yet", d.note || "Nothing can be stated yet for these filters. Nothing is estimated.")}
          <section class="card" style="margin-top:14px"><h2>Where to go next</h2><div class="btnrow">${d.recommended.map(r => TOOL_VIEW[r.tool] ? `<a class="btn" href="#/${TOOL_VIEW[r.tool]}">${esc(r.label)}</a>` : "").join("")}</div></section>
          <section class="card" style="margin-top:14px"><h2>How STAXIS turns data into decisions</h2><ol class="muted" style="columns:2;margin:6px 0 0 18px">${d.process.map(p => `<li><strong>${esc(p.name)}</strong>: ${esc(p.what)}</li>`).join("")}</ol></section>`;
        wireUpgrade(out);
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#bp", el).querySelectorAll("[data-p]").forEach(b => b.onclick = () => { f.persona = b.dataset.p; keep("brief", f); $("#bp", el).querySelectorAll("[data-p]").forEach(x => x.classList.toggle("primary", x === b)); run(); });
    $("#bf2", el).onsubmit = ev => { ev.preventDefault(); run(); };
    $("#bpdf", el).onclick = () => { const v = read(), m = $("#bmsg2", el); m.hidden = false; m.className = "msg"; m.textContent = "Making the PDF…"; downloadFile("/api/v1/market/briefing.pdf", v, "stataxis-briefing.pdf", m); };
    run();
  });

  /* ---------- my channels: every login maps its own channels to itself ---------- */
  document.addEventListener("click", ev => {
    const b = ev.target.closest && ev.target.closest("[data-mine]"); if (!b) return;
    const sel = b.closest("label, details, form")?.querySelector('select[name="channels"]') || b.closest("form")?.querySelector('select[name="channels"]'); if (!sel) return;
    [...sel.options].forEach(o => { o.selected = MINE.map(String).includes(o.value); });
  });
  add("mychannels", "Market tools", "My channels", async el => {
    el.innerHTML = head("My channels", "Map your own channels to this login. Once a channel is yours, one click selects it in every filter, and you can open its IFX Score and authenticity record.") +
      `<div id="mcmsg" class="msg" hidden></div><div id="mcout"><p class="muted">Loading…</p></div>
      <section class="card" style="margin-top:14px"><h2>Add a channel</h2>
        <form id="mcs" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"><label>Find it among the tracked channels<br><input type="text" name="q" placeholder="name or @handle" style="min-width:260px"></label><button class="btn" type="submit">Search</button></form>
        <div id="mcres" style="margin:10px 0"></div>
        <form id="mcr" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-top:12px"><label>Or paste its @handle or link<br><input type="text" name="ref" placeholder="@yourchannel  or  https://youtube.com/@yourchannel" style="min-width:320px"></label><button class="btn primary" type="submit">Claim it</button></form>
        <p class="muted" style="margin-top:8px">Claiming starts a check, not an approval. You get a short code to put in the channel's own description; finding it there proves the channel is yours.</p></section>`;
    const say = (t, ok) => { const m = $("#mcmsg", el); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    const chip = (t, c = "") => `<span class="tag ${c}">${esc(t)}</span>`;
    const load = async () => {
      const d = await api("/api/v1/my/channels"); MINE = d.channel_ids || [];
      if (!d.claims.length) { $("#mcout", el).innerHTML = state("No channel is mapped to this login yet", "Add yours below. Until then, the tools show everyone's numbers, not yours."); return; }
      $("#mcout", el).innerHTML = d.claims.map(c => {
        const ch = c.channel, ok = c.status === "approved", wait = c.status === "pending", no = c.status === "rejected";
        return `<section class="card" style="margin-top:14px"><div class="head"><h2>${esc(ch.name)} ${ok ? chip("Yours", "green") : wait ? chip("Waiting for proof") : chip("Declined", "red")} ${ch.tracked ? chip("Tracked") : chip("Not tracked yet")}</h2></div>
          <p class="muted">${esc(ch.handle || ch.youtube_channel_id)} · ${esc(ch.language === "unknown" ? "" : ch.language)}${ok ? ` · mapped ${c.method === "code" ? "by the code in the description" : "by an administrator"}` : ""}${no && c.note ? ` · ${esc(c.note)}` : ""}</p>
          ${wait ? `<div class="card" style="border-color:#159de8;margin:10px 0"><p style="margin:0 0 6px">Your code</p><code class="allow-copy" style="font-size:20px;user-select:all">${esc(c.code)}</code><p class="muted" style="margin:8px 0 0">${esc(d.help)}</p></div>` : ""}
          ${ok && !ch.tracked ? `<p class="muted">This channel is yours, but StatAxis is not collecting it yet (collection uses YouTube quota). An administrator switches it on.</p>` : ""}
          <div class="btnrow">${wait ? `<button class="btn primary" type="button" data-verify="${esc(c.id)}">Verify now</button>` : ""}${ok && ch.tracked ? `<button class="btn" type="button" data-open="creators">Open my IFX Score</button><button class="btn" type="button" data-open="authenticity">My authenticity record</button>` : ""}<button class="btn" type="button" data-drop="${esc(c.id)}">Remove</button></div></section>`;
      }).join("");
      el.querySelectorAll("[data-verify]").forEach(b => b.onclick = async () => { b.disabled = true; try { const r = await post("/api/v1/my/channels/verify", {claim_id: +b.dataset.verify}); say(r.found ? `${r.channel.name} is now mapped to you.` : "The code was not found in the description yet. Save the description on YouTube, wait a minute and try again.", r.found); await load(); } catch (e) { say(e.message); b.disabled = false; } });
      el.querySelectorAll("[data-drop]").forEach(b => b.onclick = async () => { if (!confirm("Remove this channel from your login? Its data stays; only the mapping goes.")) return; try { await post("/api/v1/my/channels/remove", {claim_id: +b.dataset.drop}); say("Removed.", true); await load(); } catch (e) { say(e.message); } });
      el.querySelectorAll("[data-open]").forEach(b => b.onclick = () => { const key = b.dataset.open === "creators" ? "creators" : "auth"; keep(key, {...(SP[key] || {}), channels: MINE.join(",")}); location.hash = "#/" + b.dataset.open; });
    };
    $("#mcs", el).onsubmit = async ev => {
      ev.preventDefault(); const q = new FormData(ev.target).get("q"); const box = $("#mcres", el);
      try { const r = await api("/api/v1/my/channels/search", {q}); box.innerHTML = r.channels.length ? r.channels.map(c => `<div style="display:flex;gap:10px;align-items:center;padding:6px 0;border-top:1px solid #152c40"><span style="flex:1">${esc(c.name)} <span class="muted">${esc(c.handle || "")}</span></span><button class="btn" type="button" data-claim="${esc(c.id)}">This is mine</button></div>`).join("") : `<p class="muted">No tracked channel matches. Paste its @handle below instead.</p>`;
        box.querySelectorAll("[data-claim]").forEach(b => b.onclick = async () => { try { await post("/api/v1/my/channels/claim", {channel_id: +b.dataset.claim}); say("Claimed. Put the code in your channel description, then press Verify.", true); box.innerHTML = ""; await load(); } catch (e) { say(e.message); } });
      } catch (e) { say(e.message); }
    };
    $("#mcr", el).onsubmit = async ev => { ev.preventDefault(); try { await post("/api/v1/my/channels/claim", {ref: new FormData(ev.target).get("ref")}); ev.target.reset(); say("Claimed. Put the code in your channel description, then press Verify.", true); await load(); } catch (e) { say(e.message); } };
    await load();
  });

  add("adm-claims", "Admin", "Channel claims", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Channel claims"); return; }
    el.innerHTML = head("Channel claims", "Who says which channel is theirs. A claim becomes the person's channel when the code is found in the channel's description, or when you approve it. You can also map a channel to a login yourself.") +
      `<div id="clmsg" class="msg" hidden></div>
      <form class="card" id="clf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"><label>Show<br><select name="status">${opt([["", "All"], ["pending", "Waiting"], ["approved", "Approved"], ["rejected", "Declined"]], "pending")}</select></label><button class="btn" type="submit">Show</button></form>
      <div id="clout"><p class="muted">Loading…</p></div>
      <section class="card" style="margin-top:14px"><h2>Map a channel to a login</h2><form id="cla" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
        <label>Login<br><select name="user_id" id="claus" style="min-width:240px"></select></label>
        <label>Channel<br><select name="channel_id" style="min-width:260px">${optsByLanguage(typeof channels !== "undefined" ? channels : [], () => false)}</select></label>
        <label><input type="checkbox" name="track" checked> Start tracking it</label><button class="btn primary" type="submit">Map it</button></form></section>`;
    const say = (t, ok) => { const m = $("#clmsg", el); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    const load = async () => {
      const status = new FormData($("#clf", el)).get("status") || "";
      const d = await post("/api/v1/admin/channel-claims/list", {status});
      $("#clout", el).innerHTML = `<section class="card" style="margin-top:14px">${table([
        {h: "Login", html: 1, v: c => `<strong>${esc(c.user.login)}</strong><br><span class="muted">${esc(c.user.name || "")} ${esc(c.user.organization || "")}</span>`},
        {h: "Channel", html: 1, v: c => `${esc(c.channel.name)}<br><span class="muted">${esc(c.channel.handle || c.channel.youtube_channel_id)}</span> ${c.channel.tracked ? "" : '<span class="tag">not tracked</span>'}`},
        {h: "Status", html: 1, v: c => `${esc(c.status)}${c.method ? ` <span class="muted">(${esc(c.method)})</span>` : ""}${c.note ? `<br><span class="muted">${esc(c.note)}</span>` : ""}`},
        {h: "", html: 1, v: c => `<div class="btnrow">${c.status !== "approved" ? `<button class="btn primary" data-ap="${esc(c.id)}" data-tr="1" type="button">Approve and track</button><button class="btn" data-ap="${esc(c.id)}" type="button">Approve</button>` : (!c.channel.tracked ? `<button class="btn primary" data-ap="${esc(c.id)}" data-tr="1" type="button">Start tracking</button>` : "")}${c.status !== "rejected" ? `<button class="btn" data-rj="${esc(c.id)}" type="button">Decline</button>` : ""}<button class="btn" data-rm="${esc(c.id)}" type="button">Remove</button></div>`}], d.claims, "No claims match.")}</section>`;
      el.querySelectorAll("[data-ap]").forEach(b => b.onclick = async () => { try { await post("/api/v1/admin/channel-claims/decide", {claim_id: +b.dataset.ap, decision: "approve", track: b.dataset.tr === "1"}); say("Approved.", true); load(); } catch (e) { say(e.message); } });
      el.querySelectorAll("[data-rj]").forEach(b => b.onclick = async () => { const note = prompt("Why? (optional, the person sees it)") ?? null; if (note === null) return; try { await post("/api/v1/admin/channel-claims/decide", {claim_id: +b.dataset.rj, decision: "reject", note}); say("Declined.", true); load(); } catch (e) { say(e.message); } });
      el.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => { if (!confirm("Remove this mapping?")) return; try { await post("/api/v1/admin/channel-claims/remove", {claim_id: +b.dataset.rm}); say("Removed.", true); load(); } catch (e) { say(e.message); } });
    };
    $("#clf", el).onsubmit = ev => { ev.preventDefault(); load(); };
    $("#cla", el).onsubmit = async ev => { ev.preventDefault(); const f = new FormData(ev.target); try { const r = await post("/api/v1/admin/channel-claims/assign", {user_id: +f.get("user_id"), channel_id: +f.get("channel_id"), track: f.has("track")}); say(`${r.channel.name} is now mapped to ${r.user.login}.`, true); load(); } catch (e) { say(e.message); } };
    try { const u = await post("/api/v1/admin/users/list", {q: ""}); $("#claus", el).innerHTML = u.users.map(x => `<option value="${esc(x.id)}">${esc(x.email)}${x.name ? " · " + esc(x.name) : ""}</option>`).join(""); } catch { /* the form stays empty */ }
    await load();
  }, {admin: 1});

  /* ---------- live event compare: up to 30 channels, live ---------- */
  add("liveevent", "Market tools", "Live event compare", async el => {
    const f = SP.live || {terms: "", segment: "", language: "", minutes: "60", stx_period: "7d", auto: true};
    el.innerHTML = head("Live event compare", "Up to 30 channels covering the same live event, side by side: the audience each has now, how it moved, the peak, the STX index and the tone of what each is showing. The screen refreshes by itself.") +
      `<form class="card" id="lf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"><label style="flex:1 1 100%">Name of this live event (you can change it any time)<br><input type="text" name="name" id="lname" maxlength="80" value="${esc(f.name || "")}" placeholder="e.g. Budget 2026, live coverage" style="width:min(520px,100%);font-size:18px"></label><label>Event words<br><input type="text" name="terms" value="${esc(f.terms)}" placeholder="e.g. budget, election result" style="min-width:230px"></label>
      <label>Category<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label><label>Language<br><select name="language">${opt(LANGS, f.language)}</select></label>
      <label>Window<br><select name="minutes">${opt([["30", "Last 30 min"], ["60", "Last hour"], ["120", "Last 2 hours"], ["180", "Last 3 hours"]], f.minutes)}</select></label>
      <label>STX period<br><select name="stx_period">${opt([["today", "Today"], ["7d", "7 days"], ["month", "Month"]], f.stx_period)}</select></label>
      ${filterFields(f, {place: false, age: false, known: false})}<label style="display:flex;gap:6px;align-items:center"><input type="checkbox" name="auto"${f.auto ? " checked" : ""}> Refresh every 15 s</label><button class="btn primary" type="submit">Compare now</button></form>
      <p class="muted" id="lstat" style="margin:8px 0"></p><div id="lout"></div>`;
    let timer = null, last = null;
    const eventName = () => (($("#lname", el) || {}).value || "").trim() || String(f.terms || "").split(",")[0].trim().replace(/^./, c => c.toUpperCase()) || "Live event";
    $("#lname", el).addEventListener("input", () => { f.name = $("#lname", el).value; keep("live", f); const t = $("#ltitle", el); if (t) t.textContent = eventName(); });
    const read = () => { const form = $("#lf", el), v = formValues(form); v.auto = new FormData(form).has("auto"); Object.assign(f, v); keep("live", f); return v; };
    const toneCls = {positive: "green", negative: "red", "mixed/neutral": ""};
    const draw = d => {
      last = d;
      const s = d.summary, mix = s.tone_mix, tot = Math.max(mix.positive + mix.negative + mix["mixed/neutral"], 1), out = $("#lout", el);
      if (!d.channels.length) { out.innerHTML = `<h2 id="ltitle" style="margin:6px 0 12px;font-size:28px">${esc(eventName())}</h2>` + state("Nobody to compare yet", d.note || "No channel is live with these filters.") + (d.not_live.length ? `<p class="muted">Not live: ${esc(d.not_live.join(", "))}</p>` : ""); return; }
      out.innerHTML = `<h2 id="ltitle" style="margin:6px 0 12px;font-size:28px">${esc(eventName())}</h2><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px">${kpi("Channels live", s.channels_live, "covering the event")}${kpi("Live viewers now", whole(s.total_live_now), "all channels together")}${kpi("Leader", s.leader || "—", (s.leader_share_percent ?? "—") + "% of the audience")}
        ${kpi("Tone of what is on screen", s.audience_weighted_tone == null ? "—" : (s.audience_weighted_tone > 0.15 ? "Positive" : s.audience_weighted_tone < -0.15 ? "Negative" : "Mixed"), "weighted by audience")}${kpi("Strongest STX", s.best_stx || "—", "STX " + d.stx_period)}</div>
        <div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin:12px 0" title="positive ${mix.positive}, mixed ${mix["mixed/neutral"]}, negative ${mix.negative}"><span style="width:${100 * mix.positive / tot}%;background:#35d399"></span><span style="width:${100 * mix["mixed/neutral"] / tot}%;background:#6b8299"></span><span style="width:${100 * mix.negative / tot}%;background:#ff7180"></span></div>
        <style>.lwall{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:12px 0}@media(max-width:1200px){.lwall{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:620px){.lwall{grid-template-columns:repeat(2,minmax(0,1fr))}}.lwall .lw{background:#0b2032;border:1px solid #152c40;border-radius:8px;padding:10px;min-width:0}.lwall .lw b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.lwall .lw .big{font-size:22px;font-weight:700;margin:4px 0}</style>
        <div class="lwall">${groupByLanguage(d.channels).map((r, i, arr) => (i === 0 || arr[i - 1].language !== r.language ? `<div class="langhead" style="grid-column:1/-1">${esc(langName(r.language))}</div>` : "") + `<div class="lw"><span class="muted">#${r.rank}</span><b title="${esc(r.name)}">${esc(r.name)}</b><div class="big">${whole(r.live_now)}</div>${miniSpark(r.series, r.change_5m_percent < 0 ? "#ff7180" : "#159de8")}<div class="muted" style="font-size:12px;margin-top:4px">${r.change_5m_percent == null ? "—" : `<span class="${r.change_5m_percent > 0 ? "green" : r.change_5m_percent < 0 ? "red" : ""}">${r.change_5m_percent > 0 ? "▲" : r.change_5m_percent < 0 ? "▼" : ""} ${Math.abs(r.change_5m_percent)}%</span>`} · STX ${r.stx ? dec(r.stx.score) : "—"}</div><span class="tag ${toneCls[r.tone.label] || ""}">${esc(r.tone.label)}</span></div>`).join("")}</div>
        <section class="card">${table([{h: "#", v: r => r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.name)}</strong><br><span class="muted">${esc(r.lead_title)}</span>`},
          {h: "Live now", n: 1, html: 1, v: r => `<strong>${whole(r.live_now)}</strong>`}, {h: "Share", n: 1, v: r => r.share_percent == null ? "—" : r.share_percent + "%"},
          {h: "5 min", n: 1, html: 1, v: r => r.change_5m_percent == null ? '<span class="muted">—</span>' : `<span class="${r.change_5m_percent > 0 ? "green" : r.change_5m_percent < 0 ? "red" : "muted"}">${r.change_5m_percent > 0 ? "▲" : r.change_5m_percent < 0 ? "▼" : ""} ${Math.abs(r.change_5m_percent)}%</span>`},
          {h: "Trend", html: 1, v: r => miniSpark(r.series, r.change_5m_percent < 0 ? "#ff7180" : "#159de8")}, {h: "Peak", n: 1, v: r => whole(r.peak)}, {h: "Average", n: 1, v: r => whole(r.average)},
          {h: "Live for", n: 1, v: r => r.live_for_minutes == null ? "—" : r.live_for_minutes >= 60 ? Math.floor(r.live_for_minutes / 60) + " h " + (r.live_for_minutes % 60) + " m" : r.live_for_minutes + " m"},
          {h: "STX", n: 1, html: 1, v: r => r.stx ? `<strong>${dec(r.stx.score)}</strong> <span class="muted">(${pct(r.stx.confidence)})</span>${r.stx.preliminary ? ' <span class="tag">Preliminary</span>' : ""}` : '<span class="muted">—</span>'},
          {h: "Tone", html: 1, v: r => `<span class="tag ${toneCls[r.tone.label] || ""}" title="Score ${r.tone.score}; ${Math.round(r.tone.words_recognised * 100)}% of the title's words were recognised">${esc(r.tone.label)}</span>`}], d.channels, undefined, {group: r => r.language})}</section>
        ${d.not_live.length ? `<p class="muted" style="margin-top:8px">Not live right now: ${esc(d.not_live.join(", "))}</p>` : ""}
        <div class="btnrow" style="margin-top:12px"><button class="btn" type="button" id="lpng">Download picture card (PNG)</button></div>${method(d.method)}`;
      $("#lpng", el).onclick = async () => saveCanvas(await cardPng(eventName() + " · viewers now", `${new Date(d.as_of).toLocaleTimeString("en-IN", {hour: "2-digit", minute: "2-digit"})} · ${s.channels_live} channels live`,
        d.channels.slice(0, 10).map(r => ({label: r.name, value: r.live_now, text: whole(r.live_now) + "  ·  STX " + (r.stx ? dec(r.stx.score) : "—")})), {footer: "Average live viewers across each channel's live streams. Tone is read from stream titles."}), `stataxis-live-${eventName().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "event"}-${Date.now()}.png`);
    };
    const run = async () => {
      const v = read(), qv = {terms: v.terms, segment: v.segment, language: v.language, minutes: v.minutes, stx_period: v.stx_period, channels: v.channels};
      $("#lstat", el).textContent = "Updating…";
      try { draw(await api("/api/v1/market/live-event", qv)); $("#lstat", el).textContent = "Updated " + new Date().toLocaleTimeString("en-IN") + (v.auto ? " · refreshing every 15 seconds" : " · automatic refresh is off"); }
      catch (e) { $("#lout", el).innerHTML = fail(e); wireUpgrade($("#lout", el)); $("#lstat", el).textContent = ""; }
      clearTimeout(timer);
      if (v.auto && el.isConnected) timer = setTimeout(() => { if (el.isConnected) { cache.clear(); run(); } }, 15000);
    };
    $("#lf", el).onsubmit = ev => { ev.preventDefault(); cache.clear(); run(); };
    run();
  });

  /* ---------- admin: users ---------- */
  add("adm-users", "Admin", "Users", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Users"); return; }
    el.innerHTML = head("Users", "Everyone who has an account: change a package, switch an account off or on, create an account, or reset a password.") +
      `<form class="card" id="uf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"><label>Search<br><input type="text" name="q" placeholder="name, login ID or organisation"></label><button class="btn primary" type="submit">Search</button></form>
      <p class="muted" style="margin:6px 0">Administrator accounts are not listed here, so nobody can reset or switch off an administrator by mistake. An administrator changes their own password under Profile.</p><div id="umsg" class="msg" hidden></div><div id="uout"></div><div id="upriv"></div><section class="card" style="margin-top:14px"><h2>Create an account</h2><form id="ucf" class="chform"><label>Name<input type="text" name="name" required></label><label>Login ID (username or email)<input type="text" name="email" required minlength="3" maxlength="64" autocapitalize="none" spellcheck="false" placeholder="e.g. kumud or name@company.com"></label>
      <label>Organisation<input type="text" name="organization" required></label><label>Mobile<input type="text" name="mobile"></label><label>Package<select name="plan" id="ucplan"></select></label><button class="btn primary" type="submit">Create</button></form></section>`;
    let plans = [];
    const say = (t, ok) => { const m = $("#umsg", el); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    const secret = (what, d) => { say("", true); const m = $("#umsg", el); m.hidden = false; m.className = "msg ok"; m.innerHTML = `${esc(what)} <strong>${esc(d.email)}</strong>: temporary password <code class="allow-copy" style="user-select:all">${esc(d.temporary_password)}</code><br><span class="muted">${esc(d.note)}</span>`; };
    /* the privileges of one person: tick a tool to allow it, un-tick to switch it off; no tick of yours means the package decides */
    const privileges = async uid => {
      const box = $("#upriv", el);
      const draw = (who, features) => {
        box.innerHTML = `<section class="card" style="margin-top:14px;border-color:#159de8"><div class="head"><h2>Privileges: ${esc(who.name || who.email)}</h2></div>
          <p class="muted">${esc(who.email)} · package <strong>${esc((plans.find(p => p.code === who.plan) || {}).name || who.plan)}</strong>. Tick what this person may use. A tick or un-tick you make here wins over the package; <em>Use the package</em> removes it.</p>
          <div class="btnrow" style="margin:8px 0"><button class="btn" type="button" id="pall">Tick everything</button><button class="btn" type="button" id="pnone">Un-tick everything</button><button class="btn" type="button" id="ppkg">Use the package for all</button><button class="btn" type="button" id="pclose">Close</button></div>
          ${features.map(f => `<label style="display:grid;grid-template-columns:28px 1fr auto;gap:10px;align-items:start;padding:10px 0;border-top:1px solid #152c40;cursor:pointer">
            <input type="checkbox" data-pf="${esc(f.feature)}" ${f.allowed ? "checked" : ""} style="width:20px;height:20px;margin-top:2px">
            <span><strong>${esc(f.label)}</strong><br><span class="muted">${esc(f.description)}</span></span>
            <span style="text-align:right">${f.source === "admin" ? `<span class="tag">set by ${esc((f.set_by || "an admin").split("@")[0])}</span><br><a href="#" data-pk="${esc(f.feature)}" class="muted">Use the package</a>` : `<span class="tag ${f.allowed ? "green" : ""}">${f.allowed ? "from the package" : "not in the package"}</span>`}<br><span class="muted">from ${esc((plans.find(p => p.code === f.min_plan) || {}).name || f.min_plan)}</span></span></label>`).join("")}
          <div id="pmsg" class="msg" hidden></div></section>`;
        const set = async (feature, value) => { try { const r = await post("/api/v1/admin/users/features/set", {user_id: uid, feature, allowed: value}); draw(who, r.features); } catch (e) { const m = $("#pmsg", box); m.hidden = false; m.className = "msg bad"; m.textContent = e.message; } };
        box.querySelectorAll("[data-pf]").forEach(c => c.onchange = () => set(c.dataset.pf, c.checked));
        box.querySelectorAll("[data-pk]").forEach(a => a.onclick = ev => { ev.preventDefault(); set(a.dataset.pk, null); });
        const all = async v => { for (const f of features) await post("/api/v1/admin/users/features/set", {user_id: uid, feature: f.feature, allowed: v}); privileges(uid); };
        $("#pall", box).onclick = () => all(true); $("#pnone", box).onclick = () => all(false); $("#ppkg", box).onclick = () => all(null); $("#pclose", box).onclick = () => { box.innerHTML = ""; };
        box.scrollIntoView({behavior: "smooth", block: "nearest"});
      };
      try { const d = await post("/api/v1/admin/users/features", {user_id: uid}); draw(d.user, d.features); } catch (e) { box.innerHTML = errCard(e); }
    };
    const load = async () => {
      const q = new FormData($("#uf", el)).get("q") || "";
      try {
        const d = await post("/api/v1/admin/users/list", {q}); plans = d.plans;
        $("#ucplan", el).innerHTML = plans.map(p => `<option value="${esc(p.code)}">${esc(p.name)}${p.max_seats ? " (" + p.max_seats + " seats)" : ""}</option>`).join("");
        $("#uout", el).innerHTML = `<section class="card" style="margin-top:14px">${table([
          {h: "Person", html: 1, v: u => `<strong>${esc(u.name || u.email)}</strong><br><span class="muted">${esc(u.email)}</span>`}, {h: "Organisation", v: u => u.organization || "—"}, {h: "Status", html: 1, v: u => `${esc(u.approval_status)}${u.active ? "" : ' <span class="tag red">off</span>'}${u.is_admin ? ' <span class="tag">admin</span>' : ""}${u.must_change_password ? ' <span class="tag" title="Signed in with a password an administrator made; they must choose their own first">temporary password</span>' : ""}`},
          {h: "Package", html: 1, v: u => u.is_admin ? "Admin" : `<select data-plan="${esc(u.id)}">${plans.map(p => `<option value="${esc(p.code)}"${p.code === u.plan ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>${u.seats ? `<br><span class="muted">${u.seats.used}/${u.seats.max} seats used</span>` : ""}`},
          {h: "", html: 1, v: u => `<div class="btnrow"><button class="btn" type="button" data-active="${esc(u.id)}" data-to="${u.active ? 0 : 1}">${u.active ? "Switch off" : "Switch on"}</button><button class="btn" type="button" data-reset="${esc(u.id)}">Reset password</button><button class="btn" type="button" data-rename="${esc(u.id)}" data-cur="${esc(u.email)}">Change login ID</button>${u.is_admin ? "" : `<button class="btn primary" type="button" data-priv="${esc(u.id)}">Privileges</button>`}</div>`}], d.users, "No accounts match.")}</section>`;
        el.querySelectorAll("[data-priv]").forEach(b => b.onclick = () => privileges(+b.dataset.priv));
        el.querySelectorAll("[data-plan]").forEach(s => s.onchange = async () => { try { await post("/api/v1/admin/users/plan", {user_id: +s.dataset.plan, plan: s.value}); say("Package changed.", true); load(); } catch (e) { say(e.message); load(); } });
        el.querySelectorAll("[data-active]").forEach(b => b.onclick = async () => { try { await post("/api/v1/admin/users/active", {user_id: +b.dataset.active, active: b.dataset.to === "1"}); say("Done.", true); load(); } catch (e) { say(e.message); } });
        el.querySelectorAll("[data-rename]").forEach(b => b.onclick = async () => { const v = prompt("New login ID for this person (any username, or an email). Their password stays the same.", b.dataset.cur); if (v == null || !v.trim() || v.trim().toLowerCase() === b.dataset.cur) return; try { const d = await post("/api/v1/admin/users/rename-login", {user_id: +b.dataset.rename, login_id: v}); say("Login ID is now " + d.email + ". They sign in with it from now on.", true); load(); } catch (e) { say(e.message); } });
        el.querySelectorAll("[data-reset]").forEach(b => b.onclick = async () => { if (!confirm("Make a new temporary password for this person? Their old password stops working.")) return; try { secret("New password for", await post("/api/v1/admin/users/reset-password", {user_id: +b.dataset.reset})); } catch (e) { say(e.message); } });
      } catch (e) { $("#uout", el).innerHTML = errCard(e); }
    };
    $("#uf", el).onsubmit = ev => { ev.preventDefault(); load(); };
    $("#ucf", el).onsubmit = async ev => { ev.preventDefault(); const f = ev.target; try { const d = await post("/api/v1/admin/users/create", Object.fromEntries(new FormData(f))); f.reset(); secret("Account created for", d); load(); } catch (e) { say(e.message); } };
    load();
  }, {admin: 1});

  /* ---------- admin: package access ---------- */
  add("adm-access", "Admin", "Package access", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Package access"); return; }
    el.innerHTML = head("Package access", "Which package is the lowest one that may use each tool. A change works at once for everyone.") + `<div id="xmsg" class="msg" hidden></div><div id="xout"><p class="muted">Loading…</p></div>`;
    const d = await post("/api/v1/admin/features/list", {});
    $("#xout", el).innerHTML = `<section class="card" style="border-color:${d.packages_enabled ? "#20394e" : "#35d399"}"><h2>Packages are ${d.packages_enabled ? "ON" : "OFF"}</h2>
      <p>${d.packages_enabled ? "A person's package decides what they may use, and seats are limited by package." : "Every login may use every screen and tool, whatever its package, with no seat limits. A tick you removed for one person still holds. Menu choices wait until packages are back on."}</p>
      <div class="btnrow"><button class="btn primary" type="button" id="pkgtoggle">${d.packages_enabled ? "Switch packages off" : "Switch packages on"}</button></div></section>
      <section class="card" style="margin-top:14px">${table([{h: "Tool", html: 1, v: f => `<strong>${esc(f.label)}</strong>${f.changed ? ' <span class="tag">changed</span>' : ""}`},
      {h: "Lowest package", html: 1, v: f => `<select data-feat="${esc(f.feature)}">${d.plans.map(p => `<option value="${esc(p.code)}"${p.code === f.min_plan ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>`}, {h: "Starting choice", v: f => (d.plans.find(p => p.code === f.default) || {}).name}, {h: "Last changed by", v: f => f.updated_by || "—"}], d.features)}</section>
      <section class="card" style="margin-top:14px"><h2>Packages</h2>${table([{h: "Package", v: p => p.name}, {h: "Promise", v: p => p.promise}, {h: "Seats per organisation", n: 1, v: p => p.max_seats == null ? "No limit" : p.max_seats}], d.plans)}<p class="muted" style="margin-top:8px">A package with a seat limit cannot give another seat to an organisation that already uses them all (counted by organisation name).</p></section>`;
    $("#pkgtoggle", el).onclick = async () => { const m = $("#xmsg", el); try { await post("/api/v1/admin/features/packages", {enabled: !d.packages_enabled}); cache.clear(); render(); } catch (e) { m.hidden = false; m.className = "msg bad"; m.textContent = e.message; } };
    $("#xout", el).querySelectorAll("[data-feat]").forEach(s => s.onchange = async () => { const m = $("#xmsg", el); try { await post("/api/v1/admin/features/set", {feature: s.dataset.feat, min_plan: s.value}); m.hidden = false; m.className = "msg ok"; m.textContent = "Saved. It applies now."; } catch (e) { m.hidden = false; m.className = "msg bad"; m.textContent = e.message; } });
  }, {admin: 1});

  /* ---------- admin: channel groups ---------- */
  add("adm-groups", "Admin", "Channel groups", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Channel groups"); return; }
    el.innerHTML = head("Channel groups", "Put each channel in a group so reports compare like with like: news, business, print, parties, leaders, commentators, creators or independent journalists.") + `<div id="gmsg" class="msg" hidden></div><div id="gout"><p class="muted">Loading…</p></div>`;
    await reloadChannels();
    const seg = SEGMENTS.filter(([v]) => v);
    $("#gout", el).innerHTML = `<section class="card">${table([{h: "Channel", html: 1, v: c => `<strong>${esc(c.name)}</strong>`}, {h: "Language", v: c => c.language || "—"},
      {h: "Group", html: 1, v: c => `<select data-grp="${esc(c.id)}">${seg.map(([v, l]) => `<option value="${esc(v)}"${(c.segment || "news") === v ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`}], channels, "No channels yet.")}</section>`;
    $("#gout", el).querySelectorAll("[data-grp]").forEach(s => s.onchange = async () => { const m = $("#gmsg", el); try { await post("/api/v1/admin/channels/segment", {channel_id: +s.dataset.grp, segment: s.value}); m.hidden = false; m.className = "msg ok"; m.textContent = "Group saved."; } catch (e) { m.hidden = false; m.className = "msg bad"; m.textContent = e.message; } });
  }, {admin: 1});

  /* ---------- admin: quota ---------- */
  add("adm-quota", "Admin", "YouTube quota", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("YouTube quota"); return; }
    el.innerHTML = head("YouTube quota", "How much of the daily YouTube quota the channels use, and how much to ask for when you request an increase.") +
      `<form class="card" id="qf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"><label>Extra channels to add<br><input type="number" name="extra_channels" min="0" value="0"></label>
      <label>Collect every (seconds)<br><input type="number" name="collect_seconds" min="60" placeholder="now"></label><label>Live check every (seconds)<br><input type="number" name="live_poll_seconds" min="5" placeholder="now"></label><button class="btn primary" type="submit">Work it out</button></form><div id="qout"></div>`;
    const card = (t, q) => `<section class="card"><h2>${esc(t)}</h2><dl class="kv"><dt>Channels</dt><dd>${q.channels}</dd><dt>Collect every</dt><dd>${whole(q.collect_seconds)} s</dd><dt>Live check every</dt><dd>${q.live_poll_seconds} s</dd>
      <dt>Units a day</dt><dd>${whole(q.units_per_day.total)} (collection ${whole(q.units_per_day.collection)}, live ${whole(q.units_per_day.live)})</dd><dt>Your quota now</dt><dd>${whole(q.current_quota)}</dd>
      <dt>Fits?</dt><dd class="${q.fits ? "green" : "red"}">${q.fits ? "Yes" : "No, over the quota"}</dd><dt>Ask YouTube for</dt><dd><strong>${whole(q.quota_to_request)}</strong> units a day (includes ${q.headroom_percent}% headroom)</dd></dl></section>`;
    const run = async () => {
      const v = Object.fromEntries(new FormData($("#qf", el))); try { const d = await api("/api/v1/market/quota", v);
        $("#qout", el).innerHTML = `<p class="muted" style="margin-top:12px">${whole(d.active_channels)} channels are being tracked now.</p><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px">${card("With the settings now", d.now)}${card("At the target pace (every 10 minutes, live every 30 seconds)", d.target)}</div>
          <p class="muted" style="margin-top:8px">This is an estimate from how the collector calls YouTube. The target pace is what makes the data fresh enough for reports; if you ask for more quota, use the number under "Ask YouTube for".</p>`;
      } catch (e) { $("#qout", el).innerHTML = errCard(e); }
    };
    $("#qf", el).onsubmit = ev => { ev.preventDefault(); run(); }; run();
  }, {admin: 1});

  /* the briefing is the first thing in the menu and where a person lands */
  const firstView = VIEWS.briefing; delete VIEWS.briefing;
  const rest = {...VIEWS}; for (const k of Object.keys(VIEWS)) delete VIEWS[k];
  VIEWS.briefing = firstView; Object.assign(VIEWS, rest);
  if (!location.hash || location.hash === "#") location.hash = "#/briefing";
})();
