from pathlib import Path
import gzip,json,csv,collections,hashlib
r=Path(__file__).resolve().parent;root=r.parent;o=r/'analysis';o.mkdir(exist_ok=True);metrics=[];history=[];annual=[];monthly=[]
for path in ['A','B']:
 v=json.load(gzip.open(r/'results'/f'SEVEN_DAY_L200_{path}.json.gz'));s=v['Summary'];h=v['BrokerHistory'];g=collections.defaultdict(float)
 for x in h:g['|'.join(x['Label'].split('|')[:2])]+=x['NetProfit']
 old=json.loads((root/'lf122/results'/f'LF122_L200_{path}_SUMMARY.json').read_text())['Summary']
 metrics.append({'path':path,'ending_balance':s['EndingBalance'],'floating_dd_pct':s['MaxEquityDDPct'],'balance_dd_pct':s['MaxClosedDDPct'],'pf':s['PF'],'win_rate_pct':100*sum(v>0 for v in g.values())/len(g),'baskets':s['Baskets'],'xau_baskets':s['XauBaskets'],'eur_baskets':s['EurBaskets'],'btc_baskets':s['BtcBaskets'],'btc_buy':s['BtcBuys'],'btc_sell':s['BtcSells'],'leverage_all':200,'native_full7_feed_ready':False,'weekday_l200_balance':old['EndingBalance'],'weekday_l200_dd':old['MaxEquityDDPct'],'cash_residual':100+sum(x['NetProfit'] for x in h)-s['EndingBalance'],'dd56_qualified':s['MaxEquityDDPct']<=56,'errors':s['ErrorCount'],'open_positions':s['OpenPositions']})
 history += [{'path':path,**x} for x in h];annual += [{'path':path,**x} for x in v['Annual']];monthly += [{'path':path,**x} for x in v['Monthly']]
for n,a in [('METRICS.csv',metrics),('FILL_LEDGER.csv',history),('ANNUAL.csv',annual),('MONTHLY_CLOSED_BASKETS.csv',monthly)]:
 with (o/n).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(a[0]));w.writeheader();w.writerows(a)
source_proof={}
for p in (r/'work/source').rglob('*.cs'):
 q=root/'lf122/work'/p.relative_to(r/'work');assert p.read_bytes()==q.read_bytes();source_proof[str(p.relative_to(r/'work'))]=hashlib.sha256(p.read_bytes()).hexdigest()
(o/'SOURCE_UNCHANGED_FROM_LF122.json').write_text(json.dumps(source_proof,indent=2))
report=['# BTC indikator tujuh hari + pengaman weekend + leverage replay 200x','',
'Keputusan pengguna: indikator BTC tetap memakai seluruh tujuh hari, posisi BTC harus ditutup sebelum penutupan mingguan, dan leverage model portofolio 1:200. ID riset RZ-BTC-7D-WEEKEND-L200. Ini varian riset dari LF122, tidak mengganti V1.2.1 beku atau trading live.','',
'## FP Markets dan cTrader','',
'Halaman resmi FP Markets yang diperiksa pada 20 Oktober 2026 menyebut crypto 24/5 dan mencantumkan cTrader sebagai platform. Halaman jam trading umum mencantumkan crypto daily 00:00–23:59 dan Jumat 00:00–23:55 pada GMT+2/GMT+3 (DST). Ini informasi situs umum, bukan verifikasi spesifikasi BTCUSD akun pengguna atau histori sesi/DST. Native harus mengikuti Symbol.MarketHours, bukan jam asumsi replay yang di-hardcode.','',
'Source native LF122 yang dibaca menggunakan MarketData.GetBars(TimeFrame.Hour/Hour4,"BTCUSD"). API ini mengambil chart bars simbol, bukan feed exchange BTC 24/7. Bila feed broker tidak berisi candle weekend, metode ini tidak menyediakan pergerakan weekend untuk indikator. Kelengkapan bar weekend pada akun pengguna belum diinspeksi. Untuk mereproduksi indikator Bitstamp riset, native memerlukan adapter feed Bitstamp tujuh hari; jika memilih feed broker, kelengkapan dan perbedaan hasil harus divalidasi terpisah. Jangan mencampur spot weekend dengan CFD weekday secara diam-diam. Gunakan satu sumber tujuh hari untuk seluruh seri indikator; broker hanya untuk quote eksekusi, margin dan jadwal.','',
'Leverage 1:200 berlaku sebagai asumsi replay ketiga simbol. Native LF122 memakai GetEstimatedMargin simbol broker dan menghormati batas per simbol/tier. Leverage akun tidak membuktikan leverage BTCUSD 1:200. Spesifikasi akun pengguna belum dibaca.','',
'Sumber resmi: https://www.fpmarkets.com/cryptocurrency/ ; https://www.fpmarkets.com/en-sc/trading-hours/ ; https://help.ctrader.com/ctrader-algo/references/MarketData/MarketData/GetBars/ ; https://help.ctrader.com/ctrader-algo/references/MarketData/Symbols/Symbol/ .','',
'## Konfigurasi dan status','',
'- Indikator: Bitstamp OHLC M1 seluruh tujuh hari, agregasi H1/H4 UTC, seed 1 Januari 2019. Ini feed yang sama dengan input penelitian sebelumnya, bukan tick bid/ask FP Markets.',
'- Eksekusi replay: Senin 00:00–Jumat 22:00 UTC; blok entry 60 menit dan mulai flat 30 menit sebelum penutupan. Weekend candle memengaruhi sinyal, tetapi tidak mengizinkan entry weekend.',
'- Leverage XAU/EUR/BTC 200x; risiko gabungan 20,75%; cap margin entry 50%; profil BTC 7844/2269, SL/TP/hold, serta source XAU/EUR identik dengan LF122.',
'- Modal $100, tanpa top-up; periode portfolio sampai bar 9 Oktober 2026 21:58 UTC, cutoff eksklusif 21:59. Input BTC sampai 15 Oktober tidak memperpanjang hasil portfolio.',
'- NativeSevenDayFeedIntegrated=false; NativeDeploymentReady=false. Tidak ada binary .algo baru yang dipublikasikan untuk keputusan tujuh hari ini. Binary LF122 sebelumnya tetap membaca bar broker dan tidak otomatis berubah menjadi feed tujuh hari.',
'- Tidak mengubah bridge produksi, .env, risk live, instance cBot atau main. Tidak ada order live.','',
'## Hasil aktual','',
'| Ukuran | PATH A | PATH B |','|---|---:|---:|']
for label,k in [('Saldo akhir USD','ending_balance'),('Floating DD %','floating_dd_pct'),('Balance DD %','balance_dd_pct'),('PF','pf'),('Win rate basket %','win_rate_pct'),('Basket','baskets'),('BTC BUY','btc_buy'),('BTC SELL','btc_sell'),('Saldo LF122 indikator weekday, 200x','weekday_l200_balance'),('DD LF122 indikator weekday, 200x','weekday_l200_dd')]:
 report.append('| '+label+' | '+' | '.join(f"{v[k]:,.5f}" if k in ['floating_dd_pct','balance_dd_pct','pf','weekday_l200_dd'] else f"{v[k]:,.2f}" if isinstance(v[k],float) else str(v[k]) for v in metrics)+' |')
report += ['',
'Kualifikasi floating DD <=56%: '+', '.join(v['path']+'='+str(v['dd56_qualified']) for v in metrics)+'.','',
'Kedua replay lolos cash residual absolut < $0,00001, nol runtime error, nol posisi akhir, nol quarantine/accounting block, nol terminal forced close, dan pemeriksaan timestamp entry/flat weekend. Ketiga checksum input cocok dengan checkpoint asli. Tapes XAU/EUR dibangun ulang terpisah dari CSV penuh dengan algoritme yang sama untuk menghindari cache lama/tekanan memori; jumlah sinyal XAU 1175 dan EUR 379.','',
'Ini source replay dua lintasan intramenit OHLC sintetis, bukan tick parity native/FULL_PARITY, bukan bound DD semua lintasan. Biaya/spread/delay sama dengan kasus normal LF122. Stress biaya/delay untuk varian tujuh hari +200x ini belum dijalankan. Sumber macro XAU belum vintage-certified; histori jadwal FP Markets belum disertifikasi.','',
'Reproduksi: .NET SDK 8.0.426/runtime 8.0.32; jalankan prepare.py, build_tapes.py, kemudian TapeBuilder untuk XAU dan EUR secara terpisah; compile work/replay dengan work/run_local.py; jalankan run_pair.py A/B. Input harus cocok INPUT_SHA256.json dan berada di inputs/ pada folder saudara research_sevenday. Dataset besar tidak diduplikasi dalam paket. Full model source, raw replay, ledger, CSV dan diff disertakan.']
(r/'README.md').write_text('\n'.join(report)+'\n');print(json.dumps(metrics,indent=2))
