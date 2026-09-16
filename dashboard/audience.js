(() => {
  const $ = (s) => document.querySelector(s);
  const token = () => localStorage.getItem("stataxis_access_token") || "";
  const fmt = (v) => Number(v || 0).toLocaleString("en-IN");
  const clock = (v) => v ? new Date(v).toLocaleTimeString("en-IN", { hour12: false }) : "—";
  const request = async (url, options = {}) => {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (token()) headers.Authorization = `Bearer ${token()}`;
    const response = await fetch(url, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
    return data;
  };
  const localInput = (date) => {
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
  };
  const setDefaults = () => {
    const end = new Date();
    const start = new Date(end.getTime() - 3600000);
    if ($("#aud-start") && !$("#aud-start").value) $("#aud-start").value = localInput(start);
    if ($("#aud-end") && !$("#aud-end").value) $("#aud-end").value = localInput(end);
  };
  const ensureExportButton = () => {
    const load = $("#aud-load-window");
    if (!load || $("#aud-export-excel")) return;
    const button = document.createElement("button");
    button.id = "aud-export-excel";
    button.type = "button";
    button.textContent = "Export Excel";
    button.className = load.className;
    load.parentElement?.appendChild(button);
  };
  const renderGroups = (payload) => {
    const root = $("#aud-language-groups");
    if (!root) return;
    const names = ["Hindi", "English", "Regional", "Unknown"];
    const groups = payload.languages || {};
    const max = Math.max(...names.map((n) => Number(groups[n]?.peak_concurrent || 0)), 1);
    root.innerHTML = names.map((name) => {
      const item = groups[name] || {};
      const width = Math.max(2, Math.round((Number(item.peak_concurrent || 0) / max) * 100));
      return `<div class="aud-group"><div class="aud-group-head"><strong>${name}</strong><span>${item.channel_count || 0} channels</span></div><div class="aud-bar"><i style="width:${width}%"></i></div><div class="aud-group-stats"><span><b>${fmt(item.current_concurrent)}</b> current</span><span><b>${fmt(item.peak_concurrent)}</b> peak</span><span><b>${fmt(item.average_concurrent)}</b> avg</span></div></div>`;
    }).join("");
  };
  const renderTimeline = (payload) => {
    const points = payload.timeline || [];
    const body = $("#aud-timeline-body");
    const chart = $("#aud-timeline-chart");
    if (body) body.innerHTML = points.slice(-180).reverse().map((p) => `<tr><td>${clock(p.observed_at)}</td><td>${fmt(p.Hindi)}</td><td>${fmt(p.English)}</td><td>${fmt(p.Regional)}</td><td>${fmt(p.total_concurrent)}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No observed live samples in this interval.</td></tr>`;
    if (chart) {
      const values = points.map((p) => Number(p.total_concurrent || 0));
      const max = Math.max(...values, 1);
      chart.innerHTML = points.map((p) => `<i style="height:${Math.max(2, Math.round((Number(p.total_concurrent || 0) / max) * 100))}%" title="${clock(p.observed_at)} · ${fmt(p.total_concurrent)}"></i>`).join("");
    }
    const overall = payload.overall || {};
    [["#aud-peak", overall.peak_concurrent], ["#aud-current", overall.current_concurrent], ["#aud-seconds", overall.observed_seconds], ["#aud-channels", overall.channel_count]].forEach(([s, v]) => { if ($(s)) $(s).textContent = fmt(v); });
    if ($("#aud-resolution")) $("#aud-resolution").textContent = `${payload.sample_resolution || "Observed samples"} · interpolation ${payload.interpolation ? "ON" : "OFF"}`;
  };
  const renderChannels = (payload) => {
    const body = $("#aud-channel-body");
    if (!body) return;
    const channels = [...(payload.channels || [])].sort((a, b) => Number(b.current_concurrent || 0) - Number(a.current_concurrent || 0));
    body.innerHTML = channels.map((c) => `<tr><td><strong>${c.name}</strong></td><td>${c.language_group}</td><td>${c.language || "unknown"}</td><td>${fmt(c.current_concurrent)}</td><td>${fmt(c.peak_concurrent)}</td><td>${clock(c.observed_at)}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">No channel observations in this window.</td></tr>`;
  };
  const loadWindow = async () => {
    const start = $("#aud-start")?.value;
    const end = $("#aud-end")?.value;
    if (!start || !end) return;
    const status = $("#aud-status");
    if (status) status.textContent = "Reading observed audience data…";
    try {
      const params = new URLSearchParams({ start: new Date(start).toISOString(), end: new Date(end).toISOString() });
      const payload = await request(`/api/v1/audience/live?${params}`);
      renderGroups(payload); renderTimeline(payload); renderChannels(payload);
      if (status) status.textContent = "Window loaded · observed data only";
    } catch (error) { if (status) status.textContent = error.message; }
  };
  const exportWindow = async () => {
    const start = $("#aud-start")?.value;
    const end = $("#aud-end")?.value;
    const status = $("#aud-status");
    if (!start || !end) { if (status) status.textContent = "Select a start and end time first."; return; }
    if (!token()) { if (status) status.textContent = "Sign in to export Excel data."; return; }
    if (status) status.textContent = "Preparing Excel export…";
    try {
      const params = new URLSearchParams({ start: new Date(start).toISOString(), end: new Date(end).toISOString() });
      const response = await fetch(`/api/v1/audience/live/export?${params}`, { headers: { Authorization: `Bearer ${token()}` } });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `${response.status} ${response.statusText}`);
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = "stataxis-live-audience.xlsx";
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(href);
      if (status) status.textContent = "Excel exported · observed data only";
    } catch (error) { if (status) status.textContent = error.message; }
  };
  let timer = null;
  const stop = () => {
    if (timer) clearInterval(timer);
    timer = null;
    if ($("#aud-start-monitor")) $("#aud-start-monitor").textContent = "Start Precision Monitor";
    if ($("#aud-stop-monitor")) $("#aud-stop-monitor").disabled = true;
  };
  const sample = async () => {
    const url = $("#aud-url")?.value.trim();
    const name = $("#aud-name")?.value.trim();
    if (!url || !name) { if ($("#aud-status")) $("#aud-status").textContent = "Enter the YouTube Live URL and display name first."; return; }
    try {
      const result = await request("/api/v1/evaluate/youtube/live-sample", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, display_name: name }) });
      if ($("#aud-status")) $("#aud-status").textContent = `${result.display_name} · ${fmt(result.concurrent_viewers)} concurrent · ${clock(result.observed_at)} · ${result.language_group}`;
      await loadWindow();
    } catch (error) { if ($("#aud-status")) $("#aud-status").textContent = error.message; stop(); }
  };
  const start = () => {
    stop();
    const seconds = Math.max(1, Number($("#aud-interval")?.value || 5));
    sample();
    timer = setInterval(sample, seconds * 1000);
    if ($("#aud-start-monitor")) $("#aud-start-monitor").textContent = `Monitoring every ${seconds}s`;
    if ($("#aud-stop-monitor")) $("#aud-stop-monitor").disabled = false;
  };
  document.addEventListener("DOMContentLoaded", () => {
    setDefaults();
    ensureExportButton();
    $("#aud-load-window")?.addEventListener("click", loadWindow);
    $("#aud-export-excel")?.addEventListener("click", exportWindow);
    $("#aud-start-monitor")?.addEventListener("click", start);
    $("#aud-stop-monitor")?.addEventListener("click", stop);
    loadWindow();
  });
})();
