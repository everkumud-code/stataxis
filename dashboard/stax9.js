/* STAX9, the helper. A small animated guide on the public pages: a round avatar in the corner that opens a panel with the STAX9 artwork, a line about the page you are on and the shortest ways to where you may want to go.
   The artwork is the owner's own (assets/stax9/); nothing is drawn or invented here. Nothing collects data or sends anything; it only links to pages. */
(() => {
  if (window.__stax9 || /\/(workspace|admin|login|stax9)(\.html)?$/.test(location.pathname)) return; window.__stax9 = 1;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const A = "/assets/stax9/";
  const path = location.pathname.replace(/\/$/, "").replace(/\.html$/, "") || "/";
  const TIPS = {
    "/": ["Welcome. I am STAX9. Tell me who you are and I will point you to the right place.", [["I buy media", "/solutions"], ["I publish or report", "/ifx"], ["I run a newsroom", "/platform"], ["Apply for access", "/apply"]]],
    "/platform": ["Four views, eight steps and one rule: every number shows its working. The FAQ at the bottom answers the common questions.", [["How STX is scored", "/stx"], ["See the IFX Score", "/ifx"], ["Apply", "/apply"]]],
    "/solutions": ["Name the decision and the audience. We write it back as a question the data can answer.", [["Platform tour", "/platform"], ["Apply as a media buyer", "/apply?role=buyer&plan=sx_analyst"]]],
    "/ifx": ["Three pillars, one score and a confidence beside it. Watch the weights fill as you scroll.", [["The method, in words", "/blog/ifx-score-explained"], ["Join the programme", "/apply?role=influencer&plan=sx_intelligence"]]],
    "/stx": ["Seven parts make the STX Index. Read the confidence before you quote a score.", [["Meet the IFX Score", "/ifx"], ["Platform tour", "/platform"]]],
    "/research": ["Behaviour tells you what. Answers tell you why. Bring me the question.", [["Read the Insights", "/insights"], ["Start a brief", "mailto:stax9@stataxis.org?subject=Research%20brief"]]],
    "/insights": ["Pick a path by what you do. Each article explains one part of how we measure.", [["Why the average beats the peak", "/blog/average-beats-peak"], ["What a flat line says", "/blog/what-a-flat-line-says"]]],
    "/apply": ["Tell us who you are and what you need. An administrator reviews every request.", [["What each package gives", "/platform#packages"], ["Back to home", "/"]]],
    "/demo": ["This is a demonstration. For live data, apply for access.", [["Apply for access", "/apply"], ["Platform tour", "/platform"]]],
  };
  const tip = TIPS[path] || (path.startsWith("/blog/") ? ["Liked this one? There are more in the lab.", [["All insights", "/insights"], ["The IFX Score", "/ifx"]]] : ["I am STAX9. Ask me where to go.", [["Home", "/"], ["Platform", "/platform"], ["Apply", "/apply"]]]);
  const esc = v => String(v).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const root = document.createElement("div"); root.className = "s9";
  root.innerHTML =
    '<div class="s9-panel" role="dialog" aria-label="STAX9, the StatAxis helper" hidden><button class="s9-x" type="button" aria-label="Close">×</button>' +
    '<div class="s9-fig"><span class="s9-shadow"></span><div class="s9-stage"><img src="' + A + 'stax9-figure.webp" alt="STAX9, the StatAxis explorer: a winged insect-like figure in black and white armour with a glowing blue 9 on the chest, holding the Axis staff" width="720" height="1080" loading="lazy">' +
    '<i class="s9-g s9-eyeL"></i><i class="s9-g s9-eyeR"></i><i class="s9-g s9-nine"></i><i class="s9-g s9-hub"></i><i class="s9-g s9-tip"></i><i class="s9-sheen"></i></div></div>' +
    '<div class="s9-body"><b>STAX9</b><em>See the stat. Shift the axis.</em><div class="s9-traits"><span>Curious</span><span>Precise</span><span>Fearless</span><span>Objective</span></div><p class="s9-say"></p><div class="s9-links"></div><small>“Trust cannot be demanded. It must be engineered.”</small></div></div>' +
    '<button class="s9-btn" type="button" aria-label="Ask STAX9 for help" aria-expanded="false"><span class="s9-av"><img src="' + A + 'stax9-head.webp" alt="" width="96" height="96"></span><span class="s9-hi">Ask STAX9</span><i class="s9-dot"></i></button>';
  document.body.appendChild(root);
  const panel = root.querySelector(".s9-panel"), btn = root.querySelector(".s9-btn"), say = root.querySelector(".s9-say"), links = root.querySelector(".s9-links"), stage = root.querySelector(".s9-stage");
  links.innerHTML = tip[1].map(([l, h]) => `<a href="${esc(h)}">${esc(l)} <i>→</i></a>`).join("");
  const type = text => { say.textContent = ""; if (reduce) { say.textContent = text; return; } let i = 0; const go = () => { say.textContent = text.slice(0, ++i); if (i < text.length) setTimeout(go, 16); }; go(); };
  let opened = false;
  const open = v => { opened = v; panel.hidden = !v; root.classList.toggle("open", v); btn.setAttribute("aria-expanded", String(v)); if (v) type(tip[0]); try { sessionStorage.setItem("s9_seen", "1"); } catch (e) { /* storage blocked */ } };
  // the large picture is fetched only when someone shows interest, so it costs nothing for everyone else
  let warm = false; const preload = () => { if (!warm) { warm = true; new Image().src = A + "stax9-figure.webp"; } };
  ["pointerenter", "focus", "touchstart"].forEach(ev => btn.addEventListener(ev, preload, {passive: true}));
  btn.addEventListener("click", () => open(!opened)); root.querySelector(".s9-x").addEventListener("click", () => open(false));
  document.addEventListener("keydown", e => { if (e.key === "Escape" && opened) open(false); });
  // the figure leans toward the pointer
  if (!reduce) window.addEventListener("pointermove", e => {
    if (!opened) return; const r = stage.getBoundingClientRect(); if (!r.width) return;
    const dx = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / 500)), dy = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / 500));
    stage.style.transform = `perspective(900px) rotateY(${dx * 7}deg) rotateX(${-dy * 5}deg)`;
  }, {passive: true});
  // a friendly nudge once per visit, never twice
  let seen = false; try { seen = sessionStorage.getItem("s9_seen") === "1"; } catch (e) { /* storage blocked */ }
  if (!seen && !reduce) setTimeout(() => { if (!opened) { root.classList.add("nudge"); setTimeout(() => root.classList.remove("nudge"), 5200); } }, 6000);
})();
