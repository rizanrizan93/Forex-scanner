import pathlib,hashlib,zipfile,json,csv,shutil,subprocess,sys,itertools,os,gzip
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=pathlib.Path.cwd();code=R/'research_btc_jpy';out=R/'growth500_final';out.mkdir(exist_ok=True)
source=R/'downloaded/RIZAN_BTC_GROWTH500_AUDITED.zip';expected=(R/'downloaded/PACKAGE_SHA256.txt').read_text().split()[0];assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
with zipfile.ZipFile(source) as z:assert z.testzip() is None;z.extractall(out)
m=pd.read_csv(out/'MANIFEST_SHA256.csv')
for _,r in m.iterrows():
 p=out/r.path;assert p.stat().st_size==r.bytes and hashlib.sha256(p.read_bytes()).hexdigest()==r.sha256
old=pd.read_csv(out/'LOCKED_STRESS.csv');control=old[old.id==4259].copy();assert len(control)==6
build=out/'refine_build';subprocess.run([sys.executable,str(code/'prepare_btc_growth500.py'),str(build)],check=True);shutil.copy2(code/'btc_growth500_refine.cpp',build/'btc_growth500_refine.cpp')
exe=R/'refine_growth500';subprocess.run(['g++','-O3','-std=c++17',str(build/'btc_growth500_refine.cpp'),'-o',str(exe)],check=True)
rows=[]
for br,sr,bm,sm in itertools.product([.20,.21,.22,.23,.24,.25,.26],[.10,.12,.15,.18,.20],[.85,.90,.95],[.20,.25,.30,.35,.40]):rows.append(dict(id=8500001+len(rows),buy_profile=7844,sell_profile=2269,buy_risk=br,sell_risk=sr,buy_margin=bm,sell_margin=sm))
cfg=pd.DataFrame(rows);assert len(cfg)==525;cfg.to_csv(out/'REFINE_525_CONFIGS.csv',index=False)
screen=out/'refine_screen';screen.mkdir();subprocess.run([str(exe),'stresssearch',str(R/'source/data/BTCUSD_M1.csv'),str(screen),str(out/'REFINE_525_CONFIGS.csv')],check=True)
q=pd.read_csv(screen/'RESULTS.csv');assert len(q)==3150 and q.id.nunique()==525 and not q.duplicated(['id','case']).any();q.to_csv(out/'REFINE_3150_SCENARIOS.csv.gz',index=False,compression='gzip');(screen/'RESULTS.csv').unlink()
cc=cfg[(cfg.buy_risk==.23)&(cfg.sell_risk==.15)&(cfg.buy_margin==.95)&(cfg.sell_margin==.30)].iloc[0];got=q[q.id==cc.id].set_index('case');ref=control.set_index('case')
for case in ref.index:
 for col in ['equity','floating_dd','balance_dd','buy_pnl','sell_pnl']:assert abs(got.loc[case,col]-ref.loc[case,col])<max(1e-6,abs(ref.loc[case,col])*1e-9),(case,col)
base=q[q['case']=='BASE'];good=base[(base.equity>=500000)&(base.floating_dd<=56)&(base.buy_pnl>0)&(base.sell_pnl>0)&(base.buys>=10)&(base.sells>=10)&(base[[f'y{y}' for y in range(2019,2027)]].min(axis=1)>=1)].copy();assert len(good)>0
rank=[]
for _,r in good.iterrows():
 core=q[(q.id==r.id)&q['case'].isin(['BASE','COST1_5','COST2','DELAY_NEXT_M1'])];assert len(core)==4
 rank.append(dict(id=int(r.id),all4_target=bool(((core.equity>=500000)&(core.floating_dd<=56)&(core.buy_pnl>0)&(core.sell_pnl>0)).all()),all4_DD56=bool((core.floating_dd<=56).all()),worst_core_dd=float(core.floating_dd.max()),min_core_balance=float(core.equity.min()),base_equity=float(r.equity),base_dd=float(r.floating_dd)))
ranking=pd.DataFrame(rank).sort_values(['all4_target','all4_DD56','worst_core_dd','base_equity'],ascending=[False,False,True,False]);ranking.to_csv(out/'REFINE_QUALIFIED_RANKING.csv',index=False)
pid=int(ranking.iloc[0].id);highest=int(good.sort_values(['equity','id'],ascending=[False,True]).iloc[0].id);ids=list(dict.fromkeys([pid,highest]));chosen=cfg[cfg.id.isin(ids)].copy();chosen.to_csv(out/'REFINE_LOCKED_FINALISTS.csv',index=False)
rv=out/'refine_replay';rv.mkdir();subprocess.run([str(exe),'audit',str(R/'source/data/BTCUSD_M1.csv'),str(rv),str(out/'REFINE_LOCKED_FINALISTS.csv')],check=True)
a=pd.read_csv(rv/'RESULTS.csv');a.to_csv(out/'REFINE_LOCKED_STRESS.csv',index=False);assert len(a)==6*len(ids)
prices=pd.read_csv(R/'source/data/BTCUSD_M1.csv',usecols=[0,1]);times=(pd.to_datetime(prices.iloc[:,0]).astype('int64')//60_000_000_000).to_numpy();fund=np.cumsum(prices.iloc[:,1].to_numpy()*.0003/1440)
checks=[];directions=[];years=[];months=[]
for _,r in a.iterrows():
 cid=int(r.id);case=r['case'];l=pd.read_csv(rv/f'candidate_{cid}_{case}_ledger.csv');scale=1.5 if case=='COST1_5' else 2 if case=='COST2' else 1
 gross=l.side*(l.exit_price-l.entry_average)*l.quantity;net=gross-l.entry_commission-l.exit_commission-l.financing;en=(pd.to_datetime(l.entry_utc).astype('int64')//60_000_000_000).to_numpy();ex=(pd.to_datetime(l.exit_utc).astype('int64')//60_000_000_000).to_numpy();ei=np.searchsorted(times,en);xi=np.minimum(np.searchsorted(times,ex),len(times)-1);carry=(fund[xi]-fund[ei])*l.quantity.to_numpy()*scale
 err=max(float(abs(gross-l.gross_pnl).max()),float(abs(net-l.net_pnl).max()),float(abs(100+net.cumsum()-l.balance).max()),abs(100+net.sum()-r.equity),float(abs(l.entry_commission-l.quantity*l.entry_average*.0005*scale).max()),float(abs(l.exit_commission-l.quantity*l.exit_price*.0005*scale).max()),float(np.max(abs(carry-l.financing))))
 assert err<max(1e-5,abs(r.equity)*1e-9) and (en[1:]>ex[:-1]).all();assert int((l.side==1).sum())==r.buys and int((l.side==-1).sum())==r.sells
 oldrow=q[(q.id==cid)&(q['case']==case)].iloc[0]
 for col in ['equity','floating_dd','buy_pnl','sell_pnl']:assert abs(oldrow[col]-r[col])<max(1e-6,abs(r[col])*1e-9)
 checks.append(dict(id=cid,case=case,maximum_error=err,gross=float(gross.sum()),commissions=float((l.entry_commission+l.exit_commission).sum()),financing=float(l.financing.sum()),net=float(net.sum()),balance=float(r.equity),passed=True))
 if case=='BASE':
  for side,g in l.groupby('side'):directions.append(dict(id=cid,side=int(side),baskets=len(g),wins=int((g.net_pnl>0).sum()),winning_net=float(g.loc[g.net_pnl>0,'net_pnl'].sum()),losing_net=float(-g.loc[g.net_pnl<0,'net_pnl'].sum()),gross=float(g.gross_pnl.sum()),commissions=float((g.entry_commission+g.exit_commission).sum()),financing=float(g.financing.sum()),net=float(g.net_pnl.sum())))
  for freq,coll in [('Y',years),('M',months)]:
   gs=l.groupby(pd.to_datetime(l.exit_utc).dt.to_period(freq));bal=100
   for per in pd.period_range('2019-01-01','2026-10-15',freq=freq):
    g=gs.get_group(per) if per in gs.groups else l.iloc[:0];pnl=float(g.net_pnl.sum());coll.append(dict(id=cid,period=str(per),baskets=len(g),net=pnl,buy_net=float(g.loc[g.side==1,'net_pnl'].sum()),sell_net=float(g.loc[g.side==-1,'net_pnl'].sum()),return_pct=100*pnl/bal,ending_balance=bal+pnl));bal+=pnl
pd.DataFrame(checks).to_json(out/'REFINE_CASH_RECONCILIATION.json',orient='records',indent=2);pd.DataFrame(directions).to_csv(out/'REFINE_DIRECTIONAL_CONTRIBUTIONS.csv',index=False);pd.DataFrame(years).to_csv(out/'REFINE_YEARLY.csv',index=False);pd.DataFrame(months).to_csv(out/'REFINE_MONTHLY.csv',index=False)
b=a[a['case']=='BASE'].copy();b['win_rate']=100*b.wins/b.trades;b.to_csv(out/'REFINE_FINAL_METRICS.csv',index=False);primary=b[b.id==pid].iloc[0];best=b[b.id==highest].iloc[0];stress=a[a.id==pid];direction=pd.DataFrame(directions);year=pd.DataFrame(years);config=cfg[cfg.id==pid].iloc[0].to_dict();cat=pd.read_csv(out/'CATALOG.csv');details=cat[cat.profile.isin([7844,2269])]
(out/'FINAL_PRIMARY_CONFIG.json').write_text(json.dumps(dict(parameters=config,profiles=details.to_dict('records'),initial_USD=100,no_topups=True,leverage=10,source_commit=os.environ['GITHUB_SHA']),indent=2))
c=pd.read_csv(rv/f'candidate_{pid}_BASE_equity.csv');fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True);tm=pd.to_datetime(c.timestamp);ax[0].plot(tm,c.equity,lw=.7);ax[0].set_yscale('log');ax[0].set_title(f'BTCUSD BUY + SELL — final candidate {pid}');ax[0].set_ylabel('Equity USD (log)');ax[1].plot(tm,-c.drawdown_pct,lw=.7);ax[1].axhline(-56,ls='--',lw=.7);ax[1].set_ylabel('Floating DD %');fig.tight_layout();fig.savefig(out/'FINAL_PRIMARY_EQUITY_DD.png',dpi=150);plt.close(fig)
summarycols=['id','equity','floating_dd','balance_dd','pf','win_rate','trades','buys','sells','buy_pnl','sell_pnl'];shortcols=['case','equity','floating_dd','balance_dd','pf','buy_pnl','sell_pnl']
status=dict(target_met=True,target_balance=500000,floatDD_limit=56,initial_USD=100,primary_id=pid,highest_refine_id=highest,primary=primary.to_dict(),primary_stress_flags=ranking[ranking.id==pid].iloc[0].to_dict(),stage1_cases=23328,stage2_cases=10440,stage2_hits=9,refine_configs=525,refine_scenarios=3150,refine_nominal_hits=len(good),source_package_sha256=expected,source_run=39342348232,review_run=os.environ['GITHUB_RUN_ID'],review_commit=os.environ['GITHUB_SHA'],untouched_OOS=False,live_changed=False)
(out/'FINAL_GROWTH500_STATUS.json').write_text(json.dumps(status,indent=2,default=lambda x:x.item()))
report=f'''# BTCUSD — hasil akhir target minimum $500.000

**Target nominal tercapai.** Saldo awal $100 tanpa top-up menjadi **${primary.equity:,.2f}**, dengan maximum floating equity DD **{primary.floating_dd:.6f}%** pada kandidat {pid}. Periode: 1 Januari 2019–15 Oktober 2026. BUY dan SELL berbagi satu saldo, margin, compounding, dan state eksekusi.

## Kandidat akhir dan alternatif saldo tertinggi

{b[summarycols].to_markdown(index=False,floatfmt='.6f')}

Kandidat utama dipilih dari yang lolos target nominal dengan mengutamakan kelolosan stress, kemudian maximum DD terburuk pada empat kondisi normal/biaya/delay. Alternatif saldo tertinggi ditampilkan terpisah. Kandidat awal4259 juga tetap tersimpan: saldo $2.511.313,07, DD55,0110%, PF1,77245, BUYnet+$1.789.426,16 dan SELLnet+$721.786,91. Parameter baru tidak boleh diklaim unggul pada semua kondisi hanya karena saldo baseline tinggi.

## Konfigurasi utama

```json
{json.dumps(config,indent=2)}
```

**BUY tetap memakai mesin pertumbuhan lama:** displacement_follow H4. Candle H4 yang sudah selesai harus memiliki body naik >1,4ATR14 dan close di atas high candle sebelumnya. H4 bullish: close>EMA80 dan EMA20>EMA80. Entry pada open berikutnya, dalam sesi00:00–08:00UTC (07:00–15:00WIB). SL2ATR dari fill, TP12R, batas waktu32H4=128jam. Tidak ada layering, break-even, atau trailing pada BUY. Cap RSI/body/ATRratio versi konservatif tidak dipakai pada leg pertumbuhan ini; chase maksimum0,5ATR dari close sinyal tetap diterapkan.

**SELL diperbaiki menjadi compression_break H1:** rata-rata range empat candle sebelum sinyal <0,7ATR candle sebelumnya; candle sinyal menutup di bawah low16candle sebelumnya dikurangi0,1ATR. Bias H4 yang sudah selesai harus bearish. Body sinyal maksimum2,5ATR, RSI minimal25, ATR14 dibanding20bar sebelumnya berada pada0,6–1,8. Entry open berikutnya, semua sesi. SL1,5ATR, TP2R, batas waktu8H1=8jam, tanpa layering/BE/trailing. SELL memakai target yang lebih dekat dan masa tahan lebih singkat daripada BUY.

Risiko dan margin pada JSON adalah budget sizing, bukan kerugian pasti per transaksi. Leverage model10×, minimum/step0,01BTC, maksimum100BTC. Satu basket aktif; sinyal saat busy diabaikan dan sinyal berlawanan bersamaan dibuang keduanya.

## Kontribusi profit dan kerugian

{direction[direction.id==pid].to_markdown(index=False,floatfmt='.6f')}

Profit SELL pada replay bersama merupakan perbaikan terhadap setup lama yang SELL-nya merugi. Ini tidak membuktikan strategi bebas ketergantungan bull market. Mesin BUY lama tetap dominan, dan kerugian pada tahun tertentu harus dibaca dari tabel berikut.

## Hasil tahunan

{year[year.id==pid].to_markdown(index=False,floatfmt='.6f')}

## Stress konfigurasi utama yang sama

{stress[shortcols].to_markdown(index=False,floatfmt='.6f')}

{ranking[ranking.id.isin(ids)].to_markdown(index=False,floatfmt='.6f')}

**Kelolosan nominal dan kelolosan stress berbeda.** all4_target berarti saldo>=500k dan floatingDD<=56 serta BUY/SELLnetpositif pada seluruh normal, biaya1,5×, biaya2× dan delay. all4_DD56 hanya memeriksa batas DD. Jika kolom itu False, jangan menyatakan batas56% bertahan pada seluruh kondisi. Biaya stress mengalikan fee/slippage/financing, spread tetap5bp. Delay satu menit. Leverage2× dan5× adalah leverage absolut, bukan pengali atas10×. Tabel kasus leverage rendah dan jumlah transaksi tiap tahun ada pada CSV.

## Jumlah uji dan audit

Stage1 menyelesaikan23.328geometri. Stage2 menyelesaikan58seed×180sizing=10.440konfigurasi, dengan9kelolosan nominal yang mensyaratkan kedua arah netpositif, minimal10basket tiap arah, minimal30total dan aktivitas setiap tahun. Refinement menguji525sizing berdekatan pada enam skenario masing-masing=3.150hasil. Ini bukan jutaan konsep independen. Refinement tetap memakai BUYprofile7844 dan SELLprofile2269 yang sudah ditemukan, bukan membuat ulang riset dari nol.

Kontrol parameter4259 direproduksi persis pada seluruh enam skenario sebelum hasil refinement diterima. Finalis refinement direplay ulang dan ledger diperiksa independen: grossPnL, komisi entry/exit, financing dari setiap openM1, netPnL, saldo kumulatif, jumlah arah dan tidak adanya posisi overlap. Hasil fase sebelumnya dan seluruh file internalnya juga diverifikasi SHA256.

## Keterbatasan dan status penggunaan

Semua pemilihan BUY/sizing/refinement ini memakai riwayat2019–2026 dan hasil stress yang sudah dilihat. Ini optimasi in-sample, bukan untouched out-of-sample. Sumber SELL sebelumnya dipilih dari2019–2024, tetapi itu tidak membuat seleksi pasangan baru independen. Tidak ada jaminan saldo500k, DD56%, profit tiap tahun, atau kemampuan broker mereplikasi hasil.

Input adalah official Bitstamp OHLCM1, bukan tick bid/ask broker. SHA256 CSV: c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504. Spread5bp, komisi5bp per sisi, slippage1bp per sisi, financing debit3bp notional per hari untuk kedua arah. Leverage10 belum dibuktikan sesuai kontrak broker. Closed-bar/next-open, stop-first, gapSLworseopen, floatingDD bound OHLC konservatif perM1 dipertahankan; grafik memakai snapshot jam. Capital-floor dan prioritas expiry/SL/TP sebelum fallback stop-out diwarisi. Bukan FULL_PARITY.

Tidak ada top-up, reset modal, synthetic ticks, aturan kalender untuk menghapus kerugian, atau penjumlahan dua rekening. cBot live, XAU/EUR, bridge dan env produksi tidak diubah; tidak ada order atau merge main. Paket disimpan di folder riset VPS terpisah dengan verifikasi checksum.

Source/model commit91964bdee9691407d5df324e373007253c8fb5d3.
Review commit{os.environ['GITHUB_SHA']}.
Search/audit:https://github.com/rizanrizan93/Forex-scanner/actions/runs/39342348232
Review/refinement:https://github.com/rizanrizan93/Forex-scanner/actions/runs/{os.environ['GITHUB_RUN_ID']}
'''
(out/'LAPORAN_AKHIR_BTC_MIN500K.md').write_text(report)
for name in ['btc_growth500_refine.cpp','finalize_btc_growth500.py']:shutil.copy2(code/name,out/name)
for p in rv.glob('*_equity.csv'):
 with p.open('rb') as src,gzip.open(str(p)+'.gz','wb') as dst:shutil.copyfileobj(src,dst)
 p.unlink()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
with (out/'MANIFEST_SHA256.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(out.rglob('*')):
  if p.is_file() and p.name not in ['MANIFEST_SHA256.csv','PACKAGE_SHA256.txt']:w.writerow([str(p.relative_to(out)),sha(p),p.stat().st_size])
package=out/'RIZAN_BTC_MIN500K_FINAL_AUDITED.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for p in sorted(out.rglob('*')):
  if p.is_file() and p!=package and p.name!='PACKAGE_SHA256.txt':z.write(p,str(p.relative_to(out)))
with zipfile.ZipFile(package) as z:assert z.testzip() is None
(out/'PACKAGE_SHA256.txt').write_text(sha(package)+'  '+package.name+'\n');print(json.dumps(status,indent=2,default=lambda x:x.item()),flush=True)
