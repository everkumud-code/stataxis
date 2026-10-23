/* The STX Index report screen: every channel's STX Index out of 100, what each of the seven factors gave it (points earned out of the most that factor could give), and its audience, channel by channel,
   with a branded PDF. Loaded by workspace.html after surveys.js; it uses the helpers of workspace.html ($, esc, api, head, add, token, whole) and the lists market.js shares (window.__sxMarket). */
"use strict";
(() => {
  const M = window.__sxMarket;
  if (typeof add !== "function" || !M) return;
  const {LANGS, SEGMENTS, opt, formValues} = M;
  const PERIODS = [["today", "Today so far"], ["7d", "Last 7 days"], ["3w", "Last 3 weeks"], ["month", "Last month"]];
  const css = document.createElement("style");
  css.textContent = ".sxr-cell{min-width:78px}.sxr-cell b{display:block;font-size:13px}.sxr-bar{height:5px;border-radius:3px;background:#11283d;margin-top:3px;overflow:hidden}.sxr-bar i{display:block;height:100%;background:#159de8}"
    + ".sxr-stx{font-size:20px;font-weight:800;color:#159de8}.sxr-dash{color:var(--muted)}.sxr-note{border:1px solid var(--line);border-left:3px solid #159de8;border-radius:10px;padding:12px 14px;margin:12px 0;font-size:13.5px;line-height:1.6}";
  document.head.appendChild(css);
  const dash = '<span class="sxr-dash">–</span>';
  const n = v => v == null ? dash : whole(v);
  const pts = f => f.points == null ? dash : `<div class="sxr-cell"><b>${f.points.toFixed(1)} <span class="muted" style="font-weight:400">/ ${f.max_points.toFixed(1)}</span></b><div class="sxr-bar"><i style="width:${Math.min(100, f.signal)}%"></i></div></div>`;

  add("stxreport", "Reports and downloads", "STX Index report", async el => {
    const f = (window.SP && window.SP.stxreport) || {period: "7d", language: "", segment: ""};
    el.innerHTML = head("STX Index report", "Every channel's STX Index out of 100, what each of the seven factors gave it, and its audience, channel by channel. Download it as a branded PDF.")
      + `<form class="card" id="sxrf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0"><label>Period<br><select name="period">${opt(PERIODS, f.period)}</select></label>
          <label>Language<br><select name="language">${opt(LANGS, f.language)}</select></label><label>Category<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label>
          <label>Scorecards in the PDF<br><select name="cards">${opt([["6", "Top 6"], ["12", "Top 12"], ["24", "Top 24"], ["60", "All"]], "12")}</select></label>
          <button class="btn primary" type="submit">Show</button><button class="btn" type="button" id="sxrpdf">Download the PDF</button></form><div id="sxrmsg" class="msg" hidden></div><div id="sxrout"><p class="muted">Loading…</p></div>`;
    const out = $("#sxrout", el), say = (t, ok) => { const m = $("#sxrmsg", el); m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    const query = () => { const v = formValues($("#sxrf", el)); (window.SP = window.SP || {}).stxreport = {period: v.period, language: v.language, segment: v.segment}; return v; };
    const draw = r => {
      const h = r.headline, byId = Object.fromEntries(r.channels.map(c => [c.channel_id, c]));
      out.innerHTML = (h ? `<div class="grid kpis"><div class="card kpi"><div class="l">Highest STX</div><div class="v">${esc(h.leader)}</div><div class="s">${h.leader_score.toFixed(1)} out of 100</div></div>
          <div class="card kpi"><div class="l">Average STX</div><div class="v">${h.average.toFixed(1)}</div><div class="s">of ${h.scored} scored channels (raw ${h.average_raw.toFixed(1)})</div></div>
          <div class="card kpi"><div class="l">Period</div><div class="v" style="font-size:18px">${esc(r.period_label)}</div><div class="s">${r.scored} of ${r.channels_in_window} channels with data</div></div></div>` : '<p class="muted">No channel has a score in this window.</p>')
        + `<div class="sxr-note"><b>How to read it.</b> Each factor is a 0-100 signal; the <b>points</b> it gives are the signal times its weight (audience 30%, growth 20%, momentum 15%, acceleration 10%, consistency 10%, competition 10%, event 5%) and they add up to the <b>Raw</b> STX. The <b>STX</b> column is the score every StatAxis screen shows: the raw score pulled toward 50 when data is thin (<b>Conf.</b>). A dash means no data in the window: the other factors share its weight, so the maximums always add up to 100. It is never read as zero.</div>`
        + (r.channels.length ? `<section class="card"><h2>1. Score out of 100, and what each factor gave</h2><div style="overflow:auto"><table><thead><tr><th>#</th><th>Channel</th><th>Group</th><th>STX</th><th>Raw</th><th>Conf.</th>${r.weights.map(w => `<th title="${esc(w.meaning)}">${esc(w.label)}<br><span class="muted" style="font-weight:400">${w.weight_percent}%</span></th>`).join("")}</tr></thead><tbody>
          ${r.channels.map(c => `<tr><td>${c.rank}</td><td><b>${esc(c.name)}</b>${c.preliminary ? ' <span class="tag" title="Less than half of the weight had data">preliminary</span>' : ""}</td><td class="muted">${esc(c.group)}</td><td><span class="sxr-stx">${c.stx.toFixed(1)}</span></td><td>${c.raw == null ? dash : c.raw.toFixed(1)}</td><td>${c.confidence == null ? dash : c.confidence + "%"}</td>${c.factors.map(x => `<td>${pts(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
          <p class="muted" style="margin-top:8px">Each factor cell reads points earned / the most points that factor could give this channel; the bar is the factor's 0-100 signal.</p></section>
        <section class="card" style="margin-top:14px"><h2>2. Audience, channel by channel</h2><div style="overflow:auto"><table><thead><tr><th>#</th><th>Channel</th><th>Group</th><th>Average live viewers</th><th>Peak viewers</th><th>Now</th><th>Views gained</th><th>Share of its group</th><th>Uploads</th><th>Likes + comments</th></tr></thead><tbody>
          ${[...r.audience_order.map(id => byId[id]), ...r.channels.filter(c => !r.audience_order.includes(c.channel_id))].map((c, i) => `<tr><td>${r.audience_order.includes(c.channel_id) ? i + 1 : dash}</td><td><b>${esc(c.name)}</b></td><td class="muted">${esc(c.group)}</td><td>${n(c.audience.average)}</td><td>${n(c.audience.peak)}</td><td>${n(c.audience.now)}</td><td>${n(c.audience.views_gained)}</td><td>${c.audience.share_percent == null ? dash : c.audience.share_percent.toFixed(1) + "%"}</td><td>${n(c.audience.uploads)}</td><td>${n(c.audience.engagement)}</td></tr>`).join("")}</tbody></table></div></section>
        <section class="card" style="margin-top:14px"><h2>3. Who leads each factor</h2><div style="overflow:auto"><table><thead><tr><th>Factor</th><th>Weight</th><th>Channels with data</th><th>First</th><th>Second</th><th>Third</th></tr></thead><tbody>
          ${r.leaders.map(x => `<tr><td><b>${esc(x.label)}</b></td><td>${x.weight_percent}%</td><td>${x.with_data}</td>${[0, 1, 2].map(i => `<td>${x.top[i] ? `${esc(x.top[i].name)} <span class="muted">(${Math.round(x.top[i].signal)})</span>` : dash}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>` : "")
        + `<details class="card" style="margin-top:14px"><summary><b>What the seven factors measure</b></summary><table style="margin-top:8px"><tbody>${r.weights.map(w => `<tr><td><b>${esc(w.label)}</b></td><td>${w.weight_percent}%</td><td class="muted">${esc(w.meaning)}</td></tr>`).join("")}</tbody></table>
           <p class="muted" style="margin-top:8px">${esc(r.note)}</p></details>`;
    };
    const show = async () => { const v = query(); out.innerHTML = '<p class="muted">Working it out…</p>'; say(""); try { draw(await api("/api/v1/market/stx-report", {period: v.period, language: v.language, segment: v.segment})); } catch (e) { out.innerHTML = ""; say(e.message); } };
    $("#sxrf", el).onsubmit = ev => { ev.preventDefault(); show(); };
    $("#sxrpdf", el).onclick = async () => {
      const v = query(), b = $("#sxrpdf", el); b.disabled = true; say("Making the PDF…", true);
      try {
        const res = await fetch("/api/v1/market/stx-report.pdf?" + new URLSearchParams({period: v.period, language: v.language, segment: v.segment, cards: v.cards}), {headers: {Authorization: "Bearer " + token()}});
        if (!res.ok) { let d = null; try { d = await res.json(); } catch { /* not JSON */ } throw new Error((d && d.error) || "Could not make the PDF."); }
        const name = (/filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "") || [])[1] || "stataxis-stx-index-report.pdf", url = URL.createObjectURL(await res.blob()), a = document.createElement("a");
        a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000); say("Downloaded " + name, true);
      } catch (e) { say(e.message); }
      b.disabled = false;
    };
    show();
  });
})();
