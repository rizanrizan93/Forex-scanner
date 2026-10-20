from pathlib import Path
import json,csv,gzip,hashlib,zipfile,collections,datetime,shutil,difflib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
r=Path(__file__).resolve().parent;o=r/'delivery_v121';
if o.exists():shutil.rmtree(o)
o.mkdir()
reports=[json.loads((r/'replay'/n).read_text())['Reports'][0] for n in ['weekday_A_22.json','weekday_B_22.json']]
metrics=[];ledger=[];annual=[];monthly=[];proof=[];directions=[]
def dt(s):return datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
def write(n,rows):
 with (o/n).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
for a in reports:
 s=a['Summary'];case=s['cfg']['Name'];h=a['BrokerHistory'];btc=[x for x in h if x['SymbolName']=='BTCUSD'];violations=[]
 assert s['ErrorCount']==0 and not s['AccountingBlock'] and not s['Quarantined'] and s['OpenPositions']==0
 for x in btc:
  start,end=dt(x['EntryTime']),dt(x['ClosingTime']);monday=(start-datetime.timedelta(days=start.weekday())).replace(hour=0,minute=0,second=0,microsecond=0);deadline=monday+datetime.timedelta(days=4,hours=21,minutes=30);marketclose=monday+datetime.timedelta(days=4,hours=22)
  if start.weekday()>=5:violations.append({'position':x['PositionId'],'reason':'weekend_entry'})
  if start>deadline-datetime.timedelta(minutes=30,seconds=-5):violations.append({'position':x['PositionId'],'reason':'entry_cutoff'})
  if end>=marketclose or end.weekday()>=5:violations.append({'position':x['PositionId'],'reason':'held_at_market_close_or_weekend'})
  if end>deadline+datetime.timedelta(seconds=5):violations.append({'position':x['PositionId'],'reason':'flat_buffer_exceeded'})
 assert not violations,violations[:5]
 identity=max(abs(x['NetProfit']-(x['GrossProfit']+x['Commissions']+x['ExitCommission']+x['Swap'])) for x in h);net=sum(x['NetProfit'] for x in h);residual=100+net-s['EndingBalance'];assert abs(residual)<1e-5 and identity<1e-7
 peak=100;dd=0
 for e in a['CashEvents']:peak=max(peak,e['Balance']);dd=max(dd,100*(peak-e['Balance'])/peak)
 assert abs(dd-s['MaxClosedDDPct'])<1e-8
 groups=collections.defaultdict(float)
 for x in h:groups['|'.join(x['Label'].split('|')[:2])]+=x['NetProfit']
 pf=sum(max(0,x) for x in groups.values())/-sum(min(0,x) for x in groups.values());assert abs(pf-s['PF'])<1e-8
 metrics.append({'case':case,'ending_balance':s['EndingBalance'],'floating_dd_model_pct':s['MaxEquityDDPct'],'balance_dd_pct':dd,'pf':pf,'win_rate_pct':100*sum(x>0 for x in groups.values())/len(groups),'baskets':s['Baskets'],'xau_baskets':s['XauBaskets'],'eur_baskets':s['EurBaskets'],'btc_baskets':len(btc),'btc_buy':s['BtcBuys'],'btc_sell':s['BtcSells'],'weekend_entries':0,'held_at_friday_close':0,'runtime_errors':0,'nominal_balance500k_dd56_pass':s['EndingBalance']>=500000 and s['MaxEquityDDPct']<=56})
 proof.append({'case':case,'checked_btc_positions':len(btc),'violations':violations,'flat_cutoff_assumed_friday_utc':'21:30','market_close_assumed_friday_utc':'22:00','broker_historical_schedule_certified':False,'gross_pnl':sum(x['GrossProfit'] for x in h),'entry_commission':-sum(x['Commissions'] for x in h),'exit_commission':-sum(x['ExitCommission'] for x in h),'funding_swap':-sum(x['Swap'] for x in h),'net_pnl':net,'initial_capital':100,'ending_balance':s['EndingBalance'],'cash_residual':residual,'max_fill_accounting_error':identity,'balance_dd_recomputed_pct':dd})
 for sym in ['XAUUSD','EURUSD','BTCUSD']:
  for side in [0,1]:
   q=[x for x in h if x['SymbolName']==sym and x['TradeType']==side];directions.append({'case':case,'symbol':sym,'side':'BUY' if side==0 else 'SELL','fills':len(q),'winning_net_fills':sum(max(0,x['NetProfit']) for x in q),'losing_net_fills':sum(min(0,x['NetProfit']) for x in q),'net_pnl':sum(x['NetProfit'] for x in q)})
 ledger += [{'case':case,**x} for x in h];annual += [{'case':case,**x} for x in a['Annual']];monthly += [{'case':case,**x} for x in a['Monthly']]
 with gzip.open(o/(case+'_RAW.json.gz'),'wt') as f:json.dump(a,f,separators=(',',':'))
write('WEEKEND_FINAL_METRICS.csv',metrics);write('FILL_LEDGER.csv',ledger);write('ANNUAL.csv',annual);write('MONTHLY.csv',monthly);write('DIRECTION_CONTRIBUTIONS.csv',directions);(o/'WEEKEND_AND_CASH_AUDIT.json').write_text(json.dumps(proof,indent=2))
fig,ax=plt.subplots(2,1,figsize=(11,6.5),sharex=True,gridspec_kw={'height_ratios':[2,1]})
for a in reports:
 q=a['Curve'];t=[dt(x['At']) for x in q];ax[0].plot(t,[x['Equity'] for x in q],label=a['Summary']['cfg']['Name'],lw=1);ax[1].plot(t,[100*(x['Peak']-x['Equity'])/x['Peak'] for x in q],lw=.8)
ax[0].set_yscale('log');ax[0].set_ylabel('Equity USD (log)');ax[0].legend();ax[0].set_title('V1.2.1 weekend-flat: assumed Friday22UTC / Monday00UTC; OHLC model')
ax[1].axhline(56,color='red',ls='--',lw=.8,label='previous DD56 limit');ax[1].legend(fontsize=8);ax[1].set_ylabel('Floating DD %');ax[1].set_xlabel('UTC')
for a in ax:a.grid(alpha=.2)
fig.tight_layout();fig.savefig(o/'WEEKEND_EQUITY_DD.png',dpi=160);plt.close(fig)
# New release only. Never bundle old $24m report as though it were this version's result.
for sub in ['source','tests']:
 for p in (r/sub).rglob('*'):
  if p.is_file() and p.suffix in ['.cs','.csproj']:
   dest=o/p.relative_to(r);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
for sub in ['SettlementTests','PortfolioTests','TimingTests','WeekendTests']:
 for p in (r/'validation'/sub).iterdir():
  if p.suffix=='.cs' or p.name in ['result.json','compile.log','events.log']:
   dest=o/p.relative_to(r);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
for n in ['BtcTests.cs','result.json','events.log','compile.log']:
 dest=o/'audit'/n;dest.parent.mkdir(exist_ok=True);shutil.copy2(r/'audit'/n,dest)
for n in ['build_native.py','BuildAlgo.cs','AssemblyInfo.cs','run_local.py','FREEZE_MANIFEST.json','README_FROZEN_WEEKEND.md','BTC_REFERENCE_SIGNALS.csv','finalize_weekend.py']:
 shutil.copy2(r/n,o/n)
for n in ['Replay.cs','ApiStubs.cs','weekday_A_22.log','weekday_A_22.progress','weekday_B_22.log','weekday_B_22.progress']:
 dest=o/'replay'/n;dest.parent.mkdir(exist_ok=True);shutil.copy2(r/'replay'/n,dest)
for n in ['compile.log','bundle.log','RizanXauEurPortfolio.algo.metadata']:
 dest=o/'native'/n;dest.parent.mkdir(exist_ok=True);shutil.copy2(r/'native'/n,dest)
name='RizanXauEurBtcPortfolio_FROZEN_WEEKEND_V1_2_1.algo';shutil.copy2(r/'native'/name,o/name)
base=zipfile.ZipFile(r.parent/'portfolio_final/RIZAN_XAU_EUR_BTC_INTEGRATED_AUDIT_2019_2026.zip');patch=''
for n in ['source/BtcEngine.cs','source/PortfolioHost.cs']:
 patch+=''.join(difflib.unified_diff(base.read(n).decode().splitlines(True),(r/n).read_text().splitlines(True),fromfile='v120/'+n,tofile='v121/'+n))
(o/'WEEKEND_CHANGE.diff').write_text(patch)
for sub in ['xau','eur']:
 for p in (r/'source'/sub).glob('*.cs'):assert p.read_bytes()==base.read(str(p.relative_to(r)))
status={'release':'1.2.1 FROZEN WEEKEND','native_source_commit':'1d6ad83f285f293b103342073b637fa16e597fb9','branch':'release/xau-eur-btc-frozen-weekend-v1.2.1','strategy_parameters_frozen':True,'xau_eur_strategy_8_files_unchanged':True,'trading_default':False,'live_deployed':False,'all_weekend_exposure_checks_pass':True,'dd56_qualified':False,'broker_tick_parity':False,'historical_broker_session_certified':False,'assumed_btc_trading_hours':'Monday00UTC-Friday22UTC','native_uses_actual_symbol_market_hours':True,'tests':1326,'initial_capital':100,'end_input_bar_utc':'2026-10-09T21:58:00Z','metrics':metrics,'algo_sha256':hashlib.sha256((o/name).read_bytes()).hexdigest(),'previous_24m_is_not_this_release_result':True}
(o/'FROZEN_STATUS.json').write_text(json.dumps(status,indent=2))
report=['# RIZAN XAU–EUR–BTC Frozen Weekend V1.2.1', '',
'**Source dibekukan dan pengaman akhir pekan lulus. Namun versi baru tidak memenuhi batas floating DD 56% pada dua jalur replay ini.** Belum dipasang ke live.', '',
'Modal awal $100 tanpa top-up. Periode 1 Januari 2019 sampai bar terakhir 9 Oktober 2026 21:58 UTC.', '',
'| Jalur | Saldo akhir USD | Floating DD model | Balance DD | PF | Basket XAU/EUR/BTC | BTC BUY/SELL |',
'|---|---:|---:|---:|---:|---:|---:|']
for x in metrics:report.append(f"| {x['case']} | {x['ending_balance']:,.2f} | {x['floating_dd_model_pct']:.4f}% | {x['balance_dd_pct']:.4f}% | {x['pf']:.5f} | {x['xau_baskets']}/{x['eur_baskets']}/{x['btc_baskets']} | {x['btc_buy']}/{x['btc_sell']} |")
report += ['',
'Hasil lama $24,54–24,80 juta / DD 52,47–54,48% memakai BTC tujuh hari dan bukan hasil rilis ini. Kalender baru, penghapusan bar saat pasar tutup, dan pemotongan hold mengubah sinyal, transaksi, serta compounding. Tidak ada optimasi ulang atau penurunan risiko diam-diam untuk memulihkan DD 56%.', '',
'## Konfigurasi yang dibekukan', '',
'- BTC BUY profil 7844: H4 displacement_follow; body >1,4 ATR dan close >high sebelumnya; H4 bullish (close >EMA80 dan EMA20 >EMA80); sesi 00–08 UTC; SL 2 ATR, TP 12R, hold 128 jam, risk 23%, margin 95%.',
'- BTC SELL profil 2269: H1 compression_break; range empat bar <0,7 ATR dan close <low 16 bar −0,1 ATR; H4 bearish; body ≤2,5 ATR, RSI ≥25, rasio ATR 20 bar 0,6–1,8. SL 1,5 ATR, TP 2R, hold delapan jam, risk 18%, margin 30%.',
'- Satu basket BTC, tanpa layering/BE/trailing. Sinyal closed, entry berikutnya, chase ≤0,5 ATR; min 0,01 BTC, max 100 BTC, step dan limit broker dihormati.',
'- Risiko portofolio 20,75% dikunci, cap margin entry 50%. Model BTC 10× dan XAU/EUR 200× dipertahankan. Ini bukan hard stop drawdown 56%.',
'- Delapan file strategi XAU/EUR identik dengan baseline Settlement 1.1.1. Perubahan host terbatas pada penguncian risk cap, identitas versi/checkpoint, dan prioritas pengaman BTC sebelum kerja entry/bridge.', '',
'## Penutupan Jumat dan recovery', '',
'- Native membaca Symbol.MarketHours.IsOpened(DateTime) di UTC. Jadwal sesi terakhir Senin–Jumat dihitung dan disegarkan setiap lima menit. Jika hari libur tercermin di API, sesi terakhir bisa maju ke Kamis.',
'- Blokir entry BTC 60 menit sebelum penutupan; mulai flatten 30 menit sebelumnya. Hold efektif adalah nilai terkecil antara hold asli dan cutoff mingguan. Sabtu/Minggu UTC tidak entry. Sinyal Jumat tidak diulang pada Senin.',
'- Pengaman dipanggil lewat timer satu detik dan tick; timer host mendahulukannya sebelum kerja entry/bridge. Tidak bergantung pada tick BTC baru.',
'- ExitPending disimpan sebelum request. Close yang ditolak tidak dianggap berhasil; retry satu detik, termasuk setelah restart. Pengaman hanya menutup posisi BTC milik cBot. Posisi XAU/EUR/manual tidak ditutup. Mode Kirim order OFF juga memblokir close.',
'- Runtime harus aktif, Kirim order ON, dan broker terhubung. Jika offline, pasar sudah tutup, atau close terus ditolak, fill tidak dapat dijamin. Log EXIT_WAIT/CLOSE_RETRY dan intent dipertahankan; penutupan dicoba pada kesempatan pertama ketika pasar terbuka. Server-side SL/TP tetap ada.',
'- Contoh: Jumat 22 UTC = Sabtu 05 WIB; flatten dimulai Sabtu 04.30 WIB. Ini contoh konversi, bukan jam broker yang di-hardcode dalam cBot.', '',
'## Audit', '',
'Build resmi cTrader.Automate 1.0.21, reference .NET 6.0.36, SDK 8.0.426 berhasil. Sebanyak 1.326 pemeriksaan lulus: settlement 171, portofolio 827, timing 121, BTC 182, weekend 25. Native compiler akhir tanpa error/warning. Uji weekend mencakup close 21/22 UTC, batas entry/flat, libur Jumat, jadwal tidak tersedia, reject/retry, restart, pasar tutup, mode OFF, kepemilikan simbol, dan sinyal Senin baru.', '',
'EntryTime dan ClosingTime diperiksa secara independen untuk 191 posisi BTC (A 96 / B 95): nol entry akhir pekan, nol posisi melewati penutupan Jumat, dan nol pelanggaran buffer flat dalam toleransi lima detik. Kedua replay mencatat ErrorCount 0, tanpa quarantine/accounting block, tanpa posisi akhir atau close paksa khusus pada akhir periode.', '',
'Identitas gross PnL − komisi − funding/swap = net PnL, saldo = $100 + net, balance DD, dan PF direkonsiliasi ulang. Bukti ada di WEEKEND_AND_CASH_AUDIT.json. Ledger seluruh fill, kontribusi BUY/SELL, laporan bulanan/tahunan dan grafik disertakan.', '',
'## Batas hasil', '',
'**Kalender replay diasumsikan Senin 00 UTC–Jumat 22 UTC. Histori jadwal broker dan DST belum disertifikasi.** Native memakai jadwal API broker aktual. Bar BTC di luar sesi asumsi dikeluarkan dari indikator; tidak ada pengisian bar yang hilang dengan harga buatan.', '',
'Replay memakai dua jalur intramenit OHLC independen posisi dan broker tiruan, dengan ACK dua detik serta delay broker dua detik. Ini bukan rekaman tick broker, bukan FULL_PARITY, dan bukan bound konservatif semua urutan M1. Macro XAU masih rekonstruksi dan belum memiliki vintage point-in-time tersertifikasi. Biaya, swap dan leverage tetap asumsi model; stress biaya portofolio versi ini belum dijalankan.', '',
'Grafik memakai snapshot per jam; DD tabel berasal dari observasi event model. Hasil optimasi historis bukan bukti performa masa depan.', '',
'## Sumber', '',
'Native source commit: `1d6ad83f285f293b103342073b637fa16e597fb9`. Branch: `release/xau-eur-btc-frozen-weekend-v1.2.1`. Build awal: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39371048685 .', '',
'Input SHA256: BTC `c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504`; XAU `3fda8011082e2691b6ebe1a8a4da5fff8e4bf0fc07baf57506b7894d95fc1808`; EUR `3c74ac5ccaeeac64f44693bc6bd4406e9225a9ef61dbb5f80756530f050506ec`.', '',
'File .algo default Kirim order OFF. Tidak ada deployment live. Jangan jalankan versi lama dan baru bersamaan pada akun yang sama.']
(o/'LAPORAN_FROZEN_WEEKEND_V121.md').write_text('\n'.join(report)+'\n')
rebuild=o/'inputs_rebuild';rebuild.mkdir(exist_ok=True)
for n in ['prep/prepare_eur.py','recover_full_eur.py']:
 shutil.copy2(r.parent/'weekend_inputs'/n,rebuild/Path(n).name)
(rebuild/'INPUT_PROVENANCE.json').write_text(json.dumps({'BTC':{'actions_run':39212036090,'artifact_id':12168391422,'csv_sha256':'c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'},'XAU_and_pre2016_EUR_prefix':{'library_file_id':'libfile_0443b246f9648191aca2c89be59b5e15','name':'RIZAN_REPLAY_SETTLEMENT_2016_2026_20261017.zip'},'EUR_raw2016_2026':{'library_file_id':'libfile_75644989d51081918a6937674837ea97','name':'RIZAN_EUR_v1.1.2_REPLAY_2016_20261009.zip'},'EUR_recovery':'prepare_eur.py verifies per-year raw archives and suffix c907028...; recover_full_eur.py preserves the valid pre2016 prefix and asserts full expected3c74ac... checksum. No missing-bar imputation.'},indent=2))
manifest={str(p.relative_to(o)):hashlib.sha256(p.read_bytes()).hexdigest() for p in o.rglob('*') if p.is_file() and p.name!='SHA256_MANIFEST.json'};(o/'SHA256_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
pkg=r/'RIZAN_XAU_EUR_BTC_FROZEN_WEEKEND_V121.zip'
with zipfile.ZipFile(pkg,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in o.rglob('*'):
  if p.is_file():z.write(p,str(p.relative_to(o)))
print(json.dumps({'metrics':metrics,'package_bytes':pkg.stat().st_size,'package_sha256':hashlib.sha256(pkg.read_bytes()).hexdigest()},indent=2))
