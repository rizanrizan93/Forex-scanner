from pathlib import Path
import json,csv,gzip,hashlib,math,zipfile,shutil,difflib,os,io
from datetime import datetime,timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
r=Path(__file__).resolve().parent;out=r/'delivery';out.mkdir(exist_ok=True)
j=json.loads((r/'replay/matrix.json').read_text());reports=j['Reports'];assert len(reports)==8
def atomic_write(p,b):
 tmp=p.with_name(p.name+'.writing')
 with tmp.open('wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
 assert tmp.read_bytes()==b
 os.replace(tmp,p)
 assert p.read_bytes()==b
metrics=[];annual=[];monthly=[];dirs=[];ledger=[];audits=[];annual_dirs=[]
for x in reports:
 s=x['Summary'];name=s['cfg']['Name'];mode,path=name.split('_PATH_')
 assert not x['CashFlows'],name
 assert not x['Open'] and not x['Errors'] and not s['AccountingBlock'] and not s['Quarantined'] and s['TerminalForcedCloses']==0
 h=x['BrokerHistory'];cash=100+sum(a['NetProfit'] for a in h);res=cash-s['EndingBalance'];assert abs(res)<1e-5,(name,res)
 for a in h:assert abs(a['NetProfit']-(a['GrossProfit']+a['Commissions']+a['ExitCommission']+a['Swap']))<1e-7
 peak=100;dd=0
 for a in x['CashEvents']:peak=max(peak,a['Balance']);dd=max(dd,(peak-a['Balance'])/peak)
 assert abs(dd*100-s['MaxClosedDDPct'])<1e-8
 btc=[a for a in h if a['SymbolName']=='BTCUSD']
 for a in btc:
  entry=datetime.fromisoformat(a['EntryTime'].replace('Z','+00:00'));close=datetime.fromisoformat(a['ClosingTime'].replace('Z','+00:00'))
  assert entry.weekday()<5
  friday=(entry+timedelta(days=(4-entry.weekday())%7)).replace(hour=21,minute=30,second=5,microsecond=0)
  assert close<=friday,(name,entry,close)
 if mode=='BASE':
  old=json.loads((r.parent/f'portfolio_weekend/replay/weekday_{path}_22.json').read_text())['Reports'][0]
  for key in ['EndingBalance','MaxEquityDDPct','MaxClosedDDPct','PF','Baskets','BtcBaskets','BtcBuys','BtcSells']:assert abs(s[key]-old['Summary'][key])<1e-8,(name,key)
  assert h==old['BrokerHistory'],'BASELINE_FILL_LEDGER_MISMATCH'
 win=sum(a['Pnl']>0 for a in x['Ledger']);btcpnl=sum(a['NetProfit'] for a in btc)
 row={'case':name,'balance':s['EndingBalance'],'floating_dd_pct':s['MaxEquityDDPct'],'balance_dd_pct':s['MaxClosedDDPct'],'pf':s['PF'],'win_rate_pct':100*win/s['Baskets'],'baskets':s['Baskets'],'btc_baskets':s['BtcBaskets'],'btc_buy':s['BtcBuys'],'btc_sell':s['BtcSells'],'btc_net_pnl':btcpnl,'errors':s['ErrorCount'],'cash_residual':res}
 metrics.append(row)
 annual += [dict(case=name,**a) for a in x['Annual']]
 monthly += [dict(case=name,**a) for a in x['Monthly']]
 ledger += [dict(case=name,**a) for a in h]
 for symbol in ['XAUUSD','EURUSD','BTCUSD']:
  for side in [0,1]:
   v=[a for a in h if a['SymbolName']==symbol and a['TradeType']==side]
   dirs.append(dict(case=name,symbol=symbol,side='BUY' if side==0 else 'SELL',fills=len(v),gross_pnl=sum(a['GrossProfit'] for a in v),gross_winning_net_trades=sum(max(0,a['NetProfit']) for a in v),gross_losing_net_trades=sum(min(0,a['NetProfit']) for a in v),commissions=sum(a['Commissions']+a['ExitCommission'] for a in v),funding=sum(a['Swap'] for a in v),net_pnl=sum(a['NetProfit'] for a in v)))
 for year in range(2019,2027):
  for symbol in ['XAUUSD','EURUSD','BTCUSD']:
   v=[a for a in h if a['SymbolName']==symbol and a['ClosingTime'].startswith(str(year))]
   annual_dirs.append(dict(case=name,year=year,symbol=symbol,net_closed_pnl=sum(a['NetProfit'] for a in v),buy_net=sum(a['NetProfit'] for a in v if a['TradeType']==0),sell_net=sum(a['NetProfit'] for a in v if a['TradeType']==1),fills=len(v)))
 audits.append(dict(case=name,cash_residual=res,btc_positions_checked=len(btc),weekend_or_cutoff_violations=0,baseline_exact_fill_parity=mode=='BASE',balance_dd_recomputed=dd*100))
 compressed=gzip.compress(json.dumps(x,separators=(',',':')).encode(),compresslevel=9,mtime=0)
 assert json.loads(gzip.decompress(compressed))==x
 atomic_write(out/f'{name}_RAW.json.gz',compressed)
for name,rows in [('METRICS.csv',metrics),('ANNUAL.csv',annual),('MONTHLY.csv',monthly),('DIRECTION_CONTRIBUTIONS.csv',dirs),('ANNUAL_DIRECTION_CONTRIBUTIONS.csv',annual_dirs),('FILL_LEDGER.csv',ledger)]:
 with (out/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
# Independent eligibility timestamp audit.
sigs=list(csv.DictReader((r/'replay/matrix.json.signals.csv').open()))
assert all(a['available']<=a['at'] for a in sigs)
source={}
frozen=json.loads((r.parent/'portfolio_weekend/delivery_v121/FREEZE_MANIFEST.json').read_text())
for name,want in frozen['source_sha256'].items():
 p=r/name
 if p.is_file():
  got=hashlib.sha256(p.read_bytes()).hexdigest();assert got==want, name;source[name]=got
(out/'AUDIT.json').write_text(json.dumps({'cases':audits,'source_sha256':source,'source_unchanged':True,'macro_timestamp_future_reads':0,'signal_opportunities':len(sigs),'macro_vintage_certified':False,'fomc_decisions':63},indent=2))
for name in ['PROTOCOL.json','prepare_filters.py','bootstrap.py','run_local.py','finalize.py','verify_zip.py','build_gate_tests.py','REPRODUCE.md']:shutil.copy2(r/name,out/name)
shutil.copytree(r/'data',out/'data',dirs_exist_ok=True)
shutil.copytree(r/'replay',out/'replay_adapter',dirs_exist_ok=True,ignore=shutil.ignore_patterns('*.json','*.partial','*.log','*.dll','*.runtimeconfig.json','*.rsp','*.signals.csv'))
shutil.copy2(r/'replay/matrix.json.signals.csv',out/'SIGNAL_ELIGIBILITY.csv')
shutil.copy2(r/'replay/GATE_TEST_RESULTS.json',out/'GATE_TEST_RESULTS.json')
shutil.copytree(r/'source',out/'source',dirs_exist_ok=True)
shutil.copytree(r/'tests',out/'tests',dirs_exist_ok=True)
# Plot actual hourly snapshots; numeric max DD is from event/second observations, not sampled chart.
fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
for x in reports:
 name=x['Summary']['cfg']['Name']
 if not name.endswith('_A'):continue
 c=x['Curve'];t=[datetime.fromisoformat(a['At'].replace('Z','+00:00')) for a in c]
 axes[0].plot(t,[a['Equity'] for a in c],label=name.split('_')[0],linewidth=1)
 axes[1].plot(t,[100*(a['Peak']-a['Equity'])/a['Peak'] for a in c],linewidth=.8)
axes[0].set_yscale('log');axes[0].set_ylabel('Equity USD (log)');axes[0].legend();axes[1].set_ylabel('Equity DD % (hourly)');axes[1].axhline(56,color='red',linestyle='--');axes[0].set_title('BTC macro/event challenger — shared XAU/EUR/BTC account, Path A')
fig.tight_layout();fig.savefig(out/'EQUITY_DD.png',dpi=150);plt.close(fig)
base={m['case'][-1]:m for m in metrics if m['case'].startswith('BASE')}
lines=['# Uji BTC Macro dan Event — 20 Oktober 2026','','Konfigurasi entry, SL/TP, risiko, leverage dan weekend tetap. Hanya kelayakan entry BTC berubah. XAU/EUR tidak diubah. Modal $100 tanpa top-up, 2019–9 Oktober 2026. Delapan replay aktual: 4 varian × 2 lintasan OHLC.','', '| Varian | Saldo akhir | Floating DD | PF | Basket BTC BUY/SELL | Net BTC |','|---|---:|---:|---:|---:|---:|']
for m in metrics:lines.append(f"| {m['case']} | ${m['balance']:,.2f} | {m['floating_dd_pct']:.2f}% | {m['pf']:.3f} | {m['btc_buy']}/{m['btc_sell']} | ${m['btc_net_pnl']:,.2f} |")
lines += ['','## Perubahan terhadap baseline','','| Varian | Perubahan saldo Path A | Perubahan saldo Path B | Perubahan DD A/B (poin persentase) |','|---|---:|---:|---:|']
for mode in ['MACRO','EVENT','BOTH']:
 pair={m['case'][-1]:m for m in metrics if m['case'].startswith(mode+'_')}
 changes={p:100*(pair[p]['balance']/base[p]['balance']-1) for p in ['A','B']}
 lines.append(f"| {mode} | {changes['A']:+.2f}% | {changes['B']:+.2f}% | {pair['A']['floating_dd_pct']-base['A']['floating_dd_pct']:+.3f} / {pair['B']['floating_dd_pct']-base['B']['floating_dd_pct']:+.3f} |")
lines += ['','Keputusan: tetap pertahankan baseline frozen. Peningkatan pada satu lintasan saja bukan bukti ketahanan; data makro current-vintage tetap memerlukan validasi point-in-time sebelum pertimbangan penerapan.','']
lines += ['','## Aturan terkunci','','BASE: tanpa filter tambahan. MACRO: BUY hanya jika perubahan yield riil DFII10 selama 20 observasi terakhir <=0; SELL >=0. Observasi tersedia setelah lag dua hari kerja federal AS, batas stale 10 hari. EVENT: tidak entry dari 1 menit setelah pengumuman suku bunga FOMC sampai 24 jam sesudahnya. BOTH: kedua syarat. Filter tidak menutup posisi yang sudah ada. Tidak memakai surprise, hasil rapat, kalender kejadian mendadak sebelum publikasi, atau kalender hasil PnL.','','## Interpretasi','','Hasil ini eksperimen awal dari aturan tetap, bukan pencarian threshold terbaik. Bandingkan saldo dan DD kedua path, serta kontribusi BTC; perubahan saldo portfolio juga melibatkan compounding dan peluang XAU/EUR yang bergeser. PnL BTC yang ditampilkan berasal dari akun gabungan, bukan hasil BTC standalone. Semua periode sudah pernah dipakai memilih strategi BTC asli, sehingga bukan out-of-sample murni.','','## Batas validasi','','DFII10 berasal dari historical current-vintage FRED, bukan ALFRED point-in-time. Lag mencegah akses observasi hari yang sama, tetapi tidak membuktikan bebas revisi atau seluruh keterlambatan publikasi. Filter ini belum layak dipromosikan atas dasar hasil historis saja. Event hanya 63 keputusan suku bunga FOMC reguler dan dua pemotongan darurat 2020; belum CPI/NFP dan bukan seluruh pernyataan Fed. Kalender DST menggunakan America/New_York. XAU masih menggunakan adapter macro rekonstruksi lama yang belum tersertifikasi. Dua lintasan harga adalah diagnostik OHLC, bukan tick broker atau batas konservatif seluruh lintasan M1. Jadwal BTC replay asumsi Senin00–Jumat22UTC; native memakai MarketHours. Biaya dasar saja, belum stress filter baru. Frozen V1.2.1 dan live tidak diubah.','','## Audit','','Baseline kedua path wajib identik seluruh fill ledger dengan artefak frozen sebelumnya. Semua saldo direkonsiliasi dari gross PnL + komisi + swap; balance DD dihitung ulang dari cash events. Semua posisi BTC diperiksa terhadap weekend dan cutoff Jumat21:30UTC. Hash source strategi harus sama dengan frozen manifest. Lihat AUDIT.json, data checksums PROTOCOL.json, SIGNAL_ELIGIBILITY.csv, FILL_LEDGER.csv, ANNUAL.csv dan MONTHLY.csv.']
(out/'LAPORAN_BTC_MACRO_EVENT.md').write_text('\n'.join(lines)+'\n')
manifest={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='SHA256_MANIFEST.json'}
(out/'SHA256_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
z=r/'RIZAN_BTC_MACRO_EVENT_WEEKEND_20261020.zip'
buffer=io.BytesIO()
with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as f:
 for p in out.rglob('*'):
  if p.is_file():f.write(p,str(p.relative_to(out)))
atomic_write(z,buffer.getvalue())
print(json.dumps(metrics,indent=2));print('ZIP',z.stat().st_size,hashlib.sha256(z.read_bytes()).hexdigest())
