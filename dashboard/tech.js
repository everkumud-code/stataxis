/* The live parts of the public pages: a short start-up counter, the dot field that answers the cursor, the platform pulse, the package table, drag-to-scroll shelves,
   reveal on scroll and the apply-form prefill. Nothing here shows a figure that did not come from the platform: the pulse is read from /api/v1/public/pulse and the package
   table from /api/v1/public/packages; if either cannot be reached the page says so instead of showing numbers. */
(() => {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const fmt = n => isFinite(n) ? Number(n).toLocaleString("en-IN") : "—";

  /* ---- start-up counter: once a session, only on the home page, never for those who want less motion ---- */
  const home = location.pathname === "/" || location.pathname.endsWith("/index.html");
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
      const x = c.getContext("2d"); let W = 0, H = 0, dpr = 1, mx = -1e4, my = -1e4, raf = 0, t = 0, vis = true;
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
          x.fillStyle = d < 150 ? `rgba(29,161,255,${a})` : `rgba(165,185,210,${a})`;
          x.beginPath(); x.arc(px, py, r, 0, 6.283); x.fill();
        }
        raf = requestAnimationFrame(draw);
      };
      size(); draw();
      hero.addEventListener("pointermove", e => { const r = hero.getBoundingClientRect(); mx = e.clientX - r.left; my = e.clientY - r.top; if (rd) rd.textContent = `X ${(mx / r.width).toFixed(3)} Y ${(my / r.height).toFixed(3)}`; });
      hero.addEventListener("pointerleave", () => { mx = my = -1e4; });
      window.addEventListener("resize", size);
      new IntersectionObserver(es => { vis = es[0].isIntersecting; cancelAnimationFrame(raf); if (vis && !document.hidden) draw(); }).observe(hero);
      document.addEventListener("visibilitychange", () => { cancelAnimationFrame(raf); if (!document.hidden && vis) draw(); });
    }
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
  }).catch(() => { box.innerHTML = '<p class="vx-sub">The package list could not be loaded right now. <a href="/apply.html" style="color:#4db6ff">Apply for access</a> and we will send it.</p>'; });

  /* ---- drag-to-scroll shelves ---- */
  $$(".vx-shelf").forEach(s => {
    let down = false, sx = 0, sl = 0, moved = false;
    s.addEventListener("pointerdown", e => { down = true; moved = false; sx = e.clientX; sl = s.scrollLeft; });
    window.addEventListener("pointermove", e => { if (!down) return; const dx = e.clientX - sx; if (Math.abs(dx) > 4) { moved = true; s.classList.add("drag"); } s.scrollLeft = sl - dx; });
    window.addEventListener("pointerup", () => { down = false; s.classList.remove("drag"); });
    s.addEventListener("click", e => { if (moved) e.preventDefault(); }, true);
  });

  /* ---- reveal on scroll ---- */
  const rv = $$(".rv");
  if (rv.length) {
    if (reduce || !("IntersectionObserver" in window)) rv.forEach(e => e.classList.add("in"));
    else { const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), {threshold: .12}); rv.forEach(e => io.observe(e)); }
  }

  /* ---- bars that breathe ---- */
  $$(".vx-bars").forEach(b => { if (!b.children.length) b.innerHTML = Array.from({length: 18}, (_, i) => `<i style="height:${30 + Math.round(Math.abs(Math.sin(i * .8)) * 60)}%;animation-delay:${(-i * .23).toFixed(2)}s"></i>`).join(""); });

  /* ---- apply links keep the role and package the visitor picked ---- */
  const q = new URLSearchParams(location.search);
  const sel = $("#requested_plan");
  if (sel && q.get("plan")) { const o = [...sel.options].find(x => x.value === q.get("plan")); if (o) sel.value = o.value; }
  const purpose = $("#purpose_of_use");
  const ROLES = {media: "We are a media company and want to see our position against others.", buyer: "We plan and buy media and want to decide where to place spend.", politician: "We run public communication or a campaign and want to know where attention is.", influencer: "I publish videos and Shorts and want to know my IFX Score."};
  if (purpose && q.get("role") && ROLES[q.get("role")] && !purpose.value) purpose.value = ROLES[q.get("role")];
})();
