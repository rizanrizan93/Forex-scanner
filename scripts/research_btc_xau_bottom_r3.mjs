#!/usr/bin/env node
// Research-only R3 replay: no orders, credentials, account access or live changes.
// Deterministic fixed-source historical daily bars, intended for audit/reproduction.
// This is an exploratory event study and NOT an out-of-sample trading strategy.
import fs from 'node:fs';
const SOURCES = [
  {asset:'BTC', url:'https://raw.githubusercontent.com/daniegitx1/btc-price-history/549fc2d8a73e23b14c50cf5057b89dc5a66b368d/data/btc_usd_daily.csv', threshold:0.35, peakDays:365, stopBuffer:0.01, fee:0.002, testStart:2020},
  {asset:'GOLD',url:'https://raw.githubusercontent.com/tohaitrieu/market-history/39ba69bb9b0cbb4bd972ebdb5dc3df729d637c8c/data/commodities/GOLD/GOLD-D1.csv',threshold:0.15,peakDays:252,stopBuffer:0.005,fee:0.001,testStart:2016}
];
const MODELS=['WATCH','HOLD5','BREAK5','BREAK10','BREAK10RSI','RECLAIM20','RECLAIM50'];
const csv=s=>s.trim().split(/\r?\n/).slice(1).map(l=>l.split(','));
function parse(s,asset){
  let d=csv(s).map(z=>asset==='BTC'
    ?{date:z[0],o:+z[1],h:+z[2],l:+z[3],c:+z[4]}
    :{date:z[2].slice(0,10),o:+z[3],h:+z[4],l:+z[5],c:+z[6]});
  d=d.filter(x=>x.c>0&&x.l>0&&x.h>0).sort((a,b)=>a.date.localeCompare(b.date));
  if(d.length<5000 || d.some((x,i)=>i>0&&x.date===d[i-1].date))throw Error('Invalid history or duplicate date');
  return d;
}
function lo(a,i,j,f){let z=Infinity;for(let k=Math.max(0,i);k<=j;k++)z=Math.min(z,a[k][f]);return z}
function hi(a,i,j,f){let z=-Infinity;for(let k=Math.max(0,i);k<=j;k++)z=Math.max(z,a[k][f]);return z}
function ma(a,i,n){let z=0;for(let k=i-n+1;k<=i;k++)z+=a[k].c;return z/n}
function rsiSimple(a,i,n=14){let up=0,dn=0;for(let j=i-n+1;j<=i;j++){const z=a[j].c-a[j-1].c;if(z>0)up+=z;else dn-=z}return 100*up/(up+dn||1)}
function analyze(d,config,model){
  let events=[],skipUntil=0;
  for(let i=370;i<d.length-120;i++){
    if(i<=skipUntil)continue;
    let w=d[i],support=lo(d,i-20,i-1,'l'),p=hi(d,i-config.peakDays,i-1,'h'),dd=w.c/p-1;
    let spring=w.l<support&&w.c>support&&(w.c-w.l)/(w.h-w.l||1)>0.6;
    if(!spring||dd> -config.threshold)continue;
    let trigger=-1,window=model==='WATCH'?0:model==='HOLD5'?5:20;
    for(let k=i;k<=i+window;k++){
      if(model!=='WATCH'&&k<=i)continue;
      if(k>i&&lo(d,i+1,k,'l')<w.l)break;
      let q=d[k],p=d[k-1],pass=false;
      switch(model){
        case 'WATCH':pass=true;break;
        case 'HOLD5':pass=k===i+5&&q.c>w.c&&q.c>ma(d,k,20);break;
        case 'BREAK5':pass=q.c>hi(d,k-5,k-1,'h')&&q.c>ma(d,k,20);break;
        case 'BREAK10':pass=q.c>hi(d,k-10,k-1,'h')&&q.c>ma(d,k,20);break;
        case 'BREAK10RSI':pass=q.c>hi(d,k-10,k-1,'h')&&q.c>ma(d,k,20)&&rsiSimple(d,k)>=40;break;
        case 'RECLAIM20':pass=q.c>ma(d,k,20)&&p.c<=ma(d,k-1,20);break;
        case 'RECLAIM50':pass=q.c>ma(d,k,50)&&p.c<=ma(d,k-1,50);break;
      }
      if(pass){trigger=k;break}
    }
    if(trigger<0)continue;
    let entry=d[trigger+1].o*(1+config.fee/2),stop=w.l*(1-config.stopBuffer);
    let risk=entry-stop;
    if(risk<=0||risk/entry>0.3)continue;
    let target=entry+2*risk,exit=d[trigger+90].c,outcome='TIMEOUT',bar=90;
    for(let k=trigger+1;k<=trigger+90;k++){
      // Conservative SL-first precedence if both SL/TP within same OHLC candle.
      if(d[k].l<=stop){exit=stop;outcome='SL';bar=k-trigger;break}
      if(d[k].h>=target){exit=target;outcome='TP';bar=k-trigger;break}
    }
    let forward=d.slice(trigger+1,trigger+91);
    let fLow=Math.min(...forward.map(x=>x.l));
    events.push({
      watch_date:w.date,entry_signal_date:d[trigger].date,entry_date:d[trigger+1].date,
      split:(+d[trigger].date.slice(0,4)>=config.testStart)?'validation':'development',
      entry,stop,target,risk_pct:100*risk/entry,confirmation_lag_bars:trigger-i,
      exit_reason:outcome,exit_bars:bar,result_R:(exit*(1-config.fee/2)-entry)/risk,
      return_90d_no_stop_pct:100*(d[trigger+90].c/entry-1),
      new_low_90d:fLow<w.l,
      post_signal_MAE_90d_pct:100*(fLow/entry-1)
    });
    skipUntil=trigger+90; // 90-bar cooldown after an entry, not an exact trade overlap guarantee
  }
  return events;
}
function stats(ev){const n=ev.length;if(!n)return {n:0};const mean=k=>ev.reduce((s,e)=>s+e[k],0)/n;
  return {n,TP:ev.filter(e=>e.exit_reason==='TP').length,SL:ev.filter(e=>e.exit_reason==='SL').length,
   TIMEOUT:ev.filter(e=>e.exit_reason==='TIMEOUT').length,
   mean_net_R:+mean('result_R').toFixed(3),
   pct_positive_unstopped_90d:+(100*ev.filter(e=>e.return_90d_no_stop_pct>0).length/n).toFixed(1),
   pct_new_low_next_90d:+(100*ev.filter(e=>e.new_low_90d).length/n).toFixed(1),
   avg_post_signal_MAE_90d_pct:+mean('post_signal_MAE_90d_pct').toFixed(2),
   avg_lag_bars:+mean('confirmation_lag_bars').toFixed(1),
   avg_stop_risk_pct:+mean('risk_pct').toFixed(1)};
}
function fmt(r){return '| '+[r.asset,r.model,r.split,r.n,r.TP??'-',r.SL??'-',r.mean_net_R??'-',r.pct_new_low_next_90d??'-',r.avg_stop_risk_pct??'-'].join(' | ')+' |'}
let result={generated_at_utc:new Date().toISOString(),study:'BTC-XAU Bottom Detection R3',method:'exploratory, daily OHLC; no macro or onchain features',source_commits:SOURCES.map(({asset,url})=>({asset,url})),model_parameters:{models:MODELS,max_confirmation_days:20,cooldown_bars:90,horizon_bars:90,TP_R:2,SL_first_same_bar:true},assets:[]};
for(const c of SOURCES){
  const res=await fetch(c.url);if(!res.ok)throw Error(c.asset+' download HTTP '+res.status);
  const d=parse(await res.text(),c.asset);
  const asset={asset:c.asset,first:d[0].date,last:d.at(-1).date,count:d.length,threshold_pct:100*c.threshold,studies:[]};
  for(const model of MODELS){
    let events=analyze(d,c,model);
    asset.studies.push({model,development:stats(events.filter(e=>e.split==='development')),
      validation:stats(events.filter(e=>e.split==='validation')),validation_events:events.filter(e=>e.split==='validation')});
  }
  result.assets.push(asset);
}
fs.mkdirSync('research_outputs/bottom_r3',{recursive:true});
fs.writeFileSync('research_outputs/bottom_r3/results.json',JSON.stringify(result,null,2)+'\n');
let rows=[];for(const a of result.assets){for(const r of a.studies){for(const split of ['development','validation'])rows.push({asset:a.asset,model:r.model,split,...r[split]})}}
const md=[
 '# BTC/XAU Bottom Detection R3 — fixed-source exploratory replay',
 '',
 '**Research-only. Not a live or production trading signal.**',
 '',
 'Data pinned to source Git commits. Bitcoin: Bitstamp daily through 2026-11-21. GOLD-D1: through 2026-02-05 (no Nov 2026 gold).',
 '',
 'A watch candidate is a 20-day sell-side sweep that closes back above the prior 20-day low with close-position >60%, during a trailing-high drawdown >=35% BTC or >=15% gold.',
 '',
 'Entry uses next candle open plus half estimated round-trip cost. Stop below sweep low by 1% (BTC) or 0.5% (gold). TP=2R. Earliest SL wins if both extremes print in one bar. Maximum hold 90 calendar candles. Cooldown >=90 bars. No leverage assumed.',
 '',
 'Costs: 0.20% round-trip BTC and 0.10% gold. No funding or market impact. Results may not match broker execution. RSI is simple 14-bar, not Wilder smoothed. Gold feed includes Sunday stamps.',
 '',
 '## Summary',
 '| Asset | Model | Split | N | TP | SL | Mean net R | New low within 90d % | Avg stop distance % |',
 '|---|---|---|---:|---:|---:|---:|---:|---:|',
 ...rows.map(fmt),
 '',
 '## Limitations',
 '- Selected parameters/period splits are exploratory and are not untouched out-of-sample. Many strategies were examined before this test.',
 '- Independent bear market episodes are few; some trades share a macro regime. All error bars are wide.',
 '- The 90-bar post-signal MAE and no-stop 90d return include periods AFTER an SL/TP exit and are strictly event-study metrics, not realized P&L.',
 '- A positive return 90 days later does NOT imply a usable entry: stop-out can occur first.',
 '- For a fair final validation, collect independent H1/H4 data, official DXY/yields, BTC on-chain, and hold out full future episodes.',
 '- No orders, API credentials, deployment or changes to Frozen V1.',
 '',
 '## Provenance',
 ...SOURCES.map(s=>'- '+s.asset+': '+s.url),
 ''
].join('\n');
fs.writeFileSync('research_outputs/bottom_r3/report.md',md);
console.log(md);
