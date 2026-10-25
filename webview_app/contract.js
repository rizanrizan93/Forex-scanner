export function runtimeState(view,now=Date.now()) {
  const safe={status:'DATA_TIDAK_VALID',reason:'Data indikator tidak valid.',fresh:false,entry:null,seconds:0};
  if(!view||view.schema!=='RIZAN_WEBVIEW_V1'||view.execution_authority!==false||view.execution_influence!==false)return safe;
  if(view.mode==='demo')return{status:'MODE_UJI',reason:'Contoh historis untuk uji tampilan; bukan sinyal live.',fresh:true,entry:null,seconds:0};
  if(['SIMBOL_TIDAK_DIDUKUNG','DATA_TIDAK_VALID','FEED_TIDAK_TERSEDIA'].includes(view.status))return{...safe,status:view.status,reason:view.reason};
  const until=Date.parse(view.fresh_until),source=Date.parse(view.source_as_of),bar=Date.parse(view.candle_as_of);
  if(!Number.isFinite(until)||!Number.isFinite(source)||!Number.isFinite(bar)||source>now+5000||bar>now||now>=until)return{...safe,status:'DATA_TERLAMBAT',reason:'Data belum baru. Sinyal lama tidak boleh dikejar.'};
  if(view.status==='ENTRY_MANUAL'){
    const expiry=Date.parse(view.entry_until),e=view.entry,side=e?.side==='BUY'?1:e?.side==='SELL'?-1:0;
    const geometry=side&&['entry','sl','tp'].every(k=>Number.isFinite(e[k])&&e[k]>0)&&side*(e.entry-e.sl)>0&&Math.abs(side*(e.tp-e.entry)-5.5*side*(e.entry-e.sl))<Math.max(.000001,Math.abs(e.entry-e.sl)*.000001);
    if(!geometry||!Number.isFinite(expiry)||now>=expiry)return{status:'SINYAL_LEWAT',reason:'Jendela entry telah lewat. Tunggu sinyal berikutnya.',fresh:true,entry:null,seconds:0};
    return{status:view.status,reason:view.reason,fresh:true,entry:e,seconds:Math.max(0,Math.ceil((expiry-now)/1000))};
  }
  return{status:view.status,reason:view.reason,fresh:true,entry:null,seconds:0};
}

export function priceBounds(rows) {
  const prices=rows.flatMap(r=>[r.low,r.high,r.buy_trigger_next,r.sell_trigger_estimate]).filter(n=>Number.isFinite(n)&&n>0);
  if(!prices.length)return[0,1];
  const lo=Math.min(...prices),hi=Math.max(...prices),pad=Math.max((hi-lo)*.12,.25);
  return[lo-pad,hi+pad];
}
