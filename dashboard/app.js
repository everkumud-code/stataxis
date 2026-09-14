(() => {
  const $ = (selector) => document.querySelector(selector);
  const setText = (selector, value) => {
    const node = $(selector);
    if (node && value !== undefined && value !== null) node.textContent = value;
  };

  const formatNumber = (value, digits = 1) =>
    Number.isFinite(Number(value))
      ? Number(value).toLocaleString("en-IN", { maximumFractionDigits: digits })
      : "—";

  const formatDelta = (value) => {
    if (!Number.isFinite(Number(value))) return "—";
    const n = Number(value);
    return `${n >= 0 ? "▲" : "▼"} ${Math.abs(n).toFixed(1)}%`;
  };

  const loadJson = async (url) => {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  };

  const renderComparison = (payload) => {
    const comparisons = payload?.comparisons || {};
    const periods = [
      ["last_3_weeks", "3 Weeks", "#hist-3w"],
      ["last_1_month", "1 Month", "#hist-1m"],
      ["last_1_year", "1 Year", "#hist-1y"],
    ];
    periods.forEach(([key, label, selector]) => {
      const change = comparisons[key]?.change || {};
      const node = $(selector);
      if (node) node.textContent = change.score_delta == null ? "—" : `${change.score_delta >= 0 ? "+" : ""}${Number(change.score_delta).toFixed(1)}`;
      const meta = $(`${selector}-meta`);
      if (meta) meta.textContent = change.sufficient_data ? label : `${label} · insufficient history`;
    });
  };

  const renderSignals = (items) => {
    const container = $("#signal-drivers");
    if (!container || !Array.isArray(items) || !items.length) return;
    const max = Math.max(...items.map((item) => Math.abs(Number(item.weighted_contribution) || 0)), 1);
    container.innerHTML = items.slice(0, 5).map((item) => {
      const value = Number(item.weighted_contribution) || 0;
      const width = Math.max(4, Math.round((Math.abs(value) / max) * 100));
      return `<div><span>${item.name}</span><i style="width:${width}%"></i><b>${value >= 0 ? "+" : ""}${value.toFixed(1)}</b></div>`;
    }).join("");
  };

  const renderIntelligence = (payload) => {
    const index = payload?.stx_index || {};
    const view = payload || {};
    setText("#stx-score", index.score == null ? "—" : Number(index.score).toFixed(1));
    setText("#stx-confidence", index.confidence == null ? "Confidence unavailable" : `Confidence ${Math.round(Number(index.confidence) * 100)}%`);
    const meter = $("#stx-meter");
    if (meter) meter.style.width = `${Math.max(0, Math.min(100, Number(index.score) || 0))}%`;

    const data = Array.isArray(view.data) ? view.data.join(" ") : null;
    const analysis = Array.isArray(view.analysis) ? view.analysis.join(" ") : null;
    setText("#view-data", data || "No persisted DATA statement available.");
    setText("#view-analysis", analysis || "No persisted ANALYSIS statement available.");
    setText("#view-conclusion", view.view || "No persisted StatAxis View available.");

    renderSignals(payload.signal_contributions || []);
  };

  const renderChannel = async (channel) => {
    const overview = await loadJson(`/api/v1/channels/${channel.id}`);
    setText("#channel-name", overview.name || channel.name);
    setText("#channel-meta", `${channel.language || "Unknown language"} · ${channel.region || "Region unknown"}`);

    const best = Array.isArray(overview.videos) ? overview.videos.find((item) => item.score != null) : null;
    if (!best) {
      setText("#api-note", "Connected, but no scored video is persisted for this channel yet.");
      return;
    }

    const intelligence = await loadJson(`/api/v1/videos/${best.video_id}/intelligence`);
    renderIntelligence(intelligence);
    setText("#selected-video", best.title || best.youtube_video_id || "Latest scored video");

    const comparison = await loadJson(`/api/v1/channels/${channel.id}/comparison`);
    renderComparison(comparison);
    setText("#api-note", `Live API · updated ${new Date(intelligence.generated_at).toLocaleString("en-IN")}`);

    if (Number.isFinite(Number(intelligence.stx_index?.score))) {
      document.querySelectorAll(".filter").forEach((button) => button.disabled = false);
    }
  };

  const boot = async () => {
    const status = $("#api-status");
    const select = $("#channel-select");
    try {
      const payload = await loadJson("/api/v1/channels");
      const channels = Array.isArray(payload.channels) ? payload.channels : [];
      if (!channels.length) throw new Error("no active channels");
      select.innerHTML = channels.map((channel) => `<option value="${channel.id}">${channel.name}</option>`).join("");

      const requested = new URLSearchParams(window.location.search).get("channel_id");
      const selected = channels.find((channel) => String(channel.id) === requested) || channels[0];
      select.value = String(selected.id);
      await renderChannel(selected);
      status.textContent = "Live API";
      status.classList.add("connected");
      select.addEventListener("change", async () => {
        status.textContent = "Loading…";
        status.classList.remove("connected");
        const channel = channels.find((item) => String(item.id) === select.value);
        try {
          await renderChannel(channel);
          status.textContent = "Live API";
          status.classList.add("connected");
        } catch (error) {
          console.warn("StatAxis dashboard refresh failed", error);
          status.textContent = "API unavailable";
        }
      });
    } catch (error) {
      console.warn("StatAxis API not available", error);
      status.textContent = "Preview";
      setText("#api-note", "Dashboard preview · connect the WSGI API to replace demo values with persisted StatAxis data.");
    }
  };

  document.addEventListener("DOMContentLoaded", boot);
})();
