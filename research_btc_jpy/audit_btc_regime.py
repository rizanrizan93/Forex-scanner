import pathlib,subprocess,sys,json,itertools,hashlib,shutil,zipfile,csv,gzip,os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=pathlib.Path.cwd();out=R/'regime_results';out.mkdir(exist_ok=True);code=R/'research_btc_jpy'
files=sorted((R/'regime_shards').glob('BTC-REGIME-SCREEN-*/SCREEN.csv'));assert len(files)==4
parts=[]
for sh,p in enumerate(files):
 d=pd.read_csv(p);assert len(d)==7776 and d.profile.nunique()==1944 and ((d.profile-1)%4==sh).all();parts.append(d)
q=pd.concat(parts,ignore_index=True);assert len(q)==31104 and not q.duplicated(['profile','side','period']).any()
q.to_csv(out/'DIRECTIONAL_SCREEN.csv.gz',index=False,compression='gzip')
assert hashlib.sha256((R/'source/data/BTCUSD_M1.csv').read_bytes()).hexdigest()=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
subprocess.run([sys.executable,str(code/'prepare_btc_regime.py'),str(out)],check=True)
shutil.copy2(code/'btc_regime.cpp',out/'btc_regime.cpp');subprocess.run(['g++','-O3','-std=c++17',str(out/'btc_regime.cpp'),'-o',str(R/'regime_audit')],check=True)
subprocess.run([str(R/'regime_audit'),'catalog',str(R/'source/data/BTCUSD_M1.csv'),str(out)],check=True)
choices={};selection={}
for side in [1,-1]:
 d=q[q.side==side];t=d[d.period=='TRAIN'].set_index('profile');v=d[d.period=='VALID'].set_index('profile')
 strict=(t.equity>t.capital)&(v.equity>v.capital)&(t.pf>1.05)&(v.pf>1.05)&(t.trades>=20)&(v.trades>=10)&(t.floating_dd<=56)&(v.floating_dd<=56)
 ok=strict.copy();fallback=False
 if not ok.any():
  fallback=True;ok=(t.equity*v.equity>t.capital*v.capital)&(t.trades>=10)&(v.trades>=5)&(t.floating_dd<=65)&(v.floating_dd<=65)
 if not ok.any():raise RuntimeError('No viable directional profile '+str(side))
 z=t[ok].copy();z['score']=np.minimum(np.log(z.equity/z.capital)/4,np.log(v.loc[z.index,'equity']/v.loc[z.index,'capital'])/2)-.005*np.maximum(z.floating_dd,v.loc[z.index,'floating_dd'])
 z=z.sort_values(['score','profile'],ascending=[False,True]).drop_duplicates(['tf_minutes','family','entry','regime']).head(12)
 choices[side]=list(z.index.astype(int));selection[str(side)]=dict(strict_count=int(strict.sum()),fallback=fallback,selected=choices[side]);z.to_csv(out/('BUY_PROFILES.csv' if side==1 else 'SELL_PROFILES.csv'))
(out/'PROFILE_SELECTION.json').write_text(json.dumps(selection,indent=2))
rows=[]
for i,(a,b,r,w,m) in enumerate(itertools.product(choices[1],choices[-1],[.05,.08,.10,.15,.20],[.5,1,1.5],[.5,.75]),1):rows.append(dict(id=i,buy_profile=a,sell_profile=b,risk=r,sell_weight=w,margin=m))
pairs=pd.DataFrame(rows);pairs.to_csv(out/'PAIR_CONFIGS.csv',index=False);print('PAIR_CONFIGURATIONS',len(pairs),selection,flush=True)
subprocess.run([str(R/'regime_audit'),'pair',str(R/'source/data/BTCUSD_M1.csv'),str(out),str(out/'PAIR_CONFIGS.csv')],check=True)
p=pd.read_csv(out/'PAIRS.csv');assert len(p)==len(pairs)*2 and not p.duplicated(['id','period']).any()
t=p[p.period=='TRAIN'].set_index('id');v=p[p.period=='VALID'].set_index('id')
coverage=(t[['y2019','y2020','y2021','y2022']].min(axis=1)>=3)&(v[['y2023','y2024']].min(axis=1)>=3)
strict=coverage&(t.equity>t.capital)&(v.equity>v.capital)&(t.buy_pnl>0)&(t.sell_pnl>0)&(v.buy_pnl>0)&(v.sell_pnl>0)&(t.buys>=10)&(t.sells>=10)&(v.buys>=5)&(v.sells>=5)&(t.floating_dd<=56)&(v.floating_dd<=56)
eligible=strict.copy();pair_fallback=False
if not eligible.any():
 pair_fallback=True;eligible=coverage&(t.equity*v.equity>t.capital*v.capital)&(t.buys>=10)&(t.sells>=10)&(v.buys>=5)&(v.sells>=5)&(t.floating_dd<=65)&(v.floating_dd<=65)
if not eligible.any():
 pair_fallback=True;eligible=coverage&(t.buys>0)&(t.sells>0)&(v.buys>0)&(v.sells>0)
coverage_pass=bool(eligible.any())
if not eligible.any():
 pair_fallback=True;eligible=(t.buys>0)&(t.sells>0)&(v.buys>0)&(v.sells>0)
assert eligible.any(),'No executed two-direction pair'
z=t[eligible].copy();z['score']=np.minimum(np.log(z.equity.clip(lower=.001)/z.capital)/4,np.log(v.loc[z.index,'equity'].clip(lower=.001)/v.loc[z.index,'capital'])/2)-.005*np.maximum(z.floating_dd,v.loc[z.index,'floating_dd'])
z=z.sort_values(['score','id'],ascending=[False,True]);ids=list(z.head(4).index)+list(z.nlargest(1,'equity').index)+list(z.nsmallest(1,'floating_dd').index)
ids=list(dict.fromkeys(ids));selected=pairs.set_index('id').loc[ids].reset_index();selected.to_csv(out/'LOCKED_FINALISTS.csv',index=False)
(out/'PAIR_SELECTION.json').write_text(json.dumps(dict(strict_count=int(strict.sum()),fallback=pair_fallback,primary_id=int(ids[0]),locked_ids=list(map(int,ids)),selection_uses_dates='2019-2024 only',diagnostics_dates='2025-2026 previously seen'),indent=2))
rv=out/'replay';rv.mkdir()
subprocess.run([str(R/'regime_audit'),'audit',str(R/'source/data/BTCUSD_M1.csv'),str(rv),str(out/'LOCKED_FINALISTS.csv')],check=True)
a=pd.read_csv(rv/'AUDIT.csv');a.to_csv(out/'LOCKED_STRESS.csv',index=False);checks=[];con=[];annual=[];monthly=[]
price=pd.read_csv(R/'source/data/BTCUSD_M1.csv',usecols=[0,1]);times=(pd.to_datetime(price.iloc[:,0]).astype('int64')//60_000_000_000).to_numpy();opens=price.iloc[:,1].to_numpy();funding=np.cumsum(opens*.0003/1440)
for _,r in a.iterrows():
 cid=int(r.id);case=r['case'];l=pd.read_csv(rv/f'candidate_{cid}_{case}_ledger.csv');scale=1.5 if case=='COST1_5' else 2 if case=='COST2' else 1
 gross=l.side*(l.exit_price-l.entry_average)*l.quantity;net=gross-l.entry_commission-l.exit_commission-l.financing
 errs=[float(abs(gross-l.gross_pnl).max()) if len(l) else 0,float(abs(net-l.net_pnl).max()) if len(l) else 0,float(abs(100+net.cumsum()-l.balance).max()) if len(l) else 0,abs(100+net.sum()-r.equity)]
 if len(l):
  entry=(pd.to_datetime(l.entry_utc).astype('int64')//60_000_000_000).to_numpy();exit=(pd.to_datetime(l.exit_utc).astype('int64')//60_000_000_000).to_numpy();ei=np.searchsorted(times,entry);xi=np.searchsorted(times,exit)
  # Continuous-input funding independently recomputed from every intervening M1 open.
  xi=np.minimum(xi,len(times)-1);expected=(funding[xi]-funding[ei])*l.quantity.to_numpy()*scale
  errs += [float(abs(l.entry_commission-l.quantity*l.entry_average*.0005*scale).max()),float(abs(l.exit_commission-l.quantity*l.exit_price*.0005*scale).max()),float(np.max(abs(expected-l.financing)))]
  assert (entry>=pd.to_datetime(l.signal_utc).astype('int64').to_numpy()//60_000_000_000).all()
  assert (entry[1:]>exit[:-1]).all(),'Overlapping/shared-state failure'
  assert int((l.side==1).sum())==r.buys and int((l.side==-1).sum())==r.sells
 assert max(errs)<max(1e-5,abs(r.equity)*1e-8),(cid,case,errs)
 checks.append(dict(id=cid,case=case,max_error=max(errs),gross=float(gross.sum()),fees=float((l.entry_commission+l.exit_commission).sum()),financing=float(l.financing.sum()),net=float(net.sum()),ending_balance=float(r.equity),passed=True))
 if case=='BASE':
  for side,g in l.groupby('side'):con.append(dict(id=cid,side=int(side),baskets=len(g),wins=int((g.net_pnl>0).sum()),winning_net=float(g.loc[g.net_pnl>0,'net_pnl'].sum()),losing_net=float(-g.loc[g.net_pnl<0,'net_pnl'].sum()),net=float(g.net_pnl.sum()),gross=float(g.gross_pnl.sum()),fees=float((g.entry_commission+g.exit_commission).sum()),financing=float(g.financing.sum())))
  for freq,collection in [('Y',annual),('M',monthly)]:
   groups=l.groupby(pd.to_datetime(l.exit_utc).dt.to_period(freq));balance=100
   for per in pd.period_range('2019-01-01','2026-10-15',freq=freq):
    g=groups.get_group(per) if per in groups.groups else l.iloc[:0];n=float(g.net_pnl.sum());collection.append(dict(id=cid,period=str(per),net=n,baskets=len(g),buy_net=float(g.loc[g.side==1,'net_pnl'].sum()),sell_net=float(g.loc[g.side==-1,'net_pnl'].sum()),return_pct=100*n/balance if balance else 0,ending_balance=balance+n));balance+=n
  c=pd.read_csv(rv/f'candidate_{cid}_BASE_equity.csv');fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True);tm=pd.to_datetime(c.timestamp);ax[0].plot(tm,c.equity,lw=.7);ax[0].set_yscale('symlog',linthresh=100);ax[0].set_ylabel('USD');ax[0].set_title(f'BTC causal entry/exit repair — pair{cid}');ax[1].plot(tm,-c.drawdown_pct,lw=.7);ax[1].axhline(-56,ls='--',lw=.6);ax[1].set_ylabel('Floating DD%');fig.tight_layout();fig.savefig(out/f'PAIR_{cid}_EQUITY_DD.png',dpi=140);plt.close(fig)
pd.DataFrame(con).to_csv(out/'DIRECTIONAL_CONTRIBUTIONS.csv',index=False);pd.DataFrame(annual).to_csv(out/'YEARLY.csv',index=False);pd.DataFrame(monthly).to_csv(out/'MONTHLY.csv',index=False);(out/'CASH_RECONCILIATION.json').write_text(json.dumps(checks,indent=2))
base=a[a['case']=='BASE'].copy();base['win_rate']=100*base.wins/base.trades.replace(0,np.nan);base['target600k_dd56']=(base.equity>=600000)&(base.floating_dd<=56)&(base.buys>0)&(base.sells>0);base.to_csv(out/'FINAL_METRICS.csv',index=False)
primary=base[base.id==ids[0]].iloc[0];year=pd.DataFrame(annual);ct=pd.DataFrame(con);primarycon=ct[ct.id==ids[0]]
status=dict(status='EXPLORATORY_M1_NOT_BROKER_VALIDATED',source_commit=os.environ['GITHUB_SHA'],run=os.environ['GITHUB_RUN_ID'],profiles=7776,directional_configurations=15552,screen_rows=31104,diagnostic_profile_capital=10000,diagnostic_pair_train_capital=100,diagnostic_pair_valid_capital=10000,full_replay_capital=100,pairs=len(pairs),strict_pairs=int(strict.sum()),pair_fallback=pair_fallback,selection_coverage_pass=coverage_pass,primary_id=int(ids[0]),primary=primary.to_dict(),primary_both_directions_net_positive=bool((primarycon.net>0).all()),primary_2026=year[(year.id==ids[0])&(year.period=='2026')].to_dict('records'),target_met_any_locked=bool(base.target600k_dd56.any()),previous600k_candidate_retained=True,live_changed=False,untouched_OOS=False)
(out/'REGIME_STATUS.json').write_text(json.dumps(status,indent=2))
cat=pd.read_csv(out/'CATALOG.csv');cat[cat.profile.isin(set(selected.buy_profile)|set(selected.sell_profile))].to_csv(out/'FINAL_PROFILE_DETAILS.csv',index=False)
report=f'''# BTCUSD — perbaikan entry, SL, TP dan regime

Primary pair{int(ids[0])} dipilih dari TRAIN2019–2022 dan VALID2023–2024, sebelum melihat hasil pasangan pada2025–2026. Periode2025–2026 sudah pernah terlihat dalam riset lama dan memotivasi perbaikan ini; bukan untouchedOOS.

7776 geometri,15552 konfigurasi arah,31104 baris dua segmen;{len(pairs)} pasangan sizing diuji. Strict pair lolos:{int(strict.sum())};fallback digunakan:{pair_fallback}. Target lama600k/DD56 pada finalis:{bool(base.target600k_dd56.any())}. Jumlah ini adalah ruang uji terbatas,bukan jutaan konsep independen.

## Parameter pasangan terkunci

{selected.to_markdown(index=False)}

{pd.read_csv(out/'FINAL_PROFILE_DETAILS.csv').to_markdown(index=False)}

## Replay kontinu2019–15Oktober2026

{base.to_markdown(index=False,floatfmt='.6f')}

## Kontribusi primary BUY/SELL

{primarycon.to_markdown(index=False,floatfmt='.6f')}

## Hasil tahunan primary

{year[year.id==ids[0]].to_markdown(index=False,floatfmt='.6f')}

## Stress parameter primary terkunci

{a[a.id==ids[0]].to_markdown(index=False,floatfmt='.6f')}

Baseline lama:$1.407.536,81,floatDD55,1416%,PF1,47765,115basket,63BUY52SELL. BUYnet+$1.477.890,14;SELLnet-$70.453,33. Tahun2026net-$970.262,66 atau-40,8051%. Perbandingan baru harus menilai arah,risiko dan tahun,tidak hanya nominal saldo. Kandidat lama tidak ditimpa.

SL0=1,5ATR;SL1 ekstrem signal/confirmation ditambahbuffer0,15ATR,jarak entry0,5–3ATR. TP2/3/6R;hold8/16bar H1/H4. Entry0closednextopen,entry1konfirmasi candleberikut menembus ekstrem,entry2retest midpoint dan rejection. Exit0fixed,exit1BE1R,exit2trailing1,5R setelah closeprofit1,5R. Stop baru efektif M1 berikutnya. Regime,RSI,ATRratio dan chasefilter hanya memakai data tersedia. Penjelasan lengkap di BTC_REGIME_PROTOCOL.md dan source.

Data BitstampOHLCM1,bukanbidasktickbroker. Asumsi leverage10,min/step0,01BTC,max100BTC,spread5bp,fee5bp/sisi,slip1bp/sisi,financingdebit3bp/hari keduaarah. Cost1,5/2 hanya fee/slip/financing;spreadtetap. Delay1menit. Leverage2/5 absolut. Satu saldo bersama,satu basketaktif,busyignored;opposing simultaneous signals keduanya dibuang. Tanpa topup atau reset modal pada replay penuh. Seleksi profile memakai10000USD per segmen untuk mengurangi distorsi minimumlot. Seleksi pasangan memakaiTRAIN100USD danVALID10000USD;return dinormalisasi terhadap modal masing-masing. Semua modal segmen hanyadiagnostik,tidakdijumlahkan. Replay penuh tetap100USD tanpa topup/reset. Minimum3basket tiap tahun2019–2024 pada segmen seleksi diwajibkan agar kandidat pasif tidak dinilai stabil.

Ledger diperiksa independen:gross,komisi,financing dari penjumlahanopenM1,net,balancesertaoverlapdanjumlaharah. DDperM1OHLCbound konservatif,grafiksnapshotjam. Capitalfloor dan expiry/SL/TP sebelum fallbackstopout diwarisi. Tidakada klaimFULL_PARITY,profitsetiaptahun,atau batasDDmasadepan. BelumdigabungXAU/EUR;tidakadaorder/livechange/mainmerge.

Commit:{os.environ['GITHUB_SHA']}
Actions:https://github.com/rizanrizan93/Forex-scanner/actions/runs/{os.environ['GITHUB_RUN_ID']}
'''
(out/'LAPORAN_BTC_ENTRY_EXIT_REGIME.md').write_text(report)
prior=R/'prior_attempt/RIZAN_BTC_ENTRY_EXIT_REGIME_RESEARCH.zip'
if prior.exists():shutil.copy2(prior,out/'FIRST_ATTEMPT_REJECTED_FOR_INACTIVITY.zip')
for name in ['prepare_btc_both.py','prepare_btc_regime.py','btc_regime.cpp','make_btc_regime_test.py','audit_btc_regime.py','BTC_REGIME_PROTOCOL.md','search_btc_position_high.cpp','btc_ten_million.cpp']:shutil.copy2(code/name,out/name)
for sh,p in enumerate(files):shutil.copy2(p.parent/'FIXTURES.log',out/f'FIXTURES_SHARD_{sh}.log');shutil.copy2(p.parent/'RUN.log',out/f'RUN_SHARD_{sh}.log')
for x in rv.glob('*_equity.csv'):
 with x.open('rb') as f,gzip.open(str(x)+'.gz','wb') as g:shutil.copyfileobj(f,g)
 x.unlink()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(out/'INPUT_SHA256.txt').write_text('c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504  BTCUSD_M1.csv\n')
with (out/'MANIFEST_SHA256.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for x in sorted(out.rglob('*')):
  if x.is_file() and x.name!='MANIFEST_SHA256.csv':w.writerow([str(x.relative_to(out)),sha(x),x.stat().st_size])
package=out/'RIZAN_BTC_ENTRY_EXIT_REGIME_RESEARCH.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for x in sorted(out.rglob('*')):
  if x.is_file() and x!=package:z.write(x,str(x.relative_to(out)))
with zipfile.ZipFile(package) as z:assert z.testzip() is None
(out/'PACKAGE_SHA256.txt').write_text(sha(package)+'  '+package.name+'\n');print(json.dumps(status,indent=2),flush=True)
