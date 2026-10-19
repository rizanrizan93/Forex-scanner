import pathlib,subprocess,sys,json,itertools,hashlib,shutil,zipfile,csv,gzip,os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=pathlib.Path.cwd();code=R/'research_btc_jpy';out=R/'growth500_results';out.mkdir(exist_ok=True)
files=sorted((R/'growth500_shards').glob('BTC-GROWTH500-SHARD-*/RESULTS.csv'));assert len(files)==4
parts=[]
for sh,p in enumerate(files):
 d=pd.read_csv(p);assert len(d)==5832 and ((d.id-1)%4==sh).all() and d['case'].eq('BASE').all();assert (p.parent/'COMMIT.txt').read_text().strip()==os.environ['GITHUB_SHA'];parts.append(d)
q=pd.concat(parts,ignore_index=True);assert len(q)==q.id.nunique()==23328 and set(q.id)==set(range(1,23329))
q.to_csv(out/'ALL_STAGE1_23328.csv.gz',index=False,compression='gzip')
assert hashlib.sha256((R/'source/data/BTCUSD_M1.csv').read_bytes()).hexdigest()=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
subprocess.run([sys.executable,str(code/'prepare_btc_growth500.py'),str(out)],check=True);shutil.copy2(code/'btc_growth500.cpp',out/'btc_growth500.cpp')
subprocess.run(['g++','-O3','-std=c++17',str(out/'btc_growth500.cpp'),'-o',str(R/'growth500_audit')],check=True)
subprocess.run([str(R/'growth500_audit'),'catalog',str(R/'source/data/BTCUSD_M1.csv'),str(out)],check=True)
def actual(d):return (d.buys>=10)&(d.sells>=10)&(d.trades>=30)&(d[[f'y{y}' for y in range(2019,2027)]].min(axis=1)>=1)
eligible=q[actual(q)&(q.buy_pnl>0)&(q.sell_pnl>0)]
seeds=pd.concat([eligible[eligible.floating_dd<=56].nlargest(20,'equity'),eligible[eligible.floating_dd<=65].nlargest(20,'equity'),eligible[eligible.equity>=200000].nsmallest(20,'floating_dd'),q[actual(q)&(q.buy_pnl>0)&(q.floating_dd<=70)].nlargest(20,'equity')]).drop_duplicates(['buy_profile','sell_profile'])
controls=q[q.buy_profile==7844];assert len(controls)==9
seeds=pd.concat([seeds,controls]).drop_duplicates(['buy_profile','sell_profile']);assert 1<=len(seeds)<=89
seeds.to_csv(out/'SIZING_SEEDS.csv',index=False)
rows=[]
for _,s in seeds.iterrows():
 for br,sr,bm,sm in itertools.product([.15,.18,.21,.23,.26,.30],[.02,.04,.075,.10,.15],[.75,.85,.95],[.3,.75]):
  rows.append(dict(id=len(rows)+1,buy_profile=int(s.buy_profile),sell_profile=int(s.sell_profile),buy_risk=br,sell_risk=sr,buy_margin=bm,sell_margin=sm))
configs=pd.DataFrame(rows);assert len(configs)==len(seeds)*180 and not configs.duplicated(list(configs.columns[1:])).any();configs.to_csv(out/'STAGE2_CONFIGS.csv',index=False)
grid=out/'grid';grid.mkdir();subprocess.run([str(R/'growth500_audit'),'all',str(R/'source/data/BTCUSD_M1.csv'),str(grid),str(out/'STAGE2_CONFIGS.csv')],check=True)
z=pd.read_csv(grid/'RESULTS.csv');assert len(z)==len(configs) and z.id.nunique()==len(z);z.to_csv(out/'ALL_STAGE2_RESULTS.csv.gz',index=False,compression='gzip');(grid/'RESULTS.csv').unlink()
good=z[actual(z)&(z.buy_pnl>0)&(z.sell_pnl>0)&(z.floating_dd<=56)].sort_values(['equity','id'],ascending=[False,True]);hits=good[good.equity>=500000].copy()
base=hits if len(hits) else good
if not len(base):base=z[actual(z)&(z.floating_dd<=56)].sort_values('equity',ascending=False)
assert len(base)>0,'No DD56 executed two-direction candidate'
base=base.copy();base['return2026']=100*base.g2026/(100+base[[f'g{y}' for y in range(2019,2026)]].sum(axis=1))
chosen=pd.concat([base.head(3),base.nsmallest(1,'floating_dd'),base.nlargest(1,'return2026'),base.assign(sell_fraction=base.sell_pnl/(base.equity-100)).nlargest(1,'sell_fraction')]).drop_duplicates('id')
params=list(configs.columns);chosen[params].to_csv(out/'LOCKED_FINALISTS.csv',index=False)
rv=out/'replay';rv.mkdir();subprocess.run([str(R/'growth500_audit'),'audit',str(R/'source/data/BTCUSD_M1.csv'),str(rv),str(out/'LOCKED_FINALISTS.csv')],check=True)
a=pd.read_csv(rv/'RESULTS.csv');a.to_csv(out/'LOCKED_STRESS.csv',index=False);checks=[];con=[];annual=[];monthly=[]
price=pd.read_csv(R/'source/data/BTCUSD_M1.csv',usecols=[0,1]);times=(pd.to_datetime(price.iloc[:,0]).astype('int64')//60_000_000_000).to_numpy();fund=np.cumsum(price.iloc[:,1].to_numpy()*.0003/1440)
for _,r in a.iterrows():
 cid=int(r.id);case=r['case'];l=pd.read_csv(rv/f'candidate_{cid}_{case}_ledger.csv');scale=1.5 if case=='COST1_5' else 2 if case=='COST2' else 1
 gross=l.side*(l.exit_price-l.entry_average)*l.quantity;net=gross-l.entry_commission-l.exit_commission-l.financing
 errors=[float(abs(gross-l.gross_pnl).max()) if len(l) else 0,float(abs(net-l.net_pnl).max()) if len(l) else 0,float(abs(100+net.cumsum()-l.balance).max()) if len(l) else 0,abs(100+net.sum()-r.equity)]
 if len(l):
  en=(pd.to_datetime(l.entry_utc).astype('int64')//60_000_000_000).to_numpy();ex=(pd.to_datetime(l.exit_utc).astype('int64')//60_000_000_000).to_numpy();ei=np.searchsorted(times,en);xi=np.minimum(np.searchsorted(times,ex),len(times)-1)
  carry=(fund[xi]-fund[ei])*l.quantity.to_numpy()*scale;errors.extend([float(abs(l.entry_commission-l.quantity*l.entry_average*.0005*scale).max()),float(abs(l.exit_commission-l.quantity*l.exit_price*.0005*scale).max()),float(np.max(abs(carry-l.financing)))])
  assert (en[1:]>ex[:-1]).all() and int((l.side==1).sum())==r.buys and int((l.side==-1).sum())==r.sells
 assert max(errors)<max(1e-5,abs(r.equity)*1e-9),(cid,case,errors)
 checks.append(dict(id=cid,case=case,maximum_error=max(errors),gross=float(gross.sum()),commissions=float((l.entry_commission+l.exit_commission).sum()),financing=float(l.financing.sum()),net=float(net.sum()),balance=float(r.equity),passed=True))
 if case=='BASE':
  old=chosen[chosen.id==cid].iloc[0]
  for k in ['equity','floating_dd','balance_dd','buy_pnl','sell_pnl']:assert abs(old[k]-r[k])<max(1e-7,abs(r[k])*1e-9)
  for side,g in l.groupby('side'):con.append(dict(id=cid,side=int(side),baskets=len(g),wins=int((g.net_pnl>0).sum()),gross=float(g.gross_pnl.sum()),winning_net=float(g.loc[g.net_pnl>0,'net_pnl'].sum()),losing_net=float(-g.loc[g.net_pnl<0,'net_pnl'].sum()),commissions=float((g.entry_commission+g.exit_commission).sum()),financing=float(g.financing.sum()),net=float(g.net_pnl.sum())))
  for freq,collection in [('Y',annual),('M',monthly)]:
   groups=l.groupby(pd.to_datetime(l.exit_utc).dt.to_period(freq));bal=100
   for per in pd.period_range('2019-01-01','2026-10-15',freq=freq):
    g=groups.get_group(per) if per in groups.groups else l.iloc[:0];pnl=float(g.net_pnl.sum());collection.append(dict(id=cid,period=str(per),net=pnl,baskets=len(g),buy_net=float(g.loc[g.side==1,'net_pnl'].sum()),sell_net=float(g.loc[g.side==-1,'net_pnl'].sum()),return_pct=100*pnl/bal if bal else 0,ending_balance=bal+pnl));bal+=pnl
  c=pd.read_csv(rv/f'candidate_{cid}_BASE_equity.csv');fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True);tm=pd.to_datetime(c.timestamp);ax[0].plot(tm,c.equity,lw=.7);ax[0].set_yscale('symlog',linthresh=100);ax[0].set_title(f'BTC BUY + SELL growth500 — candidate{cid}');ax[0].set_ylabel('Equity USD');ax[1].plot(tm,-c.drawdown_pct,lw=.7);ax[1].axhline(-56,ls='--',lw=.7);ax[1].set_ylabel('Floating DD%');fig.tight_layout();fig.savefig(out/f'CANDIDATE_{cid}_EQUITY_DD.png',dpi=140);plt.close(fig)
pd.DataFrame(con).to_csv(out/'DIRECTIONAL_CONTRIBUTIONS.csv',index=False);pd.DataFrame(annual).to_csv(out/'YEARLY.csv',index=False);pd.DataFrame(monthly).to_csv(out/'MONTHLY.csv',index=False);(out/'CASH_RECONCILIATION.json').write_text(json.dumps(checks,indent=2))
b=a[a['case']=='BASE'].copy();b['win_rate']=100*b.wins/b.trades.replace(0,np.nan);b['target_met']=(b.equity>=500000)&(b.floating_dd<=56)&(b.buy_pnl>0)&(b.sell_pnl>0)&actual(b);b.to_csv(out/'FINAL_METRICS.csv',index=False)
qual=b[b.target_met].copy();robust=[]
for _,r in qual.iterrows():
 s=a[a.id==r.id];core=s[s['case'].isin(['BASE','COST1_5','COST2','DELAY_NEXT_M1'])]
 robust.append(dict(id=int(r.id),all4_balance500k_DD56=bool(((core.equity>=500000)&(core.floating_dd<=56)).all()),all4_DD56=bool((core.floating_dd<=56).all()),all4_netpositive=bool((core.equity>100).all())))
rob=pd.DataFrame(robust,columns=['id','all4_balance500k_DD56','all4_DD56','all4_netpositive']);rob.to_csv(out/'STRESS_QUALIFICATION.csv',index=False)
if len(qual):
 merged=qual.merge(rob,on='id').sort_values(['all4_balance500k_DD56','all4_DD56','equity'],ascending=[False,False,False]);primary=merged.iloc[0]
else:primary=b.sort_values('equity',ascending=False).iloc[0]
pid=int(primary.id);status=dict(status='EXPLORATORY_M1_NOT_BROKER_VALIDATED',target_met=bool(len(hits)),target_balance=500000,floatDD_limit=56,initial_USD=100,topups=0,stage1_cases=len(q),stage2_seeds=len(seeds),stage2_cases=len(z),target_hits=len(hits),primary_id=pid,primary=primary.to_dict(),live_changed=False,untouched_OOS=False,source_commit=os.environ['GITHUB_SHA'],run=os.environ['GITHUB_RUN_ID'])
(out/'GROWTH500_STATUS.json').write_text(json.dumps(status,indent=2,default=lambda x:x.item()));cat=pd.read_csv(out/'CATALOG.csv');cfg=chosen[chosen.id==pid][params].iloc[0].to_dict();sp=int(cfg['sell_profile']) or int(cfg['buy_profile']);details=cat[cat.profile.isin([int(cfg['buy_profile']),sp])];details.to_csv(out/'PRIMARY_PROFILE_DETAILS.csv',index=False)
(out/'PRIMARY_CONFIG.json').write_text(json.dumps(dict(parameters=cfg,profiles=details.to_dict('records'),source_commit=os.environ['GITHUB_SHA']),indent=2))
year=pd.DataFrame(annual);direction=pd.DataFrame(con);core=a[a.id==pid]
report=f'''# BTCUSD — target minimum $500.000, floating DD maksimum56%

**Target nominal: {'TERCAPAI' if len(hits) else 'BELUM TERCAPAI'}.** Modal awal$100 tanpa top-up;1Januari2019–15Oktober2026. Primary ID{pid}. BUY dan SELL berbagi saldo,margin,compounding serta state eksekusi. Satu basket aktif,sinyal busy diabaikan,sinyal arah berlawanan bersamaan dibuang keduanya.

## Hasil finalis yang direplay ulang

{b[['id','equity','floating_dd','balance_dd','pf','win_rate','trades','buys','sells','buy_pnl','sell_pnl','target_met']].to_markdown(index=False,floatfmt='.6f')}

Target tambahan mengharuskan BUYdanSELL masing-masing netpositif dan minimal10basketaktual,30baskettotal,sertaaktivitas setiap tahun2019–2026. Hasil dengan SELLrugi tidak disebut perbaikan diversifikasi.

## Konfigurasi primary

```json
{json.dumps(cfg,indent=2)}
```

{details.to_markdown(index=False)}

Profilegrowth1 adalah varian mesinBUYlama:displacement_followH4 atau structure_breakD1. Entry0 nextopen,entry1 candleberikutnya harusclosedmenembusekstrem,entry2 retestmidpoint dan rejection. Regime0H4aligned,1H4+D1aligned,2H4aligned+D1tidakberlawanan. SLfixedstop_atr×ATR14,TPtp_R×jarakSL,hold_bars×TFmenit. Exit0fixed,1BE1R,2trailing1,5R setelahcloseprofit1,5R,berlakuM1berikutnya. Session0semuawaktu,1pukul00–08UTC. GrowthBUY tidak memakai capRSI/body/ATRratioV2,karena cap tersebut menghilangkan leg pertumbuhan utama. Chase0,5ATR tetap dipakai. Ini bukan bukti sudah bebas dari bull dependence.

Profilegrowth0 SELL mempertahankan aturanV2:body<=2,5ATR,RSI>=25,ATRratio0,6–1,8;regime0H4aligned,1D1aligned+H4notopposing,2ER12regime. Stopmode0fixed1,5ATR;1strukturhigh ditambahspread danbuffer0,15ATR,jarak0,5–3ATR. Definisi lengkapdi source dan protokol. Sellprofile0 berarti mirror geometriBUY sebagai kontrol,bukan penjumlahan replay terpisah.

## Kontribusi primary

{direction[direction.id==pid].to_markdown(index=False,floatfmt='.6f')}

## Hasil tahunan primary

{year[year.id==pid].to_markdown(index=False,floatfmt='.6f')}

## Stress konfigurasi primary terkunci

{core[['case','equity','floating_dd','balance_dd','pf','trades','buys','sells','buy_pnl','sell_pnl']].to_markdown(index=False,floatfmt='.6f')}

{rob.to_markdown(index=False)}

Kelolosan nominal berbeda dari kelolosan stress. Cost1,5/2 mengalikan komisi,slippage,financing saja;spreadtetap5bp. Delay satu menit. Leverage2/5adalah absolut,bukan pengali10×. Aktivitas tiap tahun tersedia dalam LOCKED_STRESS.csv;DD kecil karena tidak mampu memenuhi minimumlot harus ditafsirkan sebagai kendala aktivitas.

## Ruang uji, audit dan keterbatasan

Stage1:{len(q)}kombinasi geometri. Stage2:{len(seeds)}seed×180sizing={len(z)}konfigurasi. Targethit:{len(hits)}. Dua keluargaBUYutama dengan2592geometri dipasangkan dengan8SELLprofilehasilseleksi2019–2024ditambahmirrorcontrol. SemuaoptimasiBUY/sizingbaru memakai periodepenuh2019–2026;risikooverfitbesar,bukanuntouchedOOS. Tidakadafiltertanggaluntukmenyembunyikan2026,resetmodal,topup,atausynthetic ticks.

DataofficialBitstampOHLCM1,bukan tickbidaskbroker. SHA256CSV c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504. Leverage10hipotesis,min/step0,01BTC,max100BTC,spread5bp,komisi5bp/sisi,slippage1bp/sisi,financingdebit3bpnotional/hari keduaarah. Closed-bars,nextopen,stop-first,gapSLworseopen,OHLCboundDDsetiapM1 dipertahankan;grafiksnapshotjam. Capitalfloor,expiry/SL/TPsebelumfallbackstopout diwarisi. BukanFULL_PARITY ataujaminanhasilmasadepan.

SeluruhBASEfinalis direproduksi persis dari grid. Cashledger direkonsiliasi independen:gross,komisi,financingdariopenM1,net,saldokumulatif,arahdanoverlap. Fixturewarisan+regime serta reproduksi955kBUY lama lulus. Paket berisi semua hasil,parameter,ledger,bulanan/tahunan,grafik,source,diffdanchecksum. CBotlive,XAU/EUR,bridge,envproduksitidakdiubah;tidakadaorderataumergemain.

Commit:{os.environ['GITHUB_SHA']}
Actions:https://github.com/rizanrizan93/Forex-scanner/actions/runs/{os.environ['GITHUB_RUN_ID']}
'''
(out/'LAPORAN_BTC_GROWTH500.md').write_text(report);shutil.copy2(out/f'CANDIDATE_{pid}_EQUITY_DD.png',out/'PRIMARY_EQUITY_DD.png')
for name in ['prepare_btc_both.py','prepare_btc_regime.py','prepare_btc_growth500.py','btc_regime.cpp','btc_growth500.cpp','make_btc_regime_test.py','make_btc_growth500_test.py','generate_btc_growth500.py','audit_btc_growth500.py','BTC_GROWTH500_PROTOCOL.md','search_btc_position_high.cpp','btc_ten_million.cpp']:shutil.copy2(code/name,out/name)
for sh,p in enumerate(files):
 shutil.copy2(p.parent/'FIXTURES.log',out/f'FIXTURES_SHARD_{sh}.log');shutil.copy2(p.parent/'RUN.log',out/f'RUN_SHARD_{sh}.log')
for p in rv.glob('*_equity.csv'):
 with p.open('rb') as src,gzip.open(str(p)+'.gz','wb') as dst:shutil.copyfileobj(src,dst)
 p.unlink()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
with (out/'MANIFEST_SHA256.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(out.rglob('*')):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([str(p.relative_to(out)),sha(p),p.stat().st_size])
package=out/'RIZAN_BTC_GROWTH500_AUDITED.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as zf:
 for p in sorted(out.rglob('*')):
  if p.is_file() and p!=package:zf.write(p,str(p.relative_to(out)))
with zipfile.ZipFile(package) as zf:assert zf.testzip() is None
(out/'PACKAGE_SHA256.txt').write_text(sha(package)+'  '+package.name+'\n');print(json.dumps(status,indent=2,default=lambda x:x.item()),flush=True)
