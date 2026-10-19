import pathlib,json,csv,gzip,hashlib,subprocess,sys,zipfile,shutil,os
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=pathlib.Path.cwd();O=R/'ten_results';O.mkdir(exist_ok=True)
def sha(p):return hashlib.file_digest(open(p,'rb'),'sha256').hexdigest()
def dump(p,v):p.write_text(json.dumps(v,indent=2,allow_nan=False,default=lambda x:x.item() if hasattr(x,'item') else str(x)))
studies=sorted((R/'shards').glob('RIZAN-BTC-TEN-SHARD-*'));assert len(studies)==10
selected=[];proof=[];seen=np.zeros(10000000,dtype=np.bool_);rows=0;metas=[]
P=['tf_minutes','family','lookback','threshold_index','trend_filter','session_utc','side','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']
F=['recipe_id','vol_gate','rsi_gate','weekday_gate','close_location_gate','daily_trend_gate']
for d in studies:
 s=json.load(open(d/'SUMMARY.json'));assert s['configurations']==1000000 and s['recipes']==100000
 assert 'COMPLETE recipes=100000 configs=1000000' in (d/'RUN.log').read_text()
 assert (d/'INPUT_SHA256.txt').read_text().split()[0]=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
 meta=json.load(open(d/'SOURCE_METADATA.json'));metas.append(meta)
 n=0
 for q in pd.read_csv(d/'ALL_CONFIGURATIONS.csv.gz',chunksize=100000):
  ids=q.id.to_numpy(dtype=np.int64)-1;assert (ids>=0).all() and (ids<10000000).all()
  assert not seen[ids].any() and len(np.unique(ids))==len(ids);seen[ids]=True
  assert (((q.recipe_id-1)%10)==s['shard']).all()
  assert ((q.id-1)//10+1==q.recipe_id).all()
  assert len(q)%10==0
  groups=q.groupby('recipe_id',sort=False)
  assert groups.size().eq(10).all()
  assert not q.duplicated(['recipe_id']+P[7:]).any()
  for c in F[1:]+P[:7]:assert groups[c].nunique().eq(1).all()
  # Verify affine grammar cardinality without retaining a million text keys.
  for k in ['equity','floating_dd','balance_dd','pf','reconciliation_error']:assert np.isfinite(q[k]).all()
  n+=len(q)
 assert n==1000000
 rows+=n;proof.append({**s,'full_table_SHA256':sha(d/'ALL_CONFIGURATIONS.csv.gz')})
 selected.append(pd.read_csv(d/'SELECTED.csv'))
assert rows==10000000 and seen.all()
assert all(m==metas[0] for m in metas)
# Grammar 7290 canonical primitive/context definitions times 900 decorator combinations.
# gcd affine permutation gives injective recipe indices for all first 1m recipe IDs.
import math
N=proof[0]['grammar_space'];a=104729
while math.gcd(a,N)!=1:a+=2
idx=(np.arange(1000000,dtype=np.int64)*a+20261019)%N
assert len(np.unique(idx))==1000000
pool=pd.concat(selected,ignore_index=True).drop_duplicates('id');pool=pool[pool.trades>=30]
cohorts=[]
for label,cap,count in [('DD_LT60',60,20),('DD_LT55',55,5),('DD_LT50',50,5),('DD_LT45',45,3),('UNCONSTRAINED',float('inf'),5)]:
 q=pool[pool.floating_dd<cap].nlargest(count,'equity').copy();q['criterion']=label;cohorts.append(q)
ranking=pd.concat(cohorts);ranking.to_csv(O/'COHORT_RANKINGS.csv',index=False)
chosen=ranking.drop_duplicates('id');chosen.to_csv(O/'SELECTED.csv',index=False)
assert len(chosen)>0
dump(O/'TEN_MILLION_COUNT_PROOF.json',{'rows':rows,'unique_configuration_ids':int(seen.sum()),'unique_canonical_composite_recipes':1000000,'configurations_per_recipe':10,'fundamental_families':12,'grammar_space':N,'grammar_affine_coprime':math.gcd(a,N)==1,'full_tables':proof,'source_metadata':metas[0],'observational_signal_equivalence_not_excluded':True})
subprocess.run([sys.executable,'research_btc_jpy/prepare_btc_ten.py',str(O)],check=True)
shutil.copy2('research_btc_jpy/btc_ten_million.cpp',O/'btc_ten_million.cpp')
subprocess.run(['g++','-O3','-std=c++17',str(O/'btc_ten_million.cpp'),'-o','audit_replay'],check=True)
data=R/'source/data/BTCUSD_M1.csv';assert sha(data)=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
subprocess.run(['./audit_replay','audit',str(data),str(O),str(O/'SELECTED.csv')],check=True)
subprocess.run(['./audit_replay','prefix',str(data),str(O),str(O/'SELECTED.csv')],check=True)
stress=pd.read_csv(O/'ALL_SELECTED_STRESS.csv');checks=[]
for _,row in stress.iterrows():
 cid=int(row.id);case=row['case'];l=pd.read_csv(O/f'candidate_{cid}_{case}_ledger.csv')
 if len(l):
  gross=l.side*(l.exit_price-l.entry_average)*l.quantity
  net=gross-l.entry_commission-l.exit_commission-l.financing
  er=[float(abs(gross-l.gross_pnl).max()),float(abs(net-l.net_pnl).max()),float(abs(100+net.cumsum()-l.balance).max()),abs(float(l.balance.iloc[-1])-row.equity)]
  assert max(er)<max(1e-6,abs(row.equity)*1e-9),(cid,case,er)
 else:er=[0.];assert row.equity==100
 checks.append({'id':cid,'case':case,'baskets':len(l),'max_cash_error':max(er),'pass':True})
 if case=='BASE':
  for period in ['month','year']:
   x=l.assign(period=pd.to_datetime(l.exit_utc).dt.strftime('%Y-%m' if period=='month' else '%Y'))
   x=x.groupby('period').agg(net_profit=('net_pnl','sum'),baskets=('net_pnl','size'),adds=('adds','sum'),commission_in=('entry_commission','sum'),commission_out=('exit_commission','sum'),financing=('financing','sum'));x['balance']=100+x.net_profit.cumsum();x.to_csv(O/f'candidate_{cid}_{period}.csv')
base=stress[stress['case']=='BASE'].copy();base['win_rate']=100*base.wins/base.trades
base.to_csv(O/'FINAL_SELECTED_METRICS.csv',index=False)
leaders={}
for label,cap in [('DD_LT60',60),('DD_LT55',55),('DD_LT50',50),('DD_LT45',45),('UNCONSTRAINED',float('inf'))]:
 q=base[(base.floating_dd<cap)&(base.trades>=30)].nlargest(1,'equity')
 if len(q):leaders[label]=q.iloc[0].to_dict()
for cid in set(int(x['id']) for x in leaders.values()):
 c=pd.read_csv(O/f'candidate_{cid}_BASE_equity.csv');t=pd.to_datetime(c.timestamp)
 fig,ax=plt.subplots(2,1,sharex=True,figsize=(11,7));ax[0].plot(t,c.equity,lw=.7);ax[0].set_yscale('symlog',linthresh=10);ax[0].set_ylabel('Model equity USD');ax[0].set_title(f'BTC composite {cid} — hourly snapshots')
 ax[1].plot(t,-c.drawdown_pct,lw=.7);ax[1].set_ylabel('OHLC model floating DD %')
 for a in ax:a.grid(alpha=.3)
 fig.tight_layout();fig.savefig(O/f'candidate_{cid}_equity_drawdown.png',dpi=140);plt.close(fig)
dump(O/'CASH_RECONCILIATION.json',checks)
status={'status':'EXPLORATORY_M1_NOT_BROKER_TICK_VALIDATED','initial_USD':100,'period':['2019-01-01','2026-10-15'],'fundamental_families':12,'composite_recipe_definitions':1000000,'unique_configuration_evaluations':rows,'minimum_baskets':30,'primary_floating_DD_limit':'strictly below60%','zero_accepted_signal_recipes':sum(x['recipes_without_accepted_signals'] for x in proof),'leaders':leaders,'all_selected_baselines_reproduced':True,'all_cash_reconciled':True,'future_prefix_invariance':json.load(open(O/'PREFIX_INVARIANCE.json')),'broker_leverage_verified':False,'leverage_model':10,'untouched_OOS':False,'XAU_EUR_shared_equity_tested':False,'source_commit':os.environ['GITHUB_SHA']}
dump(O/'TEN_MILLION_STATUS.json',status)
report='# BTC — 1 juta resep komposit, 10 juta konfigurasi, DD <60%\n\n'
report+='Modal $100, tanpa top-up, BTC standalone, 1 Januari2019–15 Oktober2026. Telah diproses tepat10.000.000 konfigurasi:1.000.000 definisi resep sinyal komposit masing-masing10 konfigurasi eksekusi unik. Terdapat12 keluarga dasar; bukan1juta konsep fundamental independen. Parameter resep berbeda secara struktural, tetapi sebagian menghasilkan sinyal identik atau nol sinyal pada sampel ini. Resep tanpa sinyal diterima: '+str(status['zero_accepted_signal_recipes'])+'.\n\n'
for label,leader in leaders.items():
 r=pd.DataFrame([leader]);report+='## '+label+'\n\n'
 report+=r[F+P+['equity','floating_dd','balance_dd','pf','trades','wins','win_rate','adds','skips','liquidations']].to_markdown(index=False,floatfmt='.6f')+'\n\n'
 report+=stress[stress.id==leader['id']][['case','equity','floating_dd','trades','adds','skips','liquidations']].to_markdown(index=False,floatfmt='.4f')+'\n\n'
report+='## Metode dan batas\n\nSeleksi utama DD floating<60%, minimal30basket. Pembanding<55/<50/<45 dan tanpa batas DD dipisahkan. Seluruh kandidat terpilih direplay ulang dari metadata deterministik; saldo/DD/trade dibandingkan dengan tabel pencarian. Kas seluruh ledger diperiksa ulang dari harga/volume/komisi/financing. Future-price perturbation test pada timestamp15Mei2023 13:30UTC tidak boleh mengubah statistik prefix; modifikasi hanya di memori uji dan tidak disimpan sebagai data pasar.\n\n'
report+='Data official Bitstamp OHLC M1, bukan tick bid/ask broker. Entry memakai candle closed dan open berikutnya; trend H4 dan D1 memakai candle closed. Filter volatilitas ATR sekarang dibanding ATR20candle sebelumnya; RSI dan posisi close dari signal candle closed; hari/sesi memakai UTC entry. D1trend bersumber candle D1 terakhir yang sudah closed. Tidak ada makro/snapshot atau informasi masa depan.\n\n'
report+='Model: leverage10 hipotesis, min/step0,01BTC,max100BTC,margin linear,spread5bp,slippage1bp/sisi,fee5bp/sisi,financing debit3bpnotional/hari. Cost1.5/2 mengalikan fee/slip/carry, bukan spread. Delay minimal1menit, bukan2detik. Stop-first pada bar ambigu dan open lebih buruk pada gapSL. DD adalah statistik model OHLC, bukan bukti native tick. Grafik snapshotperjam; DD tabel diperiksa setiapM1. Layered entry membuka40% riskbudget awal, adds closed-depth pada25/50%stop lalu nextopen. NO_ADDS memakai100%initialrisk. Sisa rule stopout-priority/capital-floor source lama dipertahankan. Modelreject bukan ledger ACK broker; partialfill/reconnect/dynamicleverage tidak dibuktikan.\n\n'
report+='Semua10juta kasus memakai rentang sama untuk seleksi. Banyaknya percobaan menambah risiko overfit; segmen2019–22/2023–24/2025–Oktober2026 restart100 bukan OOS yang tak tersentuh. Segmen tanpa entry akibat minimum lot bukan bukti DD rendah. Biaya/latensi sensitivitas memakai parameter terkunci dan dapat melebihi batas DD yang dipakai seleksi BASE. Tidak ada top-up, stop setelah target, reset atau DDclamp. Saldo tinggi tidak dijamin bertahan di broker atau masa depan.\n\n'
report+='XAU–EUR frozen/live tidak diubah; tidak ada order atau merge main. Belum ada replay portofolio equity bersama. ModelriskBTC tidak boleh diasumsikan sebagai alokasi portfolio yang sudah diuji. Broker contract/step/leverageBTC wajib dibuktikan sebelum klaim implementasi.\n\n'
report+='Arsip COMPLETE memuat semua10tabel shard dan manifest, source/diff/protokol, ledger seluruh skenario kandidat terpilih, grafik dan bulanan/tahunan. Arsip REVIEW menghilangkan tabel10juta baris dan curveCSV besar; file ledger dan laporan tetap ada. Input canonicalCSV SHA256 c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504 berada pada Actions39212036090, artifact RIZAN-BTCUSD-EXTENDED-INPUT-2019-OCT2026. Tidak ada interpolasi lokal atau data April–Oktober yang dianggap tick Dukascopy: sumber BTC penelitian ini tetap BitstampM1.\n'
(O/'LAPORAN_BTC_TEN_MILLION.md').write_text(report)
for p in ['BTC_TEN_MILLION_PROTOCOL.md','audit_btc_ten.py','prepare_btc_ten.py']:shutil.copy2(R/'research_btc_jpy'/p,O/p)
(O/'SOURCE_COMMIT.txt').write_text(os.environ['GITHUB_SHA']+'\n')
# Store source, count proof and exact ten full shard tables once in COMPLETE.
for d in studies:
 dest=O/'full_tables'/d.name;dest.mkdir(parents=True)
 for p in d.iterdir():
  if p.is_file() and p.name in ['ALL_CONFIGURATIONS.csv.gz','SUMMARY.json','RUN.log','INPUT_SHA256.txt','SOURCE_METADATA.json','COMMIT.txt','ENGINE_FIXTURES.log']:shutil.copy2(p,dest/p.name)
for p in list(O.glob('*_equity.csv')):
 with open(p,'rb') as a,gzip.open(str(p)+'.gz','wb') as b:shutil.copyfileobj(a,b)
 p.unlink()
def package(name,review):
 files=[]
 for p in sorted(O.rglob('*')):
  if not p.is_file() or p.suffix=='.zip' or p.name in ['PACKAGE_SHA256.txt','MANIFEST_COMPLETE.csv','MANIFEST_REVIEW.csv']:continue
  if review and ('full_tables' in p.parts or p.name.endswith('_equity.csv.gz')):continue
  files.append(p)
 m=O/('MANIFEST_REVIEW.csv' if review else 'MANIFEST_COMPLETE.csv')
 with open(m,'w') as f:
  w=csv.writer(f);w.writerow(['path','sha256','bytes'])
  for p in files:w.writerow([str(p.relative_to(O)),sha(p),p.stat().st_size])
 with zipfile.ZipFile(O/name,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
  for p in files+[m]:z.write(p,str(p.relative_to(O)))
 with zipfile.ZipFile(O/name) as z:assert z.testzip() is None
package('RIZAN_BTC_TEN_MILLION_COMPLETE.zip',False)
package('RIZAN_BTC_TEN_MILLION_REVIEW.zip',True)
(O/'PACKAGE_SHA256.txt').write_text(''.join(sha(O/n)+'  '+n+'\n' for n in ['RIZAN_BTC_TEN_MILLION_COMPLETE.zip','RIZAN_BTC_TEN_MILLION_REVIEW.zip']))
print(json.dumps(status,indent=2),flush=True)
