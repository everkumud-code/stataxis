/* Downloads for every screen of the workspace, and for every block on it (every channel, slot or group has its own).
   Each can be taken as a PDF (the server draws it on the StatAxis letterhead) or as an image to post (drawn here). Both read what the person is looking at: headings, figures, tables, pictures and the filters they chose.
   The letterhead, the watermark and the time of download (Indian time, on every page and in the file name) come from the server.
   Loaded by workspace.html after market.js; it uses that script's helpers ($, esc, token, VIEWS). */
"use strict";
(() => {
  const IST = {timeZone: "Asia/Kolkata"};
  /* "12 Oct 2026, 3:42 pm IST": the moment of this download, in Indian time */
  window.sxDownloadedAt = () => new Date().toLocaleString("en-IN", {...IST, day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true}) + " IST";
  /* "20261012-1542": the same moment for a file name */
  window.sxFileStamp = () => new Date().toLocaleString("sv-SE", IST).replace(/\D/g, "").replace(/^(\d{8})(\d{4}).*$/, "$1-$2");

  const SKIP = new Set(["SCRIPT", "STYLE", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "FORM", "NAV", "DIALOG", "NOSCRIPT", "OPTION", "LABEL", "SVG", "IFRAME"]);
  const INLINE = new Set(["A", "B", "I", "EM", "STRONG", "SPAN", "SMALL", "CODE", "MARK", "BR", "U", "SUB", "SUP", "TIME", "ABBR", "WBR"]);
  const clean = t => String(t || "").replace(/\s+/g, " ").trim();
  const shown = n => !n.hasAttribute("hidden") && getComputedStyle(n).display !== "none";
  const inlineOnly = n => [...n.children].every(c => INLINE.has(c.tagName));

  function tableBlock(t) {
    const rows = [...t.rows].filter(shown);
    let head = [];
    const th = t.tHead && t.tHead.rows[0] ? [...t.tHead.rows[0].cells] : (rows[0] && [...rows[0].cells].every(c => c.tagName === "TH") ? [...rows[0].cells] : []);
    head = th.map(c => clean(c.innerText));
    const body = rows.filter(r => !(t.tHead && t.tHead.contains(r)) && !(th.length && r.cells[0] === th[0])).map(r => [...r.cells].map(c => clean(c.innerText || c.textContent)));
    return {t: "table", head, rows: body.slice(0, 500), cut: body.length > 500};
  }

  /* the filters the person chose, as one line: "Language: Hindi | From: 2026-10-05 | ..." */
  function filtersLine(el) {
    const parts = [];
    el.querySelectorAll("form select, form input").forEach(c => {
      if (c.closest("[data-noreport]") || c.type === "hidden" || c.type === "password" || c.type === "submit" || c.type === "button") return;
      const lab = c.closest("label"), name = lab && lab.childNodes[0] ? clean(lab.childNodes[0].textContent) : "";
      if (c.type === "checkbox") { if (c.checked && name) parts.push(name); return; }
      const value = c.tagName === "SELECT" ? clean([...c.selectedOptions].map(o => o.textContent).join(", ")) : clean(c.value);
      if (name && value && !/^all /i.test(value) && value !== "Any") parts.push(`${name}: ${value}`);
    });
    return parts.slice(0, 14).join("  |  ");
  }

  function pictureOf(canvas) {
    try {
      if (canvas.width < 120 || canvas.height < 60) return null;
      const k = Math.min(1, 900 / canvas.width), c = document.createElement("canvas");
      c.width = Math.round(canvas.width * k); c.height = Math.round(canvas.height * k);
      const x = c.getContext("2d"); x.fillStyle = "#ffffff"; x.fillRect(0, 0, c.width, c.height); x.drawImage(canvas, 0, 0, c.width, c.height);
      return c.toDataURL("image/png");
    } catch { return null; }   /* a picture the browser will not let us read is left out; the figures stay */
  }

  function capture(el) {
    const out = [];
    const walk = n => {
      if (out.length > 900) return;
      for (const c of n.childNodes) {
        if (c.nodeType === 3) { const t = clean(c.textContent); if (t) out.push({t: "p", text: t}); continue; }
        if (c.nodeType !== 1 || SKIP.has(c.tagName.toUpperCase()) || c.hasAttribute("data-noreport") || !shown(c)) continue;
        const tag = c.tagName;
        if (c.classList.contains("kpi")) { const g = q => clean((c.querySelector(q) || {}).textContent), l = g(".l"), v = g(".v"), note = g(".s"); if (l || v) out.push({t: "p", text: `${l}: ${v}${note ? " — " + note : ""}`, kpi: {l, v, s: note}}); continue; }
        if (tag === "DETAILS" || c.classList.contains("evidence")) {   /* how it was worked out: kept in the PDF, left out of a post */
          const n0 = out.length;
          if (tag === "DETAILS") walk(c); else { const t = clean(c.innerText || c.textContent); if (t) out.push({t: "p", text: t}); }
          for (let k = n0; k < out.length; k++) out[k].m = 1;
          continue;
        }
        if (tag === "TABLE") { out.push(tableBlock(c)); continue; }
        if (tag === "CANVAS") { const d = pictureOf(c); if (d) out.push({t: "img", data: d}); continue; }
        if (tag === "H1") continue;   /* the report carries the screen's name as its own title */
        if (/^H[2-4]$/.test(tag) || tag === "SUMMARY") { const t = clean(c.innerText || c.textContent); if (t) out.push({t: "h", text: t}); continue; }
        if (inlineOnly(c)) { const t = clean(c.innerText || c.textContent); if (t) out.push({t: "p", text: t}); continue; }
        walk(c);
      }
    };
    walk(el);
    return out;
  }

  /* ---------- what a report is made of ---------- */
  const slug = t => String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 28);
  const pending = el => /^\s*(Working it out|Loading…|Making the PDF…)/m.test(el.innerText);
  /* some screens fill in their tables a moment after they appear: wait for them (up to 40 seconds) rather than report an empty screen */
  async function settle(el, say) {
    for (let i = 0; i < 100 && pending(el); i++) { if (i === 3) say("Waiting for the screen to finish loading…", true); await new Promise(r => setTimeout(r, 400)); }
    if (pending(el)) throw new Error("This screen is still loading. Try again in a moment.");
  }
  function save(blob, name) {
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }
  /* one report: the whole screen, or one card of it (one channel, one slot, one group ...) */
  function scopeOf(view, screen, card) {
    if (!card) return {title: view.title, sub: filtersLine(screen), id: view.id, blocks: capture(screen), plain: plainOf(view), viewId: view.id};
    const title = unitTitle(card), blocks = capture(card);
    if (blocks[0] && blocks[0].t === "h" && blocks[0].text.startsWith(title)) blocks.shift();
    return {title, sub: [view.title, filtersLine(screen)].filter(Boolean).join("  |  "), id: `${view.id}-${slug(title)}`, blocks, plain: plainOf(view), viewId: view.id};
  }

  /* ---------- PDF ---------- */
  async function makePdf(view, screen, card, say) {
    say("Making your PDF…", true);
    try {
      await settle(screen, say);
      const s = scopeOf(view, screen, card);
      const chart = barsOf(s.blocks.filter(b => !b.m)), lead = [stxLine(s.blocks.filter(b => !b.m)), ...findingsOf(chart)].filter(Boolean);
      s.blocks.unshift({t: "h", text: "StatAxis viewpoint"}, {t: "p", text: viewpointOf(chart, view.id, lead[0] && lead[0].startsWith("STX Index") ? lead[0] : "")});
      if (lead.length) s.blocks.unshift({t: "h", text: "What stands out"}, ...lead.map(t => ({t: "p", text: "• " + t})));
      if (s.plain) s.blocks.unshift({t: "p", text: "About this report: " + s.plain});
      const res = await fetch("/api/v1/market/screen-report.pdf", {method: "POST", headers: {"Content-Type": "application/json", Authorization: "Bearer " + token()}, body: JSON.stringify({view: s.id, title: s.title, filters: s.sub, blocks: s.blocks})});
      if (!res.ok) { let m = "Could not make the PDF."; try { m = (await res.json()).error || m; } catch { /* not JSON */ } throw new Error(res.status === 429 ? "Too many in a short time. Wait a minute and try again." : m); }
      const cd = res.headers.get("Content-Disposition") || "", name = (cd.match(/filename="([^"]+)"/) || [])[1] || `stataxis-${s.id}-downloaded-${window.sxFileStamp()}.pdf`;
      save(await res.blob(), name);
      say(`Saved ${name}  ·  ${window.sxDownloadedAt()}`, true);
    } catch (e) { say(e.message); }
  }

  /* ---------- a picture to post: a dark card with the logo, the name of the thing, its figures as bars (or its key lines), ready for social media ---------- */
  const logo = SXD.logo;   /* the blue-and-gold logo of the StatAxis design */
  const num = s => { const m = String(s == null ? "" : s).replace(/,/g, "").match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; };
  function wrap(x, text, width) {
    const out = []; let line = "";
    for (const word of String(text).split(" ")) {
      const t = line ? line + " " + word : word;
      if (x.measureText(t).width > width && line) { out.push(line); line = word; } else line = t;
    }
    if (line) out.push(line);
    return out;
  }
  /* A post is for someone who has never seen StatAxis: what this is in one plain sentence, the headline numbers, and one simple chart of the result itself
     (never the method or the weights). The method stays in the PDF and on the screen. */
  const PLAIN = {
    briefing: "The week's most useful findings, in plain words, written for your role.",
    overview: "The market today at a glance: who leads, what moved, what is live.",
    market: "Every news channel ranked by how many views it gained in this period.",
    channel: "One channel's audience, momentum and content in one place.",
    dashboard: "One channel in depth, with the market beside it.",
    stream: "Live, replay, video and Shorts audiences compared.",
    content: "The videos that gained the most views.",
    competition: "Who leads, who is climbing, and how far behind each channel is.",
    trends: "How a channel's audience has moved over time.",
    live: "How many people are watching each channel live right now.",
    liveevent: "Channels compared on one live event, side by side.",
    primetime: "Which channels draw the biggest live audiences in each evening hour.",
    stx: "STX is a score out of 100 for how strongly a channel's audience is showing up. Higher means stronger. It blends audience size, growth, momentum and consistency.",
    changed: "What moved since the last period, video by video.",
    research: "The tone and the topics in video titles.",
    evaluate: "One public video checked and scored.",
    weekly: "How many views each channel's new videos of the week have collected.",
    builder: "A ranking for the days, hours and genre chosen.",
    creators: "The IFX Score rates creators and journalists out of 100 on Impact, Followership and eXposure.",
    planner: "Where to place ad spots on live news, and roughly what each costs, from real audience numbers.",
    authenticity: "Viewing patterns that look unusual, for a person to look at. A pattern is not proof of anything.",
    audience: "Where viewers live and how old they are, shown only where a channel or a study has supplied it.",
    spikes: "Sudden rises in a channel's live audience, the stream that carried each, and who gained while who lost in the same minutes.",
    forecasts: "What StatAxis expected each channel's prime-time audience to be, written down before the slot, with how close it turned out to be.",
    notes: "A dated note on what the data said, written each day and each week.",
    alerts: "Alerts a person has set on a channel's live audience, and what fired.",
    completeness: "How many of the live readings that should be in StatAxis's record are there, per channel and day.",
  };
  const plainOf = view => PLAIN[view.id] || (typeof MENU_HINT !== "undefined" && MENU_HINT[view.id]) || "";
  /* the first table that has a column of numbers worth drawing: its first text column labels the bars. Weights and points are the method, not the result, so they are never the bars. */
  function barsOf(blocks) {
    for (const b of blocks) {
      if (b.t !== "table" || b.m || b.rows.length < 2) continue;
      const rows = b.rows.slice(0, 24), cols = b.head.length;   /* up to three posts of eight */
      const numeric = c => rows.filter(r => num(r[c]) != null && /\d/.test(r[c])).length >= Math.ceil(rows.length * 0.5);
      const rank = c => rows.every((r, i) => num(r[c]) === i + 1);
      let label = -1, value = -1;
      for (let c = 0; c < cols; c++) { if (label < 0 && !numeric(c)) label = c; }
      for (let c = 0; c < cols; c++) { if (c !== label && numeric(c) && !rank(c) && !/weight|points/i.test(b.head[c])) { value = c; break; } }
      if (label >= 0 && value >= 0) {
        /* a channel with no data (a dash, "not enough history", or nothing measured) is left out of a post: only channels with figures are shown */
        const kept = rows.map(r => ({label: r[label], value: num(r[value]) != null && /\d/.test(r[value]) ? Math.max(0, num(r[value])) : null, text: r[value]})).filter(r => r.value != null && r.value > 0);
        if (kept.length) return {caption: /reading/i.test(b.head[value]) ? "Each one, out of 100" : b.head[value], rows: kept};
      }
    }
    return null;
  }
  /* "StatAxis viewpoint": our reading of the figures in two or three sentences: how the lead looks, how the audience is shared, and what to keep in mind. Worked out from the figures shown; it describes, it does not accuse. */
  const VIEWPOINT_NOTE = {
    authenticity: "An unusual pattern is a reason to look closer, not proof of anything: StatAxis reports patterns in public numbers and leaves conclusions to people who can check the facts.",
    stx: "STX is a guide to relative strength, not a verdict: a signal with little history counts for less, which is why the confidence is shown next to the score.",
    creators: "The IFX Score compares creators with each other on what is public; a high score is a strong showing on these measures, nothing more.",
    planner: "Use the figures to compare slots with each other, and confirm any price with the channel's own rate card.",
  };
  function viewpointOf(chart, viewId, stx = "") {   /* our finding is part of our viewpoint: the STX line, when the figures carry one, comes first */
    const caution = VIEWPOINT_NOTE[viewId] || "Read the figures with the period in mind: a short window can be moved by a single event, and these are measured on YouTube, not on television.";
    const have = chart ? chart.rows.filter(r => r.value != null && r.value > 0).sort((a, b) => b.value - a.value) : [];
    if (have.length < 2) return `${stx} ${caution}`.trim();
    const [top, next] = have, total = have.reduce((t, r) => t + r.value, 0), share = Math.round(100 * top.value / total), ratio = top.value / next.value;
    const lead = ratio >= 2 ? `${top.label} has a runaway lead` : ratio >= 1.2 ? `${top.label} has a clear lead` : `${top.label} and ${next.label} are in a close race`;
    const spread = have.length < 3 ? "" : share >= 50 ? `One channel holds the majority of this audience (${share}%).` : share >= 30 ? "One channel leads, yet the audience is still shared across several." : "The audience is spread widely; no channel dominates.";
    return `${stx} ${lead}. ${spread} ${caution}`.replace(/\s+/g, " ").trim();
  }
  /* The STX Index is the platform's own measure and the first thing a reader should see: when a table has an STX column, the report says who is highest and what the average is */
  function stxLine(blocks) {
    for (const b of blocks) {
      if (b.t !== "table" || b.m || !b.rows.length) continue;
      const c = b.head.findIndex(h => /^STX/i.test(h)); if (c < 0) continue;
      const isNum = col => b.rows.filter(r => num(r[col]) != null && /\d/.test(r[col])).length >= Math.ceil(b.rows.length * 0.5);
      let label = -1; for (let k = 0; k < b.head.length; k++) { if (k !== c && !isNum(k)) { label = k; break; } }
      const have = b.rows.map(r => ({name: label >= 0 ? r[label] : "", v: /\d/.test(r[c]) ? num(r[c]) : null})).filter(x => x.v != null);
      if (!have.length) continue;
      const top = have.reduce((m, x) => x.v > m.v ? x : m), avg = have.reduce((t, x) => t + x.v, 0) / have.length;
      return `STX Index: ${top.name} is highest at ${top.v.toFixed(1)}; the average of the ${have.length} scored channels is ${avg.toFixed(1)}.`;
    }
    return "";
  }
  /* "What stands out": a few plain sentences worked out only from the figures shown (who leads, by how much, how the total is shared), so a reader gets a take-away and not just a table */
  function findingsOf(chart) {
    if (!chart) return [];
    const have = chart.rows.filter(r => r.value != null && r.value > 0).sort((a, b) => b.value - a.value);
    if (!have.length) return [];
    const [top, next] = have, out = [`${top.label} leads with ${top.text}.`];
    if (next) out.push(top.value >= 1.2 * next.value ? `That is about ${(top.value / next.value).toFixed(1)} times ${next.label}, the next one (${next.text}).` : `${next.label} is close behind at ${next.text}, so the lead is narrow.`);
    const total = have.reduce((t, r) => t + r.value, 0);
    if (have.length >= 3 && total > 0) out.push(`${top.label} holds ${Math.round(100 * top.value / total)}% of the total across these ${have.length}.`);
    const missing = chart.rows.filter(r => r.value == null).length, zero = chart.rows.filter(r => r.value === 0).length;
    if (missing > 0) out.push(`${missing} of ${chart.rows.length} do not have enough data yet; they will appear as it builds up.`);
    else if (zero > 0) out.push(`${zero} of ${chart.rows.length} show 0 in this period.`);
    return out.slice(0, 4);
  }
  async function postPng(title, subtitle, blocks, plain = "", viewId = "", pg = {n: 1}) {   /* one post of a series: {canvas, pages}; the StatAxis design (sxdesign.js) */
    const D = SXD, W = 1080, P = 64, m = document.createElement("canvas").getContext("2d");
    const result = blocks.filter(b => !b.m), kpis = result.filter(b => b.kpi && b.kpi.v).slice(0, 3).map(b => b.kpi);
    const chart = barsOf(result), allFinds = [stxLine(result), ...findingsOf(chart)].filter(Boolean).slice(0, 4);   /* the STX Index leads every take-away */
    const stx = allFinds[0] && allFinds[0].startsWith("STX Index") ? allFinds[0] : "", finds = allFinds.filter(f => f !== stx);
    const vp = viewpointOf(chart, viewId, stx);
    let body = [];   /* text lines when there is no table of numbers: {text, kind} */
    const few = result.filter(b => (b.t === "p" || b.t === "h") && !b.kpi).length <= 5, fs = few ? 38 : 30, lh = few ? 56 : 44;   /* a short note is set larger, like a poster */
    if (!chart) {
      for (const b of result) {
        if (b.t === "table") { for (const r of b.rows.filter(row => row.slice(1).some(c => /\d/.test(c))).slice(0, 6)) body.push({text: r.filter(Boolean).join("  ·  "), kind: "p"}); continue; }   /* rows with no figures are left out */
        if ((b.t === "p" || b.t === "h") && !b.kpi && !/^(review now|check|nothing unusual)(?![a-z])/i.test(b.text)) body.push({text: b.text, kind: b.t});   /* the radar's risk labels stay on the screen; they are not for a post */
      }
      m.font = `500 ${fs}px ${D.F.body}`;
      body = body.flatMap(l => wrap(m, l.text, W - 2 * P).slice(0, l.kind === "h" ? 1 : 3).map((t, i) => ({text: t, kind: l.kind, first: i === 0}))).slice(0, 14);
    }
    /* more than one post can hold: eight bars (or twelve lines) to a post, numbered 1 of 3, 2 of 3 ... ; the introduction is on the first, our reading on the last */
    const ROWS_PER = 8, LINES_PER = 12, pages = Math.max(1, chart ? Math.ceil(chart.rows.length / ROWS_PER) : Math.ceil(body.length / LINES_PER)), n = Math.min(pg.n || 1, pages), first = n === 1, last = n === pages;
    const chartP = chart ? {...chart, rows: chart.rows.slice((n - 1) * ROWS_PER, n * ROWS_PER)} : null, bodyP = body.slice((n - 1) * LINES_PER, n * LINES_PER), rowH = 76, hs = 90;
    const label = String(viewId || "report").replace(/[^a-z0-9]+/gi, " ").trim() || "report";
    /* one pass measures, the other draws: the same steps, so the picture is exactly as tall as what is on it */
    const paint = (x, draw) => {
      let y = 100;
      if (draw) {
        D.eyebrow(x, `Fig. ${String(n).padStart(2, "0")} — ${label}`, P, y);
        if (pages > 1) { x.textAlign = "right"; x.fillStyle = D.C.blue; x.font = `400 40px ${D.F.head}`; x.fillText(`${n} of ${pages}`, W - P, y); x.textAlign = "left"; }
      }
      const tl = D.headLines(x, title, W - 2 * P, hs, 3); y += 34 + hs * 0.86;
      if (draw) D.headline(x, title, P, y, W - 2 * P, hs, 3);
      y += (tl - 1) * hs * 0.98 + 30;
      x.font = `500 24px ${D.F.body}`; const sub = wrap(x, subtitle, W - 2 * P).slice(0, 2);
      sub.forEach(t => { if (draw) { x.fillStyle = D.C.mute; x.fillText(t, P, y + 6); } y += 32; });
      y += 18;
      if (first && plain) {
        x.font = `500 28px ${D.F.body}`; wrap(x, plain, W - 2 * P).slice(0, 4).forEach(t => { if (draw) { x.fillStyle = D.C.text; x.fillText(t, P, y + 24); } y += 40; });
        y += 18;
      }
      if (first && stx) {   /* the STX Index is the headline of every report: a framed callout right under the title */
        x.font = `600 31px ${D.F.body}`; const lines = wrap(x, stx.replace(/^STX Index:\s*/, ""), W - 2 * P - 56).slice(0, 3), h = 74 + lines.length * 42;
        if (draw) {
          x.fillStyle = D.C.panel; x.strokeStyle = D.C.blue; x.lineWidth = 2.5; x.beginPath(); x.roundRect(P, y, W - 2 * P, h, 16); x.fill(); x.stroke();
          x.fillStyle = D.C.blue; x.font = `500 20px ${D.F.mono}`; if ("letterSpacing" in x) x.letterSpacing = "4px"; x.fillText("STX INDEX", P + 28, y + 40); if ("letterSpacing" in x) x.letterSpacing = "0px";
          x.fillStyle = D.C.white; x.font = `600 31px ${D.F.body}`; lines.forEach((t, i) => x.fillText(t, P + 28, y + 86 + i * 42));
        }
        y += h + 34;
      }
      if (first && kpis.length) {   /* the headline numbers, big */
        const gap = 20, w = (W - 2 * P - gap * (kpis.length - 1)) / kpis.length;
        kpis.forEach((k, i) => {
          const left = P + i * (w + gap);
          if (draw) {
            x.fillStyle = D.C.panel; x.strokeStyle = D.C.line; x.lineWidth = 2; x.beginPath(); x.roundRect(left, y, w, 140, 14); x.fill(); x.stroke();
            x.fillStyle = D.C.mute; x.font = `600 20px ${D.F.body}`; x.fillText(String(k.l).slice(0, 26), left + 20, y + 34);
            x.fillStyle = i === 0 ? D.C.blue : D.C.white; x.font = `400 66px ${D.F.head}`; x.fillText(String(k.v).slice(0, 12), left + 20, y + 100);
            if (k.s && k.s.length <= 36) { x.fillStyle = D.C.mute; x.font = `500 16px ${D.F.body}`; x.fillText(String(k.s).slice(0, Math.floor(w / 9)), left + 20, y + 126); }
          }
        });
        y += 140 + 34;
      }
      if (chartP) {
        if (draw) { x.fillStyle = D.C.mute; x.font = `500 20px ${D.F.mono}`; if ("letterSpacing" in x) x.letterSpacing = "3px"; x.fillText(String(chart.caption || "").toUpperCase().slice(0, 40), P, y + 20); if ("letterSpacing" in x) x.letterSpacing = "0px"; }
        y += 50;
        const max = Math.max(...chart.rows.map(r => r.value || 0), 1), left = 430, bar = W - left - P - 200;   /* one scale for the whole series */
        chartP.rows.forEach((r, i) => {
          const yy = y + i * rowH;
          if (draw) {
            D.number(x, String((n - 1) * ROWS_PER + i + 1).padStart(2, "0"), P, yy + 56, 58);
            x.fillStyle = D.C.white; x.font = `600 27px ${D.F.body}`; x.fillText(String(r.label).slice(0, 18), P + 98, yy + 50);
            if (r.value == null) { x.fillStyle = D.C.mute; x.font = `500 22px ${D.F.body}`; x.fillText(String(r.text).slice(0, 30), left, yy + 50); }
            else {
              const w = Math.max(5, bar * r.value / max);
              x.fillStyle = i === 0 && first ? D.C.blue : D.C.blueDeep; x.fillRect(left, yy + 20, w, 38);
              x.fillStyle = D.C.white; x.font = `700 27px ${D.F.body}`; x.fillText(String(r.text).slice(0, 14), left + w + 14, yy + 51);
            }
            x.fillStyle = D.C.line; x.fillRect(P, yy + rowH - 6, W - 2 * P, 1);
          }
        });
        y += chartP.rows.length * rowH + 20;
      } else {
        bodyP.forEach((l, i) => { if (draw) { x.fillStyle = l.kind === "h" ? D.C.blue : D.C.text; x.font = l.kind === "h" ? `400 ${fs + 14}px ${D.F.head}` : `500 ${fs}px ${D.F.body}`; x.fillText(l.kind === "h" ? l.text.toUpperCase() : l.text, P, y + fs + i * lh); } });
        y += bodyP.length * lh + 30;
      }
      if (last && finds.length) {
        if (draw) { x.fillStyle = D.C.mute; x.font = `500 20px ${D.F.mono}`; if ("letterSpacing" in x) x.letterSpacing = "4px"; x.fillText("WHAT STANDS OUT", P, y + 14); if ("letterSpacing" in x) x.letterSpacing = "0px"; }
        y += 44; x.font = `500 27px ${D.F.body}`;
        finds.forEach(f => { wrap(x, f, W - 2 * P - 34).slice(0, 2).forEach((t, k) => { if (draw) { if (k === 0) { x.fillStyle = D.C.blue; x.beginPath(); x.arc(P + 8, y + 16, 6, 0, Math.PI * 2); x.fill(); } x.fillStyle = D.C.text; x.fillText(t, P + 34, y + 24); } y += 36; }); y += 8; });
        y += 14;
      }
      if (last && vp) {   /* our viewpoint, last: the blue italic line to remember */
        if (draw) { x.fillStyle = D.C.mute; x.font = `500 20px ${D.F.mono}`; if ("letterSpacing" in x) x.letterSpacing = "4px"; x.fillText("STATAXIS VIEWPOINT", P, y + 14); if ("letterSpacing" in x) x.letterSpacing = "0px"; }
        y += 24; x.font = `italic 400 36px ${D.F.serif}`;
        wrap(x, vp, W - 2 * P).slice(0, 8).forEach(t => { y += 48; if (draw) { x.fillStyle = D.C.blue; x.fillText(t, P, y); } });
        y += 24;
      }
      return y;
    };
    const used = paint(m, false), H = Math.max(1080, Math.round(used + 220));
    const c0 = document.createElement("canvas"); c0.width = W; c0.height = H; const x = c0.getContext("2d");
    D.background(x, W, H); await D.watermark(x, W, H, 0.03);
    paint(x, true);
    await D.footer(x, W, H, P, ["Measured by StatAxis from public YouTube data. Not TV ratings.", "Data via YouTube. Processed and evaluated by StatAxis.", "Downloaded " + window.sxDownloadedAt()]);
    return {canvas: c0, pages};
  }
  async function makePost(view, screen, card, say) {
    say("Making your post image…", true);
    try {
      await settle(screen, say);
      const s = scopeOf(view, screen, card);
      if (!s.blocks.length) throw new Error("There is nothing here to put in a post yet.");
      const ch = (s.sub.match(/Channel: ([^|]+?)(?:\s*\||$)/) || [])[1], title = ch && !s.title.includes(ch) ? `${s.title} · ${ch}` : s.title;
      const firstPost = await postPng(title, s.sub, s.blocks, s.plain, s.viewId, {n: 1}), pages = firstPost.pages, stamp = window.sxFileStamp(), saved = [];
      for (let n = 1; n <= pages; n++) {   /* more than one post can hold: 1 of 3, 2 of 3, 3 of 3 */
        const canvas = n === 1 ? firstPost.canvas : (await postPng(title, s.sub, s.blocks, s.plain, s.viewId, {n})).canvas;
        const name = `stataxis-${s.id}-post${pages > 1 ? `-${n}-of-${pages}` : ""}-downloaded-${stamp}.png`;
        await new Promise(res => canvas.toBlob(b => { save(b, name); res(); }, "image/png"));
        saved.push(name);
        if (n < pages) await new Promise(r => setTimeout(r, 450));   // the browser takes the files one after another
      }
      say(pages > 1 ? `Saved ${pages} images (1 of ${pages} to ${pages} of ${pages})  ·  ${window.sxDownloadedAt()}` : `Saved ${saved[0]}  ·  ${window.sxDownloadedAt()}`, true);
    } catch (e) { say(e.message); }
  }

  /* ---------- one report for each card: every channel, slot or group has its own PDF and its own post image ---------- */
  function unitTitle(card) {
    const h = card.querySelector("h2, h3, h4"); if (!h) return "";
    const c = h.cloneNode(true); c.querySelectorAll(".tag, .muted, small, .badge, button").forEach(n => n.remove());
    return clean(c.innerText || c.textContent).slice(0, 120);
  }
  const isUnit = card => card.dataset.ub === undefined && !card.matches("form, .kpi, .state") && !card.querySelector(".card, form") && !card.closest("[data-noreport]") && shown(card) &&
    !!unitTitle(card) && (!!card.querySelector("table, canvas") || clean(card.innerText).length > 70);
  function addUnitBars(view, screen) {
    screen.querySelectorAll(".card").forEach(card => {
      if (!isUnit(card)) return;
      card.dataset.ub = "1";
      const bar = document.createElement("div"); bar.className = "unitbar"; bar.setAttribute("data-noreport", "");
      bar.innerHTML = `<span class="msg" hidden role="status"></span><button class="ub" type="button" data-k="pdf" title="Download this as a PDF">${ICON_PDF}PDF</button><button class="ub" type="button" data-k="img" title="Download this as an image to post">${ICON_IMG}Post image</button>`;
      const msg = bar.querySelector(".msg"), say = (t, ok) => { msg.hidden = !t; msg.className = "msg " + (ok ? "ok" : "bad"); msg.textContent = t || ""; };
      bar.querySelector('[data-k="pdf"]').onclick = () => makePdf(view, screen, card, say);
      bar.querySelector('[data-k="img"]').onclick = () => makePost(view, screen, card, say);
      card.append(bar);
    });
  }
  const ICON_PDF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"/></svg>';
  const ICON_IMG = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/></svg>';
  let watcher = null;

  /* called by workspace.html each time a screen has been drawn */
  window.addReportBar = (host, el, view) => {
    if (watcher) watcher.disconnect();
    if (!view || view.id === "profile") return;
    const bar = document.createElement("section");
    bar.className = "reportbar"; bar.setAttribute("data-noreport", "");
    bar.innerHTML = `<div><b>Download this screen</b><span>One tap for everything above, as a PDF or as an image to post. Each block above has its own too. The time of download is on every file.</span></div>
      <div class="btnrow"><button class="btn primary" type="button" data-k="pdf">${ICON_PDF}Download PDF</button><button class="btn" type="button" data-k="img">${ICON_IMG}Download post image</button></div><div class="msg" hidden role="status"></div>`;
    const msg = bar.querySelector(".msg"), say = (t, ok) => { msg.hidden = !t; msg.className = "msg " + (ok ? "ok" : "bad"); msg.textContent = t || ""; };
    /* screens that already have a report of their own (the report builder, the role briefing) use it for the PDF */
    bar.querySelector('[data-k="pdf"]').onclick = () => { const own = el.querySelector("#bpdf"); if (own) { own.click(); return; } makePdf(view, el, null, say); };
    bar.querySelector('[data-k="img"]').onclick = () => makePost(view, el, null, say);
    host.append(bar);
    /* cards arrive as the screen's data arrives (and again after every filter change): give each its own buttons */
    let timer = 0; const sweep = () => { clearTimeout(timer); timer = setTimeout(() => addUnitBars(view, el), 250); };
    watcher = new MutationObserver(sweep); watcher.observe(el, {childList: true, subtree: true}); sweep();
  };
})();
