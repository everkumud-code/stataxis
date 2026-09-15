(() => {
  const $ = (selector) => document.querySelector(selector);
  const setText = (selector, value) => { const node = $(selector); if (node && value !== undefined && value !== null) node.textContent = value; };
  const loadJson = async (url) => { const response = await fetch(url, { headers: { Accept: "application/json" } }); if (!response.ok) throw new Error(`${response.status} ${response.statusText}`); return response.json(); };
  const periodDays = { Today: 1, "3 Weeks": 21, "1 Month": 30, "1 Year": 365 };
  const compact = (value) => Number(value).toLocaleString("en-IN", { notation: "compact", maximumFractionDigits: 1 });
  const signed = (value, digits = 1) => `${value >= 0 ? "+" : ""}${Number(value).toFixed(digits)}`;

  const renderComparison = (payload) => {
    const comparisons = payload?.comparisons || {};
    [["last_3_weeks", "3 Weeks", "#hist-3w"], ["last_1_month", "1 Month", "#hist-1m"], ["last_1_year", "1 Year", "#hist-1y"]].forEach(([key, label, selector]) => {
      const change = comparisons[key]?.change || {};
      const node = $(selector); if (node) node.textContent = change.score_delta == null ? "—" : signed(change.score_delta);
      const meta = $(`${selector}-meta`); if (meta) meta.textContent = change.sufficient_data ? `${label} · ${change.score_percent_change == null ? "" : signed(change.score_percent_change) + "%"}` : `${label} · insufficient history`;
    });
  };

  const renderMultiChannelComparison = (payload, selectedId) => {
    const body = $("#comparison-table-body");
    if (!body) return;
    const channels = Array.isArray(payload?.channels) ? payload.channels : [];
    setText("#comparison-report-note", payload?.as_of ? `As of ${new Date(payload.as_of).toLocaleString("en-IN")} · persisted STX intelligence only` : "Ranked from persisted STX intelligence · no demo scores");
    if (!channels.length) { body.innerHTML = `<tr><td colspan="7" class="muted">No scored channels available for comparison.</td></tr>`; return; }
    const cell = (change) => { const delta = change?.change?.score_delta; return delta == null ? "—" : `<span class="${delta >= 0 ? "trend-up" : "trend-down"}">${signed(delta)}</span>`; };
    body.innerHTML = channels.map((channel) => {
      const current = channel.current;
      const active = String(channel.channel_id) === String(selectedId) ? " class=\"selected-row\"" : "";
      return `<tr${active}><td>#${channel.rank}</td><td><strong>${channel.name}</strong></td><td>${current?.score == null ? "—" : Number(current.score).toFixed(1)}</td><td>${current?.confidence == null ? "—" : Math.round(Number(current.confidence) > 1 ? Number(current.confidence) : Number(current.confidence) * 100)}%</td><td>${cell(channel.last_3_weeks)}</td><td>${cell(channel.last_1_month)}</td><td>${cell(channel.last_1_year)}</td></tr>`;
    }).join("");
  };

  const renderSignals = (items) => {
    const container = $("#signal-drivers"); if (!container) return;
    if (!Array.isArray(items) || !items.length) { container.innerHTML = `<div><span>No persisted drivers</span><i style="width:4%"></i><b>—</b></div>`; return; }
    const max = Math.max(...items.map((item) => Math.abs(Number(item.weighted_contribution ?? item.contribution) || 0)), 1);
    container.innerHTML = items.slice(0, 5).map((item) => { const value = Number(item.weighted_contribution ?? item.contribution) || 0; const width = Math.max(4, Math.round((Math.abs(value) / max) * 100)); return `<div><span>${item.name}</span><i style="width:${width}%"></i><b>${signed(value)}</b></div>`; }).join("");
  };

  const renderIntelligence = (payload) => {
    const index = payload?.stx_index || { score: payload?.score, confidence: payload?.confidence, available_signals: payload?.available_signals };
    setText("#stx-score", index.score == null ? "—" : Number(index.score).toFixed(1));
    const confidence = Number(index.confidence); setText("#stx-confidence", Number.isFinite(confidence) ? `Confidence ${Math.round(confidence > 1 ? confidence : confidence * 100)}% · ${index.available_signals ?? 0} signals` : "Confidence unavailable");
    const meter = $("#stx-meter"); if (meter) meter.style.width = `${Math.max(0, Math.min(100, Number(index.score) || 0))}%`;
    setText("#view-data", Array.isArray(payload?.data) ? payload.data.join(" ") : "No persisted DATA statement available."); setText("#view-analysis", Array.isArray(payload?.analysis) ? payload.analysis.join(" ") : "No persisted ANALYSIS statement available."); setText("#view-conclusion", payload?.view || "No persisted StatAxis View available."); renderSignals(payload?.signal_contributions || payload?.contributions || []);
  };

  const renderSeries = (payload) => {
    const points = Array.isArray(payload?.points) ? payload.points : []; const svg = $("#series-chart"); const note = $("#series-note");
    if (!svg || !points.length) { if (note) note.textContent = "No persisted observation series available for this period."; return; }
    const values = points.map((point) => Number(point.value)).filter(Number.isFinite); const min = Math.min(...values); const max = Math.max(...values); const range = Math.max(max - min, 1); const width = 700; const height = 220; const left = 8; const top = 10; const bottom = 10;
    const path = points.map((point, index) => { const x = left + (index / Math.max(points.length - 1, 1)) * (width - left * 2); const y = top + (1 - (Number(point.value) - min) / range) * (height - top - bottom); return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`; }).join(" ");
    const area = `${path} L${width-left} ${height} L${left} ${height} Z`; svg.innerHTML = `<path class="gridline" d="M0 30H700 M0 95H700 M0 160H700 M0 220H700"/><path class="area" d="${area}"/><path class="trend" d="${path}"/>`;
    const axis = $("#series-axis"); if (axis) axis.innerHTML = `<span>${compact(max)}</span><span>${compact((max + min) / 2)}</span><span>${compact(min)}</span>`;
    const labels = $("#series-labels"); if (labels) { const fmt = (value) => value ? new Date(value).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }) : "—"; labels.innerHTML = `<span>${fmt(points[0]?.observed_at)}</span><span>${fmt(points[points.length - 1]?.observed_at)}</span>`; }
    setText("#audience-value", compact(values[values.length - 1])); setText("#audience-delta", `${compact(values[values.length - 1])} cumulative views`); if (note) note.textContent = `${points.length} persisted observation points · cumulative view count`;
  };

  const renderSignalsCard = (payload) => { const velocity = Number(payload?.average_view_velocity_per_minute); const direction = payload?.momentum_direction; setText("#momentum-value", Number.isFinite(velocity) ? `${velocity >= 0 ? "+" : ""}${compact(Math.abs(velocity))}/min` : "—"); setText("#momentum-direction", direction === "positive" ? "RISING" : direction === "negative" ? "FALLING" : direction === "flat" ? "FLAT" : "STX"); setText("#momentum-meta", Number.isFinite(Number(payload?.audience_momentum_per_minute)) ? `Audience momentum ${signed(Number(payload.audience_momentum_per_minute), 2)}/min` : "View velocity from persisted observations"); };

  const renderCompetition = (payload, selectedChannelId) => {
    const channels = Array.isArray(payload?.channels) ? payload.channels : []; const current = channels.find((item) => String(item.channel_id) === String(selectedChannelId)); const container = $("#competition-rows"); if (!container) return;
    if (!current || !current.current) { container.innerHTML = `<div><span>Channel comparison</span><b>—</b><em>→</em></div><div><span>Rank movement</span><b>—</b><em>→</em></div><div><span>Share movement</span><b>—</b><em>→</em></div>`; setText("#competitive-rank", "—"); setText("#competitive-share", "No current STX comparison"); setText("#competitive-meta", "Requires scored channels"); return; }
    const rank = Number(current.rank); const score = Number(current.current.score); const leaderScore = Number(channels[0]?.current?.score); const gap = Number.isFinite(leaderScore) ? score - leaderScore : null;
    setText("#competitive-rank", Number.isFinite(rank) ? `#${rank}` : "—"); setText("#competitive-share", gap == null || rank === 1 ? (rank === 1 ? "#1 STX position" : "Relative comparison") : `Gap to leader ${signed(gap)}`); setText("#competitive-meta", `${channels.length} scored channel${channels.length === 1 ? "" : "s"} in comparison`);
    const monthChange = current.last_1_month?.change?.score_delta; const rows = [["Channel comparison", rank === 1 ? "Leader" : `#${rank}`, "→"], ["Rank movement", current.last_1_month?.change?.sufficient_data ? "Tracked" : "—", current.last_1_month?.change?.sufficient_data ? "✓" : "→"], ["STX movement", monthChange == null ? "—" : signed(monthChange), monthChange == null ? "→" : monthChange >= 0 ? "↗" : "↘"]]; container.innerHTML = rows.map(([label, value, arrow]) => `<div><span>${label}</span><b>${value}</b><em>${arrow}</em></div>`).join(""); setText("#competition-note", payload?.as_of ? `As of ${new Date(payload.as_of).toLocaleString("en-IN")}` : "Current relative position");
  };

  const renderChannel = async (channel, days = 30) => {
    const overview = await loadJson(`/api/v1/channels/${channel.id}`); setText("#channel-name", overview.name || channel.name); setText("#channel-meta", `${channel.language || "Unknown language"} · ${channel.region || "Region unknown"}`);
    const best = Array.isArray(overview.videos) ? overview.videos.find((item) => item.score != null) : null;
    if (best) { const intelligence = await loadJson(`/api/v1/videos/${best.video_id}/intelligence`); renderIntelligence(intelligence); setText("#selected-video", best.title || best.youtube_video_id || "Latest scored video"); setText("#api-note", `Live API · updated ${new Date(intelligence.generated_at).toLocaleString("en-IN")}`); } else { setText("#api-note", "Connected, but no scored video is persisted for this channel yet."); renderIntelligence({}); }
    const [comparison, series, signals, allComparison] = await Promise.all([loadJson(`/api/v1/channels/${channel.id}/comparison`), loadJson(`/api/v1/channels/${channel.id}/series?days=${days}`), loadJson(`/api/v1/channels/${channel.id}/signals?hours=24`), loadJson(`/api/v1/channels/compare?ids=${(window.__stataxisChannels || []).slice(0, 12).map((item) => item.id).join(",")}`)]);
    renderComparison(comparison); renderSeries(series); renderSignalsCard(signals); renderMultiChannelComparison(allComparison, channel.id); renderCompetition(allComparison, channel.id);
  };

  const boot = async () => {
    const status = $("#api-status"); const dot = $("#api-dot"); const select = $("#channel-select"); const filters = [...document.querySelectorAll(".filter")];
    try {
      const payload = await loadJson("/api/v1/channels"); const channels = Array.isArray(payload.channels) ? payload.channels : []; if (!channels.length) throw new Error("no active channels"); window.__stataxisChannels = channels;
      select.innerHTML = channels.map((channel) => `<option value="${channel.id}">${channel.name}</option>`).join(""); const requested = new URLSearchParams(window.location.search).get("channel_id"); const selected = channels.find((channel) => String(channel.id) === requested) || channels[0]; select.value = String(selected.id); let activeDays = 30;
      const refresh = async () => { status.textContent = "Loading…"; dot.classList.remove("connected"); const channel = channels.find((item) => String(item.id) === select.value); await renderChannel(channel, activeDays); status.textContent = "Live API"; dot.classList.add("connected"); };
      await refresh(); select.addEventListener("change", () => refresh().catch(() => { status.textContent = "API unavailable"; dot.classList.remove("connected"); }));
      filters.forEach((button) => button.addEventListener("click", () => { const label = button.textContent.trim(); activeDays = periodDays[label] || 30; filters.forEach((item) => item.classList.toggle("active", item === button)); refresh().catch(() => { status.textContent = "API unavailable"; dot.classList.remove("connected"); }); }));
    } catch (error) { console.warn("StatAxis API not available", error); status.textContent = "Preview"; setText("#api-note", "Dashboard preview · connect the WSGI API to replace demo values with persisted StatAxis data."); }
  };
  document.addEventListener("DOMContentLoaded", boot);
})();
