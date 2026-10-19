"""Separate predeclared cash-goal policy; original archives never mutated."""
import pathlib,zipfile,json,hashlib,shutil,gzip,subprocess,sys,difflib
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path.cwd();SRC=ROOT/'input';OUT=ROOT/'goal_lock';OUT.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def dump(p,x):pathlib.Path(p).write_text(json.dumps(x,indent=2,allow_nan=False,default=lambda z:z.item() if hasattr(z,'item') else str(z)))
cohort=[];proof=[];allcases=[];configs=[]
leaders=json.loads((SRC/'FINAL_STATUS.json').read_text())['leaders']
for symbol in ['BTCUSD','USDJPY']:
 zpath=SRC/('RIZAN_'+symbol+'_RESEARCH_COMPACT_2019_2026.zip')
 with zipfile.ZipFile(zpath) as z:
  manifest=pd.read_csv(z.open('MANIFEST_SHA256.csv'))
  # Verify every selected input/source later against this complete manifest.
  expected=dict(zip(manifest.path,manifest.sha256))
  def read(n):
   b=z.read(n);assert hashlib.sha256(b).hexdigest()==expected[n],n
   return b
  for variant in ['GENERIC','SESSIONS','POSITION']:
   prefix='FULL_PERIOD/'+variant+'/'
   rows=pd.read_csv(__import__('io').BytesIO(read(prefix+'raw_validation/SELECTED_ROWS.csv')))
   ledgers={};wanted=[]
   for _,r in rows.iterrows():
    cid=int(r.id);q=pd.read_csv(__import__('io').BytesIO(read(prefix+'raw_validation/raw_'+str(cid)+'_ledger.csv')))
    ledgers[cid]=q
    hit=q[q.balance>=100000]
    first=hit.iloc[0] if len(hit) else None
    record={'symbol':symbol,'variant':variant,'id':cid,'baseline_final':float(r.full_equity),'baseline_trades':int(r.full_trades),'max_settled_cash':float(q.balance.max()) if len(q) else 100.,'cash_goal_hit':bool(len(hit)),'goal_lock_final':float(first.balance) if first is not None else float(r.full_equity),'goal_trade_count':int(hit.index[0]+1) if len(hit) else int(r.full_trades),'first_goal_exit_utc':str(first.exit_utc) if first is not None else None}
    cohort.append(record)
    chosen=any(a['symbol']==symbol and a['variant']==variant and int(a['id'])==cid and a['criterion'] in ['FULL','DD50'] for a in leaders)
    if len(hit) or chosen:
     r=r.copy();r.full_equity=record['goal_lock_final'];r.full_trades=record['goal_trade_count'];wanted.append(r)
     configs.append({**r.to_dict(),'symbol':symbol,'variant':variant,'policy':'SETTLED_CASH_GOAL_LOCK_100000'})
   if not wanted:continue
   study=OUT/(symbol+'_'+variant);rv=study/'raw_validation';rv.mkdir(parents=True,exist_ok=True)
   original=read(prefix+'search_direct_m1.cpp').decode()
   needle='  if(balance<step*(btc?minutes[min(s.mi,int(minutes.size())-1)].o:1.)/(lev*2)||balance<=0)break;'
   assert original.count(needle)==1,(symbol,variant)
   updated=original.replace(needle,'  if(balance>=100000.)break; // Predeclared settled cash goal; flat forever after closed basket.\n'+needle)
   source_name={'GENERIC':'search_direct_m1.cpp','SESSIONS':'search_sessions_direct.cpp','POSITION':'search_position_direct.cpp'}[variant]
   (study/source_name).write_text(updated);(study/'ORIGINAL_ENGINE.cpp').write_text(original)
   (study/'GOAL_LOCK_ONLY.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),updated.splitlines(True),fromfile='frozen_research_engine',tofile='settled_cash_goal_variant')))
   (study/'validate_raw.cpp').write_bytes(read(prefix+'validate_raw.cpp'))
   pd.DataFrame(wanted).to_csv(rv/'SELECTED_ROWS.csv',index=False)
   data=ROOT/(symbol+'_M1.csv')
   if not data.exists():
    raw=read('FULL_PERIOD/GENERIC/data/'+symbol+'_M1.csv.gz');data.write_bytes(gzip.decompress(raw))
   flags=[] if variant=='GENERIC' else ['-D'+('SESSION_VARIANT' if variant=='SESSIONS' else 'POSITION_VARIANT')]
   exe=ROOT/('goal_'+symbol+'_'+variant)
   subprocess.run(['g++','-O3','-std=c++17',*flags,str(study/'validate_raw.cpp'),'-o',str(exe)],check=True)
   subprocess.run([str(exe),str(data),symbol,str(rv/'SELECTED_ROWS.csv'),str(rv)],check=True)
   v=pd.read_csv(rv/'RAW_TOP20_STRESS.csv');v['symbol']=symbol;v['variant']=variant;allcases.append(v)
   for r in wanted:
    cid=int(r.id);new=pd.read_csv(rv/('raw_'+str(cid)+'_ledger.csv'));old=ledgers[cid].iloc[:len(new)]
    assert len(new)==int(r.full_trades)
    pd.testing.assert_frame_equal(new,old.reset_index(drop=True),check_exact=True)
    gross=new.side*(new.exit_price-new.entry_average)*new.quantity
    if symbol=='USDJPY':gross/=new.exit_price
    net=gross-new.entry_commission-new.exit_commission-new.financing
    err=max(float(abs(net-new.net_pnl).max()),float(abs(100+new.net_pnl.cumsum()-new.balance).max()),abs(float(new.balance.iloc[-1])-float(r.full_equity))) if len(new) else 0.
    assert err<max(1e-6,abs(float(r.full_equity))*1e-9)
    hits=new[new.balance>=100000]
    assert not len(hits) or int(hits.index[0])==len(new)-1
    proof.append({'symbol':symbol,'variant':variant,'id':cid,'exact_baseline_ledger_prefix':True,'cash_error':err,'trades':len(new),'ending_cash':float(r.full_equity),'all_future_entries_disabled_after_first_settled_goal':bool(len(hits)),'source_sha256':sha(study/source_name),'canonical_data_sha256':sha(data)})
    # Include exact settled cash observations and extend flat to research end.
    curve=pd.read_csv(rv/('raw_'+str(cid)+'_equity.csv'))
    extra=pd.DataFrame({'timestamp':[str(new.exit_utc.iloc[-1]),'2026-10-16 00:00:00'],'equity':[float(r.full_equity)]*2,'balance':[float(r.full_equity)]*2})
    curve=pd.concat([curve,extra],ignore_index=True).sort_values('timestamp')
    if len(hits):
     curve.to_csv(rv/('raw_'+str(cid)+'_goal_equity_with_flat_tail.csv'),index=False)
     fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True)
     ax[0].plot(pd.to_datetime(curve.timestamp),curve.equity,lw=.7);ax[0].axhline(100000,color='green',ls='--');ax[0].set_yscale('log');ax[0].set_ylabel('Model equity USD');ax[0].set_title(symbol+' '+variant+' '+str(cid)+' settled-cash goal lock')
     cash=pd.concat([pd.DataFrame({'exit_utc':['2019-01-01 00:00:00'],'balance':[100]}),new[['exit_utc','balance']],pd.DataFrame({'exit_utc':['2026-10-16 00:00:00'],'balance':[float(r.full_equity)]})])
     ax[1].step(pd.to_datetime(cash.exit_utc),cash.balance,where='post');ax[1].set_ylabel('Settled cash USD')
     for a in ax:a.grid(alpha=.25)
     fig.tight_layout();fig.savefig(rv/('raw_'+str(cid)+'_goal.png'),dpi=140);plt.close(fig)
   dump(study/'INPUT_REFERENCE.json',{'archive':zpath.name,'archive_sha256':sha(zpath),'canonical_dataset':'FULL_PERIOD/GENERIC/data/'+symbol+'_M1.csv.gz','data_sha256':sha(data)})
c=pd.DataFrame(cohort);v=pd.concat(allcases,ignore_index=True)
c.to_csv(OUT/'GOAL_LOCK_SCAN.csv',index=False);v.to_csv(OUT/'GOAL_LOCK_STRESS.csv',index=False)
pd.DataFrame(configs).to_csv(OUT/'GOAL_LOCK_CONFIGURATIONS.csv',index=False)
dump(OUT/'EXACT_PREFIX_AND_CASH_PROOF.json',proof)
summary={'policy':'settled cash >=100000 after completed basket; no later entries','goal_is_user_threshold_not_optimized_date':True,'period':'2019-01-01 through 2026-10-15','broker_parity':'NOT_VALIDATED','input_is_M1_not_bid_ask_ticks':True,'complete_selected_raw_leader_cohort':c.groupby('symbol').agg(candidates=('id','size'),cash_goal_hits=('cash_goal_hit','sum')).reset_index().to_dict('records'),'hit_candidates':c[c.cash_goal_hit].to_dict('records'),'replayed_candidates':len(proof),'source_change_only_goal_guard':True,'baseline_final_results_unchanged':True}
dump(OUT/'GOAL_LOCK_STATUS.json',summary)
shutil.copy2('research_btc_jpy/SETTLED_GOAL_LOCK_PROTOCOL.md',OUT/'SETTLED_GOAL_LOCK_PROTOCOL.md')
shutil.copy2(__file__,OUT/'EXECUTED_GOAL_LOCK_SCRIPT.py')
report='# Varian terpisah: berhenti setelah target kas tercapai\n\nAturan yang dinyatakan sebelum replay varian: sesudah seluruh basket ditutup dan semua biaya model dibayar, jika kas >= $100.000, hentikan entry selamanya. Tidak ada penutupan pada puncak floating, pemilihan tanggal, clipping saldo atau top-up. Hasil baseline tidak diganti.\n\n'
report+='Cakupan seluruh ledger kandidat raw terpilih (union top20 full, DD50, train setiap universe), bukan seluruh 6 juta lintasan konfigurasi:\n\n'+pd.DataFrame(summary['complete_selected_raw_leader_cohort']).to_markdown(index=False)+'\n\n'
report+='Kandidat yang benar-benar menyentuh target kas:\n\n'+(c[c.cash_goal_hit].to_markdown(index=False) if c.cash_goal_hit.any() else 'Tidak ditemukan.')+'\n\nHasil replay seluruh skenario kandidat yang menyentuh target:\n\n'
keys=c[c.cash_goal_hit][['symbol','variant','id']]
hits=v.merge(keys,on=['symbol','variant','id'])
report+=hits[['symbol','variant','id','case','equity','floating_dd','trades']].to_markdown(index=False)+'\n\n'
report+='Rekonsiliasi: setiap ledger BASE varian sama persis secara numerik dengan prefix ledger baseline, berhenti pada crossing kas pertama, dan PnL/kas dihitung ulang independen. Bukti lengkap: EXACT_PREFIX_AND_CASH_PROOF.json. Diff source hanya guard kas setelah ledger basket tertutup. Remaining periode memegang kas tanpa bunga. Ini kebijakan penghentian akun baru yang ditemukan melalui riset historis, bukan validasi out-of-sample atau pembuktian broker.\n\n'
report+='Batas: candle M1 resmi Bitstamp/HistData, spread dan slippage model; BTC leverage10 belum dibuktikan, leverage2 sensitivitas terpisah. USDJPY leverage200 juga asumsi model. Tidak ada urutan tick asli/bid-ask broker, ACK, partial fill, swap historis broker atau margin dinamis. DD adalah statistik OHLC engine. Tidak ada jaminan hasil masa depan. Hasil segmen restart100 tidak sama dengan compounding kontinu.\n'
(OUT/'LAPORAN_GOAL_LOCK.md').write_text(report)
with open(OUT/'MANIFEST_SHA256.csv','w') as f:
 f.write('path,sha256,bytes\n')
 for p in sorted(OUT.rglob('*')):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':f.write(str(p.relative_to(OUT))+','+sha(p)+','+str(p.stat().st_size)+'\n')
with zipfile.ZipFile('RIZAN_SETTLED_CASH_GOAL_LOCK.zip','w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for p in OUT.rglob('*'):
  if p.is_file():z.write(p,str(p.relative_to(OUT)))
shutil.copy2('RIZAN_SETTLED_CASH_GOAL_LOCK.zip',OUT/'RIZAN_SETTLED_CASH_GOAL_LOCK.zip')
(OUT/'PACKAGE_SHA256.txt').write_text(sha(OUT/'RIZAN_SETTLED_CASH_GOAL_LOCK.zip')+'  RIZAN_SETTLED_CASH_GOAL_LOCK.zip\n')
print(json.dumps(summary,indent=2),flush=True)
