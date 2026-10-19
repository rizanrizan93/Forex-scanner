"""Executed continuation; original studies remain unchanged."""
import pathlib,json,csv,gzip,shutil,hashlib,subprocess,sys,zipfile,io,os
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path.cwd();OUT=ROOT/'btc_highest';OUT.mkdir(exist_ok=True);CODE=ROOT/'research_btc_jpy'
PH=['id','tf_minutes','family','lookback','threshold_index','trend_filter','session_utc','side','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dump(p,v):pathlib.Path(p).write_text(json.dumps(v,indent=2,allow_nan=False,default=lambda x:x.item() if hasattr(x,'item') else str(x)))
studies={};stats=[];selected={};baseframes=[];allcases=[];proofs=[]
for variant in ['POSITION_HIGH','SESSIONS_HIGH']:
 inp=ROOT/'merge_input'/variant;inp.mkdir(parents=True)
 for p in (ROOT/'shards').glob('RIZAN-BTC-HIGHEST-'+variant+'-BTCUSD-*'):
  shutil.copytree(p,inp/('BTCUSD_'+p.name.rsplit('-',1)[1]))
 study=OUT/variant
 subprocess.run([sys.executable,str(CODE/'merge_direct.py'),'BTCUSD',str(inp),str(study)],check=True)
 studies[variant]=study
# Previous aggressive cohort: exact original source and full table, not an altered proxy.
study=OUT/'PREVIOUS_AGGRESSIVE';study.mkdir();studies['PREVIOUS_AGGRESSIVE']=study
with zipfile.ZipFile(ROOT/'previous'/'RIZAN_BTCUSD_AGGRESSIVE_MILLION.zip') as z:
 manifest=pd.read_csv(z.open('MANIFEST_SHA256.csv'));expect=dict(zip(manifest.path,manifest.sha256))
 for path in z.namelist():
  if path.startswith('BTCUSD/') and ('/results_BTCUSD/' in path and path.endswith('.csv.gz') or path=='BTCUSD/search_direct_m1.cpp'):
   b=z.read(path);assert hashlib.sha256(b).hexdigest()==expect[path]
   dest=study/path.removeprefix('BTCUSD/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
canonical=OUT/'data';canonical.mkdir()
src=studies['POSITION_HIGH']/'data'/'BTCUSD_M1.csv'
assert sha(src)=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
shutil.copy2(src,canonical/'BTCUSD_M1.csv')
shutil.copy2(studies['POSITION_HIGH']/'data'/'BTCUSD_M1.csv.gz',canonical/'BTCUSD_M1.csv.gz')
source_data=canonical/'BTCUSD_M1.csv'
helper=(CODE/'validate_raw.cpp').read_text().replace('if(btc)cs.push_back({"LEVERAGE2",{1.,2}});','if(btc){cs.push_back({"LEVERAGE2",{1.,2}});cs.push_back({"LEVERAGE5",{1.,5}});}')
assert 'LEVERAGE5' in helper
for variant,study in studies.items():
 r=study/'results_BTCUSD';q=pd.read_csv(r/'ALL_CONFIGURATIONS.csv.gz' if (r/'ALL_CONFIGURATIONS.csv.gz').exists() else r/'ALL_CONFIGURATIONS.csv')
 assert len(q)==1000000 and q.id.nunique()==1000000 and not q[PH[1:]].duplicated().any()
 f=q.nlargest(20,'full_equity');cohorts=[f];criteria={'FULL':int(f.iloc[0].id)}
 for cap in [30,50,70,90]:
  d=q[(q.full_floating_dd<cap)&(q.full_trades>0)].nlargest(5,'full_equity')
  if len(d):cohorts.append(d);criteria['DD'+str(cap)]=int(d.iloc[0].id)
 t=q[(q.train_dd<50)&(q.train_trades>=20)].nlargest(20,'train_equity')
 if len(t):cohorts.append(t);criteria['TRAIN']=int(t.iloc[0].id)
 sel=pd.concat(cohorts).drop_duplicates('id');selected[variant]=(sel,criteria)
 stats.append({'variant':variant,'configurations':len(q),'target_final_100k_count':int((q.full_equity>=100000).sum()),'maximum_final':float(q.full_equity.max()),'top20_cutoff':float(f.full_equity.min()),'unique_tuples':1000000,'source_sha256':sha(study/'search_direct_m1.cpp'),'selected_parameters':len(sel)})
 with open(r/'ALL_CONFIGURATIONS.csv','rb') as a,gzip.open(r/'ALL_CONFIGURATIONS.csv.gz','wb',compresslevel=5) as b:shutil.copyfileobj(a,b) if (r/'ALL_CONFIGURATIONS.csv').exists() else None
 if (r/'ALL_CONFIGURATIONS.csv').exists():(r/'ALL_CONFIGURATIONS.csv').unlink()
 rv=study/'raw_validation';rv.mkdir(exist_ok=True);sel.to_csv(rv/'SELECTED_ROWS.csv',index=False)
 source=study/'search_direct_m1.cpp';flag=[]
 if variant=='POSITION_HIGH':shutil.copy2(source,study/'search_position_direct.cpp');flag=['-DPOSITION_VARIANT']
 if variant=='SESSIONS_HIGH':shutil.copy2(source,study/'search_sessions_direct.cpp');flag=['-DSESSION_VARIANT']
 (study/'validate_raw.cpp').write_text(helper)
 exe=ROOT/('validate_'+variant);subprocess.run(['g++','-O3','-std=c++17',*flag,str(study/'validate_raw.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe),str(source_data),'BTCUSD',str(rv/'SELECTED_ROWS.csv'),str(rv)],check=True)
 subprocess.run([sys.executable,str(CODE/'reconcile_raw.py'),str(study),'BTCUSD'],check=True)
 shutil.copy2(CODE/'prefix_invariance.cpp',study/'prefix_invariance.cpp')
 pexe=ROOT/('prefix_'+variant);subprocess.run(['g++','-O3','-std=c++17',*flag,str(study/'prefix_invariance.cpp'),'-o',str(pexe)],check=True)
 subprocess.run([str(pexe),str(source_data),'BTCUSD',str(study/'PREFIX_INVARIANCE.json')],check=True)
 v=pd.read_csv(rv/'RAW_TOP20_STRESS.csv');v['variant']=variant;allcases.append(v)
 b=v[v['case']=='BASE'].copy();b['win_rate']=100*b.wins/b.trades.replace(0,np.nan);b.win_rate=b.win_rate.fillna(0);baseframes.append(b)
 proofs.append({'variant':variant,**json.load(open(rv/'RAW_CASH_RECONCILIATION.json'))})
 del q
allbase=pd.concat(baseframes,ignore_index=True);stress=pd.concat(allcases,ignore_index=True)
rank=allbase.sort_values('equity',ascending=False).drop_duplicates(PH[1:]).head(20).copy();rank.insert(0,'rank',range(1,len(rank)+1))
rank.to_csv(OUT/'TOP20_HIGHEST_TERMINAL.csv',index=False);stress.to_csv(OUT/'ALL_SELECTED_STRESS.csv',index=False)
dump(OUT/'CASH_RECONCILIATION.json',proofs)
# Daily settled-cash return correlation, explicitly not floating MTM equity.
returns={};signalsets={};intervals={};descriptions=[]
days=pd.date_range('2019-01-01','2026-10-15',freq='D')
for _,r in rank.iterrows():
 variant=r.variant;cid=int(r.id);key=variant+'_'+str(cid);rv=studies[variant]/'raw_validation'
 l=pd.read_csv(rv/('raw_'+str(cid)+'_ledger.csv'))
 pnl=l.groupby(pd.to_datetime(l.exit_utc).dt.normalize()).net_pnl.sum().reindex(days,fill_value=0)
 start=100+pnl.cumsum().shift(1,fill_value=0);returns[key]=pnl/start
 signalsets[key]=set(l.signal_utc);intervals[key]=[(pd.Timestamp(a).value//60000000000,pd.Timestamp(b).value//60000000000+1) for a,b in zip(l.entry_utc,l.exit_utc)]
 descriptions.append({'key':key,**r.to_dict()})
 l['month']=pd.to_datetime(l.exit_utc).dt.strftime('%Y-%m');l['year']=pd.to_datetime(l.exit_utc).dt.year
 for col in ['month','year']:
  g=l.groupby(col).agg(net_profit=('net_pnl','sum'),baskets=('net_pnl','size'),adds=('adds','sum'),entry_fee=('entry_commission','sum'),exit_fee=('exit_commission','sum'),financing=('financing','sum'));g['ending_balance']=100+g.net_profit.cumsum();g.to_csv(rv/('raw_'+str(cid)+'_'+col+'.csv'))
def inter(a,b):
 i=j=n=0
 while i<len(a) and j<len(b):
  n+=max(0,min(a[i][1],b[j][1])-max(a[i][0],b[j][0]))
  if a[i][1]<b[j][1]:i+=1
  else:j+=1
 return n
corr=pd.DataFrame(returns,index=days).corr();corr.to_csv(OUT/'TOP20_DAILY_SETTLED_RETURN_CORRELATION.csv')
over=[]
for i,a in enumerate(returns):
 for b in list(returns)[i+1:]:
  ix=inter(intervals[a],intervals[b]);dur=sum(e-s for s,e in intervals[a])+sum(e-s for s,e in intervals[b])-ix
  over.append({'a':a,'b':b,'signal_jaccard':len(signalsets[a]&signalsets[b])/max(1,len(signalsets[a]|signalsets[b])),'open_time_jaccard':ix/max(1,dur),'daily_settled_return_correlation':float(corr.loc[a,b])})
pd.DataFrame(over).to_csv(OUT/'TOP20_OVERLAP.csv',index=False)
for variant,study in studies.items():
 sel,criteria=selected[variant];rv=study/'raw_validation'
 keep=set(int(x.id) for _,x in rank[rank.variant==variant].iterrows())|set(criteria.values())
 for p in rv.glob('raw_*_equity.csv'):
  cid=int(p.name.split('_')[1])
  if cid not in keep:p.unlink();continue
  if not ((rank.variant==variant)&(rank.id==cid)).any() and cid!=criteria['FULL']:continue
  c=pd.read_csv(p);fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True)
  ax[0].plot(pd.to_datetime(c.timestamp),c.equity,lw=.6);ax[0].set_yscale('symlog',linthresh=10);ax[0].set_ylabel('Model equity USD');ax[0].set_title('BTC '+variant+' '+str(cid)+' — full terminal period, no goal lock')
  ax[1].plot(pd.to_datetime(c.timestamp),-c.drawdown_pct,lw=.6);ax[1].set_ylabel('OHLC model DD %')
  for a in ax:a.grid(alpha=.25)
  fig.tight_layout();fig.savefig(rv/('raw_'+str(cid)+'_equity_drawdown.png'),dpi=140);plt.close(fig)
 for p in (study/'results_BTCUSD').glob('candidate_*'):p.unlink()
 d=study/'data'
 if d.exists():
  for p in d.glob('BTCUSD_M1.csv*'):p.unlink()
  dump(d/'DATASET_REFERENCE.json',{'canonical':'data/BTCUSD_M1.csv.gz','uncompressed_sha256':sha(source_data)})
# Integration contract is a reviewable design, not an implemented/live cBot.
integration={'status':'DESIGN_ONLY_NOT_COMBINED_REPLAY','frozen_XAU_EUR_unchanged':True,'BTC_selected_parameters':[x for x in descriptions[:5]],'separate_accounts_cannot_be_added':True,'broker_BTC_specs_verified':False,'required_broker_fields':['contract_size','volume_unit_meaning','volume_min','volume_step','max_volume','tick_size','leverage_tiers','commission_currency_and_basis','financing_schedule','execution_hours','stop_distance','stopout_level'],'intent_fields':['strategy_version_hash','symbol','closed_candle_utc','side','signal_price','atr','absolute_stop','absolute_target','expiry_utc','batch_id','idempotency_key'],'coordinator_required':['one_shared_equity_snapshot','reserve_pending_margin_and_stop_risk_before_submit','check_XAU_EUR_BTC_position_conflicts','deterministic_same_timestamp_priority_declared_before_replay','ACK_reject_settlement_idempotent_checkpoint_recovery','apply_BTC_contract_units_and_24x7_calendar'],'portfolio_risk_limits':None,'portfolio_risk_limits_note':'Must be set and tested separately; standalone BTC30-60pct risk must not be silently added to existing portfolio exposure. No default allocation invented.','next_validation':'synchronized BTC_XAU_EUR event replay with unchanged frozen XAU_EUR source; broker BBO/ticks and specifications required for execution claims'}
dump(OUT/'XAU_EUR_BTC_INTEGRATION_CONTRACT.json',integration)
champ=rank.iloc[0];champstress=stress[(stress.variant==champ.variant)&(stress.id==champ.id)]
prior=allbase[(allbase.variant=='PREVIOUS_AGGRESSIVE')&(allbase.id==22375)].iloc[0]
status={'status':'EXPLORATORY_M1_MODEL_NOT_BROKER_VALIDATED','period':'2019-01-01 through2026-10-15','initial_USD':100,'no_topups':True,'goal_lock':False,'new_configuration_evaluations':2000000,'total_BTC_evaluations_including_prior':6000000,'no_claim_global_unique_count':True,'universes':stats,'champion':champ.to_dict(),'champion_stress':champstress.to_dict('records'),'previous_champion':prior.to_dict(),'combined_XAU_EUR_performance':'NOT_TESTED','input_sha256':sha(source_data),'all_selected_baselines_reconstructed_and_cash_reconciled':True}
dump(OUT/'HIGHEST_STATUS.json',status)
def table(x,cols):return x[cols].to_markdown(index=False,floatfmt='.4f')
report='# BTCUSD — lanjutan pencarian saldo akhir tertinggi\n\nStatus: EXPLORATORY_M1_MODEL_NOT_BROKER_VALIDATED. USD100, tanpa top-up,2019-01-01 sampai2026-10-15, akun BTC terpisah. Seluruh periode diteruskan tanpa stop di100k. Dua juta konfigurasi baru; total6juta evaluasi BTC termasuk tahap sebelumnya, bukan6juta tuple global unik.\n\n'
report+='Universe baru dan pembanding lama:\n\n'+pd.DataFrame(stats).to_markdown(index=False)+'\n\n'
report+='Top20 parameter aktif unik berdasarkan saldo akhir nominal:\n\n'+table(rank,['rank','variant','id','family','tf_minutes','risk','margin_fraction','add_stages','equity','floating_dd','balance_dd','pf','trades','win_rate'])+'\n\n'
report+='Parameter juara lengkap:\n\n'+table(rank.head(1),PH+['variant','equity'])+'\n\n'
report+='Stres juara dengan parameter tetap, tanpa memilih ulang pemenang menurut stres:\n\n'+table(champstress,['case','equity','floating_dd','trades','adds','skips','liquidations'])+'\n\n'
report+='Pembanding juara sebelumnya22375 direkonstruksi, tidak diganti dengan proxy. Seluruh top20 lama ikut seleksi ulang, ditambah kandidat DD30/50/70/90 dan train-only. Pemimpin dari tiga universe awal lainnya maksimum85424,59 (POSITION),18046,40 (GENERIC),1396,68 (SESSIONS); semua berada di bawah cutoff top20 aggressive lama sehingga tidak mengubah ranking terminal global. Full tables dan laporan awal tetap tersedia pada Actions39217369074.\n\n'
report+='Kesamaan kandidat: TOP20_OVERLAP.csv memuat Jaccard timestamp sinyal dan interval posisi terbuka. Korelasi memakai return kas transaksi tertutup per hari, bukan floating-equity MTM atau bukti diversifikasi XAU/EUR. Kandidat yang serupa bukan sumber keuntungan independen. Tidak dilakukan penjumlahan saldo standalone.\n\n'
report+='Validasi:5shard200ribu tepat1juta tuple unik per universe, hash input/source sama; parameter terpilih direkonstruksi dalam source asli, kas dihitung ulang dari harga/volume/fee/financing. Uji500prefix future-price perturbation per engine. Ledger, biaya, reject/skips model, grafik, bulanan/tahunan top20 dan checksum disertakan. Ini pengujian implementasi model, bukan parity broker.\n\n'
report+='Data: official Bitstamp OHLC M1. Leverage10 hipotesis; sensitivitas2 dan5 terpisah. Model minimum/step0,01BTC,max100BTC; spread5bp,slip1bp/sisi,komisi5bp/sisi,financing debit3bpnotional/hari. Biaya1.5/2 mengalikan slip/fee/carry, tidak spread. Delay adalah minimum1menit, bukan2detik. Segmen train/valid/test restart100 setelah seleksi bukan OOS murni. NO_ADDS mengubah initial risk allocation ke100%. DD adalah statistik OHLC engine, bukan jaminan drawdown tick. Tidak ada bid/ask native broker, depth, partialfill,ACK,recovery,swap/leverage tiers historis atau stop-grid broker yang dibuktikan. Source memiliki permanent capital-floor guard; lihat source untuk kebijakan deaktivasi akun. Hasil dipilih dari jutaan percobaan dalam sampel sehingga risiko overfit besar.\n\n'
report+='Persiapan penggabungan: XAU_EUR_BTC_INTEGRATION_CONTRACT.json hanya desain. Source frozen XAU/EUR dan cBot live tidak diubah. Perlu shared equity/margin coordinator, pending-risk reservation, kontrak BTC broker, kalender24/7, konflik posisi dan settlement/checkpoint yang idempoten. Risk nominal standalone BTC tidak boleh dijumlahkan ke portfolio risk lama. Angka hasil portofolio gabungan belum dihitung; wajib replay tersinkron tiga simbol lebih dahulu. Tidak ada order broker, restart bridge, perubahan env produksi atau merge main.\n\n'
report+='Source/input/manifests dan seluruh laporan disimpan pada branch research/btc-highest-balance-2019-2026 serta VPS REPLAY_RESULTS/btc-highest-balance-2019-oct2026/run-ID. Paket REVIEW tidak memuat duplikat data M1 dan million-row tables; paket COMPLETE menyimpannya. Kedua manifest menjelaskan file yang ada; penghilangan hanya berdasarkan jenis file, bukan hasil performa.\n'
(OUT/'LAPORAN_BTC_HIGHEST.md').write_text(report)
for p in [CODE/'BTC_HIGHEST_PROTOCOL.md',CODE/'btc_highest_audit.py']:shutil.copy2(p,OUT/p.name)
(OUT/'REPORT_SOURCE_COMMIT.txt').write_text(os.environ['GITHUB_SHA']+'\n')
source_data.unlink()
def package(name,review):
 files=[]
 for p in sorted(OUT.rglob('*')):
  if not p.is_file() or p.suffix=='.zip' or p.name in ['PACKAGE_SHA256.txt','MANIFEST_COMPLETE.csv','MANIFEST_REVIEW.csv']:continue
  if review and (p.name=='ALL_CONFIGURATIONS.csv.gz' or p.name=='BTCUSD_M1.csv.gz' or p.name.endswith('_equity.csv')):continue
  files.append(p)
 manifest=OUT/('MANIFEST_REVIEW.csv' if review else 'MANIFEST_COMPLETE.csv')
 with open(manifest,'w') as f:
  w=csv.writer(f);w.writerow(['path','sha256','bytes'])
  for p in files:w.writerow([str(p.relative_to(OUT)),sha(p),p.stat().st_size])
 with zipfile.ZipFile(OUT/name,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
  for p in files+[manifest]:z.write(p,str(p.relative_to(OUT)))
 with zipfile.ZipFile(OUT/name) as z:
  assert z.testzip() is None
  for p in files:assert hashlib.sha256(z.read(str(p.relative_to(OUT)))).hexdigest()==sha(p)
package('RIZAN_BTC_HIGHEST_REVIEW.zip',True);package('RIZAN_BTC_HIGHEST_COMPLETE.zip',False)
with open(OUT/'PACKAGE_SHA256.txt','w') as f:
 for p in sorted(OUT.glob('*.zip')):f.write(sha(p)+'  '+p.name+'\n')
print('HIGHEST_RESULT',json.dumps(status,indent=2),flush=True)
