from pathlib import Path
import csv,json,hashlib,io,gzip
from datetime import datetime,timedelta,timezone
from bisect import bisect_right
from pandas.tseries.holiday import USFederalHolidayCalendar
r=Path(__file__).resolve().parent;prior=r.parent/'btc_macro_event';out=r/'output';out.mkdir(exist_ok=True)
holidays=set(USFederalHolidayCalendar().holidays('2018-01-01','2027-01-01').strftime('%Y-%m-%d'))
def avail(day):
 d=datetime.fromisoformat(day).replace(tzinfo=timezone.utc);n=0
 while n<2:
  d+=timedelta(days=1)
  if d.weekday()<5 and d.strftime('%Y-%m-%d') not in holidays:n+=1
 return d
series={};coverage=[]
for filename in ['risk_close.csv','rates.csv']:
 rows=list(csv.DictReader((r/'data'/filename).open()))
 for col in rows[0]:
  if col=='observation_date':continue
  a=[]
  for row in rows:
   day=row['observation_date']
   if not row[col] or not '2018-01-01'<=day<='2026-10-09':continue
   a.append({'date':day,'available':avail(day),'value':float(row[col])})
  lookback=5 if col=='VIXCLS' else 20
  for i,x in enumerate(a):x['change']=((x['value']/a[i-lookback]['value']-1) if col=='NASDAQ100' else x['value']-a[i-lookback]['value']) if i>=lookback else None
  series[col]=a
  coverage.append(dict(series=col,observations=len(a),first=a[0]['date'],last=a[-1]['date'],lookback=lookback))
# Fixed hypotheses: only record strong disagreement. No selection of thresholds using PnL.
protocol={'scope':'Data feasibility and conditional trade diagnostic ONLY; no new shared-wallet replay and no new trading rule deployed.','rules':{'RISK_VETO':'Flag when side*NASDAQ100_20obs_return<0 AND side*VIX_5obs_change>0.','TRIPLE_VETO':'RISK_VETO plus side*DGS2_20obs_change>0.'},'availability':'Two US federal business-day conservative lag; stale observation>10 calendar days invalid. Current-vintage not certified point-in-time.','evaluation':'Classify previously executed baseline BTC fills; arithmetic slice of old trades is NOT a replay of a new strategy. Cannot infer changed ending balance, DD or profitability.'}
(r/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
signals=list(csv.DictReader((prior/'delivery/SIGNAL_ELIGIBILITY.csv').open()));feature=[]
for sig in signals:
 at=datetime.fromisoformat(sig['at'].replace('Z','+00:00'));side=int(sig['side']);f=dict(at=at.isoformat(),side=side);valid=True
 for col,a in series.items():
  k=bisect_right([x['available'] for x in a],at)-1;x=a[k] if k>=0 else None
  if x is None or x['change'] is None or (at.date()-datetime.fromisoformat(x['date']).date()).days>10:valid=False
  if x is not None:
   assert x['available']<=at
   f[col+'_observation']=x['date'];f[col+'_available']=x['available'].isoformat();f[col+'_change']=x['change']
 f['valid']=valid
 f['risk_veto']=valid and side*f['NASDAQ100_change']<0 and side*f['VIXCLS_change']>0
 f['triple_veto']=f['risk_veto'] and side*f['DGS2_change']>0
 feature.append(f)
features={datetime.fromisoformat(x['at']):x for x in feature};diagnostics=[]
for sidepath in ['A','B']:
 rep=json.loads(gzip.decompress((prior/f'delivery/BASE_PATH_{sidepath}_RAW.json.gz').read_bytes()))
 btc=[h for h in rep['BrokerHistory'] if h['SymbolName']=='BTCUSD']
 for rule in ['risk_veto','triple_veto']:
  for group in ['flagged','not_flagged']:
   selected=[]
   for h in btc:
    t=datetime.fromisoformat(h['EntryTime'].replace('Z','+00:00')).replace(minute=0,second=0,microsecond=0);f=features[t]
    assert f['valid']
    if bool(f[rule])==(group=='flagged'):selected.append(h)
   diagnostics.append(dict(path=sidepath,rule=rule,group=group,trades=len(selected),wins=sum(h['NetProfit']>0 for h in selected),mean_net_return_on_entry_notional_pct=sum(h['NetProfit']/(h['VolumeInUnits']*h['EntryPrice'])*100 for h in selected)/len(selected) if selected else None,warning='Conditional baseline slice; not a new replay or counterfactual portfolio result'))
for name,rows in [('COVERAGE.csv',coverage),('SIGNAL_MACRO_FEATURES.csv',feature),('CONDITIONAL_DIAGNOSTIC.csv',diagnostics)]:
 with (out/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
status={'coverage':coverage,'signals_checked':len(feature),'all_three_inputs_available':sum(x['valid'] for x in feature),'risk_veto_flags':sum(x['risk_veto'] for x in feature),'triple_veto_flags':sum(x['triple_veto'] for x in feature),'future_observation_access':0,'macro_vintage_certified':False,'new_replay_executed':False,'live_changed':False,'raw_data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (r/'data').iterdir() if p.is_file()}}
(out/'DATA_AUDIT.json').write_text(json.dumps(status,indent=2));print(json.dumps(status,indent=2));print(json.dumps(diagnostics,indent=2))
