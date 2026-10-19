import pathlib,zipfile,json,csv,gzip,io,hashlib,re,shutil,subprocess,sys,os
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path.cwd();OUT=ROOT/'dd_results';OUT.mkdir(exist_ok=True);CODE=ROOT/'research_btc_jpy'
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
   src2=re.sub(r'const double risks\[\]=\{[^}]+\},margins\[\]=\{[^}]+\};','const double risks[]={.01,.02,.03,.04,.05,.06,.075,.08,.1,.12,.15,.2,.25,.3,.4,.5,.6},margins[]={.1,.2,.25,.3,.4,.5,.6,.75,.95};',src)
   assert src2!=src
   (study/'search_direct_m1.cpp').write_text(src2)
   flags=[]
   if 'POSITION' in variant:shutil.copy2(study/'search_direct_m1.cpp',study/'search_position_direct.cpp');flags=['-DPOSITION_VARIANT']
   if 'SESSIONS' in variant:shutil.copy2(study/'search_direct_m1.cpp',study/'search_sessions_direct.cpp');flags=['-DSESSION_VARIANT']
   studies[variant]=(study,flags)
   q=pd.read_csv(io.BytesIO(read(prefix+'results_BTCUSD/ALL_CONFIGURATIONS.csv.gz')),compression='gzip')
   assert len(q)==1000000
   low=q[(q.full_floating_dd<50)&(q.full_trades>0)];band=q[(q.full_floating_dd>=50)&(q.full_floating_dd<=55)&(q.full_trades>0)];under=q[(q.full_floating_dd<=55)&(q.full_trades>0)]
   b=pd.concat([low.nlargest(10,'full_equity'),band.nlargest(10,'full_equity')]).drop_duplicates('id');b['variant']=variant;b['origin']='PRIOR_FULL_TABLE';baseline.append(b)
   train=q[(q.train_dd<50)&(q.train_trades>=20)].nlargest(2,'train_equity')
   seed=pd.concat([low.nlargest(5,'full_equity'),under.nlargest(5,'full_equity'),q.nlargest(3,'full_equity'),train]).drop_duplicates('id')
   seeds[variant]=seed;seed.to_csv(study/'SEEDS.csv',index=False)
   stats.append({'variant':variant,'prior_rows':len(q),'below50_count':len(low),'band50_to55_count':len(band),'max_below50':float(low.full_equity.max()) if len(low) else None,'max_band50_to55':float(band.full_equity.max()) if len(band) else None,'selected_seeds':len(seed),'original_source_sha256':hashlib.sha256(src.encode()).hexdigest()})
   del q
assert sha(data)=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
helper=(CODE/'validate_raw.cpp').read_text().replace('ix(risks,8,','ix(risks,int(sizeof(risks)/sizeof(risks[0])),').replace('ix(margins,3,','ix(margins,int(sizeof(margins)/sizeof(margins[0])),')
helper=helper.replace('if(btc)cs.push_back({"LEVERAGE2",{1.,2}});','if(btc){cs.push_back({"LEVERAGE2",{1.,2}});cs.push_back({"LEVERAGE5",{1.,5}});}')
sweepblock=r'''
 if(argc>5&&string(argv[5])=="SWEEP"){
  R seedResult=simulate(p,true,parse("2019-01-01 00:00:00"),endtime);
  if(abs(seedResult.eq-val("full_equity"))>max(1e-6,abs(val("full_equity"))*1e-9)||seedResult.trades!=int(val("full_trades")))throw runtime_error("SEED_DIFFERENTIAL_FAILED");
  for(double rr:vector<double>{.01,.02,.03,.04,.05,.06,.075,.08,.1,.12,.15,.2,.25})for(double mm:vector<double>{.1,.2,.3,.4,.5,.6,.75,.95}){
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
refined=[];sweep_proof=[]
for variant,(study,flags) in studies.items():
 (study/'sweep.cpp').write_text(sweeper);exe=ROOT/('sweep_'+variant)
 subprocess.run(['g++','-O3','-std=c++17',*flags,str(study/'sweep.cpp'),'-o',str(exe)],check=True)
 sweepdir=study/'sweep';sweepdir.mkdir()
 subprocess.run([str(exe),str(data),'BTCUSD',str(study/'SEEDS.csv'),str(sweepdir),'SWEEP'],check=True)
 q=pd.read_csv(sweepdir/'RAW_TOP20_STRESS.csv');q['variant']=variant;q['origin']='TARGETED_SIZING_GRID'
 q=q.rename(columns={'equity':'full_equity','floating_dd':'full_floating_dd','trades':'full_trades'})
 refined.append(q);sweep_proof.append({'variant':variant,'all_original_seed_equity_and_trade_counts_reconciled':True,'seeds':len(seeds[variant]),'unique_sizing_cases':len(q)})
 (sweepdir/'RAW_VALIDATION_PROOF.json').unlink()
 dump(sweepdir/'SIZING_SWEEP_PROOF.json',sweep_proof[-1])
ref=pd.concat(refined,ignore_index=True);ref.to_csv(OUT/'ALL_TARGETED_SIZING_CASES.csv',index=False)
pool=pd.concat(baseline+[ref],ignore_index=True)
for col in PH[1:]:
 if col!='family':pool[col]=pd.to_numeric(pool[col]).round(12)
low=pool[(pool.full_floating_dd<50)&(pool.full_trades>0)].sort_values('full_equity',ascending=False).drop_duplicates(PH[1:]).head(5)
band=pool[(pool.full_floating_dd>=50)&(pool.full_floating_dd<=55)&(pool.full_trades>0)].sort_values('full_equity',ascending=False).drop_duplicates(PH[1:]).head(5)
chosen=pd.concat([low.assign(criterion='DD_LT50'),band.assign(criterion='DD_50_TO55')]).drop_duplicates(['variant','id'])
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
base=stress[stress['case']=='BASE'].merge(chosen[['variant','id','criterion','origin']],on=['variant','id']);base['win_rate']=100*base.wins/base.trades
base.to_csv(OUT/'FINAL_DD50_55_COMPARISON.csv',index=False)
leaders=[]
for label in ['DD_LT50','DD_50_TO55']:
 z=base[base.criterion==label].sort_values('equity',ascending=False)
 if len(z):leaders.append(z.iloc[0].to_dict())
status={'status':'EXPLORATORY_M1_NOT_BROKER_VALIDATED','initial_USD':100,'period_end':'2026-10-15','prior_rows_screened':sum(x['prior_rows'] for x in stats),'targeted_sizing_evaluations':len(ref),'source_numeric_grids_only_changed':True,'original_seed_differential':sweep_proof,'leaders':leaders,'universes':stats,'BTC_leverage_model':10,'broker_leverage_verified':False,'combined_XAU_EUR_DD':'NOT_TESTED','no_DD_kill_switch':True,'all_selected_cash_reconciled':True}
dump(OUT/'DD50_55_STATUS.json',status)
report='# BTC — prioritas DD di bawah50%, maksimum55%\n\nUSD100 standalone, tanpa top-up atau stop setelah target,2019-01-01 sampai2026-10-15. Screen seluruh6juta baris penelitian lama, kemudian sizing sweep terarah '+str(len(ref))+' kasus unik per source universe. Ini bukan jutaan keluarga independen dan bukan OOS murni.\n\n'
report+='DD yang dibatasi adalah floating DD model OHLC, bukan balance DD atau jaminan tick/broker. Kelompok utama DD<50; kelompok cadangan50–55 dipisah.\n\n'
report+=base[['criterion','variant','id','family','tf_minutes','risk','margin_fraction','add_stages','equity','floating_dd','balance_dd','pf','trades','win_rate']].sort_values(['criterion','equity'],ascending=[True,False]).to_markdown(index=False,floatfmt='.4f')+'\n\n'
for leader in leaders:
 s=stress[(stress.variant==leader['variant'])&(stress.id==leader['id'])]
 report+='## '+leader['criterion']+' '+str(leader['id'])+'\n\n'
 report+=pd.DataFrame([leader])[PH+['equity','floating_dd']].to_markdown(index=False)+'\n\n'
 report+=s[['case','equity','floating_dd','trades','adds','skips','liquidations']].to_markdown(index=False,floatfmt='.4f')+'\n\n'
report+='Batas: data official Bitstamp M1, bukan tick bid/ask broker. Leverage10 hipotesis; sensitivitas2/5 terpisah. Spread5bp,slip1bp/sisi,fee5bp/sisi,financing debit3bpnotional/hari prorata. Biaya1.5/2 mengalikan slip/fee/carry, bukan spread. Delay minimum1menit, bukan2detik. NO_ADDS mengalokasikan100% initialrisk, bukan ablation volume tetap. Angka stres dan segmen restart100 bukan hasil gabungan dan bukan OOS yang tak tersentuh. DD nominal<50 atau<=55 tidak menjamin batas bertahan saat biaya/spread/urutan tick berubah. Tidak ada DD kill switch retroaktif atau reset akun.\n\n'
report+='Seluruh seed awal direkonsiliasi dengan hasil source lama setelah hanya memperluas array numerik risk/margin. Replikasi baseline kandidat terpilih dicek ulang; PnL dan kas dihitung independen dari ledger. Source asli, source sizing-grid, seluruh sizing cases, ledger, grafik dan bulanan/tahunan dipertahankan. Input SHA256c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504 tersimpan pada arsip rujukan Actions39218690359 dan39233081519. Input tidak diinterpolasi atau dimodifikasi. Batas engine stop-first/capital-floor/ACK/nativebroker seperti laporan sebelumnya tetap berlaku.\n\n'
report+='XAU/EUR dan trading live tidak diubah. DD akun BTC standalone tidak dapat disamakan dengan DD portfolio bersama. Hasil dipilih setelah banyak percobaan pada periode sama; wajib bedakan optimasi historis dan bukti ketahanan masa depan.\n'
(OUT/'LAPORAN_BTC_DD50_55.md').write_text(report)
for p in [CODE/'BTC_DD50_55_PROTOCOL.md',CODE/'btc_dd50_55.py']:shutil.copy2(p,OUT/p.name)
dump(OUT/'INPUT_ARCHIVE_REFERENCES.json',{'old_archive_sha256':sha(old),'high_archive_sha256':sha(new),'canonical_csv_sha256':sha(data)})
(OUT/'SOURCE_COMMIT.txt').write_text(os.environ['GITHUB_SHA']+'\n');data.unlink()
with open(OUT/'MANIFEST_SHA256.csv','w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(OUT.rglob('*')):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([str(p.relative_to(OUT)),sha(p),p.stat().st_size])
with zipfile.ZipFile(OUT/'RIZAN_BTC_DD50_55_AUDIT.zip','w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for p in OUT.rglob('*'):
  if p.is_file() and p.suffix!='.zip':z.write(p,str(p.relative_to(OUT)))
with zipfile.ZipFile(OUT/'RIZAN_BTC_DD50_55_AUDIT.zip') as z:assert z.testzip() is None
(OUT/'PACKAGE_SHA256.txt').write_text(sha(OUT/'RIZAN_BTC_DD50_55_AUDIT.zip')+'  RIZAN_BTC_DD50_55_AUDIT.zip\n')
print(json.dumps(status,indent=2),flush=True)
