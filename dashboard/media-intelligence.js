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
      body.innerHTML=data.channels.map((r,i)=>`<tr><td>#${r.rank ?? i+1}</td><td><strong>${r.channel || r.name || 'Channel'}</strong></td><td>${r.current_concurrent==null?'—':fmt(r.current_concurrent)}</td><td>${r.average_concurrent==null?'—':fmt(Math.round(r.average_concurrent))}</td><td>${r.peak_concurrent==null?'—':fmt(r.peak_concurrent)}</td><td>${r.view_delta==null?'—':fmt(r.view_delta)}</td><td>${data.market?.view_delta_total?((Number(r.view_delta||0)/Number(data.market.view_delta_total))*100).toFixed(1)+'%':'—'}</td><td>${r.rank_change==null?'—':`<span class="${r.rank_change>=0?'trend-up':'trend-down'}">${r.rank_change>=0?'+':''}${r.rank_change}</span>`}</td></tr>`).join('');
      $('#api-status').textContent='Live'; $('#api-dot').classList.add('connected'); $('#api-note').textContent='LIVE DATA · Rendered from persisted StatAxis observations.';
    } catch (_) {}
  };
  document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('.market-tab').forEach(btn=>btn.addEventListener('click',()=>render(btn.dataset.market)));
    $('#market-period')?.addEventListener('change',tryLive); $('#market-scope')?.addEventListener('change',tryLive);
    render('hindi'); setTimeout(tryLive,250);
    const score=$('#stx-score-large'); const small=$('#stx-score'); if(score&&small){const sync=()=>score.textContent=small.textContent;sync();new MutationObserver(sync).observe(small,{childList:true,subtree:true});}
  });
})();