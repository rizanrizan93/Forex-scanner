from pathlib import Path
import shutil,difflib,json,hashlib
r=Path(__file__).resolve().parent;base=r.parent/'lf122/work';base=base if base.exists() else r.parent/'research_btc_leverage_follow/work';w=r/'work';w.mkdir(exist_ok=True)
for p in base.rglob('*'):
 if p.is_file() and (p.suffix in ['.cs','.csproj'] or p.name=='run_local.py'):
  q=w/p.relative_to(base);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
p=w/'replay/Replay.cs';before=p.read_text();s=before
s=s.replace('bdata.Rows.Where(v=>Environment.GetEnvironmentVariable("BTC_FULL_INDICATORS")=="1"||BrokerCalendar.Open(v.At)).Select','bdata.Rows.Select')
s=s.replace('"../xau-tape.json"','"../fresh_xau_tape.json"').replace('"../eur-tape.json"','"../fresh_eur_tape.json"')
s=s.replace('BtcWeekendBarsFiltered=true,','BtcWeekendBarsFiltered=false,BtcIndicatorSource="Bitstamp OHLC all seven days",NativeSevenDayFeedIntegrated=false,')
p.write_text(s)
(r/'CHANGE_FROM_LF122.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True),s.splitlines(True),fromfile='LF122/replay/Replay.cs',tofile='SEVEN_DAY_L200/replay/Replay.cs')))
config={'id':'RZ-BTC-7D-WEEKEND-L200','based_on':'LF122 source c187174e27894abad35f010b6ee6766971055665','indicator_source':'Bitstamp OHLC M1 all seven days, aggregate H1/H4 in UTC','indicator_seed':'2019-01-01 UTC','execution':'FP Markets intended; research fake broker, Monday00-Friday22 UTC assumed','entry_buffer_minutes':60,'flatten_buffer_minutes':30,'btc_leverage_model':200,'xau_eur_leverage_model':200,'portfolio_risk_cap':0.2075,'entry_margin_cap':0.5,'btc_fixed_10x_floor':False,'native_seven_day_external_feed_integrated':False,'native_deployment_ready':False,'trading_enabled':False,'live_changed':False,'existing_native_LF122_uses_broker_GetBars':True,'full_parity':False}
(r/'CONFIG.json').write_text(json.dumps(config,indent=2));print(config['id'])
