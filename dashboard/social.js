/* Facebook, Instagram and X for the workspace: rankings, each channel beside YouTube, one channel in depth with a comparison, the best posts, and the administrator's setup.
   Loaded by workspace.html after market.js; it uses the helpers of workspace.html ($, esc, api, post, table, head, kpi, state, spark, whole, dec, compact, add, isAdmin, channels, IST_ZONE)
   and the ones market.js shares through window.__sxMarket. */
"use strict";
(() => {
  const M = window.__sxMarket;
  if (!M || !M.fail) return;
  const {SP, keep, opt, formValues, LANGS, SEGMENTS, fail, wireUpgrade} = M;
  const PLATFORMS = [["", "All three"], ["facebook", "Facebook"], ["instagram", "Instagram"], ["x", "X"]];
  const LABEL = {facebook: "Facebook", instagram: "Instagram", x: "X"};
  const PERIODS = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["180", "6 months"], ["365", "1 year"]];
  const when = iso => iso ? new Date(iso).toLocaleString("en-IN", {day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true, ...IST_ZONE}) + " IST" : "—";
  const day = iso => iso ? new Date(iso).toLocaleDateString("en-IN", {day: "numeric", month: "short", year: "numeric", ...IST_ZONE}) : "—";
  const signed = n => n == null ? "—" : (n > 0 ? "+" : "") + whole(n);
  const signedPct = n => n == null ? "—" : (n > 0 ? "+" : "") + dec(n, 2) + "%";
  const link = (url, text) => url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>` : esc(text);
  const handleLink = r => link(r.url, (r.platform === "x" ? "@" : r.platform === "instagram" ? "@" : "") + r.handle);
  const growthText = r => r.growth_abs == null ? "—" : `${signed(r.growth_abs)}${r.growth_span_days != null && r.growth_span_days < r.__days - 1 ? ` (over ${dec(r.growth_span_days)} d)` : ""}`;
  const rate = r => r.engagement_rate == null ? "—" : dec(r.engagement_rate, 2) + "%" + (r.low_sample ? " ·" : "");
  const rateNote = `<p class="muted" style="margin-top:8px">Engagement rate: likes, comments and shares per post, as a percentage of the followers. A dot (·) means fewer than 5 posts had figures, so treat it lightly. Reach is not public, so this shows how many people reacted, not how many saw the post.</p>`;
  const statusTag = r => r.status === "ok" ? '<span class="tag green">read</span>' : r.status === "not_configured" ? '<span class="tag">no key yet</span>' : r.status ? `<span class="tag red">${esc(r.status.replace("_", " "))}</span>` : '<span class="tag">not read yet</span>';
  const SOCIAL_METHOD = "Followers are the public follower count at the time each account was read, through the platform's official API or from a sheet the channel supplied. Growth compares the newest reading with the one at the start of the period (a shorter span is shown when we have read for less time). A figure a platform does not give is shown as a dash, never as zero.";

  const filters = (f, {platform = true, sort = false} = {}) => `<form class="card" id="sf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0">
      ${platform ? `<label>Platform<br><select name="platform">${opt(PLATFORMS, f.platform || "")}</select></label>` : ""}
      <label>Language<br><select name="language">${opt(LANGS, f.language || "")}</select></label>
      <label>Category<br><select name="segment">${opt(SEGMENTS, f.segment || "")}</select></label>
      <label>Period<br><select name="days">${opt(PERIODS, f.days || "30")}</select></label>
      ${sort ? `<label>Rank by<br><select name="sort">${opt([["followers", "Followers"], ["growth", "Growth %"], ["growth_abs", "Growth (people)"], ["engagement", "Engagement rate"], ["posts", "Posts in the period"]], f.sort || "followers")}</select></label>` : ""}
      <button class="btn primary" type="submit">Show</button></form>`;

  /* ---------- rankings per platform ---------- */
  add("social", "Social media", "Social media rankings", async el => {
    const f = SP.social || {platform: "", language: "", segment: "", days: "30", sort: "followers"};
    el.innerHTML = head("Social media rankings", "Facebook, Instagram and X: who has the most followers, who is growing fastest and whose posts people react to.") + filters(f, {sort: true}) + `<div id="sout"></div>`;
    const run = async () => {
      const v = formValues($("#sf", el)); keep("social", v); const out = $("#sout", el); out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/social/overview", v);
        if (!d.coverage.accounts) {
          out.innerHTML = state("No social media account is linked yet", isAdmin ? "Link the Facebook, Instagram and X accounts of the channels under Channels and data → Social media setup. Figures can come from the platforms' official APIs or from a sheet." : "An administrator has not linked any account for these channels yet.", isAdmin ? `<a class="btn primary" href="#/adm-social">Open social media setup</a>` : "");
          return;
        }
        out.innerHTML = `<div class="grid kpis">${kpi("Channels with an account", `${d.coverage.channels_with_an_account} of ${d.coverage.channels}`, "channels shown that have at least one account linked")}${kpi("Accounts read", `${d.coverage.accounts_with_data} of ${d.coverage.accounts}`, "accounts with a follower figure", "gold")}
          ${d.platforms.filter(p => p.with_data).map(p => kpi(p.label + " followers", compact(p.followers_total), `${p.with_data} accounts` + (p.growth_pct_total != null ? ` · ${signedPct(p.growth_pct_total)} in ${d.days} days` : ""))).join("")}</div>` +
          d.platforms.map(p => `<section class="card" style="margin-top:14px"><h2>${esc(p.label)}</h2>` + table([
            {h: "Rank", n: 1, v: r => r.rank == null ? "—" : r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.channel)}</strong>`}, {h: "Handle", html: 1, v: handleLink}, {h: "Followers", n: 1, v: r => whole(r.followers)},
            {h: `Growth in ${d.days} days`, n: 1, v: r => (r.__days = d.days, growthText(r))}, {h: "Growth %", n: 1, v: r => signedPct(r.growth_pct)}, {h: "Posts in period", n: 1, v: r => whole(r.posts_in_period)},
            {h: "Average reactions per post", n: 1, v: r => dec(r.avg_interactions)}, {h: "Engagement rate", n: 1, v: rate}, {h: "Read at (IST)", v: r => when(r.observed_at)}, {h: "", html: 1, v: r => r.followers == null ? statusTag(r) : ""}],
            p.rows, `No ${p.label} account is linked for these channels.`) + `</section>`).join("") + rateNote + `<details class="card" style="margin-top:14px"><summary>How these numbers were worked out</summary><p class="muted" style="margin-top:8px">${esc(d.method)}</p></details>`;
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#sf", el).onsubmit = ev => { ev.preventDefault(); run(); }; run();
  });

  /* ---------- every channel on one row: YouTube and the three platforms ---------- */
  add("socialpresence", "Social media", "Social media beside YouTube", async el => {
    const f = SP.socialpresence || {language: "", segment: "", days: "30"};
    el.innerHTML = head("Social media beside YouTube", "Each channel's YouTube subscribers and its followers on Facebook, Instagram and X, side by side.") + filters(f, {platform: false}) + `<div id="pout"></div>`;
    const run = async () => {
      const v = formValues($("#sf", el)); keep("socialpresence", v); const out = $("#pout", el); out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/social/presence", v);
        const stx = r => r.stx ? dec(r.stx.score) : "—";
        out.innerHTML = `<section class="card">` + table([
          {h: "Rank", n: 1, v: r => r.rank == null ? "—" : r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.channel)}</strong>`}, {h: "YouTube subscribers", n: 1, v: r => whole(r.youtube)}, {h: "Facebook", n: 1, v: r => whole(r.facebook)},
          {h: "Instagram", n: 1, v: r => whole(r.instagram)}, {h: "X", n: 1, v: r => whole(r.x)}, {h: "Social followers (total)", n: 1, v: r => whole(r.total)}, {h: `Growth of the social accounts in ${d.days} days`, n: 1, v: r => signed(r.growth_abs)}, {h: "STX Index", n: 1, v: stx}],
          d.rows, "No channel has a follower figure yet.", {group: r => r.language}) + `<p class="muted" style="margin-top:8px">${esc(d.note)} The STX Index is the YouTube-based score; the social figures sit beside it and are not part of it.</p></section>
          <details class="card" style="margin-top:14px"><summary>How these numbers were worked out</summary><p class="muted" style="margin-top:8px">${esc(d.method)}</p></details>`;
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#sf", el).onsubmit = ev => { ev.preventDefault(); run(); }; run();
  });

  /* ---------- one channel in depth, and several side by side ---------- */
  const chOptions = (cur, multi) => {
    const sorted = [...channels].sort((a, b) => String(a.language || "").localeCompare(String(b.language || "")) || String(a.name).localeCompare(String(b.name)));
    return sorted.map(c => `<option value="${esc(c.id)}"${(multi ? String(cur || "").split(",").includes(String(c.id)) : String(cur || "") === String(c.id)) ? " selected" : ""}>${esc(c.name)}${c.language ? " · " + esc(c.language) : ""}</option>`).join("");
  };
  add("socialchannel", "Social media", "Social media: one channel", async el => {
    const f = SP.socialchannel || {channel_id: "", days: "90"}, g = SP.socialcompare || {channels: "", platform: "instagram", days: "30"};
    el.innerHTML = head("Social media: one channel", "A channel on every platform: follower history, its best posts and the hours its posts do best. Below, several channels on one platform side by side.") +
      `<form class="card" id="scf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0"><label>Channel<br><select name="channel_id" style="min-width:260px"><option value="">Choose a channel…</option>${chOptions(f.channel_id)}</select></label>
        <label>History<br><select name="days">${opt(PERIODS.slice(1), f.days)}</select></label><button class="btn primary" type="submit">Show</button></form><div id="scout"></div>
      <h2 style="margin-top:22px">Compare channels</h2>
      <form class="card" id="cmf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0"><label>Channels (up to 12)<br><select name="channels" multiple size="7" style="min-width:260px">${chOptions(g.channels, true)}</select></label>
        <label>Platform<br><select name="platform">${opt(PLATFORMS.slice(1), g.platform)}</select></label><label>History<br><select name="days">${opt(PERIODS.slice(1), g.days)}</select></label><button class="btn primary" type="submit">Compare</button></form><div id="cmout"></div>`;
    const one = async () => {
      const v = formValues($("#scf", el)); keep("socialchannel", v); const out = $("#scout", el);
      if (!v.channel_id) { out.innerHTML = `<p class="muted">Choose a channel to see it.</p>`; return; }
      out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/social/channel", v);
        const yt = d.youtube, accounts = d.accounts;
        out.innerHTML = `<div class="grid kpis">${kpi("YouTube subscribers", whole(yt.subscribers), "latest reading")}${accounts.map(a => kpi(LABEL[a.platform] + " followers", whole(a.followers), a.followers == null ? "not read yet" : `${signed(a.growth_abs)} in 30 days · read ${when(a.observed_at)}`)).join("")}
          ${kpi("Posts in the period", whole(d.posts_in_period), d.posts_per_week != null ? `about ${dec(d.posts_per_week)} a week` : "no post figures yet")}</div>` +
          (accounts.length ? accounts.map(a => `<section class="card" style="margin-top:14px"><h2>${esc(LABEL[a.platform])} · ${handleLink(a)} ${statusTag(a)}</h2>${a.series.length >= 2 ? spark(a.series, "value", LABEL[a.platform] + " followers") : `<p class="muted">At least two readings on different days are needed to draw the history${a.followers != null ? " (" + whole(a.followers) + " followers so far)" : ""}.</p>`}
            ${a.error ? `<p class="muted">${esc(a.error)}</p>` : ""}</section>`).join("") : state("No account is linked for this channel", "An administrator can link its Facebook, Instagram and X accounts under Social media setup.")) +
          (yt.series.length >= 2 ? `<section class="card" style="margin-top:14px"><h2>YouTube subscribers</h2>${spark(yt.series, "value", "YouTube subscribers")}</section>` : "") +
          `<section class="card" style="margin-top:14px"><h2>Best posts in the last ${d.days} days</h2>` + table([
            {h: "Platform", v: r => r.platform_label}, {h: "Posted (IST)", v: r => when(r.posted_at)}, {h: "Post", html: 1, v: r => link(r.permalink, r.text || "(open the post)")}, {h: "Likes", n: 1, v: r => whole(r.likes)}, {h: "Comments", n: 1, v: r => whole(r.comments)},
            {h: "Shares", n: 1, v: r => whole(r.shares)}, {h: "Views", n: 1, v: r => whole(r.views)}, {h: "Reactions", n: 1, v: r => whole(r.interactions)}], d.top_posts, "No post with figures yet.") + `</section>` +
          (d.by_hour.length ? `<section class="card" style="margin-top:14px"><h2>When its posts do best (Indian time)</h2>` + table([{h: "Hour", v: r => String(r.hour).padStart(2, "0") + ":00"}, {h: "Posts", n: 1, v: r => whole(r.posts)}, {h: "Average reactions per post", n: 1, v: r => dec(r.average_interactions)}], d.by_hour) +
            `<p class="muted" style="margin-top:8px">Only posts with reaction figures are counted. A few posts in an hour is a hint, not a rule.</p></section>` : "") +
          `<details class="card" style="margin-top:14px"><summary>How these numbers were worked out</summary><p class="muted" style="margin-top:8px">${esc(d.method)}</p></details>`;
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    const cmp = async () => {
      const v = formValues($("#cmf", el)); keep("socialcompare", v); const out = $("#cmout", el);
      if (!v.channels) { out.innerHTML = `<p class="muted">Choose two or more channels (hold Ctrl or Shift to choose several).</p>`; return; }
      out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/social/compare", v);
        out.innerHTML = `<section class="card">` + table([{h: "Channel", html: 1, v: r => `<strong>${esc(r.channel)}</strong>`}, {h: "Handle", html: 1, v: handleLink}, {h: "Followers", n: 1, v: r => whole(r.followers)}, {h: "Growth in 30 days", n: 1, v: r => signed(r.growth_abs)},
          {h: "Growth %", n: 1, v: r => signedPct(r.growth_pct)}, {h: "Engagement rate", n: 1, v: rate}], d.rows, "None of these channels has an account on this platform.") + `</section>` +
          d.rows.filter(r => r.series.length >= 2).map(r => `<section class="card" style="margin-top:14px"><h2>${esc(r.channel)} · ${esc(r.platform_label)}</h2>${spark(r.series, "value", r.channel + " followers")}</section>`).join("") + rateNote;
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#scf", el).onsubmit = ev => { ev.preventDefault(); one(); }; $("#cmf", el).onsubmit = ev => { ev.preventDefault(); cmp(); };
    if (f.channel_id) one(); if (g.channels) cmp();
  });

  /* ---------- the best posts ---------- */
  add("socialposts", "Social media", "Social media: top posts", async el => {
    const f = SP.socialposts || {platform: "", language: "", segment: "", days: "7", sort: "interactions"};
    el.innerHTML = head("Social media: top posts", "The posts that got the most reactions in the chosen days, on Facebook, Instagram and X.") +
      `<form class="card" id="tpf" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0"><label>Platform<br><select name="platform">${opt(PLATFORMS, f.platform)}</select></label><label>Language<br><select name="language">${opt(LANGS, f.language)}</select></label>
        <label>Category<br><select name="segment">${opt(SEGMENTS, f.segment)}</select></label><label>Posted in the last<br><select name="days">${opt([["1", "1 day"], ["3", "3 days"], ["7", "7 days"], ["30", "30 days"], ["90", "90 days"]], f.days)}</select></label>
        <label>Rank by<br><select name="sort">${opt([["interactions", "Reactions"], ["views", "Views (where given)"], ["rate", "Reactions as % of followers"]], f.sort)}</select></label><button class="btn primary" type="submit">Show</button></form><div id="tpout"></div>`;
    const run = async () => {
      const v = formValues($("#tpf", el)); keep("socialposts", v); const out = $("#tpout", el); out.innerHTML = `<p class="muted">Working it out…</p>`;
      try {
        const d = await api("/api/v1/social/posts", {...v, limit: 40});
        out.innerHTML = `<section class="card">` + table([{h: "Rank", n: 1, v: r => r.rank}, {h: "Channel", html: 1, v: r => `<strong>${esc(r.channel)}</strong>`}, {h: "Platform", v: r => r.platform_label}, {h: "Posted (IST)", v: r => when(r.posted_at)},
          {h: "Post", html: 1, v: r => link(r.permalink, r.text || "(open the post)")}, {h: "Reactions", n: 1, v: r => whole(r.interactions)}, {h: "Likes", n: 1, v: r => whole(r.likes)}, {h: "Comments", n: 1, v: r => whole(r.comments)}, {h: "Shares", n: 1, v: r => whole(r.shares)},
          {h: "Views", n: 1, v: r => whole(r.views)}, {h: "% of followers", n: 1, v: r => r.rate == null ? "—" : dec(r.rate, 2) + "%"}], d.posts, "No post with figures in these days yet.") + `<p class="muted" style="margin-top:8px">${esc(d.note)}</p></section>`;
      } catch (e) { out.innerHTML = fail(e); wireUpgrade(out); }
    };
    $("#tpf", el).onsubmit = ev => { ev.preventDefault(); run(); }; run();
  });

  /* ---------- administrator: keys, accounts, sheets ---------- */
  const readFile = async input => input && input.files && input.files[0] ? await input.files[0].text() : "";
  const errorsList = list => list && list.length ? `<details open><summary>${list.length} row${list.length === 1 ? "" : "s"} not used</summary><ul class="muted">${list.slice(0, 25).map(e => `<li>Row ${esc(e.row)}: ${esc(e.error)}</li>`).join("")}${list.length > 25 ? `<li>… and ${list.length - 25} more</li>` : ""}</ul></details>` : "";
  add("adm-social", "Admin", "Social media setup", async el => {
    if (!isAdmin) { el.innerHTML = adminOnly("Social media setup"); return; }
    el.innerHTML = head("Social media setup", "Link the Facebook, Instagram and X accounts of your channels, save the platform keys, and bring in figures from a sheet. Keys stay on the server and are shown only as their last four characters.") + `<div id="smout"><p class="muted">Loading…</p></div>`;
    const out = $("#smout", el);
    const say = (t, ok) => { const m = $("#smmsg", el); if (!m) return; m.hidden = !t; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = t || ""; };
    const draw = async (filter = {}) => {
      const [st, list] = await Promise.all([api("/api/v1/social/admin/status"), api("/api/v1/social/admin/accounts", filter)]);
      const s = st.settings, keyRow = (name, label, secret) => `<label>${label}<br><input type="${secret ? "password" : "text"}" name="${name}" autocomplete="off" placeholder="${s[name].set ? "saved " + esc(s[name].hint) + " — leave empty to keep" : "not saved yet"}"></label>
        ${s[name].set ? `<label style="align-self:end"><input type="checkbox" name="clear_${name}"> remove the saved one</label>` : ""}`;
      out.innerHTML = `<div class="grid kpis">${Object.values(st.by_platform).map(p => kpi(p.label, `${p.with_data} of ${p.accounts}`, `accounts with figures · ${p.failing} failing · ${p.no_key} waiting for a key`, p.failing ? "" : "gold")).join("")}${kpi("Last successful read", when(st.last_read_at), "by the collector")}</div>
        <div id="smmsg" class="msg" hidden></div>
        <section class="card" style="margin-top:14px"><h2>Platform keys</h2>
          <form id="smkeys" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;align-items:end">
            ${keyRow("meta_token", "Meta access token (Facebook and Instagram)", true)}${keyRow("meta_ig_user_id", "Instagram account id (a professional account that can read other accounts)", false)}${keyRow("x_bearer", "X bearer token", true)}
            <label>X accounts read in one pass (X charges per read)<br><input type="number" name="x_max_per_run" min="0" max="5000" value="${esc(s.x_max_per_run)}"></label>
            <label>Hours between two readings of an account<br><input type="number" name="hours_between" min="1" max="168" value="${esc(s.hours_between)}"></label>
            <div class="btnrow"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" id="smrun">Read the accounts that are due now</button></div></form>
          <details style="margin-top:12px"><summary>How to get the keys</summary><ol class="muted" style="margin-top:8px">
            <li><b>Instagram and Facebook:</b> at developers.facebook.com make an app, and a long-lived access token for a Facebook user who manages a Facebook page linked to an Instagram professional account. Give the token the permissions
              <i>instagram_basic</i>, <i>pages_read_engagement</i> and, to read other pages' public posts, apply for <i>Page Public Content Access</i>. Paste the token, and the id of that Instagram professional account (a number).
              Instagram can read only <i>business and creator</i> accounts; Facebook page figures are read the same way.</li>
            <li><b>X:</b> at developer.x.com make a project on a paid plan and copy its <i>Bearer token</i>. X charges for reads, so set how many accounts one pass may read.</li>
            <li>Until a key is saved, accounts show "no key yet" and nothing is lost: add accounts and bring figures in from a sheet below. StatAxis never asks for anyone's platform password.</li></ol></details></section>
        <section class="card" style="margin-top:14px"><h2>Link an account</h2>
          <form id="smadd" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"><label>Channel<br><select name="channel_id" style="min-width:240px" required><option value="">Choose…</option>${chOptions("")}</select></label>
            <label>Platform<br><select name="platform">${opt(PLATFORMS.slice(1), "instagram")}</select></label><label>Handle or address<br><input type="text" name="handle" placeholder="@aajtak or https://x.com/aajtak" required></label><button class="btn primary" type="submit">Link</button></form></section>
        <section class="card" style="margin-top:14px"><h2>Bring in a sheet</h2><p class="muted">CSV files (comma, semicolon or tab). Pick the file, or paste the rows. Rows that cannot be used are listed with the reason; the others are kept.</p>
          ${[["accounts", "Accounts", "channel, platform, handle", "channel is the StatAxis number, the YouTube channel id, the YouTube @handle or the exact name"], ["stats", "Follower figures", "platform, handle, date, followers, following, posts", "date as 2026-10-12; the account must be linked first"],
             ["posts", "Posts", "platform, handle, post_id, posted_at, text, permalink, likes, comments, shares, views", "figures are stored as of now; leave a figure empty when it is not known"]].map(([key, title, cols, note]) => `<form class="smimp" data-kind="${key}" style="margin-top:12px"><b>${title}</b> <span class="muted">columns: ${esc(cols)}. ${esc(note)}.</span>
            <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:start;margin-top:6px"><input type="file" accept=".csv,.txt,.tsv"><textarea name="csv" rows="3" style="min-width:280px;flex:1" placeholder="or paste the rows here, with the column names in the first line"></textarea><button class="btn" type="submit">Import</button></div><div class="smres"></div></form>`).join("")}</section>
        <section class="card" style="margin-top:14px"><h2>Linked accounts</h2>
          <form id="smfilter" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:8px"><label>Platform<br><select name="platform">${opt(PLATFORMS, filter.platform || "")}</select></label>
            <label><input type="checkbox" name="problems" value="1"${filter.problems ? " checked" : ""}> only accounts with a problem</label><button class="btn" type="submit">Filter</button></form>
          ${table([{h: "Channel", html: 1, v: r => `<strong>${esc(r.channel)}</strong>`}, {h: "Platform", v: r => r.platform_label}, {h: "Handle", html: 1, v: r => link(r.url, r.handle)}, {h: "Status", html: 1, v: r => statusTag(r) + (r.error ? ` <span class="muted">${esc(r.error)}</span>` : "")},
            {h: "Last read (IST)", v: r => when(r.last_ok_at)}, {h: "", html: 1, v: r => `<button class="btn" type="button" data-check="${r.id}">Read now</button> <button class="btn" type="button" data-fig="${r.id}">Add a figure</button> <button class="btn" type="button" data-del="${r.id}">Remove</button>`}],
            list.accounts, "No account is linked yet.")}</section>`;
      wire(filter);
    };
    const wire = filter => {
      $("#smkeys", out).onsubmit = async ev => { ev.preventDefault(); const f = new FormData(ev.target), body = {};
        for (const [k, v] of f.entries()) { if (k.startsWith("clear_")) body[k] = true; else if (v !== "") body[k] = v; }
        try { await post("/api/v1/social/admin/settings", body); await draw(filter); say("Saved.", true); } catch (e) { say(e.message); } };
      $("#smrun", out).onclick = async () => { say("Reading the accounts that are due (up to 30)…", true); try { const r = (await post("/api/v1/social/admin/run", {})).counts; await draw(filter); say(`Read ${r.read} accounts, ${r.new_posts} new posts, ${r.failed} failed, ${r.no_key} waiting for a key${r.left_for_next_pass ? `, ${r.left_for_next_pass} left for the next pass` : ""}.`, true); } catch (e) { say(e.message); } };
      $("#smadd", out).onsubmit = async ev => { ev.preventDefault(); const v = formValues(ev.target); try { await post("/api/v1/social/admin/accounts/save", {channel_id: +v.channel_id, platform: v.platform, handle: v.handle}); await draw(filter); say("Linked.", true); } catch (e) { say(e.message); } };
      $("#smfilter", out).onsubmit = ev => { ev.preventDefault(); const v = formValues(ev.target); draw({platform: v.platform || undefined, problems: v.problems ? 1 : undefined}); };
      out.querySelectorAll(".smimp").forEach(form => form.onsubmit = async ev => { ev.preventDefault();
        const res = $(".smres", form); const csv = (await readFile($("input[type=file]", form))) || $("textarea", form).value;
        if (!csv.trim()) { res.innerHTML = `<p class="muted">Pick a file or paste the rows first.</p>`; return; }
        res.innerHTML = `<p class="muted">Importing…</p>`;
        try {
          const kind = form.dataset.kind, r = await post(`/api/v1/social/admin/${kind === "accounts" ? "accounts" : kind}/import`, {csv});
          res.innerHTML = `<p class="muted">${kind === "accounts" ? `${r.added} linked, ${r.updated} updated.` : kind === "stats" ? `${r.stored} figures stored.` : `${r.posts} posts read, ${r.new_posts} new.`}</p>${errorsList(r.errors)}`;
          if (kind === "accounts") draw(filter);
        } catch (e) { res.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`; } });
      out.querySelectorAll("[data-check]").forEach(b => b.onclick = async () => { b.disabled = true; say("Reading the account…", true);
        try { const r = await post("/api/v1/social/admin/accounts/check", {id: +b.dataset.check}); await draw(filter); say(r.result.status === "ok" ? `Read: ${whole(r.result.followers)} followers, ${r.result.posts} posts.` : r.result.message, r.result.status === "ok"); } catch (e) { say(e.message); b.disabled = false; } });
      out.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { if (!confirm("Remove this account and every figure stored for it?")) return; try { await post("/api/v1/social/admin/accounts/delete", {id: +b.dataset.del}); await draw(filter); say("Removed.", true); } catch (e) { say(e.message); } });
      out.querySelectorAll("[data-fig]").forEach(b => b.onclick = async () => {
        const date = prompt("Date of the figure (for example 2026-10-12):", new Date(Date.now() + 19800000).toISOString().slice(0, 10)); if (!date) return;
        const followers = prompt("Followers on that date:"); if (followers == null || followers === "") return;
        try { await post("/api/v1/social/admin/stats/add", {account_id: +b.dataset.fig, date, followers}); say("Figure saved.", true); } catch (e) { say(e.message); } });
    };
    try { await draw(); } catch (e) { out.innerHTML = fail(e); }
  }, {admin: 1});
})();
