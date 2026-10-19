import pathlib,zipfile,json,csv,gzip,io,hashlib,re,shutil,subprocess,sys,os
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path.cwd();OUT=ROOT/'legacy_results';OUT.mkdir(exist_ok=True);CODE=ROOT/'research_btc_jpy'
PH=['id','tf_minutes','family','lookback','threshold_index','trend_filter','session_utc','side','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dump(p,x):pathlib.Path(p).write_text(json.dumps(x,indent=2,allow_nan=False,default=lambda z:z.item() if hasattr(z,'item') else str(z)))
def verify_file(p,manifest):
 rows=pathlib.Path(manifest).read_text().splitlines();expected={l.split('  ',1)[1]:l.split('  ',1)[0] for l in rows};assert sha(p)==expected[p.name]
old=ROOT/'old'/'RIZAN_BTCUSD_RESEARCH_COMPACT_2019_2026.zip';new=ROOT/'high'/'RIZAN_BTC_HIGHEST_COMPLETE.zip'
verify_file(old,ROOT/'old'/'COMPACT_SHA256.txt');verify_file(new,ROOT/'high'/'PACKAGE_SHA256.txt')
archives=[(old,'MANIFEST_SHA256.csv', [('ORIGINAL_'+v,'FULL_PERIOD/'+v+'/') for v in ['GENERIC','SESSIONS','POSITION']]),(new,'MANIFEST_COMPLETE.csv',[(v,v+'/') for v in ['PREVIOUS_AGGRESSIVE','POSITION_HIGH','SESSIONS_HIGH']])]
studies={};seeds={};baseline=[];stats=[]
data=ROOT/'BTCUSD_M1.csv'
for archive,manifest,variants in archives:
 with zipfile.ZipFile(archive) as z:
  m=pd.read_csv(z.open(manifest));ex=dict(zip(m.path,m.sha256))
  def read(n):
   b=z.read(n);assert hashlib.sha256(b).hexdigest()==ex[n],n;return b
  if not data.exists():data.write_bytes(gzip.decompress(read('FULL_PERIOD/GENERIC/data/BTCUSD_M1.csv.gz')))
  for variant,prefix in variants:
   study=OUT/variant;study.mkdir();studies[variant]=study
   src=read(prefix+'search_direct_m1.cpp').decode();(study/'ORIGINAL_ENGINE.cpp').write_text(src)
   # Only extend numeric sizing grids; reproduce every original selected seed.
   src2=re.sub(r'const double risks\[\]=\{[^}]+\},margins\[\]=\{[^}]+\};','const double risks[]={0.01,0.02,0.03,0.04,0.05,0.06,0.07,0.075,0.08,0.09,0.1,0.11,0.12,0.13,0.14,0.15,0.16,0.17,0.18,0.19,0.2,0.21,0.22,0.23,0.24,0.25,0.26,0.27,0.28,0.29,0.3,0.31,0.32,0.33,0.34,0.35,0.36,0.37,0.38,0.39,0.4,0.5,0.6},margins[]={0.1,0.2,0.25,0.3,0.31,0.32,0.33,0.34,0.35,0.36,0.37,0.38,0.39,0.4,0.41,0.42,0.43,0.44,0.45,0.46,0.47,0.48,0.49,0.5,0.51,0.52,0.53,0.54,0.55,0.56,0.57,0.58,0.59,0.6,0.61,0.62,0.63,0.64,0.65,0.66,0.67,0.68,0.69,0.7,0.71,0.72,0.73,0.74,0.75,0.76,0.77,0.78,0.79,0.8,0.81,0.82,0.83,0.84,0.85,0.86,0.87,0.88,0.89,0.9,0.91,0.92,0.93,0.94,0.95};',src)
   assert src2!=src
   (study/'search_direct_m1.cpp').write_text(src2)
   flags=[]
   if 'POSITION' in variant:shutil.copy2(study/'search_direct_m1.cpp',study/'search_position_direct.cpp');flags=['-DPOSITION_VARIANT']
   if 'SESSIONS' in variant:shutil.copy2(study/'search_direct_m1.cpp',study/'search_sessions_direct.cpp');flags=['-DSESSION_VARIANT']
   studies[variant]=(study,flags)
   q=pd.read_csv(io.BytesIO(read(prefix+'results_BTCUSD/ALL_CONFIGURATIONS.csv.gz')),compression='gzip')
   assert len(q)==1000000
   low=q[(q.full_floating_dd<60)&(q.full_trades>=30)];band=q[(q.full_floating_dd>=50)&(q.full_floating_dd<60)&(q.full_trades>=30)];under=q[(q.full_floating_dd<60)&(q.full_trades>=30)]
   b=pd.concat([low.nlargest(10,'full_equity'),band.nlargest(10,'full_equity')]).drop_duplicates('id');b['variant']=variant;b['origin']='PRIOR_FULL_TABLE';baseline.append(b)
   train=q[(q.train_dd<50)&(q.train_trades>=20)].nlargest(2,'train_equity')
   seed=pd.concat([low.nlargest(5,'full_equity'),under.nlargest(5,'full_equity'),q.nlargest(3,'full_equity'),train]).drop_duplicates('id')
   seeds[variant]=seed;seed.to_csv(study/'SEEDS.csv',index=False)
   stats.append({'variant':variant,'prior_rows':len(q),'below60_count':len(low),'band50_to60_count':len(band),'max_below60':float(low.full_equity.max()) if len(low) else None,'max_band50_to60':float(band.full_equity.max()) if len(band) else None,'selected_seeds':len(seed),'original_source_sha256':hashlib.sha256(src.encode()).hexdigest()})
   del q
assert sha(data)=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
helper=(CODE/'validate_raw.cpp').read_text().replace('ix(risks,8,','ix(risks,int(sizeof(risks)/sizeof(risks[0])),').replace('ix(margins,3,','ix(margins,int(sizeof(margins)/sizeof(margins[0])),')
helper=helper.replace('if(btc)cs.push_back({"LEVERAGE2",{1.,2}});','if(btc){cs.push_back({"LEVERAGE2",{1.,2}});cs.push_back({"LEVERAGE5",{1.,5}});}')
helper=helper.replace('Global full-period top20, DD50 top20 and train-selected top20 union; no minimum full trade-count filter','Legacy DD60 screening and fine sizing; selected cohort only')
helper=helper.replace('name=="BASE"?outdir+"/raw_"+to_string(p.id):""','name=="BASE"?outdir+"/raw_"+to_string(p.id):outdir+"/raw_"+to_string(p.id)+"_"+name')
helper=helper.replace('R r=simulate(p,true,a,z);','R r=simulate(p,true,a,z,{},outdir+"/raw_"+to_string(p.id)+"_"+label);')
sweepblock=r'''
 if(argc>5&&string(argv[5])=="SWEEP"){
  R seedResult=simulate(p,true,parse("2019-01-01 00:00:00"),endtime);
  if(abs(seedResult.eq-val("full_equity"))>max(1e-6,abs(val("full_equity"))*1e-9)||seedResult.trades!=int(val("full_trades")))throw runtime_error("SEED_DIFFERENTIAL_FAILED");
  for(double rr:vector<double>{0.01,0.02,0.03,0.04,0.05,0.06,0.07,0.08,0.09,0.1,0.11,0.12,0.13,0.14,0.15,0.16,0.17,0.18,0.19,0.2,0.21,0.22,0.23,0.24,0.25,0.26,0.27,0.28,0.29,0.3,0.31,0.32,0.33,0.34,0.35,0.36,0.37,0.38,0.39,0.4})for(double mm:vector<double>{0.1,0.2,0.25,0.3,0.31,0.32,0.33,0.34,0.35,0.36,0.37,0.38,0.39,0.4,0.41,0.42,0.43,0.44,0.45,0.46,0.47,0.48,0.49,0.5,0.51,0.52,0.53,0.54,0.55,0.56,0.57,0.58,0.59,0.6,0.61,0.62,0.63,0.64,0.65,0.66,0.67,0.68,0.69,0.7,0.71,0.72,0.73,0.74,0.75,0.76,0.77,0.78,0.79,0.8,0.81,0.82,0.83,0.84,0.85,0.86,0.87,0.88,0.89,0.9,0.91,0.92,0.93,0.94,0.95}){
   P a=p;a.risk=ix(risks,int(sizeof(risks)/sizeof(risks[0])),rr);a.margin=ix(margins,int(sizeof(margins)/sizeof(margins[0])),mm);
   if(!seenSweep.insert(canonical(a)).second)continue;
   a.id=1000000+(++sweepCount);
   R r=simulate(a,true,parse("2019-01-01 00:00:00"),endtime);
   o<<"GRID,";params(o,a);o<<",";result(o,r);o<<"\n";
  }
  n++;continue;
 }
'''
sweeper=helper.replace('int n=0;','int n=0,sweepCount=0;set<string>seenSweep;').replace(' vector<pair<string,Model>> cs=',sweepblock+'\n vector<pair<string,Model>> cs=')
assert 'SEED_DIFFERENTIAL_FAILED' in sweeper
checkpoint=ROOT/'checkpoint'/'ALL_TARGETED_SIZING_CASES.csv'
assert sha(checkpoint)=='7d97759d0bc498d64e9c81380a0526a7a4b2ca7be1093eb55cf5baa8fadb0e4e'
ref=pd.read_csv(checkpoint);assert len(ref)==157320 and set(ref.variant)==set(studies)
shutil.copy2(checkpoint,OUT/'ALL_TARGETED_SIZING_CASES.csv')
sweep_proof=[]
seedhelper=re.sub(r' vector<pair<string,Model>> cs=[^\n]*',' vector<pair<string,Model>> cs={{"BASE",{}}};',helper)
seedhelper=re.sub(r' for\(auto seg:[^\n]*\n','',seedhelper)
for variant,(study,flags) in studies.items():
 (study/'seed_validate.cpp').write_text(seedhelper)
 exe=ROOT/('seed_validate_'+variant);subprocess.run(['g++','-O3','-std=c++17',*flags,str(study/'seed_validate.cpp'),'-o',str(exe)],check=True)
 seedroot=study/'seed_check';seedrv=seedroot/'raw_validation';seedrv.mkdir(parents=True)
 subprocess.run([str(exe),str(data),'BTCUSD',str(study/'SEEDS.csv'),str(seedrv)],check=True)
 subprocess.run([sys.executable,str(CODE/'reconcile_raw.py'),str(seedroot),'BTCUSD'],check=True)
 sweep_proof.append({'variant':variant,'all_original_seed_equity_and_trade_counts_reconciled':True,'seeds':len(seeds[variant]),'unique_sizing_cases':int((ref.variant==variant).sum()),'sizing_rows_restored_from_verified_checkpoint':True,'checkpoint_run':39252456294})
 dump(study/'SIZING_SWEEP_PROOF.json',sweep_proof[-1])
dump(OUT/'RESUME_PROVENANCE.json',{'original_sizing_run':39252456294,'original_sizing_commit':'0d6c1065aff3cfb6c838372dada44e097f193b7e','checkpoint_sha256':sha(checkpoint),'rows_unchanged':157320,'failure_reason':'Legacy BASE-only reconciler scanned newly added stress ledgers and compared their balance to BASE. Filter now restricts BASE files, while separate all-case reconciler verifies every scenario. No tolerance or financial execution changes.','original_seeds_reverified':True})

pool=pd.concat(baseline+[ref],ignore_index=True)
for col in PH[1:]:
 if col!='family':pool[col]=pd.to_numeric(pool[col]).round(12)
low=pool[(pool.full_floating_dd<60)&(pool.full_trades>=30)].sort_values('full_equity',ascending=False).drop_duplicates(PH[1:]).head(5)
band=pool[(pool.full_floating_dd<50)&(pool.full_trades>=30)].sort_values('full_equity',ascending=False).drop_duplicates(PH[1:]).head(5)
chosen=pd.concat([low.assign(criterion='DD_LT60'),band.assign(criterion='DD_LT50_BACKUP')]).drop_duplicates(['variant','id'])
computed_best=chosen[chosen.criterion=='DD_LT60'].full_equity.max()
chosen=pd.read_csv(ROOT/'checkpoint'/'SELECTED_BEFORE_STRESS.csv')
assert abs(chosen[chosen.criterion=='DD_LT60'].full_equity.max()-computed_best)<1e-6
chosen.to_csv(OUT/'SELECTED_BEFORE_STRESS.csv',index=False)
allcases=[];cash=[];curves=[]
for variant,g in chosen.groupby('variant'):
 study,flags=studies[variant];rv=study/'raw_validation';rv.mkdir()
 g.to_csv(rv/'SELECTED_ROWS.csv',index=False);(study/'validate_raw.cpp').write_text(helper)
 exe=ROOT/('validate_'+variant);subprocess.run(['g++','-O3','-std=c++17',*flags,str(study/'validate_raw.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe),str(data),'BTCUSD',str(rv/'SELECTED_ROWS.csv'),str(rv)],check=True)
 subprocess.run([sys.executable,str(CODE/'reconcile_raw.py'),str(study),'BTCUSD'],check=True)
 cash.append({'variant':variant,**json.load(open(rv/'RAW_CASH_RECONCILIATION.json'))})
 v=pd.read_csv(rv/'RAW_TOP20_STRESS.csv');v['variant']=variant;allcases.append(v)
 for _,row in g.iterrows():
  cid=int(row.id);l=pd.read_csv(rv/('raw_'+str(cid)+'_ledger.csv'));c=pd.read_csv(rv/('raw_'+str(cid)+'_equity.csv'))
  for k in ['month','year']:
   dates=pd.to_datetime(l.exit_utc);l[k]=dates.dt.strftime('%Y-%m') if k=='month' else dates.dt.year
   m=l.groupby(k).agg(net_profit=('net_pnl','sum'),baskets=('net_pnl','size'),adds=('adds','sum'),fee_in=('entry_commission','sum'),fee_out=('exit_commission','sum'),financing=('financing','sum'));m['ending_balance']=100+m.net_profit.cumsum();m.to_csv(rv/('raw_'+str(cid)+'_'+k+'.csv'))
  fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True);t=pd.to_datetime(c.timestamp)
  ax[0].plot(t,c.equity,lw=.7);ax[0].set_yscale('symlog',linthresh=10);ax[0].set_ylabel('Model equity USD');ax[0].set_title('BTC '+row.criterion+' '+variant+' '+str(cid))
  ax[1].plot(t,-c.drawdown_pct,lw=.7);ax[1].set_ylabel('OHLC model DD %')
  for a in ax:a.grid(alpha=.25)
  fig.tight_layout();fig.savefig(rv/('raw_'+str(cid)+'_plot.png'),dpi=140);plt.close(fig)
stress=pd.concat(allcases,ignore_index=True);stress.to_csv(OUT/'ALL_SELECTED_STRESS.csv',index=False);dump(OUT/'CASH_RECONCILIATION.json',cash)
all_cash=[]
for _,r in stress.iterrows():
 study,_flags=studies[r.variant]
 suffix='' if r['case']=='BASE' else '_'+r['case']
 ledger=study/'raw_validation'/('raw_'+str(int(r.id))+suffix+'_ledger.csv')
 l=pd.read_csv(ledger)
 if len(l):
  gross=l.side*(l.exit_price-l.entry_average)*l.quantity
  net=gross-l.entry_commission-l.exit_commission-l.financing
  errors=[float(abs(gross-l.gross_pnl).max()),float(abs(net-l.net_pnl).max()),float(abs(100+net.cumsum()-l.balance).max()),abs(float(l.balance.iloc[-1])-r.equity)]
  assert max(errors)<max(1e-6,abs(r.equity)*1e-9),(r.variant,r.id,r['case'],errors)
 else:errors=[0.];assert r.equity==100
 all_cash.append({'variant':r.variant,'id':int(r.id),'case':r['case'],'maximum_error':max(errors),'pass':True})
dump(OUT/'ALL_CASE_CASH_RECONCILIATION.json',all_cash)
base=stress[stress['case']=='BASE'].merge(chosen[['variant','id','criterion','origin']],on=['variant','id']);base['win_rate']=100*base.wins/base.trades
base.to_csv(OUT/'FINAL_DD60_LEGACY_COMPARISON.csv',index=False)
leaders=[]
for label in ['DD_LT60','DD_LT50_BACKUP']:
 z=base[base.criterion==label].sort_values('equity',ascending=False)
 if len(z):leaders.append(z.iloc[0].to_dict())
status={'status':'EXPLORATORY_M1_NOT_BROKER_VALIDATED','initial_USD':100,'period_end':'2026-10-15','prior_rows_screened':sum(x['prior_rows'] for x in stats),'targeted_sizing_evaluations':len(ref),'source_numeric_grids_only_changed':True,'original_seed_differential':sweep_proof,'leaders':leaders,'universes':stats,'BTC_leverage_model':10,'broker_leverage_verified':False,'combined_XAU_EUR_DD':'NOT_TESTED','no_DD_kill_switch':True,'all_selected_cash_reconciled':True}
dump(OUT/'DD60_LEGACY_STATUS.json',status)
report='# BTC — legacy DD60 dan fine sizing\n\n'
report+='Penyaringan ulang seluruh6.000.000 konfigurasi BTC lama dengan batas floatingDD<60%, lalu fine sizing '+str(len(ref))+' tuple baru. Ini terpisah dari10juta konfigurasi komposit baru; tidak boleh dihitung sebagai10juta keluarga baru. Semua dimulaiUSD100 pada2019-01-01 sampai2026-10-15. Source keluarga lama tidak diganti; hanya gridnumerik sizing diperluas.\n\n'
report+=base[['criterion','variant','id','family','tf_minutes','risk','margin_fraction','add_stages','equity','floating_dd','balance_dd','pf','trades','win_rate']].to_markdown(index=False,floatfmt='.6f')+'\n\n'
for leader in leaders:
 z=stress[(stress.variant==leader['variant'])&(stress.id==leader['id'])]
 report+='## '+leader['criterion']+'\n\n'
 report+=pd.DataFrame([leader])[PH+['equity','floating_dd']].to_markdown(index=False,floatfmt='.6f')+'\n\n'
 report+=z[['case','equity','floating_dd','trades','adds','skips','liquidations']].to_markdown(index=False,floatfmt='.4f')+'\n\n'
report+='Fine sizing diselesaikan pada run39252456294; seluruh157.320baris dipulihkan dengan SHA256identik. Seluruh seed original direproduksi kembali saat pemulihan. Kandidat terpilih direplay ulang dan ledger seluruh skenario direkonsiliasi independen. Source/diff parameter dan semua hasil sizing disimpan. Seleksi minimum30basket, konsisten dengan10juta replay komposit. Tidak ada top-up, reset, stop setelah target, atau DDclamp.\n\n'
report+='Batas tetap: officialBitstampM1 bukan tick bid/ask broker, leverage10 hipotesis; step/min0,01BTC,max100BTC; spread5bp,slip1bp/sisi,fee5bp/sisi,financing3bpnotional/hari. Cost1.5/2 mengalikan fee/slip/carry tanpa menggandakan spread. Delayminimum1menit bukan2detik. Closed-only signals,nextopen,stop-first,gapopenlebihburuk. Modelstopoutpriority dancapital-floorlama dipertahankan. Segmen restart100 dan pemilihanfullperiod bukan untouchedOOS. Hasil portfolio BTC+XAU/EUR belum diuji. Konfigurasi risk nominal bukan alokasi portofolio. Live/frozenXAU-EUR tidak diubah.\n\n'
report+='Sumber lengkap6universe dan manifestinput tersedia pada Actions39218690359 serta39233081519. SHA256uncompressedCSV c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504. Label parity adalah konsistensi model, bukan broker-nativeparity.\n'
(OUT/'LAPORAN_BTC_DD60_LEGACY.md').write_text(report)
for p in [CODE/'BTC_DD60_LEGACY_PROTOCOL.md',CODE/'btc_dd60_legacy.py']:shutil.copy2(p,OUT/p.name)
dump(OUT/'INPUT_ARCHIVE_REFERENCES.json',{'old_archive_sha256':sha(old),'high_archive_sha256':sha(new),'canonical_csv_sha256':sha(data)})
for curve in OUT.rglob('*_equity.csv'):
 with open(curve,'rb') as a,gzip.open(str(curve)+'.gz','wb') as b:shutil.copyfileobj(a,b)
 curve.unlink()
(OUT/'SOURCE_COMMIT.txt').write_text(os.environ['GITHUB_SHA']+'\n');data.unlink()
with open(OUT/'MANIFEST_SHA256.csv','w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(OUT.rglob('*')):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([str(p.relative_to(OUT)),sha(p),p.stat().st_size])
with zipfile.ZipFile(OUT/'RIZAN_BTC_DD60_LEGACY_AUDIT.zip','w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for p in OUT.rglob('*'):
  if p.is_file() and p.suffix!='.zip':z.write(p,str(p.relative_to(OUT)))
with zipfile.ZipFile(OUT/'RIZAN_BTC_DD60_LEGACY_AUDIT.zip') as z:assert z.testzip() is None
(OUT/'PACKAGE_SHA256.txt').write_text(sha(OUT/'RIZAN_BTC_DD60_LEGACY_AUDIT.zip')+'  RIZAN_BTC_DD60_LEGACY_AUDIT.zip\n')
print(json.dumps(status,indent=2),flush=True)
