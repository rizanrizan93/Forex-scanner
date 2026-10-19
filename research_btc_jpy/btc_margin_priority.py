"""Selected-candidate sensitivity; not an exhaustive corrected search or broker parity."""
import pathlib,json,csv,gzip,shutil,hashlib,subprocess,zipfile,io,difflib,sys
import pandas as pd
ROOT=pathlib.Path.cwd();OUT=ROOT/'margin_priority';OUT.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
# Existing engine checks SL/TP before a fallback stopout; this explicit variant
# chooses the nearer adverse stopout boundary when both are reachable.
with zipfile.ZipFile(ROOT/'input'/'RIZAN_BTC_HIGHEST_COMPLETE.zip') as z:
 manifest=pd.read_csv(z.open('MANIFEST_COMPLETE.csv'));expected=dict(zip(manifest.path,manifest.sha256))
 def read(n):
  b=z.read(n);assert hashlib.sha256(b).hexdigest()==expected[n],n
  return b
 rank=pd.read_csv(io.BytesIO(read('TOP20_HIGHEST_TERMINAL.csv')))
 data=ROOT/'BTCUSD_M1.csv';data.write_bytes(gzip.decompress(read('data/BTCUSD_M1.csv.gz')))
 comparisons=[];cash=[];changed=[]
 for variant,g in rank.groupby('variant'):
  study=OUT/variant;study.mkdir()
  original=read(variant+'/search_direct_m1.cpp').decode()
  needle='   // Avoid updating the equity peak with intrabar highs: ordering unknown.'
  assert original.count(needle)==1
  block='''   // Sensitivity only: linear BTC margin, same model50pct stopout.
   if(btc&&b.t<expires){
    double available=(balance-commission-financing)/n;
    double liquid=side>0?(avg-available)/(1.-fee*model.scale-.5/lev):(avg+available)/(1.+fee*model.scale+.5/lev);
    bool crossedMargin=liquid>0&&(side>0?lo<=liquid:hi>=liquid);
    bool beforeStop=side>0?liquid>sl:liquid<sl;
    if(crossedMargin&&beforeStop){
     xprice=(side>0?min(liquid,exitopen):max(liquid,exitopen))-side*slip(exitopen);
     why="PRIORITY_STOPOUT";r.liquidations++;
    }
   }
'''
  strict=original.replace(needle,block+needle).replace('   double eqworst=','   if(why=="PRIORITY_STOPOUT")worst=xprice;\n   double eqworst=').replace('double best=hs?exitopen:','double best=(hs||why=="PRIORITY_STOPOUT")?exitopen:')
  (study/'EXECUTION_ONLY.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),strict.splitlines(True),fromfile='baseline_execution',tofile='margin_priority_sensitivity')))
  srcname={'POSITION_HIGH':'search_position_direct.cpp','SESSIONS_HIGH':'search_sessions_direct.cpp','PREVIOUS_AGGRESSIVE':'search_direct_m1.cpp'}[variant]
  flags=['-DPOSITION_VARIANT'] if variant=='POSITION_HIGH' else ['-DSESSION_VARIANT'] if variant=='SESSIONS_HIGH' else []
  helper=read(variant+'/validate_raw.cpp').decode()
  a=helper.index('if(name=="BASE"){double e=val("full_equity");');b=helper.index('o<<name<<',a)
  helper=helper[:a]+helper[b:];helper=helper.replace('for(auto&[name,m]:cs){','cs.resize(1);for(auto&[name,m]:cs){').replace('for(auto seg:vector<tuple<string,int64_t,int64_t>>','if(false)for(auto seg:vector<tuple<string,int64_t,int64_t>>')
  (study/'validate_raw.cpp').write_text(helper)
  sel=g.copy();sel['full_equity']=sel.equity;sel['full_trades']=sel.trades;sel.to_csv(study/'SELECTED_ROWS.csv',index=False)
  results={}
  for label,source in [('BASELINE',original),('PRIORITY_STOPOUT',strict)]:
   (study/srcname).write_text(source);dest=study/label;dest.mkdir()
   exe=ROOT/('validate_'+variant+'_'+label)
   subprocess.run(['g++','-O3','-std=c++17',*flags,str(study/'validate_raw.cpp'),'-o',str(exe)],check=True)
   subprocess.run([str(exe),str(data),'BTCUSD',str(study/'SELECTED_ROWS.csv'),str(dest)],check=True)
   results[label]=pd.read_csv(dest/'RAW_TOP20_STRESS.csv')
   (study/(label+'_ENGINE.cpp')).write_text(source)
   for cid in g.id:
    new=pd.read_csv(dest/('raw_'+str(cid)+'_ledger.csv'))
    if label=='BASELINE':
     old=pd.read_csv(io.BytesIO(read(variant+'/raw_validation/raw_'+str(cid)+'_ledger.csv')))
     pd.testing.assert_frame_equal(new,old,check_exact=True)
    net=new.side*(new.exit_price-new.entry_average)*new.quantity-new.entry_commission-new.exit_commission-new.financing
    err=max(float(abs(net-new.net_pnl).max()),float(abs(100+new.net_pnl.cumsum()-new.balance).max()))
    assert err<max(1e-6,abs(float(new.balance.iloc[-1]))*1e-9)
    cash.append({'variant':variant,'id':int(cid),'case':label,'cash_error':err,'baseline_ledger_exactly_reproduced':label=='BASELINE'})
  for _,r in g.iterrows():
   a=results['BASELINE'][results['BASELINE'].id==r.id].iloc[0];b=results['PRIORITY_STOPOUT'][results['PRIORITY_STOPOUT'].id==r.id].iloc[0]
   rec={'variant':variant,'id':int(r.id),'rank_nominal':int(r['rank']),'baseline_equity':float(a.equity),'priority_equity':float(b.equity),'equity_difference':float(b.equity-a.equity),'baseline_dd':float(a.floating_dd),'priority_dd':float(b.floating_dd),'priority_stopouts':int(b.liquidations),'baseline_stopouts':int(a.liquidations),'baseline_trades':int(a.trades),'priority_trades':int(b.trades)}
   comparisons.append(rec)
  # Both exact engine sources are preserved separately above.
  (study/srcname).unlink()
 # Copy the prior report, top20 table, integration schema and notes into a compact
 # final evidence bundle; no rewriting of original findings.
 for n in ['LAPORAN_BTC_HIGHEST.md','TOP20_HIGHEST_TERMINAL.csv','ALL_SELECTED_STRESS.csv','HIGHEST_STATUS.json','XAU_EUR_BTC_INTEGRATION_CONTRACT.json','CASH_RECONCILIATION.json','PACKAGE_SHA256.txt']:
  (OUT/n).write_bytes(read(n) if n in expected else z.read(n))
 c=pd.DataFrame(comparisons).sort_values('rank_nominal');c.to_csv(OUT/'MARGIN_PRIORITY_COMPARISON.csv',index=False)
 (OUT/'MARGIN_PRIORITY_CASH_PROOF.json').write_text(json.dumps(cash,indent=2))
 # Independent arithmetic fixtures for the linear model boundary.
 for side in [1,-1]:
  liq=(100-side*10)/(1-side*.05)
  equity=100+side*(liq-100)*10
  margin=10*liq/10
  assert abs(equity-.5*margin)<1e-9
  assert (liq>90 if side>0 else liq<110)
 status={'status':'SELECTED_CANDIDATE_EXECUTION_SENSITIVITY_NOT_BROKER_PARITY','parameters_unchanged':True,'selected_count':len(c),'changed_final_balances':int((abs(c.equity_difference)>1e-6).sum()),'exhaustive_corrected_search':False,'same_50pct_model_stopout':True,'closer_adverse_boundary_and_worse_open_gap_fill':True,'cash_reconciled':True,'baseline_ledgers_exact':True,'source_selected_from_run':39233081519}
 (OUT/'MARGIN_PRIORITY_STATUS.json').write_text(json.dumps(status,indent=2))
 note='''# BTC: audit tambahan urutan margin stop-out
Ini eksperimen eksekusi pada20kandidat nominal teratas, parameter sinyal/sizing/biaya tetap. Engine awal memilihSL/TP sebelum fallback stop-out. Varian memilih batas stop-out model50%margin jika batas adverse tersebut lebih dekat daripada SL; gap memakai open lebih buruk dan slippage model. Jika TP dan batas adverse sama-sama ada dalam satu M1, asumsi adverse-first dipertahankan. Ini bukan urutan tick broker atau pencarian jutaan konfigurasi yang telah dikoreksi.

Baseline direproduksi persis dari ledger, dua rumus boundary diuji independen, dan kas kedua jalur dihitung ulang. Hasil:
'''
 note+=c.to_markdown(index=False)+'\n\nJumlah saldo akhir berubah: '+str(status['changed_final_balances'])+'. Nilai nominal dalam laporan awal tetap disimpan. Jika berubah, jangan menyebut ranking awal sebagai ranking tertinggi dari seluruh universe di bawah eksekusi varian; hanya20kandidat yang diperiksa. Margin bertingkat, actual stopout broker, financing real, ACK/reject serta urutan penambahan stage masih perlu verifikasi. Tidak ada perubahan XAU/EUR/live.\n'
 (OUT/'LAPORAN_MARGIN_PRIORITY.md').write_text(note)
 shutil.copy2('research_btc_jpy/BTC_CBOT_INTEGRATION_NOTES.md',OUT/'BTC_CBOT_INTEGRATION_NOTES.md')
 (OUT/'PREVIOUS_VPS_VERIFICATION.txt').write_bytes((ROOT/'input'/'VPS_VERIFICATION.txt').read_bytes())
 (OUT/'EXECUTED_MARGIN_PRIORITY.py').write_bytes(pathlib.Path(__file__).read_bytes())
 data.unlink()
 with open(OUT/'MANIFEST_SHA256.csv','w') as f:
  w=csv.writer(f);w.writerow(['path','sha256','bytes'])
  for p in sorted(OUT.rglob('*')):
   if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([str(p.relative_to(OUT)),sha(p),p.stat().st_size])
 with zipfile.ZipFile(OUT/'RIZAN_BTC_HIGHEST_FINAL_REVIEW.zip','w',zipfile.ZIP_DEFLATED,compresslevel=5) as result:
  for p in OUT.rglob('*'):
   if p.is_file() and p.suffix!='.zip':result.write(p,str(p.relative_to(OUT)))
 (OUT/'FINAL_PACKAGE_SHA256.txt').write_text(sha(OUT/'RIZAN_BTC_HIGHEST_FINAL_REVIEW.zip')+'  RIZAN_BTC_HIGHEST_FINAL_REVIEW.zip\n')
 print(json.dumps(status,indent=2),flush=True);print(c.to_string(index=False),flush=True)
