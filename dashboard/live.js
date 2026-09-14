(() => {
  const $ = (s) => document.querySelector(s);
  const text = (s, v) => { const n = $(s); if (n && v != null) n.textContent = v; };
  const get = async (u) => { const r = await fetch(u, {headers:{Accept:"application/json"}}); if (!r.ok) throw new Error(`${r.status}`); return r.json(); };
  const periods = {Today:1,"3 Weeks":21,"1 Month":30,"1 Year":365};

  function renderSeries(p){
    const pts = p?.points || [], svg=$("#series-chart"); if(!svg) return;
    if(!pts.length){ text("#series-note","No persisted observation series available."); return; }
    const vals=pts.map(x=>Number(x.value)).filter(Number.isFinite), min=Math.min(...vals), max=Math.max(...vals), range=Math.max(max-min,1), w=700,h=220;
    const path=pts.map((x,i)=>{const X=8+(i/Math.max(pts.length-1,1))*684,Y=10+(1-(Number(x.value)-min)/range)*200;return `${i?"L":"M"}${X.toFixed(1)} ${Y.toFixed(1)}`}).join(" ");
    svg.innerHTML=`<path class="gridline" d="M0 30H700 M0 95H700 M0 160H700 M0 220H700"/><path class="area" d="${path} L692 220 L8 220 Z"/><path class="trend" d="${path}"/>`;
    const compact=(v)=>Number(v).toLocaleString("en-IN",{notation:"compact",maximumFractionDigits:1});
    const axis=$("#series-axis"); if(axis) axis.innerHTML=`<span>${compact(max)}</span><span>${compact((max+min)/2)}</span><span>${compact(min)}</span>`;
    text("#series-note",`${pts.length} persisted observation points · cumulative view count`);
    text("#audience-value",vals.at(-1)?.toLocaleString("en-IN") || "—");
  }
  function renderHistory(p){
    [["last_3_weeks","#hist-3w","#hist-3w-meta","3 Weeks"],["last_1_month","#hist-1m","#hist-1m-meta","1 Month"],["last_1_year","#hist-1y","#hist-1y-meta","1 Year"]].forEach(([k,v,m,l])=>{const c=p?.comparisons?.[k]?.change||{};text(v,c.score_delta==null?"—":`${c.score_delta>=0?"+":""}${Number(c.score_delta).toFixed(1)}`);text(m,c.sufficient_data?l:`${l} · insufficient history`);});
  }
  function renderCompetitive(p,id){
    const c=$("#competitive-rows"); if(!c) return; const rows=p?.channels||[];
    c.innerHTML=rows.slice(0,5).map(x=>{const d=x.last_1_month?.change?.score_delta; const mark=x.channel_id===id?"●":d==null?"→":d>0?"▲":d<0?"▼":"→"; return `<div class="${x.channel_id===id?"selected-row":""}"><span>${x.rank}. ${x.name}</span><b>${x.current?.score==null?"—":Number(x.current.score).toFixed(1)}</b><em>${mark}</em></div>`;}).join("");
  }
  function renderSignals(p){
    const m=Number(p?.average_audience_momentum_per_minute), v=Number(p?.average_view_velocity_per_minute);
    text("#momentum-value",Number.isFinite(m)?(m===0?"Flat":m>0?"Positive":"Negative"):"—");
    text("#momentum-delta",Number.isFinite(m)?`${m>=0?"+":""}${m.toFixed(2)}/min concurrent`:"Insufficient live data");
    text("#position-value",Number.isFinite(v)?`${v>=0?"+":""}${v.toFixed(1)}/min`:"—");
    text("#position-meta","Recent view velocity");
  }
  async function loadChannel(ch,days,all){
    const overview=await get(`/api/v1/channels/${ch.id}`), best=(overview.videos||[]).find(v=>v.score!=null);
    if(best){const intel=await get(`/api/v1/videos/${best.video_id}/intelligence`); text("#selected-video",best.title||best.youtube_video_id); const idx=intel.stx_index||intel; text("#stx-score",idx.score==null?"—":Number(idx.score).toFixed(1)); text("#stx-confidence",Number.isFinite(Number(idx.confidence))?`Confidence ${Math.round(Number(idx.confidence)*100)}% · ${idx.available_signals||0} signals`:"Confidence unavailable"); text("#view-data",(intel.data||[]).join(" ")); text("#view-analysis",(intel.analysis||[]).join(" ")); text("#view-conclusion",intel.view||"No persisted StatAxis View available.");}
    const ids=all.slice(0,3).map(x=>x.id).join(",");
    const [hist,series,signals,competitive]=await Promise.all([get(`/api/v1/channels/${ch.id}/comparison`),get(`/api/v1/channels/${ch.id}/series?days=${days}`),get(`/api/v1/channels/${ch.id}/signals?hours=24`),get(`/api/v1/channels/compare?ids=${ids}`)]);
    renderHistory(hist); renderSeries(series); renderSignals(signals); renderCompetitive(competitive,ch.id);
  }
  document.addEventListener("DOMContentLoaded",async()=>{
    const status=$("#api-status"), sel=$("#channel-select"), filters=[...document.querySelectorAll(".filter")];
    try{
      const data=await get("/api/v1/channels"), all=data.channels||[]; if(!all.length) throw new Error("no channels");
      sel.innerHTML=all.map(c=>`<option value="${c.id}">${c.name}</option>`).join(""); let days=30;
      const refresh=async()=>{status.textContent="Loading…"; status.classList.remove("connected"); const ch=all.find(c=>String(c.id)===sel.value)||all[0]; await loadChannel(ch,days,all); status.textContent="Live API"; status.classList.add("connected");};
      await refresh(); sel.addEventListener("change",()=>refresh().catch(()=>status.textContent="API unavailable"));
      filters.forEach(b=>b.addEventListener("click",()=>{days=periods[b.textContent.trim()]||30;filters.forEach(x=>x.classList.toggle("active",x===b));refresh().catch(()=>status.textContent="API unavailable")}));
    }catch(e){status.textContent="Preview"; text("#api-note","Dashboard preview · API unavailable");}
  });
})();
