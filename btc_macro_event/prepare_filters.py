from pathlib import Path
import csv,json,hashlib
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from pandas.tseries.holiday import USFederalHolidayCalendar
holidays=set(USFederalHolidayCalendar().holidays("2018-01-01","2027-01-01").strftime("%Y-%m-%d"))
r=Path(__file__).resolve().parent
# Fixed before inspecting any challenger PnL. Only regular policy decisions and two emergency rate cuts.
dates={2019:'01-30 03-20 05-01 06-19 07-31 09-18 10-30 12-11',2020:'01-29 03-03 03-15 04-29 06-10 07-29 09-16 11-05 12-16',2021:'01-27 03-17 04-28 06-16 07-28 09-22 11-03 12-15',2022:'01-26 03-16 05-04 06-15 07-27 09-21 11-02 12-14',2023:'02-01 03-22 05-03 06-14 07-26 09-20 11-01 12-13',2024:'01-31 03-20 05-01 06-12 07-31 09-18 11-07 12-18',2025:'01-29 03-19 05-07 06-18 07-30 09-17 10-29 12-10',2026:'01-28 03-18 04-29 06-17 07-29 09-16'}
events=[]
for y,ds in dates.items():
 for md in ds.split():
  d=f'{y}-{md}';hr=10 if d=='2020-03-03' else 17 if d=='2020-03-15' else 14
  at=datetime.fromisoformat(d).replace(hour=hr,tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
  events.append({'release_utc':at.isoformat(),'block_from_utc':(at+timedelta(minutes=1)).isoformat(),'block_to_utc':(at+timedelta(hours=24)).isoformat(),'source':f'https://www.federalreserve.gov/newsevents/pressreleases/monetary{d.replace("-","")}a.htm'})
with (r/'data/fomc.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(events[0]));w.writeheader();w.writerows(events)
rows=[]
for x in csv.DictReader((r/'data/fred_daily.csv').open()):
 if not x['DFII10']:continue
 day=datetime.fromisoformat(x['observation_date']).replace(tzinfo=timezone.utc)
 if day.year<2018 or day>datetime(2026,10,15,tzinfo=timezone.utc):continue
 # Two US federal business-day lag at midnight UTC, conservatively after next-business-day H15 16:15 ET.
 avail=day;n=0
 while n<2:
  avail+=timedelta(days=1)
  if avail.weekday()<5 and avail.strftime("%Y-%m-%d") not in holidays:n+=1
 rows.append({'observation_utc':day.isoformat(),'available_utc':avail.isoformat(),'value':float(x['DFII10'])})
for i,x in enumerate(rows):x['delta20']=x['value']-rows[i-20]['value'] if i>=20 else ''
with (r/'data/real_yield.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
protocol={'baseline_source_commit':'1d6ad83f285f293b103342073b637fa16e597fb9','variants':['BASE','MACRO','EVENT','BOTH'],'macro':'DFII10 latest observation available under conservative 2-US-federal-business-day lag; delta vs 20 prior nonmissing observations. BUY delta<=0, SELL delta>=0. Reject missing/stale >10 days. No threshold search.','event':'Block new entry from 1min after public FOMC rate decision through +24h. No pre-event knowledge, no outcome/surprise/direction used. 63 regular decisions/emergency rate cuts; not CPI/NFP or every Fed announcement.','macro_vintage_certified':False,'limitation':'Current-vintage historical DFII10, may contain revisions; lag prevents same-day access but is not ALFRED point-in-time certification. XAU macro reconstruction unchanged and uncertified. Diagnostic OHLC paths, not tick parity.','parameters':'No entry/SL/TP/risk/leverage/calendar changes; all three instruments share same account and execution. BTC10x XAU/EUR200x inherited frozen baseline.','data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (r/'data').glob('*.csv')}}
(r/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
print('events',len(events),'macro rows',len(rows),rows[-1])
