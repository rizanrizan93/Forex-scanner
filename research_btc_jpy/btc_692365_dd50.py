import pathlib,zipfile,gzip,hashlib,json,csv,subprocess,os,re,shutil
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
O=pathlib.Path('focus_results');O.mkdir(exist_ok=True)
def sha(p):return hashlib.file_digest(open(p,'rb'),'sha256').hexdigest()
def dump(p,v):p.write_text(json.dumps(v,indent=2,allow_nan=False,default=lambda x:x.item() if hasattr(x,'item') else str(x)))
arc=pathlib.Path('high/RIZAN_BTC_HIGHEST_COMPLETE.zip')
assert sha(arc)=='1995e8a40f9fd7af043e35ae62d0b5c8bc999f3f7576f795ad8750362c210d34'
with zipfile.ZipFile(arc) as z:
 m=pd.read_csv(z.open('MANIFEST_COMPLETE.csv'));expected=dict(zip(m.path,m.sha256))
 def read(n):
  b=z.read(n);assert hashlib.sha256(b).hexdigest()==expected[n],n;return b
 src=read('POSITION_HIGH/search_direct_m1.cpp').decode()
 data=pathlib.Path('BTCUSD_M1.csv');data.write_bytes(gzip.decompress(read('data/BTCUSD_M1.csv.gz')))
 (O/'ORIGINAL_ENGINE.cpp').write_text(src)
 old=pd.read_csv(z.open('POSITION_HIGH/raw_validation/SELECTED_ROWS.csv'))
 seed=old[old.id==692365];assert len(seed)==1;seed.to_csv(O/'ORIGINAL_692365.csv',index=False)
assert sha(data)=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
# Same execution rules, expanded numeric sizing arrays only.
src2=re.sub(r'const double risks\[\]=\{[^}]+\},margins\[\]=\{[^}]+\};',
 'const double risks[]={'+','.join(str(i/100) for i in range(1,61))+'},margins[]={'+','.join(str(x) for x in [.3,.5,.6,.75,.95]+[i/100 for i in range(30,96) if i not in [30,50,60,75,95]])+'};',src)
assert src2!=src
(O/'search_direct_m1.cpp').write_text(src2)
driver=r'''
#define main prior_main
#include "search_direct_m1.cpp"
#undef main
int main(int argc,char**argv){try{
 btc=true;symbol="BTCUSD";load(argv[1]);for(int k=0;k<4;k++)agg[k]=aggregate(widths[k]);h4=agg[2];
 P p{692365,2,8,0,2,1,1,1,4,6,3,39,4,2,2};
 int64_t a=parse("2019-01-01 00:00:00");R original=simulate(p,true,a,endtime);
 if(abs(original.eq-1005025.5238208736)>1e-5||abs(original.dd-67.92092400829017)>1e-8||original.trades!=63)throw runtime_error("ORIGINAL_692365_DIFFERENTIAL_FAILED");
 ofstream proof("focus_results/SEED_PARITY.json");proof<<setprecision(17)<<"{\"original_balance\":"<<original.eq<<",\"original_dd\":"<<original.dd<<",\"trades\":"<<original.trades<<",\"differential_pass\":true,\"unchanged_signal_family\":true}\n";
 ofstream out("focus_results/ALL_FOCUSED_CASES.csv");out<<setprecision(17)<<ph<<","<<rh<<"\n";
 vector<pair<P,R>> rows;set<string>seen;int count=0;
 auto eval=[&](P x){if(!seen.insert(canonical(x)).second)return;x.id=2000000+(++count);R r=simulate(x,true,a,endtime);params(out,x);out<<",";result(out,r);out<<"\n";rows.push_back({x,r});if(count%2000==0)cout<<"FOCUSED_CASES "<<count<<endl;};
 eval(p);
 for(int st:vector<int>{2,3,4,5})for(int tp:vector<int>{3,4,5,6,7})for(int ho:vector<int>{1,2,3})for(int lay=0;lay<3;lay++)for(int be=0;be<3;be++)for(int rr:vector<int>{3,4,5,7,9,11,14,19,24,29,39})for(int mm=0;mm<5;mm++){
  P x=p;x.stop=st;x.tp=tp;x.hold=ho;x.layers=lay;x.be=be;x.risk=rr;x.margin=mm;eval(x);
 }
 // Predeclared refinement: top 12 distinct geometries under 50 or 55, plus 8 unrestricted.
 vector<P> seeds;set<string> geo;
 for(int band=0;band<3;band++){
  vector<pair<P,R>> rank=rows;sort(rank.begin(),rank.end(),[](auto&x,auto&y){return x.second.eq>y.second.eq;});int got=0;
  for(auto&x:rank){if(x.second.trades<20||(band==0&&x.second.dd>=50)||(band==1&&x.second.dd>55))continue;
   auto y=x.first;y.risk=0;y.margin=0;string k=canonical(y);if(!geo.insert(k).second)continue;
   seeds.push_back(x.first);if(++got>=(band==2?8:12))break;
  }
 }
 for(auto x:seeds)for(int rr=0;rr<40;rr++)for(int mm=0;mm<int(sizeof(margins)/sizeof(margins[0]));mm++){x.risk=rr;x.margin=mm;eval(x);}
 out.close();
 ofstream selected("focus_results/SELECTED.csv");selected<<setprecision(17)<<ph<<","<<rh<<"\n";set<int> ids;
 // Baseline, unconstrained highest, top 5 below 50, top 3 from 50 to55.
 ids.insert(2000001);
 sort(rows.begin(),rows.end(),[](auto&x,auto&y){return x.second.eq>y.second.eq;});
 ids.insert(rows[0].first.id);
 for(int band=0;band<2;band++){int n=0;for(auto&x:rows)if(x.second.trades>=20&&(band==0?x.second.dd<50:(x.second.dd>=50&&x.second.dd<=55))){ids.insert(x.first.id);if(++n>=(band==0?5:3))break;}}
 for(double bound:vector<double>{45.,48.})for(auto&x:rows)if(x.second.trades>=20&&x.second.dd<bound){ids.insert(x.first.id);break;}
 ofstream stress("focus_results/ALL_SELECTED_STRESS.csv");stress<<setprecision(17)<<"case,"<<ph<<","<<rh<<"\n";
 for(auto&x:rows)if(ids.count(x.first.id)){
  params(selected,x.first);selected<<",";result(selected,x.second);selected<<"\n";
  vector<tuple<string,Model,int64_t,int64_t>> cs={{"BASE",{},a,endtime},{"COST1_5",{1.5},a,endtime},{"COST2",{2},a,endtime},{"DELAY_NEXT_M1",{1.,0,1},a,endtime},{"LEVERAGE2",{1.,2},a,endtime},{"LEVERAGE5",{1.,5},a,endtime},{"NO_ADDS",{1.,0,0,1},a,endtime},{"SEGMENT_2019_2022",{},a,parse("2023-01-01 00:00:00")},{"SEGMENT_2023_2024",{},parse("2023-01-01 00:00:00"),parse("2025-01-01 00:00:00")},{"SEGMENT_2025_OCT2026",{},parse("2025-01-01 00:00:00"),endtime}};
  for(auto&[name,model,start,end]:cs){
   string log="focus_results/candidate_"+to_string(x.first.id)+"_"+name;
   R r=simulate(x.first,true,start,end,model,log);if(name=="BASE"&&(abs(r.eq-x.second.eq)>1e-6||r.dd!=x.second.dd))throw runtime_error("SELECTED_REPLAY_FAILED");
   stress<<name<<",";params(stress,x.first);stress<<",";result(stress,r);stress<<"\n";
  }
 }
 cout<<"FOCUSED_COMPLETE cases="<<count<<" selected="<<ids.size()<<endl;
}catch(exception&e){cerr<<e.what()<<endl;return 1;}}
'''
(O/'focused.cpp').write_text(driver)
subprocess.run(['g++','-O3','-std=c++17',str(O/'ORIGINAL_ENGINE.cpp'),'-o','original_fixtures'],check=True)
r=subprocess.run(['./original_fixtures','--test'],capture_output=True,text=True);(O/'ENGINE_FIXTURES.txt').write_text(r.stdout+r.stderr);assert r.returncode==0
subprocess.run(['g++','-O3','-std=c++17',str(O/'focused.cpp'),'-o','focused'],check=True)
subprocess.run(['./focused',str(data)],check=True)
allq=pd.read_csv(O/'ALL_FOCUSED_CASES.csv');s=pd.read_csv(O/'ALL_SELECTED_STRESS.csv');checks=[]
for _,row in s.iterrows():
 cid=int(row.id);case=row['case'];l=pd.read_csv(O/f'candidate_{cid}_{case}_ledger.csv')
 if len(l):
  gross=l.side*(l.exit_price-l.entry_average)*l.quantity
  net=gross-l.entry_commission-l.exit_commission-l.financing
  errors=[float(np.max(np.abs(gross-l.gross_pnl))),float(np.max(np.abs(net-l.net_pnl))),float(np.max(np.abs(100+net.cumsum()-l.balance))),abs(float(l.balance.iloc[-1])-row.equity)]
  assert max(errors)<max(1e-6,abs(row.equity)*1e-9),(cid,case,errors)
 else:errors=[0.];assert row.equity==100
 checks.append({'id':cid,'case':case,'baskets':len(l),'max_cash_error':max(errors),'pass':True})
 if case=='BASE':
  for period in ['month','year']:
   dates=pd.to_datetime(l.exit_utc);g=l.assign(period=dates.dt.strftime('%Y-%m' if period=='month' else '%Y'))
   g=g.groupby('period').agg(net_profit=('net_pnl','sum'),baskets=('net_pnl','size'),adds=('adds','sum'),entry_fees=('entry_commission','sum'),exit_fees=('exit_commission','sum'),financing=('financing','sum'));g['balance']=100+g.net_profit.cumsum();g.to_csv(O/f'candidate_{cid}_{period}.csv')
  c=pd.read_csv(O/f'candidate_{cid}_BASE_equity.csv');t=pd.to_datetime(c.timestamp)
  fig,ax=plt.subplots(2,1,sharex=True,figsize=(11,7));ax[0].plot(t,c.equity,lw=.7);ax[0].set_yscale('log');ax[0].set_ylabel('Model equity USD');ax[0].set_title(f'BTC H4 displacement {cid} — hourly snapshots')
  ax[1].plot(t,-c.drawdown_pct,lw=.7);ax[1].set_ylabel('Model floating DD %')
  for a in ax:a.grid(alpha=.3)
  fig.tight_layout();fig.savefig(O/f'candidate_{cid}_equity_drawdown.png',dpi=130);plt.close(fig)
dump(O/'CASH_RECONCILIATION.json',checks)
base=s[s['case']=='BASE'].copy();base['win_rate']=100*base.wins/base.trades
best=base[(base.floating_dd<50)&(base.trades>=20)].nlargest(1,'equity')
band=base[(base.floating_dd>=50)&(base.floating_dd<=55)&(base.trades>=20)].nlargest(1,'equity')
assert len(best)==1
before=base[base.id==2000001]
comparison=pd.concat([before.assign(label='BEFORE_692365'),best.assign(label='AFTER_DD_LT50'),band.assign(label='SECONDARY_DD_50_TO55')])
comparison.to_csv(O/'BEFORE_VS_AFTER.csv',index=False)
status={'status':'EXPLORATORY_M1_NOT_TICK_OR_BROKER_VALIDATED','source_candidate':692365,'period':['2019-01-01','2026-10-15'],'initial_USD':100,'unique_focused_cases':len(allq),'dd_lt50_cases':int(((allq.floating_dd<50)&(allq.trades>=20)).sum()),'baseline_differential_pass':True,'cash_reconciliation_pass':True,'signal_locked':'H4 displacement threshold 0.2, closed H4 trend, BUY, UTC00-08','best_below50':best.iloc[0].to_dict(),'secondary_50_to55':band.iloc[0].to_dict() if len(band) else None,'lookahead':'closed signals and next open inherited source; no new future-dependent rules','OOS':False,'XAU_EUR_integration':'NOT_TESTED','source_commit':os.environ['GITHUB_SHA']}
dump(O/'FOCUSED_STATUS.json',status)
cols=['label','id','equity','floating_dd','balance_dd','pf','trades','win_rate','adds','skips','liquidations']
report='# BTC 692365 — pencarian saldo tertinggi dengan floating DD <50%\n\n'
report+='Akun standalone USD100, tanpa top-up;2019-01-01 sampai2026-10-15. Sinyal H4 displacement BUY, trend H4, threshold0.2 dan sesi UTC00–08 tetap. Parameter risk/margin, stop,TP,holding,layering dan BE dioptimasi sebagai konfigurasi riset baru. Strategi XAU–EUR/live tidak diubah.\n\n'
report+=f'Diuji {len(allq):,} konfigurasi unik. Baseline692365 direproduksi sebelum pencarian: saldo dan DD toleransi ketat,63basket. Seluruh hasil pilihan direplay ulang dan ledger semua skenario direkonsiliasi independen.\n\n'
report+=comparison[cols].to_markdown(index=False,floatfmt='.4f')+'\n\n'
report+='## Konfigurasi dan sensitivitas pilihan DD<50\n\n'
report+=best[['id','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']].to_markdown(index=False)+'\n\n'
report+=s[s.id==best.iloc[0].id][['case','equity','floating_dd','trades','adds','skips','liquidations']].to_markdown(index=False,floatfmt='.4f')+'\n\n'
report+='## Pembanding ruang DD\n\n'
for bound in [45,48]:
 v=base[(base.floating_dd<bound)&(base.trades>=20)].nlargest(1,'equity')
 if len(v):
  report+=f'Pilihan tertinggi yang direplay untuk DD<{bound}:\n\n'+v[['id','equity','floating_dd','risk','margin_fraction','stop_atr','tp_R','hold_bars','add_stages','breakeven_R']].to_markdown(index=False)+'\n\n'
  report+=s[s.id==v.iloc[0].id][['case','equity','floating_dd','trades','skips']].to_markdown(index=False,floatfmt='.4f')+'\n\n'
report+='Semua kasus biaya/latensi memakai parameter terkunci. Segment2019–22/2023–24/2025–Okt2026 masing-masing restartUSD100; bukan OOS tak tersentuh. Seluruh periode dipakai seleksi, sehingga hasil ini optimasi historis dan rentan overfit. Batas DD<50 disaring pada BASE, bukan jaminan untuk skenario stres atau masa depan.\n\n'
report+='Model tetap: Bitstamp M1 OHLC resmi, bukan tick bid/ask broker. Leverage10 hipotesis; margin linear, minimum/step0.01BTC,max100BTC. Spread5bp,slippage1bp/sisi,komisi5bp/sisi,financing debit3bpnotional/hari. COST1_5/2 mengalikan fee/slip/carry, bukan spread. Delay NEXT_M1 minimum satu menit, bukan2detik. Financing long/short sama sesuai model sebelumnya, bukan spesifikasi broker yang dibuktikan.\n\n'
report+='DD model diperiksa tiapM1 dengan urutan intrabar konservatif/stop-first. Grafik hanya snapshotperjam, angka DD acuan dari tabel fullM1. Stop gap memakai open yang lebih buruk. BE mulai berlaku barnext. Bila layering, initialrisk40%,adds pada25/50%kedalamanstop lalu barnext; risk bukan persen kerugian pasti. NO_ADDS mengalokasikan100%initialrisk sehingga bukan ablation volume tetap. ModelSL/TP mendahului fallbackstopout; ACK/recovery/partialfills/dynamicbrokerleverage tidak divalidasi. Capital-floor permanen source dipertahankan. Tidak ada DDclamp, penghentian setelah target, reset atau top-up.\n\n'
report+='Pembanding pencarian sebelumnya: D1 structure_break USD56,582.38/DD46.75%; keluarga berbeda, bukan hasil perubahan692365. USD1juta tidak dijamin tetap tercapai dengan DD<50. Hasil standaloneBTC tidak membuktikan DD atau saldo portfolio equity bersama XAU–EUR. Profit tinggi harus diuji lagi dengan spesifikasi broker dan tick independen.\n\n'
report+='Artefak: seluruh konfigurasi, source asli+diff parameter, protokol, parity fixture, ledger semua kasus terpilih, kas,perbulan/pertahun,grafik,checksum. CanonicalinputCSV SHA256 c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504; archiveSHA1995e8a40f9fd7af043e35ae62d0b5c8bc999f3f7576f795ad8750362c210d34, Actions39233081519.\n'
(O/'LAPORAN_BTC_692365_DD50.md').write_text(report)
import difflib
(O/'ENGINE_PARAMETER_DIFF.patch').write_text(''.join(difflib.unified_diff(src.splitlines(True),src2.splitlines(True),fromfile='ORIGINAL_ENGINE.cpp',tofile='search_direct_m1.cpp')))
shutil.copy2('research_btc_jpy/btc_692365_dd50.py',O/'btc_692365_dd50.py')
shutil.copy2('research_btc_jpy/BTC_692365_DD50_PROTOCOL.md',O/'BTC_692365_DD50_PROTOCOL.md')
# Compress full table and repeated scenario curves; keep all ledgers and BASE curves accessible.
for p in list(O.glob('*_equity.csv'))+[O/'ALL_FOCUSED_CASES.csv']:
 if p.name.endswith('_BASE_equity.csv'):continue
 with open(p,'rb') as f,gzip.open(str(p)+'.gz','wb') as g:shutil.copyfileobj(f,g)
 p.unlink()
dump(O/'INPUT_PROVENANCE.json',{'archive_SHA256':sha(arc),'csv_SHA256':sha(data),'source_SHA256':hashlib.sha256(src.encode()).hexdigest(),'data_unchanged':True})
with open(O/'MANIFEST_SHA256.csv','w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(O.iterdir()):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([p.name,sha(p),p.stat().st_size])
with zipfile.ZipFile(O/'RIZAN_BTC_692365_DD50_AUDIT.zip','w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for p in O.iterdir():
  if p.is_file() and p.suffix!='.zip':z.write(p,p.name)
with zipfile.ZipFile(O/'RIZAN_BTC_692365_DD50_AUDIT.zip') as z:assert z.testzip() is None
(O/'PACKAGE_SHA256.txt').write_text(sha(O/'RIZAN_BTC_692365_DD50_AUDIT.zip')+'  RIZAN_BTC_692365_DD50_AUDIT.zip\n')
print(json.dumps(status,indent=2),flush=True)
