(() => {
  'use strict';
  const data=JSON.parse(document.getElementById('rizan-data').textContent);
  const $=id=>document.getElementById(id);
  const fmt=new Intl.NumberFormat('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const date=value=>{const d=new Date(value);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat('id-ID',{timeZone:'Asia/Jakarta',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d)+' WIB':'—';};
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let mode='live',count=72;
  try{const saved=localStorage.getItem('rizan-webview-mode');if(saved==='demo')mode='demo';}catch{}
  function draw(rows) {
    const host=$('chart');
    if(!rows.length){host.innerHTML='<div class="empty">Menunggu candle yang dapat diverifikasi.<br>Sinyal lama tidak menjadi entry baru.</div>';return;}
    const W=Math.max(280,host.clientWidth),H=host.clientHeight||245,L=6,R=58,T=20,B=28,pw=W-L-R,ph=H-T-B;
    const [lo,hi]=priceBounds(rows),y=p=>T+(hi-p)/(hi-lo)*ph,x=i=>L+(i+.5)*pw/rows.length,bw=Math.max(2,Math.min(10,pw/rows.length*.6));
    let svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Chart candle XAU M5 dari core cBot">`;
    for(let i=0;i<5;i++){const p=lo+(hi-lo)*i/4,Y=y(p);svg+=`<line x1="${L}" x2="${W-R}" y1="${Y}" y2="${Y}" stroke="var(--line)" stroke-width=".8"/><text x="${W-R+7}" y="${Y+4}" fill="var(--muted)" font-size="10" font-family="system-ui">${fmt.format(p)}</text>`;}
    for(const [key,color]of[['buy_trigger_next','var(--blue)'],['sell_trigger_estimate','var(--amber)']]){
      let path='',open=false;rows.forEach((r,i)=>{const p=r[key];if(Number.isFinite(p)&&p>0){path+=`${open?'L':'M'}${x(i).toFixed(2)},${y(p).toFixed(2)} `;open=true;}else open=false;});
      svg+=`<path d="${path}" fill="none" stroke="${color}" stroke-width="1.3" stroke-dasharray="4 4"/>`;
    }
    rows.forEach((r,i)=>{
      const X=x(i),color=r.close>=r.open?'var(--green)':'var(--red)',top=y(Math.max(r.open,r.close)),height=Math.max(1,Math.abs(y(r.open)-y(r.close)));
      svg+=`<g><title>${esc(date(r.at_utc))} · O ${fmt.format(r.open)} H ${fmt.format(r.high)} L ${fmt.format(r.low)} C ${fmt.format(r.close)}${r.signal_side?` · ${r.signal_side===1?'BUY':'SELL'} teknis`:''}</title><line x1="${X}" x2="${X}" y1="${y(r.high)}" y2="${y(r.low)}" stroke="${color}"/><rect x="${X-bw/2}" y="${top}" width="${bw}" height="${height}" fill="${color}" rx=".5"/>`;
      if(r.signal_side===1){const Y=y(r.low)+12;svg+=`<path d="M${X},${Y-5}l-5,9h10Z" fill="var(--green)"/>`;}
      if(r.signal_side===-1){const Y=y(r.high)-12;svg+=`<path d="M${X},${Y+5}l-5,-9h10Z" fill="var(--red)"/>`;}
      svg+='</g>';
    });
    for(const i of[0,Math.floor((rows.length-1)/2),rows.length-1]){
      const label=new Intl.DateTimeFormat('id-ID',{timeZone:'Asia/Jakarta',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(rows[i].at_utc));
      svg+=`<text x="${x(i)}" y="${H-7}" fill="var(--muted)" font-size="10" text-anchor="${i===0?'start':i===rows.length-1?'end':'middle'}" font-family="system-ui">${label} WIB</text>`;
    }
    svg+='</svg>';host.innerHTML=svg;
  }
  const names={MODE_UJI:'MODE UJI',DATA_TIDAK_VALID:'DATA BELUM VALID',DATA_TERLAMBAT:'MENUNGGU DATA BARU',FEED_TIDAK_TERSEDIA:'FEED BELUM TERSEDIA',MENUNGGU_INDIKATOR:'MENUNGGU INDIKATOR',MENUNGGU_POLA:'MENUNGGU POLA',PERSIAPAN_BUY:'ABA-ABA BUY',PERSIAPAN_SELL:'ABA-ABA SELL',DI_LUAR_SESI:'DI LUAR SESI',ENTRY_MANUAL:'ACUAN ENTRY MANUAL',SINYAL_LEWAT:'SINYAL SUDAH LEWAT',BLOCK:'SYARAT BELUM LENGKAP',POSISI_AKTIF:'BUKAN ENTRY BARU',SIMBOL_TIDAK_DIDUKUNG:'KHUSUS XAUUSD',WARMUP:'PEMANASAN DATA'};
  function tick() {
    const view=data[mode],state=runtimeState(view),f=view.frame;
    $('clock').textContent=new Intl.DateTimeFormat('id-ID',{timeZone:'Asia/Jakarta',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date());
    $('status').textContent=names[state.status]||'MENUNGGU DATA';$('reason').textContent=state.reason;
    $('status-panel').dataset.tone=state.entry?'ready':['BLOCK','DATA_TIDAK_VALID'].includes(state.status)?'blocked':'wait';
    $('countdown').textContent=state.entry?`${state.seconds} dtk`:'';
    $('test-banner').hidden=mode!=='demo';$('live').classList.toggle('selected',mode==='live');$('demo').classList.toggle('selected',mode==='demo');
    $('source-time').textContent=date(view.source_as_of);$('bar-time').textContent=date(view.candle_as_of);
    const visible=state.fresh&&f;
    $('price').textContent=visible?fmt.format(f.close):'—';
    for(const [id,key]of[['h1','h1_bias'],['m15','m15_bias']]){const v=visible?f[key]:null;$(id).textContent=v===1?'BUY':v===-1?'SELL':v===0?'NETRAL':'—';$(id).className=v===1?'buy':v===-1?'sell':'';}
    $('buy-level').textContent=visible&&f.buy_trigger_next?fmt.format(f.buy_trigger_next):'—';
    $('sell-level').textContent=visible&&(f.sell_trigger_estimate||f.sell_sweep_next)?fmt.format(f.sell_trigger_estimate||f.sell_sweep_next):'—';
    $('sell-label').textContent=visible&&f.sell_trigger_estimate?'SELL · ESTIMASI KONFIRMASI':'SELL · HIGH PANTAUAN';
    $('entry-panel').hidden=!state.entry;
    for(const [id,key]of[['entry-price','entry'],['entry-sl','sl'],['entry-tp','tp']])$(id).textContent=state.entry?fmt.format(state.entry[key]):'—';
    $('entry-side').textContent=state.entry?state.entry.side+' · ACUAN MANUAL':'ACUAN MANUAL';
    const key=mode+':'+state.fresh+':'+count+':'+view.candle_as_of;
    if(key!==tick.chartKey){draw(state.fresh?(view.history||[]).slice(-count):[]);tick.chartKey=key;}
  }
  function change(next){mode=next;try{localStorage.setItem('rizan-webview-mode',mode);}catch{}tick();}
  $('live').addEventListener('click',()=>change('live'));$('demo').addEventListener('click',()=>change('demo'));
  document.querySelectorAll('[data-count]').forEach(b=>b.addEventListener('click',()=>{count=Number(b.dataset.count);document.querySelectorAll('[data-count]').forEach(x=>x.classList.toggle('selected',x===b));tick();}));
  document.addEventListener('visibilitychange',tick);
  window.addEventListener('resize',()=>{tick.chartKey=null;tick();});
  tick();setInterval(tick,1000);
})();
