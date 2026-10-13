/* Copy guard: a deterrent for casual copying of the site's text and numbers.
   It stops selecting, copying, cutting, dragging, saving, printing and the usual view-source and developer-tool shortcuts on the page, and the right-click menu.
   It leaves form fields alone (a person must be able to type and paste into a form), anything marked class="allow-copy" (a temporary password, a verification code) and e-mail links.
   Administrators are not restricted. Be clear about what this is: a browser can always be made to show what it received, so this keeps honest visitors from copying by accident and slows the rest.
   The real protection is that nothing private is ever sent to the browser: every private figure sits behind a login and a package check on the server, and the downloadable reports are not machine-readable. */
(() => {
  try { const a = JSON.parse(sessionStorage.getItem("stataxis_account") || localStorage.getItem("stataxis_account") || "null"); if (a && a.is_admin) return; } catch (e) { /* no stored account */ }
  const css = document.createElement("style");
  css.textContent = "html,body{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}input,textarea,select,[contenteditable=true],.allow-copy,.allow-copy *,a[href^='mailto:']{-webkit-user-select:text;user-select:text}img,svg,canvas,a{-webkit-user-drag:none}@media print{body{display:none!important}}";
  (document.head || document.documentElement).appendChild(css);
  const allowed = t => !!(t && t.closest && t.closest("input,textarea,select,[contenteditable=true],.allow-copy,a[href^='mailto:']"));
  const stop = e => { if (!allowed(e.target)) e.preventDefault(); };
  ["contextmenu", "copy", "cut", "dragstart", "selectstart"].forEach(ev => document.addEventListener(ev, stop, true));
  document.addEventListener("keydown", e => {
    const mod = e.ctrlKey || e.metaKey, k = (e.key || "").toLowerCase();
    if (e.key === "F12" || (mod && e.shiftKey && ["i", "j", "c", "k"].includes(k)) || (mod && ["u", "s", "p"].includes(k))) { e.preventDefault(); return; }
    if (mod && ["c", "x", "a"].includes(k) && !allowed(e.target)) e.preventDefault();
  }, true);
})();
