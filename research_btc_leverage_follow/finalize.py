from pathlib import Path
import json,gzip,collections,csv,hashlib,shutil,zipfile
r=Path(__file__).resolve().parent;root=r.parent.parent;d=root/'delivery_lf122';d.mkdir(exist_ok=True);out=r/'analysis';out.mkdir(exist_ok=True)
metrics=[];ledger=[];annual=[];monthly=[]
for path in ['A','B']:
 a=json.load(gzip.open(r/'results'/f'LF122_L200_{path}.json.gz'));s=a['Summary'];h=a['BrokerHistory'];g=collections.defaultdict(float)
 for v in h:g['|'.join(v['Label'].split('|')[:2])]+=v['NetProfit']
 metrics.append(dict(path=path,balance=s['EndingBalance'],floating_dd=s['MaxEquityDDPct'],balance_dd=s['MaxClosedDDPct'],pf=s['PF'],win_rate=100*sum(v>0 for v in g.values())/len(g),baskets=s['Baskets'],xau=s['XauBaskets'],eur=s['EurBaskets'],btc=s['BtcBaskets'],btc_buy=s['BtcBuys'],btc_sell=s['BtcSells'],btc_leverage=s['BtcLeverage'],xau_eur_leverage=s['cfg']['Leverage'],cash_residual=100+sum(v['NetProfit'] for v in h)-s['EndingBalance'],errors=s['ErrorCount'],positions=s['OpenPositions'],dd56_pass=s['MaxEquityDDPct']<=56))
 ledger += [{'path':path,**v} for v in h];annual += [{'path':path,**v} for v in a['Annual']];monthly += [{'path':path,**v} for v in a['Monthly']]
def save(name,rows):
 with (out/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
for n,v in [('METRICS.csv',metrics),('FILL_LEDGER.csv',ledger),('ANNUAL.csv',annual),('MONTHLY.csv',monthly)]:save(n,v)
tests={}
for n in ['SettlementTests','PortfolioTests','TimingTests','WeekendTests','btc','LeverageTests']:
 v=json.loads((r/'checks'/f'{n}.json').read_text());assert v['Pass'];tests[n]=v['Checks']
assert sum(tests.values())==1357
(out/'TEST_COUNTS.json').write_text(json.dumps(tests,indent=2))
base=root/'frozen';unchanged={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for sub in ['xau','eur'] for p in (base/'source'/sub).glob('*.cs')}
for n,h in unchanged.items():assert hashlib.sha256((r/'work'/n).read_bytes()).hexdigest()==h
for n in ['BtcCore.cs','BtcWeekendPolicy.cs']:assert (base/'source'/n).read_bytes()==(r/'work/source'/n).read_bytes()
algo=r/'work/native/RizanXauEurBtcPortfolio_RESEARCH_LEVERAGE_FOLLOW_V1_2_2.algo';shutil.copy2(algo,d/algo.name)
report=['# LF122 — BTC mengikuti margin engine XAU/EUR','',
'Varian riset terpisah dari FROZEN WEEKEND V1.2.1. Replay memakai leverage 200× pada XAU, EUR dan BTC; native memakai GetEstimatedMargin broker untuk masing-masing simbol. Tidak ada asumsi bahwa leverage akun 200× menjamin leverage simbol BTC 200× di broker. Tidak ada deployment atau order live.','',
'Floor BTC 10× dihapus dari perhitungan ukuran awal, reservasi margin dan gate gabungan. Account.Margin menjadi reservasi margin bersama seperti instrumen lain; binary search menghormati GetEstimatedMargin aktual, termasuk leverage simbol lebih rendah. Profil BUY/SELL, risk 23%/18%, margin budget 95%/30%, cap risiko gabungan 20,75%, margin gabungan 50%, entry/SL/TP/hold/sinyal dan pengaman weekend tetap. Native identitas robot baru RizanXauEurBtcLeverageFollow, assembly 1.2.2.0 dan checkpoint terpisah; default EnableTrading=false.','',
'Modal $100 tanpa top-up. Periode 2019-01-01 sampai bar 2026-10-09 21:58 UTC. Input/checksum, biaya normal, spread, delay dua detik, indikator weekday dan dua path sama dengan audit sebelumnya.','',
'| Ukuran | PATH A | PATH B |','|---|---:|---:|']
for label,key in [('Saldo akhir USD','balance'),('Floating DD %','floating_dd'),('Balance DD %','balance_dd'),('Profit factor','pf'),('Win rate basket %','win_rate'),('Basket','baskets'),('BTC BUY','btc_buy'),('BTC SELL','btc_sell')]:
 vals=[f"{v[key]:,.5f}" if key in ['floating_dd','balance_dd','pf'] else f"{v[key]:,.2f}" if isinstance(v[key],float) else str(v[key]) for v in metrics];report.append('| '+label+' | '+' | '.join(vals)+' |')
report += ['','Kedua path masih gagal floating DD ≤56%; bukan promosi pengganti baseline beku. Saldo V1.2.1 tetap $14.168.707,28/$18.043.274,23 dengan DD 62,94884%/63,77678%; angka baru tidak mengubah rekaman versi lama.','',
'Seluruh 1.357 pemeriksaan lulus: 1.326 regresi sebelumnya dan 31 pemeriksaan leverage/margin tambahan. Fixture recovery menunjuk checkpoint LF122 yang terisolasi; syarat keselamatan regresi tidak dilonggarkan. Build native resmi 0 error/0 warning. Tidak ada posisi akhir, terminal forced close, error runtime, quarantine atau accounting block; cash residual < $0,00001 dan audit cutoff weekend lolos.','',
'Tes khusus membuktikan account leverage 200× tidak mengalahkan leverage simbol BTC: broker 2×/5×/10×/200× menghasilkan batas volume berbeda, tetap mematuhi risiko/margin bersama. Margin invalid (NaN atau leverage nol) memblokir order; OFF tidak mengirim order.','',
'Ini source replay OHLC dengan fake broker, bukan tick parity native/FULL_PARITY. Kalender replay Senin00–Jumat22 UTC belum tersertifikasi historis broker/DST; macro belum vintage-certified. Stress biaya/delay versi LF122 belum dijalankan; hasil stress V1.2.1 tidak dipindahkan ke sini.','',
'Reproduksi: paket menyertakan work/source, work/replay, run_local.py, native build tools dan source tests. Gunakan SDK 8.0.426/runtime 8.0.32; input dan dependensi native sama dengan paket audit V1.2.1. Jalankan run_local.py untuk compile Replay.dll, lalu run_pair.py A dan B dengan input di folder workspace inputs/. prepare.py dapat merekonstruksi work/ bila work/ audit sebelumnya beserta vendor dependencies sudah tersedia.','',
'Seluruh delapan source strategi XAU/EUR, BtcCore dan BtcWeekendPolicy tetap identik byte. Source patch ada di CHANGE_FROM_V121.diff. METRICS, ledger, tahunan, bulanan, dua raw replay dan bukti tes disertakan.']
(r/'README.md').write_text('\n'.join(report)+'\n');shutil.copy2(r/'README.md',d/'LAPORAN_LF122_BTC_MENGIKUTI_ENGINE.md')
print(json.dumps(metrics,indent=2))
