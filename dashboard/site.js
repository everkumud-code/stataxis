/* Shared parts of the public pages: the favicon, the navigation, the footer (with the legal notices), the mobile menu and the terms-and-cookies gate. The logo file is the original one. */
const favicon = document.createElement("link"); favicon.rel = "icon"; favicon.type = "image/svg+xml"; favicon.href = "/assets/stataxis-favicon.svg"; document.head.appendChild(favicon);
const MENU = [["/platform.html", "Platform"], ["/solutions.html", "Solutions"], ["/ifx.html", "IFX Score"], ["/stx.html", "STX Index"], ["/research.html", "Research"], ["/insights.html", "Insights"]];
const nav = '<header class="vx-nav"><div class="vx-nav-in"><a class="vx-logo" href="/" aria-label="StatAxis home"><img src="/assets/stataxis-logo.svg" alt="StatAxis — Stat the View. Axis the Viewpoint."></a><nav class="vx-menu" aria-label="Main">'
  + MENU.map(([h, l]) => `<a href="${h}">${l}</a>`).join("") + '<a class="cta" href="/apply.html">Get early access</a></nav><button class="vx-burger" aria-label="Open menu" aria-expanded="false">☰</button></div><div class="vx-drawer">'
  + MENU.map(([h, l]) => `<a href="${h}">${l}</a>`).join("") + '<a href="/stax9.html">STAX9</a><a href="/apply.html">Get early access</a><a href="/login.html">Sign in</a></div></header>';
const col = (h, items) => `<div class="vx-ft-col"><h5>${h}</h5>${items.map(([u, l]) => `<a href="${u}">${l}</a>`).join("")}</div>`;
const footer = '<footer class="vx-footer vx-ft"><div class="vx-ft-wrap"><div class="vx-ft-top"><div class="vx-ft-cta"><h2>Tell us who you<br>want to reach.</h2><a class="vx-btn" href="/apply.html">Start a conversation <span class="arr">→</span></a></div><div class="vx-ft-cols">'
  + col("Data", [["/platform.html", "Platform"], ["/solutions.html", "Solutions"], ["/ifx.html", "IFX Score"], ["/stx.html", "STX Index"]])
  + col("Company", [["/research.html", "Research"], ["/insights.html", "Insights"], ["/stax9.html", "STAX9"], ["mailto:stax9@stataxis.org", "Contact"]])
  + col("Access", [["/login.html", "Sign in"], ["/apply.html", "Apply"], ["/privacy.html", "Privacy Policy"], ["/terms.html", "Terms & Conditions"]])
  + '</div></div><div class="vx-ft-legal"><div><strong>StatAxis Technology Lab</strong><br>Lab-grown website, developed in the State-of-the-Art Technology Data Lab of StatAxis.<br>Built indigenously with our own systems, processes and technology.</div>'
  + '<div class="sx-legal"><strong>Data, Name & Intellectual Property</strong><br>Prior written permission from StatAxis is required before using or mentioning the StatAxis name, logo, data, content or STX Index in any external publication, product, service, campaign or communication.<br>Without our prior written consent, do not use our name, logo, data or STX Index.<br>No production credit is assigned to any third party.<br>STX Index and other scores are generated independently by StatAxis. They are not sourced from, provided by or endorsed by YouTube.</div></div>'
  + '<div class="vx-ft-bar"><span>© 2026 STATAXIS · DIGITAL MEDIA MARKET INTELLIGENCE &amp; DATA SERVICES</span><a href="#" class="vx-top" onclick="window.scrollTo({top:0,behavior:\'smooth\'});return false">BACK TO TOP ↑</a></div></div>'
  + '<div class="vx-wordmark" aria-hidden="true"><canvas></canvas><div class="vx-wm-tag"></div></div></footer>';
document.getElementById("nav").innerHTML = nav; document.getElementById("footer").innerHTML = footer;
const toggle = document.querySelector(".vx-burger"), drawer = document.querySelector(".vx-drawer");
if (toggle && drawer) toggle.addEventListener("click", () => { const open = drawer.classList.toggle("open"); toggle.setAttribute("aria-expanded", String(open)); toggle.textContent = open ? "×" : "☰"; });
const path = location.pathname.replace(/\/$/, "") || "/";
document.querySelectorAll(".vx-menu a").forEach(a => { if (a.getAttribute("href") === path) a.style.color = "#fff"; });

const SX_COOKIE_KEY = "stataxis_cookie_consent_v1", SX_TERMS_KEY = "stataxis_terms_consent_v1";
(function () {
  const style = document.createElement("style");
  style.textContent = ".sx-consent{position:fixed;inset:0;z-index:10000;background:rgba(3,5,9,.95);backdrop-filter:blur(14px);display:flex;align-items:center;justify-content:center;padding:22px}.sx-consent-box{width:min(720px,100%);background:#0d121a;border:1px solid #26324a;border-radius:16px;padding:32px;box-shadow:0 28px 80px rgba(0,0,0,.65);color:#eef2f7;font-family:var(--sans,system-ui)}.sx-consent-kicker{color:#1da1ff;font-family:var(--mono,monospace);font-size:11px;letter-spacing:.2em}.sx-consent h2{font-size:34px;letter-spacing:-.035em;margin:10px 0 10px}.sx-consent p{color:#9aa7b8;line-height:1.65}.sx-consent-section{border:1px solid #1a2230;background:#080c12;border-radius:12px;padding:16px;margin:14px 0}.sx-consent-section strong{color:#eef2f7}.sx-consent-check{display:flex;gap:10px;align-items:flex-start;color:#d3dbe7;font-size:13.5px;margin:15px 0}.sx-consent-check input{accent-color:#1da1ff;margin-top:3px}.sx-consent a{color:#4db6ff}.sx-consent-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.sx-consent button{border:1px solid #26324a;background:#101826;color:#eef2f7;border-radius:7px;padding:12px 18px;font-weight:600;cursor:pointer;font-family:inherit}.sx-consent button:hover{border-color:#1da1ff}.sx-consent button.primary{background:#1da1ff;border-color:#1da1ff;color:#001018}.sx-consent button.primary:disabled{opacity:.4;cursor:not-allowed}.sx-consent button.primary:not(:disabled):hover{background:#4db6ff}.sx-consent-note{font-size:12px;color:#6c7b8d}.sx-consent-deny{font-size:12px;color:#ff7180;margin-top:10px}";
  document.head.appendChild(style);
  if (location.pathname.endsWith("/terms.html") || location.pathname.endsWith("terms.html") || location.pathname.endsWith("/privacy.html") || location.pathname.endsWith("privacy.html")) return;
  if (localStorage.getItem(SX_COOKIE_KEY) && localStorage.getItem(SX_TERMS_KEY)) return;
  document.documentElement.style.overflow = "hidden";
  const gate = document.createElement("div"); gate.className = "sx-consent";
  gate.innerHTML = '<div class="sx-consent-box"><div class="sx-consent-kicker">WELCOME TO STATAXIS</div><h2>Before you enter</h2><p>We use essential cookies to remember consent and basic website preferences. Before continuing, please review and agree to the StatAxis Terms & Conditions.</p><div class="sx-consent-section"><strong>Cookie consent</strong><p class="sx-consent-note">StatAxis currently uses essential consent/preference storage. No non-essential tracking is required to enter this website.</p><div class="sx-consent-actions"><button id="sxEssential">Continue with essential cookies</button><button id="sxAll" class="primary">Accept cookies</button></div></div><div class="sx-consent-section"><strong>Terms & Conditions</strong><p class="sx-consent-note">By entering the website, you acknowledge that website content, data, analysis, branding and the STX Index are protected and subject to StatAxis terms.</p><label class="sx-consent-check"><input id="sxTerms" type="checkbox"> <span>I have read and agree to the <a href="/terms.html" target="_blank" rel="noopener">StatAxis Terms & Conditions</a> and consent to proceed.</span></label></div><button id="sxEnter" class="primary" disabled>Agree & Enter Website</button><div id="sxDeny" class="sx-consent-deny"></div></div>';
  document.body.appendChild(gate);
  let cookieOk = !!localStorage.getItem(SX_COOKIE_KEY);
  const terms = document.getElementById("sxTerms"), enter = document.getElementById("sxEnter"), deny = document.getElementById("sxDeny");
  const update = () => { enter.disabled = !(cookieOk && terms.checked); };
  document.getElementById("sxEssential").onclick = () => { localStorage.setItem(SX_COOKIE_KEY, "essential"); cookieOk = true; deny.textContent = "Essential cookie consent recorded."; update(); };
  document.getElementById("sxAll").onclick = () => { localStorage.setItem(SX_COOKIE_KEY, "accepted"); cookieOk = true; deny.textContent = "Cookie consent recorded."; update(); };
  terms.onchange = update;
  enter.onclick = () => { if (!cookieOk || !terms.checked) return; localStorage.setItem(SX_TERMS_KEY, "accepted"); gate.remove(); document.documentElement.style.overflow = ""; };
})();


{ const h = document.createElement("script"); h.src = "/stax9.js"; document.body.appendChild(h); }
