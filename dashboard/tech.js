/* The live parts of the public pages: a short start-up counter, the dot field that answers the cursor, the platform pulse, the package table, drag-to-scroll shelves,
   reveal on scroll and the apply-form prefill. Nothing here shows a figure that did not come from the platform: the pulse is read from /api/v1/public/pulse and the package
   table from /api/v1/public/packages; if either cannot be reached the page says so instead of showing numbers. */
(() => {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const fmt = n => isFinite(n) ? Number(n).toLocaleString("en-IN") : "—";

  /* ---- the scenes: each returns how bright a dot at (u, v) should be at time t; the method stage and the page headers both use them ---- */
  const SCENES = [
      (u, v, t) => { const k = (v * 6 - t * 1.6 + Math.sin(u * 14) * 1.2) % 1; const col = Math.abs(Math.sin(u * 17.3)) > .55; return col ? Math.max(0, 1 - Math.abs(((k + 1) % 1) - .5) * 4) : .04; },
      (u, v, t) => { const a = Math.atan2(v - .5, u - .5), d = Math.hypot(u - .5, v - .5); const sw = ((a - t * 1.8) % 6.283 + 6.283) % 6.283; return d < .46 ? (Math.abs(d * 7 % 1 - .5) < .08 ? .35 : .06) + Math.max(0, 1 - sw / 1.2) * .7 : 0; },
      (u, v, t) => { const bars = 18, i = Math.floor(u * bars), h = .18 + .72 * (.5 + .5 * Math.sin(i * 1.7 + t * 1.4)) * (.4 + i / bars * .6); return (u * bars % 1) > .22 && v > 1 - h ? .35 + (v - (1 - h)) * 1.2 : .04; },
      (u, v, t) => { const y = .55 - .25 * Math.sin(u * 8 + t) - .12 * Math.sin(u * 19 - t * 1.6); const d = Math.abs(v - y), peak = Math.exp(-Math.pow((u - (.5 + .3 * Math.sin(t * .6))) * 7, 2)); return Math.max(d < .045 ? .8 : 0, peak * (d < .3 ? .6 : 0)) + .04; },
      (u, v, t) => { let b = .04; for (let k = 0; k < 5; k++) { const cx = .5 + .3 * Math.cos(k * 1.2566 + t * .5), cy = .5 + .3 * Math.sin(k * 1.2566 + t * .5), d = Math.hypot(u - cx, v - cy); b = Math.max(b, d < .1 ? .9 - d * 5 : 0, Math.abs(d - .13) < .01 ? .45 : 0); } return b; },
      (u, v, t) => { const pages = [[.2, .14, .5, .7], [.28, .2, .5, .7], [.36, .26, .5, .7]]; let b = .04; pages.forEach(([l, tp, w, h], i) => { const inx = u > l && u < l + w, iny = v > tp && v < tp + h, edge = (Math.abs(u - l) < .012 || Math.abs(u - l - w) < .012) && iny || (Math.abs(v - tp) < .012 || Math.abs(v - tp - h) < .012) && inx; if (edge) b = Math.max(b, .55 + .3 * Math.sin(t * 2 + i)); if (i === 2 && inx && iny && Math.abs((v - tp) * 22 % 1 - .5) < .14 && u < l + w * (.45 + .45 * ((v * 9 + .5) % 1))) b = Math.max(b, .5); }); return b; },
      (u, v, t) => { const k = (t * .35) % 1, on = Math.abs(v - (1 - u)) < .035, pos = Math.abs(u - k) < .06; const ring = Math.abs(Math.hypot(u - .82, v - .2) - (.07 + ((t * .5) % 1) * .12)) < .012; return Math.max(on ? .35 : 0, on && pos ? 1 : 0, ring ? .8 : 0, .04); },
      (u, v, t) => { const a = Math.atan2(v - .5, u - .5), d = Math.hypot(u - .5, v - .5), head = (t * 1.5) % 6.283, da = ((a + 6.283 - head) % 6.283); return Math.abs(d - .3) < .025 ? .25 + Math.max(0, 1 - da / 2.2) * .75 : d < .02 ? .8 : .04; }];

  /* ---- start-up counter: once a session, only on the home page, never for those who want less motion ---- */
  const home = location.pathname === "/" || location.pathname.endsWith("/");
  let seen = false; try { seen = sessionStorage.getItem("sx_boot") === "1"; sessionStorage.setItem("sx_boot", "1"); } catch (e) { /* storage blocked */ }
  if (home && !reduce && !seen && !$(".sx-consent")) {
    const pre = document.createElement("div"); pre.className = "vx-pre"; pre.setAttribute("aria-hidden", "true");
    pre.innerHTML = '<div class="bar"><i></i></div><div class="row"><span>STATAXIS</span><b id="vx-n">000</b><span>SYNCING THE MARKET</span></div>';
    document.body.appendChild(pre);
    const n = $("#vx-n", pre), bar = $("i", pre), t0 = performance.now(), dur = 1100;
    const tick = t => { const k = Math.min(1, (t - t0) / dur), v = Math.round(100 * (1 - Math.pow(1 - k, 2.4))); n.textContent = String(v).padStart(3, "0"); bar.style.width = v + "%"; if (k < 1) requestAnimationFrame(tick); else { pre.classList.add("done"); setTimeout(() => pre.remove(), 600); } };
    requestAnimationFrame(tick);
  }

  /* ---- dot field: a grid of dots that swells in waves and parts around the cursor ---- */
  const hero = $(".vx-hero");
  if (hero) {
    const c = $("canvas", hero), rd = $("#vx-xy");
    if (c && !reduce) {
      const x = c.getContext("2d"); let W = 0, H = 0, dpr = 1, mx = -1e4, my = -1e4, raf = 0, t = 0, vis = true; const ripples = [];
      const size = () => { dpr = Math.min(window.devicePixelRatio || 1, 2); W = hero.clientWidth; H = hero.clientHeight; c.width = W * dpr; c.height = H * dpr; x.setTransform(dpr, 0, 0, dpr, 0, 0); };
      const step = 24;
      const draw = () => {
        x.clearRect(0, 0, W, H); t += .012;
        const cols = Math.ceil(W / step) + 1, rows = Math.ceil(H / step) + 1;
        for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
          let px = i * step, py = j * step;
          const nx = i / cols, ny = j / rows;
          // a slow field of waves, brightest toward the right of the hero where the headline is not
          const w = Math.sin(nx * 9 + t * 1.3) * Math.cos(ny * 7 - t) * .5 + .5, side = Math.min(1, Math.max(0, (nx - .25) * 1.5));
          let a = (.05 + w * .5) * side + .025, r = 1.15 + w * 1.4 * side;
          const dx = px - mx, dy = py - my, d = Math.hypot(dx, dy);
          if (d < 150) { const f = 1 - d / 150; px += dx / (d || 1) * f * 18; py += dy / (d || 1) * f * 18; a = Math.min(1, a + f * .9); r += f * 2.2; }
          for (const rp of ripples) { const dr = Math.abs(Math.hypot(px - rp.x, py - rp.y) - rp.r); if (dr < 46) { const f = 1 - dr / 46; a = Math.min(1, a + f * .85); r += f * 2.4; } }
          x.fillStyle = d < 150 || a > .6 ? `rgba(29,161,255,${a})` : `rgba(165,185,210,${a})`;
          x.beginPath(); x.arc(px, py, r, 0, 6.283); x.fill();
        }
        for (let i = ripples.length - 1; i >= 0; i--) { ripples[i].r += 9; if (ripples[i].r > Math.max(W, H) * 1.1) ripples.splice(i, 1); }
        raf = requestAnimationFrame(draw);
      };
      size(); draw();
      hero.addEventListener("pointermove", e => { const r = hero.getBoundingClientRect(); mx = e.clientX - r.left; my = e.clientY - r.top; if (rd) rd.textContent = `X ${(mx / r.width).toFixed(3)} Y ${(my / r.height).toFixed(3)}`; });
      hero.addEventListener("pointerleave", () => { mx = my = -1e4; });
      hero.addEventListener("pointerdown", e => { const r = hero.getBoundingClientRect(); ripples.push({x: e.clientX - r.left, y: e.clientY - r.top, r: 0}); });
      window.addEventListener("resize", size);
      new IntersectionObserver(es => { vis = es[0].isIntersecting; cancelAnimationFrame(raf); if (vis && !document.hidden) draw(); }).observe(hero);
      document.addEventListener("visibilitychange", () => { cancelAnimationFrame(raf); if (!document.hidden && vis) draw(); });
    }
  }

  /* ---- footer wordmark: STATAXIS drawn in dots; the dots swell, turn blue and part around the cursor, and a click sends a ring through the letters ---- */
  const wmBox = $(".vx-wordmark");
  if (wmBox) {
    const c = $("canvas", wmBox), tag = $(".vx-wm-tag", wmBox), x = c.getContext("2d");
    let W = 0, H = 0, dpr = 1, dots = [], mx = -1e4, my = -1e4, raf = 0, t = 0, vis = false, st = 8; const ripples = [];
    const build = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2); W = wmBox.clientWidth; H = wmBox.clientHeight;
      c.width = W * dpr; c.height = H * dpr; x.setTransform(dpr, 0, 0, dpr, 0, 0);
      st = Math.max(5, Math.round(W / 150));
      const off = document.createElement("canvas"), o = off.getContext("2d"); off.width = W; off.height = H;
      const face = '900 FSpx "Arial Black", Arial, Helvetica, sans-serif'; let fs = H * 1.05;
      o.font = face.replace("FS", fs); fs *= Math.min(1, (W * .985) / o.measureText("STATAXIS").width);
      o.font = face.replace("FS", fs); o.textBaseline = "alphabetic"; o.textAlign = "center"; o.fillStyle = "#fff"; o.fillText("STATAXIS", W / 2, H * .94);
      const px = o.getImageData(0, 0, W, H).data; dots = [];
      for (let j = st / 2; j < H; j += st) for (let i = st / 2; i < W; i += st) dots.push({x: i, y: j, on: px[((j | 0) * W + (i | 0)) * 4 + 3] > 128, ph: Math.random() * 6.283});
    };
    const draw = () => {
      x.clearRect(0, 0, W, H); t += .02; const rad = Math.max(90, W * .09);
      for (const d of dots) {
        let px = d.x, py = d.y, a = d.on ? .8 : .07, r = d.on ? st * .3 : st * .1, hot = false;
        if (d.on) a += Math.sin(t + d.ph + d.x * .01) * .1;
        const dx = px - mx, dy = py - my, dist = Math.hypot(dx, dy);
        if (dist < rad) { const f = 1 - dist / rad; px += dx / (dist || 1) * f * st * .9; py += dy / (dist || 1) * f * st * .9; a = Math.min(1, a + f * (d.on ? .5 : .9)); r += f * st * (d.on ? .45 : .6); hot = f > .25; }
        for (const rp of ripples) { const dr = Math.abs(Math.hypot(d.x - rp.x, d.y - rp.y) - rp.r); if (dr < 40) { const f = 1 - dr / 40; a = Math.min(1, a + f * .9); r += f * st * .4; hot = true; } }
        x.fillStyle = hot ? `rgba(29,161,255,${a})` : d.on ? `rgba(235,242,250,${a})` : `rgba(120,150,185,${a})`;
        x.beginPath(); x.arc(px, py, r, 0, 6.283); x.fill();
      }
      for (let i = ripples.length - 1; i >= 0; i--) { ripples[i].r += 10; if (ripples[i].r > W * 1.1) ripples.splice(i, 1); }
      raf = requestAnimationFrame(draw);
    };
    const start = () => { cancelAnimationFrame(raf); if (vis && !document.hidden) draw(); };
    build();
    if (reduce) { draw(); cancelAnimationFrame(raf); }
    else {
      wmBox.addEventListener("pointermove", e => {
        const r = wmBox.getBoundingClientRect(); mx = e.clientX - r.left; my = e.clientY - r.top;
        const code = ((Math.round(mx) * 31 + Math.round(my) * 17) % 65535).toString(16).toUpperCase().padStart(4, "0");
        tag.innerHTML = `<b>STX-${code}</b>signal ${Math.abs(Math.sin(mx * .013 + my * .021)).toFixed(2)}`; tag.style.opacity = 1;
        tag.style.transform = `translate(${Math.min(mx + 18, W - 130)}px,${Math.max(my - 44, 4)}px)`;
      });
      wmBox.addEventListener("pointerleave", () => { mx = my = -1e4; tag.style.opacity = 0; });
      wmBox.addEventListener("pointerdown", e => { const r = wmBox.getBoundingClientRect(); ripples.push({x: e.clientX - r.left, y: e.clientY - r.top, r: 0}); });
      new IntersectionObserver(es => { vis = es[0].isIntersecting; start(); }).observe(wmBox);
      document.addEventListener("visibilitychange", start);
    }
    let rz = 0; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { build(); if (reduce) draw(); }, 150); });
  }

  /* ---- method stage: eight scenes drawn in dots; the open step chooses the scene, the cursor parts the dots ---- */
  const acc = $(".vx-acc"), stage = $(".vx-stage");
  if (acc && stage) {
    const items = $$("li", acc), cv = $("canvas", stage), tags = $(".vx-stage-tags", stage), sid = $(".vx-stage-id", stage), x = cv.getContext("2d");
    const NAMES = items.map(li => $("b", li).textContent);
    const TAGS = [["Public YouTube data", "every few minutes", "live every minute"], ["Integrity checks", "Authenticity radar", "flags, not verdicts"], ["Weekly views", "Prime time", "STX · IFX Score"], ["Finding", "Evidence attached", "Confidence shown"],
      ["Media company", "Buyer · Campaign", "Creator · Audience"], ["Branded PDF", "Findings first", "Method last"], ["Plan the spend", "Choose the messenger", "Open the tool"], ["Reviewer decision", "Kept on record", "Shapes the next report"]];
    const POS = [[[56, 16], [10, 52], [52, 80]], [[58, 14], [8, 46], [54, 82]], [[10, 14], [56, 46], [20, 80]], [[8, 18], [54, 50], [14, 80]], [[56, 12], [6, 48], [52, 82]], [[10, 16], [54, 44], [18, 82]], [[8, 14], [52, 48], [12, 82]], [[54, 14], [6, 50], [48, 82]]];
    // each scene returns how bright a dot at (u, v) in 0..1 should be, and whether it is "hot" (blue) at time t
    const S = SCENES;
    let W = 0, H = 0, dpr = 1, cur = 0, raf = 0, t = 0, vis = false, mx = -1e4, my = -1e4, timer = 0, hover = false;
    const size = () => { dpr = Math.min(window.devicePixelRatio || 1, 2); W = stage.clientWidth; H = stage.clientHeight; cv.width = W * dpr; cv.height = H * dpr; x.setTransform(dpr, 0, 0, dpr, 0, 0); };
    const draw = () => {
      x.clearRect(0, 0, W, H); t += .016; const st = 13, cols = Math.ceil(W / st), rows = Math.ceil(H / st), f = S[cur];
      for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
        let px = (i + .5) * st, py = (j + .5) * st; const v = Math.max(0, Math.min(1.2, f(px / W, py / H, t)));
        let a = .06 + v * .82, r = .8 + v * 2.4; const dx = px - mx, dy = py - my, d = Math.hypot(dx, dy);
        if (d < 120) { const k = 1 - d / 120; px += dx / (d || 1) * k * 9; py += dy / (d || 1) * k * 9; a = Math.min(1, a + k * .6); r += k * 1.6; }
        x.fillStyle = v > .45 ? `rgba(29,161,255,${Math.min(1, a)})` : `rgba(150,172,200,${a})`; x.beginPath(); x.arc(px, py, r, 0, 6.283); x.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    const show = n => {
      cur = (n + items.length) % items.length; items.forEach((li, k) => li.classList.toggle("on", k === cur));
      sid.textContent = `STEP ${String(cur + 1).padStart(2, "0")} · ${NAMES[cur].toUpperCase()}`;
      tags.innerHTML = TAGS[cur].map((s, k) => `<span style="left:${POS[cur][k][0]}%;top:${POS[cur][k][1]}%;animation-delay:${k * .15 + .1}s">${esc(s)}</span>`).join("");
    };
    const tick = () => { clearTimeout(timer); if (reduce) return; timer = setTimeout(() => { if (!hover && vis) show(cur + 1); tick(); }, 4500); };
    const restart = () => { acc.classList.remove("run"); void acc.offsetWidth; };
    items.forEach((li, k) => { const go = () => { show(k); tick(); }; li.addEventListener("mouseenter", () => { hover = true; go(); }); li.addEventListener("click", go); li.addEventListener("focusin", go); li.tabIndex = 0; });
    acc.addEventListener("mouseleave", () => { hover = false; });
    size(); show(0);
    if (reduce) { draw(); cancelAnimationFrame(raf); }
    else {
      stage.addEventListener("pointermove", e => { const r = stage.getBoundingClientRect(); mx = e.clientX - r.left; my = e.clientY - r.top; });
      stage.addEventListener("pointerleave", () => { mx = my = -1e4; });
      new IntersectionObserver(es => { vis = es[0].isIntersecting; cancelAnimationFrame(raf); if (vis && !document.hidden) { draw(); tick(); } }).observe(stage);
      document.addEventListener("visibilitychange", () => { cancelAnimationFrame(raf); if (!document.hidden && vis) draw(); });
    }
    window.addEventListener("resize", () => { size(); if (reduce) draw(); });
  }

  /* ---- data rain: move the mouse and letters and numbers drop from its tail, then fade as they fall ---- */
  if (!reduce && window.matchMedia && window.matchMedia("(pointer:fine)").matches && !$(".vx-trail")) {
    const cv = document.createElement("canvas"); cv.className = "vx-trail"; cv.setAttribute("aria-hidden", "true"); document.body.appendChild(cv);
    const g = cv.getContext("2d"); let W = 0, H = 0, dpr = 1, raf = 0, lx = null, ly = null, carry = 0; const bits = [];
    const POOL = "0123456789STATAXIS0123456789ABCDEFGHJKMNPRVWXYZ%+▲▼·#";
    const size = () => { dpr = Math.min(window.devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight; cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0); };
    const spawn = (x, y) => {
      if (bits.length > 220) bits.shift();
      bits.push({x: x + (Math.random() - .5) * 10, y: y + (Math.random() - .5) * 8, vx: (Math.random() - .5) * .7, vy: .2 + Math.random() * .7, life: 0, max: 55 + Math.random() * 60,
        ch: POOL[(Math.random() * POOL.length) | 0], fs: 11 + Math.random() * 6, blue: Math.random() < .55});
    };
    const frame = () => {
      g.clearRect(0, 0, W, H);
      for (let i = bits.length - 1; i >= 0; i--) {
        const b = bits[i]; b.life++; b.vy += .085; b.x += b.vx; b.y += b.vy;
        if (b.life > b.max || b.y > H + 20) { bits.splice(i, 1); continue; }
        const k = b.life / b.max, a = (k < .12 ? k / .12 : 1 - Math.pow((k - .12) / .88, 1.4)) * .95;
        g.font = `500 ${b.fs}px ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace`;
        g.fillStyle = b.blue ? `rgba(29,161,255,${a})` : `rgba(226,236,248,${a * .85})`;
        if (k < .1) { g.shadowColor = "rgba(29,161,255,.9)"; g.shadowBlur = 8; } else g.shadowBlur = 0;
        g.fillText(b.ch, b.x, b.y);
      }
      g.shadowBlur = 0;
      raf = bits.length ? requestAnimationFrame(frame) : 0;
    };
    const wake = () => { if (!raf && !document.hidden) raf = requestAnimationFrame(frame); };
    window.addEventListener("pointermove", e => {
      if (e.pointerType && e.pointerType !== "mouse") return;
      const x = e.clientX, y = e.clientY;
      if (lx != null) {
        const dx = x - lx, dy = y - ly, d = Math.hypot(dx, dy); carry += d;
        // one glyph for every ~16px of travel, placed along the path just travelled: that is the tail
        while (carry >= 16) { carry -= 16; const t = Math.max(0, 1 - carry / (d || 1)); spawn(lx + dx * t, ly + dy * t); }
        wake();
      }
      lx = x; ly = y;
    }, {passive: true});
    document.addEventListener("pointerleave", () => { lx = ly = null; });
    document.addEventListener("visibilitychange", () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; lx = ly = null; } else wake(); });
    window.addEventListener("resize", size); size();
  }

  /* ---- platform pulse in the bar under the hero ---- */
  const bar = $("#vx-pulse");
  const pulse = async () => {
    if (!bar) return;
    try {
      const r = await fetch("/api/v1/public/pulse"); if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      const st = $("[data-k=state]", bar); st.textContent = d.status === "online" ? "● ONLINE" : "● WAITING FOR DATA"; st.className = d.status === "online" ? "on" : "wait";
      $("[data-k=channels]", bar).textContent = fmt(d.channels_measured); $("[data-k=live]", bar).textContent = fmt(d.channels_live_now);
      $("[data-k=obs]", bar).textContent = fmt(d.observations_stored);
      $("[data-k=age]", bar).textContent = d.last_measurement_minutes_ago == null ? "—" : d.last_measurement_minutes_ago < 1 ? "<1 MIN" : d.last_measurement_minutes_ago + " MIN";
    } catch (e) { const st = $("[data-k=state]", bar); if (st) { st.textContent = "● STATUS UNAVAILABLE"; st.className = "wait"; } }
  };
  pulse(); if (bar) setInterval(pulse, 60000);

  /* ---- package table: what each package includes, read from the platform ---- */
  const box = $("#tx-matrix");
  if (box) fetch("/api/v1/public/packages").then(r => r.ok ? r.json() : Promise.reject()).then(d => {
    const order = d.order, plans = d.plans;
    box.innerHTML = `<div class="vx-scroll"><table class="vx-matrix"><thead><tr><th>Tool</th>${plans.map(p => `<th>${esc(p.name.replace("SX ", ""))}<small>${p.max_seats ? p.max_seats + " seat" + (p.max_seats > 1 ? "s" : "") : "no seat limit"}</small></th>`).join("")}</tr></thead><tbody>${
      d.features.map(f => `<tr><td><strong>${esc(f.label)}</strong><small>${esc(f.description)}</small></td>${plans.map(p => `<td class="${order.indexOf(p.code) >= order.indexOf(f.min_plan) ? "y" : "n"}">${order.indexOf(p.code) >= order.indexOf(f.min_plan) ? "●" : "–"}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <p class="vx-sub" style="font-size:15px">${d.commercial_packages.length ? d.commercial_packages.map(p => esc(p.name) + (p.amount != null ? " · " + esc(p.currency) + " " + Number(p.amount).toLocaleString("en-IN") : "")).join("  |  ") : "Prices are given on application. Tell us who you are and we will recommend the package that fits."}</p>`;
  }).catch(() => { box.innerHTML = '<p class="vx-sub">The package list could not be loaded right now. <a href="/apply" style="color:#4db6ff">Apply for access</a> and we will send it.</p>'; });

  /* ---- drag-to-scroll shelves ---- */
  $$(".vx-shelf").forEach(s => {
    let down = false, sx = 0, sl = 0, moved = false;
    s.addEventListener("pointerdown", e => { down = true; moved = false; sx = e.clientX; sl = s.scrollLeft; });
    window.addEventListener("pointermove", e => { if (!down) return; const dx = e.clientX - sx; if (Math.abs(dx) > 4) { moved = true; s.classList.add("drag"); } s.scrollLeft = sl - dx; });
    window.addEventListener("pointerup", () => { down = false; s.classList.remove("drag"); });
    s.addEventListener("click", e => { if (moved) e.preventDefault(); }, true);
  });

  /* ---- depth and motion for every page: staggered reveals, count-up figures, header scenes, a timeline that draws itself ---- */
  $$(".sx-card,.sx-band,.sx-section-head,.sx-hero > *:not(.vx-scene),.vx-det li,.vx-dcol,.vx-path").forEach(el => el.classList.add("rv"));
  new Set($$(".rv").map(el => el.parentElement)).forEach(par => {
    const kids = [...par.children].filter(c => c.classList.contains("rv"));
    if (kids.length > 1) kids.forEach((c, i) => { if (!c.style.transitionDelay) c.style.transitionDelay = Math.min(i * 70, 420) + "ms"; });
  });
  const countUp = el => {
    const n = +el.dataset.count, t0 = performance.now(), dur = 1300;
    if (reduce) { el.textContent = fmt(n); return; }
    const tick = t => { const k = Math.min(1, (t - t0) / dur), v = Math.round(n * (1 - Math.pow(1 - k, 3))); el.textContent = fmt(v); if (k < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  };
  const watch = (sel, fn) => { const els = $$(sel); if (!els.length) return; if (!("IntersectionObserver" in window)) { els.forEach(fn); return; } const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { fn(e.target); io.unobserve(e.target); } }), {threshold: .3}); els.forEach(e => io.observe(e)); };
  watch("[data-count]", countUp);
  watch(".vx-tl, .vx-wbar", el => el.classList.add("go"));
  $$(".vx-scene[data-scene]").forEach(box => {
    const cv = $("canvas", box), fn = SCENES[+box.dataset.scene] || SCENES[0], x = cv.getContext("2d"), host = box.parentElement;
    let W = 0, H = 0, dpr = 1, raf = 0, t = Math.random() * 20, vis = false, mx = -1e4, my = -1e4;
    const size = () => { dpr = Math.min(window.devicePixelRatio || 1, 2); W = box.clientWidth; H = box.clientHeight; cv.width = W * dpr; cv.height = H * dpr; x.setTransform(dpr, 0, 0, dpr, 0, 0); };
    const draw = () => {
      x.clearRect(0, 0, W, H); t += .016; const st = 14, cols = Math.ceil(W / st), rows = Math.ceil(H / st);
      for (let i = 0; i < cols; i++) for (let k = 0; k < rows; k++) {
        let px = (i + .5) * st, py = (k + .5) * st; const v = Math.max(0, Math.min(1.2, fn(px / W, py / H, t))); let a = .05 + v * .8, r = .8 + v * 2.2;
        const dx = px - mx, dy = py - my, d = Math.hypot(dx, dy);
        if (d < 110) { const f = 1 - d / 110; px += dx / (d || 1) * f * 8; py += dy / (d || 1) * f * 8; a = Math.min(1, a + f * .6); r += f * 1.5; }
        x.fillStyle = v > .45 ? `rgba(29,161,255,${Math.min(1, a)})` : `rgba(150,172,200,${a})`; x.beginPath(); x.arc(px, py, r, 0, 6.283); x.fill();
      }
      raf = requestAnimationFrame(draw);
    };
    size();
    if (reduce) { draw(); cancelAnimationFrame(raf); return; }
    host.addEventListener("pointermove", e => { const r = box.getBoundingClientRect(); mx = e.clientX - r.left; my = e.clientY - r.top; });
    host.addEventListener("pointerleave", () => { mx = my = -1e4; });
    new IntersectionObserver(es => { vis = es[0].isIntersecting; cancelAnimationFrame(raf); if (vis && !document.hidden) draw(); }).observe(box);
    document.addEventListener("visibilitychange", () => { cancelAnimationFrame(raf); if (!document.hidden && vis) draw(); });
    window.addEventListener("resize", size);
  });

  /* ---- reveal on scroll ---- */
  const rv = $$(".rv");
  if (rv.length) {
    if (reduce || !("IntersectionObserver" in window)) rv.forEach(e => e.classList.add("in"));
    else { const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), {threshold: .12}); rv.forEach(e => io.observe(e)); }
  }

  /* ---- bars that breathe ---- */
  $$(".vx-bars").forEach(b => { if (!b.children.length) b.innerHTML = Array.from({length: 18}, (_, i) => `<i style="height:${30 + Math.round(Math.abs(Math.sin(i * .8)) * 60)}%;animation-delay:${(-i * .23).toFixed(2)}s"></i>`).join(""); });


  /* ---- mouse and hover effects: only with a real pointer, never when motion is unwanted ---- */
  const finePointer = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  if (!reduce) {
    const bar = document.createElement("div"); bar.id = "vx-progress"; document.body.appendChild(bar);
    const prog = () => { const h = document.documentElement.scrollHeight - innerHeight; bar.style.transform = `scaleX(${h > 0 ? Math.min(1, scrollY / h) : 0})`; };
    addEventListener("scroll", prog, {passive: true}); addEventListener("resize", prog); prog();
  }
  if (finePointer && !reduce) {
    const glow = document.createElement("div"), ring = document.createElement("div"); glow.id = "vx-glow"; ring.id = "vx-ring"; ring.setAttribute("aria-hidden", "true"); glow.setAttribute("aria-hidden", "true");
    document.body.append(glow, ring);
    let tx = -1e3, ty = -1e3, gx = tx, gy = ty, cx = tx, cy = ty, on = false;
    const loop = () => { gx += (tx - gx) * .08; gy += (ty - gy) * .08; cx += (tx - cx) * .28; cy += (ty - cy) * .28;
      glow.style.transform = `translate(${gx}px,${gy}px)`; ring.style.transform = `translate(${cx}px,${cy}px)`; requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    const PANELS = ".vx-prod,.vx-role,.vx-post,.vx-q,.vx-p,.vx-edge,.sx-card,.sx-band,.vx-partner";
    const TILT = ".vx-q,.vx-role,.vx-post,.sx-card";
    const BTNS = ".vx-btn,.sx-btn,.vx-menu a.cta";
    document.querySelectorAll(PANELS).forEach(p => p.classList.add("fx"));
    document.addEventListener("pointermove", e => {
      tx = e.clientX; ty = e.clientY; if (!on) { on = true; document.body.classList.add("fx-on"); }
      const t = e.target.closest ? e.target : e.target.parentElement; if (!t) return;
      ring.classList.toggle("big", !!t.closest("a,button,.vx-q,.vx-prod,.vx-post,.vx-role"));
      ring.classList.toggle("dot", !!t.closest("input,textarea,select,.vx-code"));
      const panel = t.closest(PANELS);
      if (panel) {
        const r = panel.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
        panel.style.setProperty("--mx", x + "px"); panel.style.setProperty("--my", y + "px");
        if (panel.matches(TILT)) { panel.style.setProperty("--ry", ((x / r.width - .5) * 7).toFixed(2) + "deg"); panel.style.setProperty("--rx", ((.5 - y / r.height) * 6).toFixed(2) + "deg"); }
      }
      const b = t.closest(BTNS);
      if (b) { const r = b.getBoundingClientRect(); b.style.transform = `translate(${((e.clientX - r.left) / r.width - .5) * 10}px,${((e.clientY - r.top) / r.height - .5) * 8}px)`; }
    }, {passive: true});
    document.addEventListener("pointerout", e => {
      const from = e.target.closest ? e.target : null; if (!from) return;
      const panel = from.closest(PANELS); if (panel && !panel.contains(e.relatedTarget)) { panel.style.setProperty("--rx", "0deg"); panel.style.setProperty("--ry", "0deg"); }
      const b = from.closest(BTNS); if (b && !b.contains(e.relatedTarget)) b.style.transform = "";
    });
    document.documentElement.addEventListener("pointerleave", () => { on = false; document.body.classList.remove("fx-on"); });
    document.addEventListener("pointerdown", () => { ring.classList.add("dot"); }); document.addEventListener("pointerup", () => { ring.classList.remove("dot"); });
  }

  /* ---- apply links keep the role and package the visitor picked ---- */
  const q = new URLSearchParams(location.search);
  const sel = $("#requested_plan");
  if (sel && q.get("plan")) { const o = [...sel.options].find(x => x.value === q.get("plan")); if (o) sel.value = o.value; }
  const purpose = $("#purpose_of_use");
  const ROLES = {media: "We are a media company and want to see our position against others.", buyer: "We plan and buy media and want to decide where to place spend.", politician: "We run public communication or a campaign and want to know where attention is.", influencer: "I publish videos and Shorts and want to know my IFX Score."};
  if (purpose && q.get("role") && ROLES[q.get("role")] && !purpose.value) purpose.value = ROLES[q.get("role")];
})();
