import pathlib,sys,json,subprocess,gzip,shutil,hashlib,zipfile
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path.cwd();OUT=ROOT/'aggressive_results';OUT.mkdir(exist_ok=True);CODE=ROOT/'research_btc_jpy'
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dump(p,x):pathlib.Path(p).write_text(json.dumps(x,indent=2,allow_nan=False,default=lambda z:z.item() if hasattr(z,'item') else str(z)))
PH=['id','tf_minutes','family','lookback','threshold_index','trend_filter','session_utc','side','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']
leaders=[];tables={};selected_frames={};status=[]
for symbol in ['BTCUSD','USDJPY']:
 for p in (ROOT/'shards').glob('RIZAN-AGGRESSIVE-M1-'+symbol+'-*'):
  d=ROOT/'merge_input'/(symbol+'_'+p.name.rsplit('-',1)[1]);d.parent.mkdir(exist_ok=True)
  if not d.exists():shutil.copytree(p,d)
 study=OUT/symbol
 subprocess.run([sys.executable,str(CODE/'merge_direct.py'),symbol,str(ROOT/'merge_input'),str(study)],check=True)
 r=study/('results_'+symbol);q=pd.read_csv(r/'ALL_CONFIGURATIONS.csv');tables[symbol]=q[PH+['full_equity','full_floating_dd','full_trades']].copy()
 full=q.nlargest(20,'full_equity');dd=q[(q.full_floating_dd<50)&(q.full_trades>0)].nlargest(20,'full_equity');train=q[(q.train_dd<50)&(q.train_trades>=20)].nlargest(20,'train_equity')
 selected=pd.concat([full,dd,train]).drop_duplicates('id');selected_frames[symbol]=selected
 # Exact chronological regression on the actual aggressive source.
 shutil.copy2(CODE/'prefix_invariance.cpp',study/'prefix_invariance.cpp')
 exe=ROOT/('prefix_'+symbol);subprocess.run(['g++','-O3','-std=c++17',str(study/'prefix_invariance.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe),str(study/'data'/(symbol+'_M1.csv')),symbol,str(r/'PREFIX_INVARIANCE.json')],check=True)
 status.append({'symbol':symbol,'configurations':len(q),'target_final_any_trade_count':int((q.full_equity>=100000).sum()),'target_final_dd50':int(((q.full_equity>=100000)&(q.full_floating_dd<50)).sum()),'maximum_final':float(q.full_equity.max()),'dataset_sha256':sha(study/'data'/(symbol+'_M1.csv')),'engine_sha256':sha(study/'search_direct_m1.cpp')})
 # Keep complete million table with all counts; redundant shard curves not needed.
 with open(r/'ALL_CONFIGURATIONS.csv','rb') as a,gzip.open(r/'ALL_CONFIGURATIONS.csv.gz','wb',compresslevel=5) as b:shutil.copyfileobj(a,b)
 (r/'ALL_CONFIGURATIONS.csv').unlink()
 del q
a=tables['BTCUSD'].sort_values('id').reset_index(drop=True);b=tables['USDJPY'].sort_values('id').reset_index(drop=True)
pd.testing.assert_frame_equal(a[PH],b[PH],check_exact=True)
pairs=a[PH].copy()
for symbol,t in [('BTCUSD',a),('USDJPY',b)]:
 pairs[symbol+'_equity']=t.full_equity;pairs[symbol+'_dd']=t.full_floating_dd;pairs[symbol+'_trades']=t.full_trades
pairs['min_final']=pairs[['BTCUSD_equity','USDJPY_equity']].min(axis=1)
pairs['both_target']=(pairs.BTCUSD_equity>=100000)&(pairs.USDJPY_equity>=100000)
pairs.sort_values('min_final',ascending=False).head(100).to_csv(OUT/'SAME_PARAMETERS_CROSS_INSTRUMENT_TOP100.csv',index=False)
pairbest=pairs.sort_values('min_final',ascending=False).iloc[0];pairid=int(pairbest.id)
for symbol in ['BTCUSD','USDJPY']:
 study=OUT/symbol;r=study/('results_'+symbol);rv=study/'raw_validation';rv.mkdir(exist_ok=True)
 q=tables[symbol];p=q[q.id==pairid]
 # Add paired champion's train fields from complete table.
 allq=pd.read_csv(r/'ALL_CONFIGURATIONS.csv.gz')
 selected=pd.concat([selected_frames[symbol],allq[allq.id==pairid]]).drop_duplicates('id');selected.to_csv(rv/'SELECTED_ROWS.csv',index=False);del allq
 shutil.copy2(CODE/'validate_raw.cpp',study/'validate_raw.cpp');exe=ROOT/('validate_'+symbol)
 subprocess.run(['g++','-O3','-std=c++17',str(study/'validate_raw.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe),str(study/'data'/(symbol+'_M1.csv')),symbol,str(rv/'SELECTED_ROWS.csv'),str(rv)],check=True)
 subprocess.run([sys.executable,str(CODE/'reconcile_raw.py'),str(study),symbol],check=True)
 v=pd.read_csv(rv/'RAW_TOP20_STRESS.csv')
 for criterion,cid in [('FULL',int(q.sort_values('full_equity',ascending=False).iloc[0].id)),('SAME_PARAMETERS',pairid)]:
  x=v[(v.id==cid)&(v['case']=='BASE')].iloc[0].to_dict();x.update(symbol=symbol,criterion=criterion,win_rate=100*x['wins']/x['trades'] if x['trades'] else 0)
  leaders.append(x)
  c=pd.read_csv(rv/('raw_'+str(cid)+'_equity.csv'));l=pd.read_csv(rv/('raw_'+str(cid)+'_ledger.csv'))
  fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True);t=pd.to_datetime(c.timestamp)
  ax[0].plot(t,c.equity,lw=.7);ax[0].set_yscale('symlog',linthresh=10);ax[0].set_ylabel('Model equity USD');ax[0].set_title(symbol+' AGGRESSIVE '+criterion+' '+str(cid))
  ax[1].plot(t,-c.drawdown_pct,lw=.7);ax[1].set_ylabel('OHLC model DD %')
  for z in ax:z.grid(alpha=.25)
  fig.tight_layout();fig.savefig(OUT/(symbol+'_'+criterion+'.png'),dpi=140);plt.close(fig)
  if len(l):
   l['month']=pd.to_datetime(l.exit_utc).dt.strftime('%Y-%m');m=l.groupby('month').agg(net_profit=('net_pnl','sum'),baskets=('net_pnl','size'),adds=('adds','sum'),commission_in=('entry_commission','sum'),commission_out=('exit_commission','sum'),financing=('financing','sum'));m['balance']=100+m.net_profit.cumsum();m.to_csv(rv/('raw_'+str(cid)+'_month.csv'))
 # Explicit isolated restart period trade counts, including zero-trade BTC outcomes.
 v.to_csv(OUT/(symbol+'_ALL_SELECTED_STRESS.csv'),index=False)
 # Remove only uncompressed duplicate input; full gzip and source retained.
 (study/'data'/(symbol+'_M1.csv')).unlink()
 for p in r.glob('candidate_*'):p.unlink()
for p in [CODE/'AGGRESSIVE_EXPLORATION_PROTOCOL.md',CODE/'search_aggressive_direct.cpp',CODE/'aggressive_audit.py']:shutil.copy2(p,OUT/p.name)
pd.DataFrame(leaders).to_csv(OUT/'AGGRESSIVE_LEADERS.csv',index=False)
result={'status':'EXPLORATORY_M1_MODEL_NOT_BROKER_VALIDATED','initial_each_USD':100,'period_end':'2026-10-15','universes':status,'same_parameter_both_final_target_count':int(pairs.both_target.sum()),'same_parameter_best_min_final':pairbest.to_dict(),'leverage_BTC':10,'leverage_BTC_verified':False,'leverage_JPY':200,'all_selected_source_reconstructed_and_cash_reconciled':True,'prefix_regression_parameters_per_symbol':500,'leaders':leaders}
dump(OUT/'AGGRESSIVE_STATUS.json',result)
report='# Pencarian agresif terpisah — hasil aktual\n\nSatu juta konfigurasi aktif unik per instrumen; grid dinyatakan sebelum eksekusi, mengubah hanya ruang pencarian strategi baru, tidak menyentuh frozen XAU/EUR atau hasil pencarian awal. Akun $100 terpisah, tanpa top-up; periode2019–15Oktober2026. Risiko10–60%, margin50–95%: dapat menyebabkan drawdown ekstrem.\n\n'+pd.DataFrame(status).to_markdown(index=False)+'\n\n'
report+='Hasil pemimpin dan satu parameter identik lintas instrumen:\n\n'+pd.DataFrame(leaders)[['symbol','criterion','id','family','tf_minutes','risk','margin_fraction','equity','floating_dd','pf','trades','win_rate']].to_markdown(index=False)+'\n\n'
report+='Jumlah konfigurasi parameter identik yang mencapai saldo akhir>=100k di KEDUA instrumen: '+str(int(pairs.both_target.sum()))+'. Seluruh 1juta parameter dipasangkan berdasarkan tuple yang sama, bukan hanya ID atau hasil akhir.\n\n'
for x in leaders:
 s=pd.read_csv(OUT/(x['symbol']+'_ALL_SELECTED_STRESS.csv'));s=s[s.id==x['id']]
 report+=x['symbol']+' '+x['criterion']+' stres dan segmen restart100:\n\n'+s[['case','equity','floating_dd','trades','skips','liquidations']].to_markdown(index=False)+'\n\n'
report+='Batas validitas: hasil terbaik dipilih dari periode penuh sehingga overfit/selection bias besar. Uji segmen setelah pemilihan bukan OOS murni. BTC data OHLC resmi Bitstamp, USDJPY HistData M1, bukan bid/ask tick broker. Leverage BTC10, spread, slippage, komisi, financing, batas volume dan stop-out adalah asumsi riset, bukan kontrak historis broker yang diverifikasi. USDJPY leverage200 juga model. Biaya1.5/2 tidak mengalikan spread; DELAY_NEXT_M1 adalah penundaan minimum1menit, bukan2detik. NO_ADDS mengalokasikan100% initialrisk. DD OHLC bukan jaminan DDtick. Seluruh input/sourcehash, million-row tables, rawledgers, cashproof dan500prefix regression perinstrumen disertakan. Hasil nominal100k, bila ada, hanya sukses modelhistoris dan harus dibedakan dari bukti ketahanan biaya/leverage atau penggunaan live.\n'
(OUT/'LAPORAN_AGGRESSIVE.md').write_text(report)
with open(OUT/'MANIFEST_SHA256.csv','w') as f:
 f.write('path,sha256,bytes\n')
 for p in sorted(OUT.rglob('*')):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':f.write(str(p.relative_to(OUT))+','+sha(p)+','+str(p.stat().st_size)+'\n')
for symbol in ['BTCUSD','USDJPY']:
 zp=OUT/('RIZAN_'+symbol+'_AGGRESSIVE_MILLION.zip')
 with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
  for p in OUT.rglob('*'):
   if p.is_file() and p.suffix!='.zip' and (p.relative_to(OUT).parts[0]==symbol or len(p.relative_to(OUT).parts)==1):z.write(p,str(p.relative_to(OUT)))
with open(OUT/'PACKAGE_SHA256.txt','w') as f:
 for p in sorted(OUT.glob('*.zip')):f.write(sha(p)+'  '+p.name+'\n')
print(json.dumps(result,indent=2),flush=True)
