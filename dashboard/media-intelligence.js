(() => {
  const $ = (s) => document.querySelector(s);
  const token = () => localStorage.getItem('stataxis_access_token') || '';
  const demo = {
    hindi:{title:'Hindi News',rows:[['Aaj Tak',1,15500,11000,19300,20.3,'27%','+2'],['IndiaTV',2,8600,1600,14400,17.8,'24%','+1'],['TV9 Bharatvarsh',3,8000,1100,9600,15.1,'20%','0'],['Republic Bharat',4,4400,1000,13500,10.8,'14%','+1'],['ABP News',5,4100,800,7200,8.9,'12%','-1'],['News18 India',6,4200,600,6900,7.4,'10%','0']]},
    'english-india':{title:'English India',rows:[['Republic World',1,4100,2200,14000,11.4,'31%','+1'],['Firstpost',2,800,600,1100,7.2,'20%','+1'],['WION',3,800,400,900,6.8,'19%','0'],['Times Now',4,700,100,1200,5.9,'16%','-1'],['India Today',5,600,300,1000,5.1,'14%','0']]},
    business:{title:'Business News',rows:[['CNBC Awaaz',1,5200,3100,9200,20.3,'27%','+1'],['CNBC TV18',2,4300,2600,7600,17.6,'24%','0'],['Zee Business',3,3600,2100,6100,14.1,'19%','-1'],['NDTV Profit',4,2100,1200,3900,8.1,'11%','0'],['moneycontrol',5,1800,1000,3400,7.3,'10%','+1'],['ET NOW',6,1500,900,2800,6.6,'9%','-1']]},
    tamil:{title:'Tamil News',rows:[['Polimer News',1,9800,6100,16400,189.2,'30%','+1'],['Puthiyathalaimurai TV',2,7600,4800,12200,122.4,'19%','0'],['News Tamil 24X7',3,6900,4200,11000,110.8,'17%','+1'],['Thanthi TV',4,6200,3900,10080,100.8,'16%','-1'],['News18 Tamil Nadu',5,4400,2700,8100,65.3,'10%','0'],['Sun News Tamil',6,3500,2200,6900,50.3,'8%','0']]},
    'regional-india':{title:'Regional India',rows:[['Thanthi TV',1,6200,3900,10080,100.8,'24%','+1'],['ABP Ananda',2,3900,2500,6200,72.4,'17%','0'],['News18 Kerala',3,3300,2100,5400,64.8,'15%','+1'],['Polimer News',4,9800,6100,16400,189.2,'30%','+2']]}
  };
  const fmt = n => Number(n).toLocaleString('en-IN');
  const render = (key) => {
    const m = demo[key] || demo.hindi, body = $('#market-channel-body'); if (!body) return;
    $('#market-title').textContent = m.title;
    body.innerHTML = m.rows.map(r => `<tr><td>#${r[1]}</td><td><strong>${r[0]}</strong></td><td>${fmt(r[2])}</td><td>${fmt(r[3])}</td><td>${fmt(r[4])}</td><td>${r[5]}M</td><td>${r[6]}</td><td class="${String(r[7]).startsWith('-')?'trend-down':'trend-up'}">${r[7]}</td></tr>`).join('');
    const total = m.rows.reduce((a,r)=>a+Number(r[5]),0), avg = m.rows.reduce((a,r)=>a+Number(r[2]),0)/m.rows.length, peak = Math.max(...m.rows.map(r=>r[4]));
    $('#market-total').textContent = `${total.toFixed(1)}M`; $('#market-average').textContent = fmt(Math.round(avg)); $('#market-peak').textContent = fmt(peak); $('#market-leader').textContent = `${m.rows[0][0]} · ${m.rows[0][6]}`;
  };
  const enhanceHero = () => {
    const hero = $('.stax9-hero'), copy = $('.hero-copy');
    if (!hero || !copy || hero.dataset.enhanced) return;
    hero.dataset.enhanced = '1';
    hero.innerHTML = `<div class="stax9-visual"><div class="stax9-glow"></div><img src="stax9-explorer.svg" alt="STAX9 futuristic explorer" loading="eager"><span class="stax9-tag">STAX9 · EXPLORER</span></div><div class="stax9-copy"><strong>MEET STAX9</strong><p>A curious, precise intelligence companion built to look beyond the obvious.</p><span>Same data. A wider view.</span></div>`;
    const trust = document.createElement('blockquote');
    trust.className = 'hero-trust';
    trust.innerHTML = '<span>“</span><strong>Trust cannot be demanded.<br>It must be engineered.</strong><span>”</span>';
    copy.insertBefore(trust, copy.querySelector('.hero-actions'));
    const stx = document.createElement('div');
    stx.className = 'hero-stx';
    stx.innerHTML = '<span>STATAXIS INTELLIGENCE</span><b>STX Index™</b><p>A composite signal that brings audience, growth, momentum, consistency, competition and event evidence into one qualified view.</p><a href="#stx">Explore STX Index →</a>';
    copy.appendChild(stx);
    if (!document.getElementById('stax9-hero-enhancements')) {
      const style = document.createElement('style');
      style.id = 'stax9-hero-enhancements';
      style.textContent = `.hero-trust{margin:8px 0 2px;max-width:620px;padding:16px 22px;border-left:3px solid #12c8ff;background:linear-gradient(90deg,#071a2d,#071a2d00);color:#eaf6ff;font-size:18px;line-height:1.35;display:flex;gap:10px;align-items:flex-start}.hero-trust span{color:#12c8ff;font-size:28px;line-height:.8}.hero-trust strong{font-weight:850;letter-spacing:-.01em}.hero-stx{margin-top:16px;max-width:620px;padding:13px 16px;border:1px solid #1b5578;border-radius:11px;background:#071a2de6}.hero-stx>span{display:block;color:#12c8ff;font-size:8px;font-weight:900;letter-spacing:.16em}.hero-stx b{display:block;color:#fff;font-size:18px;margin-top:3px}.hero-stx p{margin:4px 0 7px;color:#8fa8c1;font-size:10px;line-height:1.45}.hero-stx a{color:#12c8ff;text-decoration:none;font-size:9px;font-weight:900;letter-spacing:.08em}.stax9-hero{min-height:430px!important;position:relative;overflow:hidden}.stax9-visual{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}.stax9-visual img{position:relative;z-index:2;width:min(100%,520px);height:100%;object-fit:contain;filter:drop-shadow(0 18px 40px #008cff2b)}.stax9-glow{position:absolute;width:330px;height:330px;border-radius:50%;background:radial-gradient(circle,#0dafff3b,transparent 68%);filter:blur(2px)}.stax9-tag{position:absolute;right:10px;top:12px;z-index:4;color:#12c8ff;font-size:8px;font-weight:900;letter-spacing:.16em}.stax9-copy{z-index:5}.hero-card{grid-template-columns:1.05fr .95fr}.hero-copy h1{max-width:720px}@media(max-width:900px){.hero-card{grid-template-columns:1fr}.stax9-hero{min-height:420px!important}.hero-stx{max-width:100%}}@media(max-width:620px){.hero-trust{font-size:15px}.stax9-hero{min-height:350px!important}.stax9-visual img{width:95%}.hero-stx p{font-size:9px}}.live-stx{display:inline-flex;align-items:center;gap:5px;margin-left:7px;padding:2px 6px;border:1px solid #1b5578;border-radius:6px;color:#12c8ff;font-size:9px;font-weight:900;letter-spacing:.04em}.live-stx em{color:#8fa8c1;font-style:normal;font-weight:700}`;
      document.head.appendChild(style);
    }
  };
  const renderStx = (stx) => {
    if (!stx || stx.score == null) return;
    const score = Number(stx.score), confidence = Number(stx.confidence || 0);
    $('#stx-score') && ($('#stx-score').textContent = score.toFixed(1));
    $('#stx-score-large') && ($('#stx-score-large').textContent = score.toFixed(1));
    $('#stx-confidence') && ($('#stx-confidence').textContent = `Confidence ${Math.round(confidence * 100)}%`);
    $('#stx-meter') && ($('#stx-meter').style.width = `${Math.max(0, Math.min(100, score))}%`);
    const box = $('#signal-drivers'), components = stx.components || {};
    if (box && Object.keys(components).length) {
      const labels = [['audience','Audience'],['growth','Growth'],['momentum','Momentum'],['acceleration','Acceleration'],['consistency','Consistency'],['competitive_position','Competition'],['anomaly_event','Anomaly / Event']];
      box.innerHTML = labels.map(([key,label]) => { const value = Number(components[key] ?? 0); return `<div><span>${label}</span><i style="width:${Math.max(0,Math.min(100,value))}%"></i><b>${Math.round(value)}%</b></div>`; }).join('');
    }
  };
  const renderCompetition = (channels) => {
    const box = $('#competition-rows'); if (!box || !Array.isArray(channels) || !channels.length) return;
    const leader = channels[0], leaderViews = Number(leader.view_delta || 0);
    const top = channels.slice(0,4);
    box.innerHTML = top.map((r,i) => {
      const movement = r.rank_change == null ? '—' : `${r.rank_change >= 0 ? '+' : ''}${r.rank_change}`;
      const share = leaderViews > 0 && r.view_delta != null ? `${(Number(r.view_delta)/leaderViews*100).toFixed(1)}% of leader` : '—';
      return `<div><span>${r.channel || r.name || 'Channel'}</span><b>#${r.rank ?? i+1}</b><em>${movement} · ${share}</em></div>`;
    }).join('');
    $('#competitive-rank') && ($('#competitive-rank').textContent = `#${leader.rank || 1}`);
    $('#competitive-share') && ($('#competitive-share').textContent = leader.view_delta == null ? 'Measured position' : 'Current leader by observed view movement');
    $('#competition-note') && ($('#competition-note').textContent = 'LIVE DATA · Rank movement and relative share are calculated from the persisted observation window.');
  };
  const renderContent = (payload) => {
    const items = payload?.content?.top_videos;
    const box = $('.content-grid'); if (!box || !Array.isArray(items) || !items.length) return;
    box.innerHTML = items.slice(0,4).map((v,i) => {
      const delta = v.view_delta == null ? '—' : `+${fmt(v.view_delta)} views`;
      const velocity = v.view_velocity_per_minute == null ? 'velocity unavailable' : `${fmt(Math.round(v.view_velocity_per_minute))}/min`;
      const classification = String(v.classification || 'OBSERVED').toUpperCase();
      return `<div class="content-item"><span>#${String(i+1).padStart(2,'0')}</span><b>${v.title || 'Untitled video'}</b><small>${classification} · ${velocity}</small><strong>${delta}</strong></div>`;
    }).join('');
    $('.content-intel .badge') && ($('.content-intel .badge').textContent = 'LIVE DATA');
  };
  const loadChannelContent = async (channelId, period, scope) => {
    if (!channelId) return;
    try {
      const res = await fetch(`/api/v1/channels/${encodeURIComponent(channelId)}/media-intelligence?period=${encodeURIComponent(period)}&stream_scope=${encodeURIComponent(scope)}&top_videos=4`,{headers:{Accept:'application/json',Authorization:`Bearer ${token()}`} });
      if (!res.ok) return;
      renderContent(await res.json());
    } catch (_) {}
  };
  const tryLive = async () => {
    const access = token(); if (!access) return;
    try {
      const p = $('#market-period')?.value || '7d', scope = $('#market-scope')?.value || 'all';
      const res = await fetch(`/api/v1/markets/report?period=${encodeURIComponent(p)}&stream_scope=${encodeURIComponent(scope)}&limit=12`,{headers:{Accept:'application/json',Authorization:`Bearer ${access}`}});
      if (!res.ok) return;
      const data = await res.json();
      if (!Array.isArray(data.channels) || !data.channels.length) return;
      const body=$('#market-channel-body');
      $('#market-title').textContent = data.filters?.market || data.filters?.language || 'Live Market';
      body.innerHTML=data.channels.map((r,i)=>{ const stx=r.stx || {}; const badge=stx.score==null?'':`<span class="live-stx">STX ${Number(stx.score).toFixed(1)} <em>${Math.round(Number(stx.confidence||0)*100)}%</em></span>`; return `<tr><td>#${r.rank ?? i+1}</td><td><strong>${r.channel || r.name || 'Channel'}</strong></td><td>${r.current_concurrent==null?'—':fmt(r.current_concurrent)}</td><td>${r.average_concurrent==null?'—':fmt(Math.round(r.average_concurrent))}</td><td>${r.peak_concurrent==null?'—':fmt(r.peak_concurrent)}</td><td>${r.view_delta==null?'—':fmt(r.view_delta)}</td><td>${data.market?.view_delta_total?((Number(r.view_delta||0)/Number(data.market.view_delta_total))*100).toFixed(1)+'%':'—'}</td><td><span class="${r.rank_change>=0?'trend-up':'trend-down'}">${r.rank_change==null?'—':`${r.rank_change>=0?'+':''}${r.rank_change}`}</span>${badge}</td></tr>`; }).join('');
      renderStx(data.channels[0].stx);
      renderCompetition(data.channels);
      await loadChannelContent(data.channels[0].channel_id, p, scope);
      $('#api-status').textContent='Live'; $('#api-dot').classList.add('connected'); $('#api-note').textContent='LIVE DATA · Rendered from persisted StatAxis observations.';
    } catch (_) {}
  };
  document.addEventListener('DOMContentLoaded',()=>{
    enhanceHero();
    document.querySelectorAll('.market-tab').forEach(btn=>btn.addEventListener('click',()=>render(btn.dataset.market)));
    $('#market-period')?.addEventListener('change',tryLive); $('#market-scope')?.addEventListener('change',tryLive);
    render('hindi'); setTimeout(tryLive,250);
    const score=$('#stx-score-large'); const small=$('#stx-score'); if(score&&small){const sync=()=>score.textContent=small.textContent;sync();new MutationObserver(sync).observe(small,{childList:true,subtree:true});}
  });
})();
