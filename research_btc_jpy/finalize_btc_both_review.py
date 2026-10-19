"""Verify completed630k archive, independently replay locked287447, enrich report."""
import pathlib,zipfile,hashlib,json,csv,subprocess,sys,os,gzip,shutil
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=pathlib.Path.cwd();p=root/'downloaded/RIZAN_BTC_BUYSELL_DD56_600K.zip'
expected=(root/'downloaded/PACKAGE_SHA256.txt').read_text().split()[0]
assert hashlib.sha256(p.read_bytes()).hexdigest()==expected
out=root/'review';out.mkdir(exist_ok=True)
with zipfile.ZipFile(p) as z:
 assert z.testzip() is None
 z.extractall(out)
manifest=pd.read_csv(out/'MANIFEST_SHA256.csv')
for _,r in manifest.iterrows():
 x=out/r.path;assert x.stat().st_size==r.bytes and hashlib.sha256(x.read_bytes()).hexdigest()==r.sha256
q=pd.read_csv(out/'ALL_630000_RESULTS.csv.gz')
assert len(q)==630000 and q.id.nunique()==630000 and set(q.id)==set(range(1,630001))
both=q[(q.buy_baskets>0)&(q.sell_baskets>0)&(q.trades>=30)]
low=both[both.floating_dd<=56].sort_values(['equity','id'],ascending=[False,True]);best=low.iloc[0]
assert len(low)>0 and best.equity>=600000
code=root/'research_btc_jpy';locked=root/'locked287447';locked.mkdir(exist_ok=True)
params=list(q.columns[1:list(q.columns).index('equity')]);q[q.id==287447][params].to_csv(locked/'SELECTED.csv',index=False)
subprocess.run([sys.executable,str(code/'prepare_btc_both.py'),str(locked)],check=True)
shutil.copy2(code/'btc_both.cpp',locked/'btc_both.cpp')
subprocess.run(['g++','-O3','-std=c++17',str(locked/'btc_both.cpp'),'-o',str(locked/'replay')],check=True)
subprocess.run([str(locked/'replay'),'audit',str(root/'source/data/BTCUSD_M1.csv'),str(locked),str(locked/'SELECTED.csv')],check=True)
ind=out/'independent';ind.mkdir(exist_ok=True)
subprocess.run([sys.executable,str(code/'independent_btc_287447.py'),str(root/'source/data/BTCUSD_M1.csv'),str(ind),str(locked)],check=True)
shutil.copy2(code/'independent_btc_287447.py',ind/'independent_btc_287447.py')
for n in ['finalize_btc_both_review.py','resume_btc_both.py']:shutil.copy2(code/n,out/n)
cid=int(best.id);stress=pd.read_csv(out/'ALL_SELECTED_STRESS.csv');b=stress[(stress.id==cid)&(stress['case']=='BASE')].iloc[0]
for k in ['equity','floating_dd','balance_dd','trades','buy_baskets','sell_baskets']:assert abs(b[k]-best[k])<max(1e-7,abs(best[k])*1e-9)
l=pd.read_csv(out/f'replay/candidate_{cid}_BASE_ledger.csv');l['exit']=pd.to_datetime(l.exit_utc)
con=[]
for side,g in l.groupby('side'):
 con.append(dict(direction='BUY' if side>0 else 'SELL',baskets=len(g),wins=int((g.net_pnl>0).sum()),gross_pnl=g.gross_pnl.sum(),winning_net=g.loc[g.net_pnl>0,'net_pnl'].sum(),losing_net=-g.loc[g.net_pnl<0,'net_pnl'].sum(),commissions=(g.entry_commission+g.exit_commission).sum(),financing=g.financing.sum(),net_pnl=g.net_pnl.sum(),adds=int(g['adds'].sum())))
con=pd.DataFrame(con);con.to_csv(out/'BEST_BUY_SELL_CONTRIBUTIONS.csv',index=False)
for freq,name in [('M','MONTHLY'),('Y','YEARLY')]:
 z=l.copy();z['period']=z.exit.dt.to_period(freq)
 idx=pd.period_range('2019-01-01','2026-10-15',freq=freq)
 totals=z.groupby('period').agg(net_pnl=('net_pnl','sum'),baskets=('net_pnl','size'),adds=('adds','sum')).reindex(idx,fill_value=0)
 totals['starting_balance']=100+totals.net_pnl.cumsum()-totals.net_pnl;totals['ending_balance']=100+totals.net_pnl.cumsum();totals['return_pct']=100*totals.net_pnl/totals.starting_balance
 totals.to_csv(out/f'BEST_{name}.csv',index_label='period')
curve=pd.read_csv(out/f'replay/candidate_{cid}_BASE_equity.csv.gz');times=pd.to_datetime(curve.timestamp)
fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
axes[0].plot(times,curve.equity,color='#167b9e',lw=.7,label='Floating equity, hourly snapshots');axes[0].plot(l.exit,l.balance,color='#a65d00',lw=1,label='Settled balance');axes[0].set_yscale('log');axes[0].set_ylabel('USD (log scale)');axes[0].legend(loc='upper left',fontsize=8)
axes[0].set_title(f'BTCUSD BUY + SELL | ID {cid} | $100, no top-ups | Bitstamp M1 model')
axes[1].plot(times,-curve.drawdown_pct,color='#b02d3b',lw=.7);axes[1].axhline(-56,color='black',ls='--',lw=.7);axes[1].set_ylabel('Floating DD (%)')
for ax in axes:ax.grid(alpha=.2)
fig.tight_layout();fig.savefig(out/'BEST_EQUITY_DD.png',dpi=150);plt.close(fig)
metrics=pd.DataFrame([dict(final_balance=best.equity,floating_dd=best.floating_dd,balance_dd=best.balance_dd,pf=best.pf,win_rate=100*best.wins/best.trades,total_baskets=int(best.trades),buy=int(best.buy_baskets),sell=int(best.sell_baskets),adds=int(best['adds']))]);metrics.to_csv(out/'BEST_METRICS.csv',index=False)
selected=stress[stress.id==cid][['case','equity','floating_dd','balance_dd','pf','trades','buy_baskets','sell_baskets','adds']].copy();selected['target_pass']=(selected.equity>=600000)&(selected.floating_dd<=56)&(selected.buy_baskets>0)&(selected.sell_baskets>0);selected.to_csv(out/'BEST_LOCKED_STRESS.csv',index=False)
def table(d):return d.to_markdown(index=False,floatfmt='.6f')
report=f'''# BTCUSD BUY + SELL — audit akhir grid 630.000

**Target nominal tercapai:** modal $100 tanpa top-up menjadi ${best.equity:,.2f}, dengan maximum floating equity DD {best.floating_dd:.6f}%. Periode 1 Januari 2019–15 Oktober 2026. Kandidat ID {cid}. Ini hasil optimasi historis pada model OHLC M1, bukan bukti performa masa depan atau validasi tick broker.

{table(metrics)}

## Penyelesaian checkpoint

Run39273886250 gagal pada empat shard: nilai TP1,5R milik seed72 tidak ada dalam lookup parser. Audit lama dilewati. Keempat ZIP parsial diverifikasi terhadap SHA256 GitHub. Tepat447.300 baris dipertahankan; hanya182.700 ID yang belum selesai dijalankan di run39335312836. Masing-masing shard berisi157.500 ID, seluruh630.000 ID unik1–630.000,100 seed ×6.300 sizing. Nilai TP1,5 ditambahkan di akhir daftar agar indeks lama tidak bergeser. Tidak ada perubahan aturan transaksi/model sizing lama.

Data mencakup4.096.800 menit berurutan,2019-01-01 00:00 sampai2026-10-15 23:59 UTC. Tidak ada timestamp duplikat atau menit hilang. SHA256 CSV: c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504.

## Konfigurasi lengkap

```json
{json.dumps({k:best[k].item() if hasattr(best[k],'item') else best[k] for k in params},indent=2)}
```

Untuk displacement_follow: body candle=(close-open)/ATR14; threshold_index2 berarti BUY ketika body>1,4 dan close>high candle sebelumnya; SELL ketika body<-1,4 dan close<low sebelumnya. ATR14 menggunakan smoothing Wilder. H4 trend_filter1 memerlukan close>EMA80 dan EMA20>EMA80 untuk BUY, kondisi sebaliknya untuk SELL. Seluruh indikator memakai candle yang sudah closed. Session1 adalah waktu sinyal/entry dasar00:00–08:00 UTC (07:00–15:00 WIB). Lookback8 tersimpan pada geometri, tetapi tidak dipakai oleh rumus displacement_follow. Gate tambahan dengan nilai0 tidak memfilter sinyal.

SL berjarak stop_atr×ATR dari fill awal. TP berjarak tp_R×jarakSL dari fill. Hold32 H4 adalah128 jam sejak timestamp sinyal. Budget risiko/margin terpisah menurut arah; sizing dibulatkan ke bawah0,01BTC, maksimal100BTC. Lihat engine.hpp untuk rumus biaya dan margin penuh. BUY/SELL berbagi saldo dan compounding; satu basket aktif; sinyal ketika busy diabaikan. Tidak menjumlahkan dua replay terpisah.

## Kontribusi BUY dan SELL

{table(con)}

Winning_net adalah jumlah net PnL basket menang; losing_net adalah nilai absolut jumlah net PnL basket rugi. SELL benar-benar tereksekusi; jumlah transaksi yang besar tidak berarti kontribusinya positif. Profit keseluruhan masih bergantung kuat pada BUY.

## Stress konfigurasi terkunci

{table(selected)}

BASE memakai leverage10×. LEVERAGE2 dan LEVERAGE5 berarti leverage absolut2× dan5×, bukan pengali atas10×. Biaya1,5×/2× mengalikan komisi, slippage dan financing; spread tetap5bp. Delay memakai entry next-M1, bukan delay2detik. Kelolosan baseline tidak berarti tahan stress.

## Audit dan batas model

Seluruh finalis direplay ulang di C++, dibandingkan dengan screening, dan ledger direkonsiliasi dari gross PnL, komisi, financing, net PnL dan saldo kumulatif. Script Python independen merekonstruksi H4, sinyal dan seluruh jalur M1 kandidat287447 pada keenam kondisi; hasil saldo, DD dan ledger cocok dengan toleransi numerik. Hasil perbandingan berada di independent/INDEPENDENT_PYTHON_CHECK.json. Rekonsiliasi cash adalah pemeriksaan independen terhadap ledger, bukan pembuktian feed broker.

Asumsi: official Bitstamp OHLC M1, leverage10× belum dibuktikan sesuai broker, minimum/step0,01BTC,maksimum100BTC,spread5bp,komisi5bp per sisi,slippage1bp per sisi,financing debit3bp notional per hari untuk kedua arah. Entry pada open setelah sinyal closed,stop-first untuk SL/TP ambigu,gap SL menggunakan open yang lebih buruk. Floating DD diperiksa pada setiap M1 dengan bound OHLC konservatif; grafik hanya snapshot per jam.

Capital-floor model lama dan prioritas expiry/SL/TP sebelum fallback stop-out tetap diwarisi. Intrabar OHLC tidak menentukan urutan tick sesungguhnya. Financing/gap,liquidity,tiering volume dan spesifikasi kontrak broker belum divalidasi. Seluruh periode adalah in-sample setelah optimasi banyak konfigurasi; tidak ada untouched out-of-sample. Tidak ada klaim FULL_PARITY atau DD masa depan dibatasi56%. BTC belum digabung dengan XAU–EUR; trading live tidak diubah.

Laporan bulanan/tahunan lengkap termasuk periode nol transaksi berada di BEST_MONTHLY.csv dan BEST_YEARLY.csv. Ledger tiap skenario,rekonsiliasi,source,adapter diff,hash sumber dan seluruh hasil630.000 tersimpan dalam paket.

Source search/audit commit:44a5ef28a751ac1c73714f6d40b2a20fc110b9fc.
Checkpoint commit:f3e97d82547b403be0845bee43bb43046da72e29.
Review commit:{os.environ['GITHUB_SHA']}.
Search/audit:https://github.com/rizanrizan93/Forex-scanner/actions/runs/39335312836
Review:https://github.com/rizanrizan93/Forex-scanner/actions/runs/{os.environ['GITHUB_RUN_ID']}
'''
(out/'LAPORAN_BTC_BUYSELL_DD56.md').write_text(report)
(out/'REVIEW_PROVENANCE.json').write_text(json.dumps(dict(original_package_sha256=expected,original_run=39335312836,review_commit=os.environ['GITHUB_SHA'],review_run=os.environ['GITHUB_RUN_ID'],best_id=cid,independent_candidate=287447),indent=2))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
with (out/'MANIFEST_SHA256.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for x in sorted(out.rglob('*')):
  if x.is_file() and x.name not in ['MANIFEST_SHA256.csv','PACKAGE_SHA256.txt']:w.writerow([str(x.relative_to(out)),sha(x),x.stat().st_size])
package=out/'RIZAN_BTC_BUYSELL_DD56_600K.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for x in sorted(out.rglob('*')):
  if x.is_file() and x!=package and x.name!='PACKAGE_SHA256.txt':z.write(x,str(x.relative_to(out)))
with zipfile.ZipFile(package) as z:assert z.testzip() is None
(out/'PACKAGE_SHA256.txt').write_text(sha(package)+'  '+package.name+'\n')
print(table(metrics),flush=True);print(table(selected),flush=True)
