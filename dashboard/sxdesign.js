/* The StatAxis look for every picture and every PDF page that leaves the workspace. One design, taken from design/reference.png:
   a near-black background with a faint dot grid and a thin arc, white heavy condensed capitals for the headline, electric blue for numbers and accents,
   a blue italic serif for the line we want remembered, a spaced monospace label with a blue dot, and the blue-and-gold logo. Nothing else is used. */
"use strict";
(() => {
  const C = {bg: "#010509", panel: "#050d17", blue: "#0b8ded", blueLight: "#5fb4ff", blueDeep: "#0b52b1", white: "#fdfdfd", text: "#ccd5dd", mute: "#9ba0a6", line: "#255073", gold: "#edc461"};
  const F = {
    head: '"Anton","Bebas Neue","League Gothic","Impact","Haettenschweiler","Arial Narrow Bold",sans-serif',
    body: '"Inter Tight","Inter","Segoe UI Variable Display","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif',
    serif: '"Instrument Serif","Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif',
    mono: '"JetBrains Mono","SFMono-Regular",Menlo,Consolas,"Courier New",monospace',
  };
  const SERIES = [C.blue, C.white, C.blueLight, C.mute, C.blueDeep, C.gold, "#2f6fd0", "#bfe0ff"];   /* the colours a chart may use: blues, white, grey and the logo's gold */
  let logoP = null;
  const logo = () => logoP || (logoP = new Promise(res => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = "/assets/stataxis-logo-dark.svg"; }));
  const LOGO_RATIO = 200 / 760;
  const wrap = (x, text, width) => {
    const out = []; let line = "";
    for (const word of String(text).split(" ")) { const t = line ? line + " " + word : word; if (x.measureText(t).width > width && line) { out.push(line); line = word; } else line = t; }
    if (line) out.push(line);
    return out;
  };
  /* the black page, with a faint dot grid, a soft blue glow at the top left and a thin arc with one bright dot at the right edge */
  function background(x, W, H) {
    x.fillStyle = C.bg; x.fillRect(0, 0, W, H);
    const g = x.createRadialGradient(W * 0.1, 0, 0, W * 0.1, 0, Math.max(W, H) * 0.9); g.addColorStop(0, "rgba(11,82,177,0.22)"); g.addColorStop(1, "rgba(1,5,9,0)"); x.fillStyle = g; x.fillRect(0, 0, W, H);
    x.fillStyle = "rgba(70,120,210,0.13)"; for (let yy = 26; yy < H; yy += 28) for (let xx = 26; xx < W; xx += 28) x.fillRect(xx, yy, 2, 2);
    x.save(); x.strokeStyle = "rgba(11,141,237,0.30)"; x.lineWidth = 1.6; const r = H * 0.5, cx = W + r * 0.9, cy = H * 0.3;   /* a big circle, only its left edge shows at the right of the page */
    x.beginPath(); x.arc(cx, cy, r, 0, Math.PI * 2); x.stroke(); x.beginPath(); x.arc(cx, cy, r * 1.12, 0, Math.PI * 2); x.stroke();
    x.fillStyle = C.blue; x.shadowColor = C.blue; x.shadowBlur = 14; x.beginPath(); x.arc(cx - r * Math.cos(0.3), cy + r * Math.sin(0.3), 5, 0, Math.PI * 2); x.fill(); x.restore();
  }
  /* "FIG. 00 - SYMPTOMS": a blue dot and a spaced monospace label */
  function eyebrow(x, text, px, py, size = 22) {
    x.fillStyle = C.blue; x.beginPath(); x.arc(px + 10, py - size * 0.35, 10, 0, Math.PI * 2); x.fill();
    x.fillStyle = C.mute; x.font = `500 ${size}px ${F.mono}`; if ("letterSpacing" in x) x.letterSpacing = "4px"; x.fillText(String(text).toUpperCase(), px + 34, py); if ("letterSpacing" in x) x.letterSpacing = "0px";
  }
  /* the headline: white heavy condensed capitals, as many lines as it needs (at most maxLines); returns the y under the last line */
  function headline(x, text, px, py, maxW, size = 92, maxLines = 3) {
    x.fillStyle = C.white; x.font = `400 ${size}px ${F.head}`; if ("letterSpacing" in x) x.letterSpacing = "-1px";
    const lines = wrap(x, String(text).toUpperCase(), maxW).slice(0, maxLines); lines.forEach((t, i) => x.fillText(t, px, py + i * size * 0.98));
    if ("letterSpacing" in x) x.letterSpacing = "0px";
    return py + lines.length * size * 0.98;
  }
  const headLines = (x, text, maxW, size, maxLines) => { x.font = `400 ${size}px ${F.head}`; return wrap(x, String(text).toUpperCase(), maxW).slice(0, maxLines).length; };
  /* a big blue number such as 01, 02 */
  function number(x, text, px, py, size = 64) { x.fillStyle = C.blue; x.font = `400 ${size}px ${F.head}`; x.fillText(text, px, py); }
  /* the line to remember: blue italic serif */
  function serif(x, text, px, py, size = 54) { x.fillStyle = C.blue; x.font = `italic 400 ${size}px ${F.serif}`; x.fillText(text, px, py); }
  /* the footer every picture ends with: a thin rule, up to three small lines, the handle and site, and the logo at the right (170 px) */
  async function footer(x, W, H, P, lines = []) {
    x.fillStyle = C.line; x.fillRect(P, H - 176, W - 2 * P, 2);
    x.textAlign = "left"; x.fillStyle = C.text; x.font = `500 22px ${F.body}`;
    lines.slice(0, 3).forEach((t, i) => x.fillText(t, P, H - 136 + i * 30));
    const lead = "stataxis.org  ·  x.com/stataxis  —  Stat the View. ";
    x.font = `500 22px ${F.body}`; x.fillStyle = C.text; x.fillText(lead, P, H - 30);
    const w = x.measureText(lead).width; x.fillStyle = C.blue; x.font = `italic 400 25px ${F.serif}`; x.fillText("Axis the Viewpoint.", P + w, H - 30);
    const lg = await logo(), lw = 250;
    if (lg) x.drawImage(lg, W - P - lw, H - 160, lw, lw * LOGO_RATIO);
    else { x.fillStyle = C.blue; x.font = `400 40px ${F.head}`; x.textAlign = "right"; x.fillText("STATAXIS", W - P, H - 70); x.textAlign = "left"; }
  }
  /* the logo, faint and tilted, repeated: a crop or a screenshot still carries it */
  async function watermark(x, W, H, alpha = 0.05) {
    const lg = await logo(); if (!lg) return;
    x.save(); x.globalAlpha = alpha; x.translate(W / 2, H / 2); x.rotate(-0.55);
    for (let r = -10; r <= 10; r++) for (let k = -4; k <= 4; k++) x.drawImage(lg, k * 440 + (r % 2) * 220 - 150, r * 150 - 38, 300, 300 * LOGO_RATIO);
    x.restore();
  }
  window.SXD = {C, F, SERIES, logo, wrap, background, eyebrow, headline, headLines, number, serif, footer, watermark, LOGO_RATIO};
})();
