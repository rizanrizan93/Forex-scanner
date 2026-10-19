import pathlib,pandas as pd,json,subprocess,sys,hashlib,csv,zipfile,gzip,shutil,os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=pathlib.Path.cwd();out=R/'both_results';out.mkdir(exist_ok=True);code=R/'research_btc_jpy'
files=sorted((R/'shards').glob('RIZAN-BTC-BOTH56-SHARD-*/RESULTS.csv.gz'));assert len(files)==4
q=pd.concat([pd.read_csv(f) for f in files],ignore_index=True)
assert len(q)==630000 and q.id.nunique()==630000 and q.id.min()==1 and q.id.max()==630000
assert (q['case']=='BASE').all()
geometry=['seed_id','risk','margin_fraction','short_risk','short_margin']
assert not q.duplicated(geometry).any()
assert q.groupby('seed_id').size().eq(6300).all()
for sh,f in enumerate(files):
 z=pd.read_csv(f);assert len(z)==157500 and ((z.id-1)%4==sh).all()
 assert (f.parent/'COMMIT.txt').read_text().strip()==os.environ['GITHUB_SHA']
assert hashlib.sha256((R/'source/data/BTCUSD_M1.csv').read_bytes()).hexdigest()=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
q.to_csv(out/'ALL_630000_RESULTS.csv.gz',index=False,compression='gzip')
both=q[(q.buy_baskets>=1)&(q.sell_baskets>=1)&(q.trades>=30)]
low=both[both.floating_dd<=56].sort_values(['equity','id'],ascending=[False,True])
hits=low[low.equity>=600000]
def distinct(d):
 return d.drop_duplicates(['equity','floating_dd','buy_baskets','sell_baskets','adds'])
selected=pd.concat([distinct(low).head(3),distinct(both.sort_values('equity',ascending=False)).head(1),distinct(both[both.equity>=600000].sort_values(['floating_dd','id'])).head(2)]).drop_duplicates('id')
assert len(selected)>0
# Extra results columns in selected CSV do not change parameter parsing.
input_cols=list(q.columns[1:list(q.columns).index('equity')]);selected[input_cols].to_csv(out/'SELECTED.csv',index=False)
subprocess.run([sys.executable,str(code/'prepare_btc_both.py'),str(out)],check=True)
shutil.copy2(code/'btc_both.cpp',out/'btc_both.cpp')
subprocess.run(['g++','-O3','-std=c++17',str(out/'btc_both.cpp'),'-o',str(R/'audit_replay')],check=True)
rv=out/'replay';rv.mkdir()
subprocess.run([str(R/'audit_replay'),'audit',str(R/'source/data/BTCUSD_M1.csv'),str(rv),str(out/'SELECTED.csv')],check=True)
stress=pd.read_csv(rv/'RESULTS.csv');stress.to_csv(out/'ALL_SELECTED_STRESS.csv',index=False)
checks=[];contrib=[]
for _,r in stress.iterrows():
 p=rv/('candidate_'+str(int(r.id))+'_'+r['case']+'_ledger.csv')
 l=pd.read_csv(p)
 if len(l):
  gross=l.side*(l.exit_price-l.entry_average)*l.quantity
  net=gross-l.entry_commission-l.exit_commission-l.financing
  errs=[float(abs(gross-l.gross_pnl).max()),float(abs(net-l.net_pnl).max()),float(abs(100+net.cumsum()-l.balance).max()),abs(float(l.balance.iloc[-1])-r.equity)]
  assert max(errs)<max(1e-6,abs(r.equity)*1e-9),(r.id,r['case'],errs)
  assert int((l.side==1).sum())==r.buy_baskets and int((l.side==-1).sum())==r.sell_baskets
 else:errs=[abs(r.equity-100)]
 if r['case']=='BASE':
  old=selected[selected.id==r.id].iloc[0]
  assert abs(old.equity-r.equity)<max(1e-6,r.equity*1e-9) and abs(old.floating_dd-r.floating_dd)<1e-8
  assert old.buy_baskets==r.buy_baskets and old.sell_baskets==r.sell_baskets
  for direction,g in l.groupby('side'):
   contrib.append(dict(id=int(r.id),side=int(direction),baskets=len(g),gross_pnl=float(g.gross_pnl.sum()),gross_winning_net=float(g.loc[g.net_pnl>0,'net_pnl'].sum()),gross_losing_net=float(-g.loc[g.net_pnl<0,'net_pnl'].sum()),wins=int((g.net_pnl>0).sum()),net_pnl=float(g.net_pnl.sum()),adds=int(g['adds'].sum()),fees=float((g.entry_commission+g.exit_commission).sum()),financing=float(g.financing.sum())))
  for k,fmt in [('month','%Y-%m'),('year','%Y')]:
   l[k]=pd.to_datetime(l.exit_utc).dt.strftime(fmt)
   g=l.groupby(k).agg(net_profit=('net_pnl','sum'),baskets=('net_pnl','size'),adds=('adds','sum'));g['ending_balance']=100+g.net_profit.cumsum();g.to_csv(rv/('candidate_'+str(int(r.id))+'_'+k+'.csv'))
  c=pd.read_csv(rv/('candidate_'+str(int(r.id))+'_BASE_equity.csv'))
  fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True)
  t=pd.to_datetime(c.timestamp);ax[0].plot(t,c.equity,lw=.7);ax[0].set_yscale('symlog',linthresh=100);ax[0].set_ylabel('Model equity USD')
  ax[0].set_title('BTC BUY + SELL '+str(int(r.id))+' — M1 model')
  ax[1].plot(t,-c.drawdown_pct,lw=.7);ax[1].set_ylabel('DD %')
  for a in ax:a.grid(alpha=.25)
  fig.tight_layout();fig.savefig(rv/('candidate_'+str(int(r.id))+'_plot.png'),dpi=140);plt.close(fig)
 checks.append(dict(id=int(r.id),case=r['case'],maximum_error=max(errs),gross_pnl=float(l.gross_pnl.sum()),commissions=float((l.entry_commission+l.exit_commission).sum()),financing=float(l.financing.sum()),net_pnl=float(l.net_pnl.sum()),final_balance=float(r.equity),pass_check=True))
pd.DataFrame(contrib).to_csv(out/'BUY_SELL_CONTRIBUTIONS.csv',index=False)
(out/'CASH_RECONCILIATION.json').write_text(json.dumps(checks,indent=2))
base=stress[stress['case']=='BASE'].copy();base['win_rate']=100*base.wins/base.trades
base.to_csv(out/'FINAL_SELECTED_METRICS.csv',index=False)
status={'status':'EXPLORATORY_M1_NOT_BROKER_VALIDATED','target_met':bool(len(hits)),'initial_USD':100,'period':'2019-01-01 through 2026-10-15','floating_DD_limit':56,'minimum_final_balance':600000,'new_cases':len(q),'seed_geometries':100,'both_directions_and_30_baskets':len(both),'nominal_DD56_hits':len(low),'target_hits':len(hits),'all_selected_case_cash_reconciled':True,'no_topups':True,'live_changed':False,'combined_XAU_EUR':'NOT_TESTED','best_DD56':low.iloc[0].to_dict() if len(low) else None}
(out/'BUYSELL_STATUS.json').write_text(json.dumps(status,indent=2))
cols=['id','seed_id','family','tf_minutes','risk','short_risk','margin_fraction','short_margin','equity','floating_dd','pf','trades','buy_baskets','sell_baskets']
report='# BTC BUY + SELL — target $600k dan floating DD maksimal56%\n\n'
report+='Status target nominal: **'+('TERCAPAI' if len(hits) else 'BELUM TERCAPAI')+'**. ModalUSD100 tanpa topup,2019-01-01 sampai2026-10-15. Targetbukanjaminanprofit.\n\n'
report+='630.000 konfigurasi baru adalah100geometri hasil seleksi historis x21riskBUY x12riskSELL x5marginBUY x5marginSELL. Bukan630.000keluarga atau dataOOS. Semua profil menerimaBUYdanSELL; kelayakanpemenangmemerlukanminimal1basketmasing-masingarah dan30baskettotal.\n\n'
report+='## Kandidat DD56 tertinggi\n\n'+low.head(5)[cols].to_markdown(index=False,floatfmt='.6f')+'\n\n'
report+='## Replay ulang terpilih\n\n'+base[cols].to_markdown(index=False,floatfmt='.6f')+'\n\n'
for cid in base.id:
 report+='### '+str(int(cid))+'\n\n'
 report+=stress[stress.id==cid][['case','equity','floating_dd','trades','buy_baskets','sell_baskets','adds','skips','liquidations']].to_markdown(index=False,floatfmt='.6f')+'\n\n'
report+='SemuaBASEterpilih direproduksi dari parameter dansemualedger6skenario direkonsiliasiindependen. KeuanganBUYdanSELL berbagi saldo,compounding,margin; engine satu basketaktif, sinyal saatbusy diabaikan. Risk/margin dapatberbedaantararah, sinyal/SL/TP/hold/stageseedtidakberbedaantararah. BUYdanSELL bukan duareplayyangdijumlahkan.\n\n'
report+='DataofficialBitstampOHLCM1,bukantickbidaskbroker;leverage10hipotesis,min/step0.01BTC,max100BTC;spread5bp,fee5bp/sisi,slip1bp/sisi,carrydebit3bp/hari keduaarah. COST1_5/2 mengalikanfee/slip/carry,bukanspread;DELAY_NEXT_M1 minimum1menit,bukan2detik. Leverage2dan5hanyasensitivitas.\n\n'
report+='Closed-bars,nextopen,stop-firstambiguity,gapSLworseopen dipertahankan. DDperM1 memakaiOHLCbound konservatif,grafiksnapshotperjam. Baseline692365 dan955kBUYdireproduksi sebelumpencarian;9fixturewarisanlulus. Sourceadapterhanyamenambahgridnumerik,directionalrisk/margin,dancounterarah. Capitalfloor lama danprioritasSL/TPsebelumfallbackstopoutmasihada;brokerRAW/tiering/ACKnativebelumdibuktikan.\n\n'
report+='Seluruhperiodeadalahsampeloptimasi,risikooverfitbesar. Tidakadaklaim batasDDmasadepan,untouchedOOS,atauFULL_PARITY. BTC+XAU+EURbelumdireplaybersama. cBotlive,frozenXAU-EUR,bridge,envproduksitidakdiubah;tidakadaorderataumergemain.\n\n'
report+='Commit: '+os.environ['GITHUB_SHA']+'\n\nActions: https://github.com/rizanrizan93/Forex-scanner/actions/runs/'+os.environ['GITHUB_RUN_ID']+'\n'
(out/'LAPORAN_BTC_BUYSELL_DD56.md').write_text(report)
for n in ['search_btc_position_high.cpp','btc_ten_million.cpp','resume_btc_both.py','prepare_btc_both.py','generate_btc_both.py','btc_both.cpp','audit_btc_both.py','BUYSELL_SEEDS.json','BTC_BUYSELL_DD56_PROTOCOL.md']:shutil.copy2(code/n,out/n)
for p in rv.glob('*_equity.csv'):
 with p.open('rb') as a,gzip.open(str(p)+'.gz','wb') as b:shutil.copyfileobj(a,b)
 p.unlink()
for sh,f in enumerate(files):
 shutil.copy2(f.parent/'RECOVERY.json',out/('RECOVERY_SHARD_'+str(sh)+'.json'))
 shutil.copy2(f.parent/'RUN.log',out/('RESUME_SHARD_'+str(sh)+'.log'))
 shutil.copy2(f.parent/'FIXTURES.log',out/('FIXTURES_SHARD_'+str(sh)+'.log'))
shutil.copy2(R/'.github/workflows/btc-buysell-dd56.yml',out/'WORKFLOW.yml')
(out/'INPUT_PROVENANCE.json').write_text(json.dumps(dict(csv_sha256=hashlib.sha256((R/'source/data/BTCUSD_M1.csv').read_bytes()).hexdigest(),input_run=39212036090,artifact_id=12168391422,source_commit=os.environ['GITHUB_SHA'],checkpoint_commit='f3e97d82547b403be0845bee43bb43046da72e29',reused_rows=447300,newly_replayed_rows=182700),indent=2))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
with (out/'MANIFEST_SHA256.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(out.rglob('*')):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([str(p.relative_to(out)),sha(p),p.stat().st_size])
package=out/'RIZAN_BTC_BUYSELL_DD56_600K.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for p in out.rglob('*'):
  if p.is_file() and p!=package:z.write(p,str(p.relative_to(out)))
with zipfile.ZipFile(package) as z:assert z.testzip() is None
(out/'PACKAGE_SHA256.txt').write_text(sha(package)+'  '+package.name+'\n')
print(json.dumps(status,indent=2),flush=True)

