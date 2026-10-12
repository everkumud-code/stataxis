/* One-tap report under every screen of the workspace.
   The bar at the bottom reads what the person is looking at (headings, figures, tables, pictures, the filters they chose) and asks the server for a branded PDF of it.
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

  async function makeReport(view, el, msg) {
    const say = (text, ok) => { msg.hidden = !text; msg.className = "msg " + (ok ? "ok" : "bad"); msg.textContent = text || ""; };
    say("Making your report…", true);
    try {
      /* some screens fill in their tables a moment after they appear: wait for them (up to 40 seconds) rather than report an empty screen */
      const pending = () => /^\s*(Working it out|Loading…|Making the PDF…)/m.test(el.innerText);
      for (let i = 0; i < 100 && pending(); i++) { if (i === 3) say("Waiting for the screen to finish loading…", true); await new Promise(r => setTimeout(r, 400)); }
      if (pending()) throw new Error("This screen is still loading. Try again in a moment.");
      const body = JSON.stringify({view: view.id, title: view.title, filters: filtersLine(el), blocks: capture(el)});
      const res = await fetch("/api/v1/market/screen-report.pdf", {method: "POST", headers: {"Content-Type": "application/json", Authorization: "Bearer " + token()}, body});
      if (!res.ok) { let m = "Could not make the report."; try { m = (await res.json()).error || m; } catch { /* not JSON */ } throw new Error(res.status === 429 ? "Too many reports in a short time. Wait a minute and try again." : m); }
      const cd = res.headers.get("Content-Disposition") || "", name = (cd.match(/filename="([^"]+)"/) || [])[1] || `stataxis-${view.id}-downloaded-${window.sxFileStamp()}.pdf`;
      const blob = await res.blob(), a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      say(`Downloaded ${name}  ·  ${window.sxDownloadedAt()}`, true);
    } catch (e) { say(e.message); }
  }

  /* called by workspace.html each time a screen has been drawn */
  window.addReportBar = (host, el, view) => {
    if (!view || view.id === "profile") return;
    const bar = document.createElement("section");
    bar.className = "reportbar"; bar.setAttribute("data-noreport", "");
    bar.innerHTML = `<div><b>Take this screen with you</b><span>One tap: a branded PDF of everything above. The time of download is printed on every page.</span></div>
      <div class="btnrow"><button class="btn primary" type="button">Download branded report (PDF)</button></div><div class="msg" hidden role="status"></div>`;
    const btn = bar.querySelector("button"), msg = bar.querySelector(".msg");
    /* screens that already have a report of their own (the report builder, the role briefing) use it */
    btn.onclick = () => { const own = el.querySelector("#bpdf"); if (own) { own.click(); return; } makeReport(view, el, msg); };
    host.append(bar);
  };
})();
