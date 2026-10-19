import pathlib,sys,json,csv,gzip,shutil,subprocess,hashlib,datetime,zipfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path.cwd();STUDIES=ROOT/'full_studies';OUT=ROOT/'deliverables';OUT.mkdir(exist_ok=True);CODE=ROOT/'research_btc_jpy'
PH=['id','tf_minutes','family','lookback','threshold_index','trend_filter','session_utc','side','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']
def jread(p):return json.loads(pathlib.Path(p).read_text())
def dump(p,x):pathlib.Path(p).write_text(json.dumps(x,indent=2,default=lambda z:z.item() if hasattr(z,'item') else str(z)))
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def table(rows,cols):
 out=['| '+' | '.join(cols)+' |','|'+'|'.join(['---']*len(cols))+'|']
 for row in rows:
  out.append('| '+' | '.join(f'{row.get(c):,.2f}' if isinstance(row.get(c),(float,np.floating)) else str(row.get(c,'')) for c in cols)+' |')
 return '\n'.join(out)
found={}
for p in STUDIES.iterdir():
 if p.is_dir() and (p/'UNIVERSE.json').exists():
  m=jread(p/'UNIVERSE.json');found[(m['symbol'],m['variant'])]=p
assert len(found)==6,found.keys()
inputdir=ROOT/'uncompressed_input';inputdir.mkdir(exist_ok=True)
for symbol in ['BTCUSD','USDJPY']:
 p=found[(symbol,'GENERIC')]/'data'/(symbol+'_M1.csv.gz');dest=inputdir/(symbol+'_M1.csv')
 with gzip.open(p,'rb') as src,open(dest,'wb') as dst:shutil.copyfileobj(src,dst)
 assert sha(dest)==jread(found[(symbol,'GENERIC')]/'data'/(symbol+'_AUDIT.json'))['sha256']
rows=[];metrics=[];configurations=[];allcases=[];cashproof=[];modes={}
for (symbol,variant),study in sorted(found.items()):
 r=study/f'results_{symbol}';summary=jread(r/'FINAL_SUMMARY.json');stats=jread(r/'UNIVERSE_STATISTICS.json');coverage=jread(r/'SHARD_COVERAGE.json');prefix=jread(r/'PREFIX_INVARIANCE.json')
 assert stats['configurations']==1000000 and coverage['ids']==1000000 and coverage['unique_parameter_tuples']==1000000 and prefix['exact_prefix_results_equal']
 dd=[];train=[]
 for q in pd.read_csv(r/'ALL_CONFIGURATIONS.csv.gz',chunksize=100000):
  dd.append(q[(q.full_floating_dd<50)&(q.full_trades>0)].nlargest(20,'full_equity'))
  train.append(q[(q.train_dd<50)&(q.train_trades>=20)].nlargest(20,'train_equity'))
 full=pd.read_csv(r/'ALL_TRADE_COUNTS_TOP20.csv').nlargest(20,'full_equity')
 d=pd.concat(dd).nlargest(20,'full_equity');t=pd.concat(train).nlargest(20,'train_equity')
 selected=pd.concat([full,d,t]).drop_duplicates('id');vdir=study/'raw_validation';vdir.mkdir(exist_ok=True)
 selected.to_csv(vdir/'SELECTED_ROWS.csv',index=False)
 leaders={'FULL':int(full.iloc[0].id),'DD50':int(d.iloc[0].id),'TRAIN':int(t.iloc[0].id)}
 dump(vdir/'LEADERS_FROZEN_BEFORE_STRESS.json',{'leaders':leaders,'selection_period_end':'2026-10-15','full_period_exploratory':True,'selection_using_stress':False,'parameter_count':len(selected)})
 shutil.copy2(CODE/'validate_raw.cpp',study/'validate_raw.cpp')
 flag=[]
 if variant=='SESSIONS':shutil.copy2(study/'search_direct_m1.cpp',study/'search_sessions_direct.cpp');flag=['-DSESSION_VARIANT']
 if variant=='POSITION':shutil.copy2(study/'search_direct_m1.cpp',study/'search_position_direct.cpp');flag=['-DPOSITION_VARIANT']
 exe=ROOT/('validate_'+symbol+'_'+variant)
 subprocess.run(['g++','-O3','-std=c++17',*flag,str(study/'validate_raw.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe),str(inputdir/(symbol+'_M1.csv')),symbol,str(vdir/'SELECTED_ROWS.csv'),str(vdir)],check=True)
 subprocess.run([sys.executable,str(CODE/'reconcile_raw.py'),str(study),symbol],check=True)
 proof=jread(vdir/'RAW_CASH_RECONCILIATION.json');cashproof.append({'symbol':symbol,'variant':variant,**proof})
 v=pd.read_csv(vdir/'RAW_TOP20_STRESS.csv');v['symbol']=symbol;v['variant']=variant;allcases.append(v)
 for label,cid in leaders.items():
  c=v[(v.id==cid)&(v['case']=='BASE')].iloc[0].to_dict();c.update(symbol=symbol,variant=variant,criterion=label,win_rate=100*c['wins']/c['trades'] if c['trades'] else 0,net_profit=c['equity']-100,model_leverage=10 if symbol=='BTCUSD' else 200)
  for case in ['COST1_5','COST2','DELAY_NEXT_M1','LEVERAGE2','TRAIN_2019_2022','VALID_2023_2024','TEST_2025_OCT2026']:
   z=v[(v.id==cid)&(v['case']==case)]
   c[case+'_equity']=float(z.iloc[0].equity) if len(z) else None;c[case+'_dd']=float(z.iloc[0].floating_dd) if len(z) else None
  rows.append(c);configurations.append({k:c[k] for k in PH+['symbol','variant','criterion','model_leverage']})
 for cid in sorted(set(leaders.values())):
  ledger=pd.read_csv(vdir/f'raw_{cid}_ledger.csv');ex=pd.to_datetime(ledger.exit_utc,utc=True);ledger['month']=ex.dt.strftime('%Y-%m');ledger['year']=ex.dt.year
  for key in ['month','year']:
   z=ledger.groupby(key).agg(net_profit=('net_pnl','sum'),trades=('net_pnl','size'),wins=('net_pnl',lambda x:int((x>0).sum())),adds=('adds','sum'),entry_commission=('entry_commission','sum'),exit_commission=('exit_commission','sum'),financing=('financing','sum'))
   if key=='month':z=z.reindex(pd.period_range('2019-01','2026-10',freq='M').astype(str),fill_value=0)
   z['ending_balance']=100+z.net_profit.cumsum();z.to_csv(vdir/f'raw_{cid}_{key}.csv')
  c=pd.read_csv(vdir/f'raw_{cid}_equity.csv');c['timestamp']=pd.to_datetime(c.timestamp,utc=True)
  fig,ax=plt.subplots(2,1,figsize=(12,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
  ax[0].plot(c.timestamp,c.equity,lw=.65,color='#165a8c');ax[0].set_yscale('symlog',linthresh=10);ax[0].set_ylabel('Model equity USD');ax[0].set_title(f'{symbol} {variant} candidate{cid}: publishedM1 model, 2019-15Oct2026')
  ax[1].plot(c.timestamp,-c.drawdown_pct,lw=.65,color='#a02b2b');ax[1].set_ylabel('Model DD %')
  for a in ax:a.grid(alpha=.25)
  fig.tight_layout();fig.savefig(vdir/f'raw_{cid}_equity_drawdown.png',dpi=140);plt.close(fig)
 metrics.append({'symbol':symbol,'variant':variant,**stats,'prefix_test_cases':prefix['tested_parameters'],'max_cash_error':proof['max_error']})
m=pd.DataFrame(rows);m.to_csv(OUT/'ALL_LEADER_RESULTS.csv',index=False);pd.concat(allcases,ignore_index=True).to_csv(OUT/'ALL_SELECTED_SCENARIOS.csv',index=False)
dump(OUT/'CONFIGURATIONS.json',configurations);dump(OUT/'UNIVERSE_STATISTICS.json',metrics);dump(OUT/'CASH_RECONCILIATION.json',cashproof)
selected=[]
for symbol in ['BTCUSD','USDJPY']:
 for label in ['FULL','DD50','TRAIN']:
  q=m[(m.symbol==symbol)&(m.criterion==label)]
  key='TRAIN_2019_2022_equity' if label=='TRAIN' else 'equity'
  selected.append(q.sort_values(key,ascending=False).iloc[0].to_dict())
pd.DataFrame(selected).to_csv(OUT/'FINAL_COMPARISON.csv',index=False)
unique={}
for symbol in ['BTCUSD','USDJPY']:
 fn=ROOT/(symbol+'_canonical.tmp')
 with open(fn,'w') as f:
  for variant in ['GENERIC','SESSIONS','POSITION']:
   p=found[(symbol,variant)]/f'results_{symbol}'/'ALL_CONFIGURATIONS.csv.gz'
   with gzip.open(p,'rt') as src:
    next(src)
    for line in src:
     z=line.rstrip('\n').split(',');f.write(','.join(z[1:15])+'\n')
 dst=ROOT/(symbol+'_unique.tmp')
 with open(dst,'w') as f:subprocess.run(['sort','-u','-S','1G',str(fn)],stdout=f,check=True,env={**__import__('os').environ,'LC_ALL':'C'})
 with open(dst) as f:unique[symbol]=sum(1 for _ in f)
 fn.unlink();dst.unlink()
dump(OUT/'GLOBAL_UNIQUE_PARAMETER_COUNTS.json',unique)
target=sum(x['target100k_any_trade_count'] for x in metrics);status='TARGET_HIT_IN_HISTORICAL_MODEL_ONLY' if target else 'TARGET_NOT_FOUND_IN_TESTED_UNIVERSES'
report=f'''# RIZAN — BTCUSD dan USDJPY, pencarian setup2019–15Oktober2026

**Status: {status}. Validitas eksekusi broker: NOT_VALIDATED.**

Setiap instrumen dimulai dariUSD100 tanpa topup, pada akun riset terpisah. Periode akhir2019-01-01–2026-10-15 23:59UTC. Tiga universe masing-masing1.000.000 tuple per instrumen telah dijalankan langsung padaM1: GENERIC, SESSIONS, POSITION. Total6.000.000 penilaian periodepenuh, gabunganunikBTC{unique['BTCUSD']:,} danUSDJPY{unique['USDJPY']:,} setelah overlapparameterH4 dihapus. Ini24keluarga aturan dasar dengan kombinasi parameter; bukan jutaan keluarga statistikindependen. Pengulangan periodeMaret/Oktober tidak dihitung sebagai konfigurasi baru.

## Hasil utama — pemilihan historis, belum bukti keuntungan broker

{table(selected,['symbol','criterion','variant','id','family','equity','floating_dd','pf','win_rate','trades','adds'])}

FULL memilih saldo tertinggi pada seluruhperiode. DD50 memilih saldo tertinggi denganDDmodel<50%. TRAIN memilih hanya berdasarkan2019–2022, lalu menampilkan kinerja periodepenuh. PemilihanFULL/DD50 menggunakan seluruhhistory dan bersifat eksploratif. HasilTRAIN/validasi/test bukan holdoutprospektif yang belum pernah dilihat; sejarah pasar ini telah diteliti sebelumnya.

Jumlah targetUSD100.000 pada setiap universe, termasuk semua jumlahtrade:

{table(metrics,['symbol','variant','configurations','target100k_any_trade_count','target100k_dd50_min30trades','profitable_fraction','best_any_trade_count_equity'])}

Tidak ada penghapusan konfigurasi rugi. Seluruhmillion-rowfile tersedia; kandidat mentah dengan sedikittrade juga diperiksa. Saldo dan drawdown disajikan sesuai model, tanpa perubahanfee atau peningkatanrisk untuk memaksakan target.

## Ketahanan biaya dan leverage untuk pemimpin setiap kriteria

{table(selected,['symbol','criterion','id','equity','COST1_5_equity','COST2_equity','DELAY_NEXT_M1_equity','LEVERAGE2_equity'])}

ModelBTC menggunakanleverage10 yang belum dibuktikan untuk akun/histori broker. LEVERAGE2 adalah sensitivitas terpisah. USDJPY menggunakanleverage200model. Biaya1,5x/2x mengalikan komisi,slippage,financing; spreadasumsi tetap. Delay memakai next-observedM1 setidaknya1menit kemudian, bukan simulasi2detik. NO_ADDS merelokasi anggaranawal menjadi100% dan bukan ablationvolume-terkunci.

## Pembagian waktu untuk pemimpin yang dipilih

{table(selected,['symbol','criterion','id','TRAIN_2019_2022_equity','VALID_2023_2024_equity','TEST_2025_OCT2026_equity'])}

Setiap segmen dimulai dari100 untuk mengisolasi kinerja segmen. Saldo periodepenuh tetap melalui compounding kontinu2019–Oktober tanpa setoran. Eksperimen terpisah pada kontrolMaret mengunci parameter sebelum April–Oktober; seluruh hasil lanjutannya tetap disertakan, termasuk kerugian.

## Data dan ketepatan waktu

BTCUSD menggunakan seluruhOHLCM1 resmiBitstamp, pasanganUSD, beserta rawresponseAPI dan checksum. Pada pembanding sampaiMaret, arsipCDD kehilangan85.414menit dan5.458candleOHLC berbeda dariAPIprimer, selisihmaksimum sekitarUSD1.908,89. Sourcefinal mengambil seluruh periode dariAPIprimer dengan aturan sama untuk semua timestamp, tidak memilih harga berdasarkan profit. Candlevolume0 yang dipublikasikan penyedia tetap dilabeli sebagai candleprovider; tidak ada tick atau harga interpolasi lokal. Ini harga tradeexchange, belum historicalbid/askCFD.

USDJPY berasal dari eksporHistData yang diaudit diActions39176779912, timezoneESTtetap+5jam keUTC. Semua timestamp,uniqueIDs,positiveOHLC,hash dan bulanperiode diverifikasi. Gapweekend/holiday/sparsequotes tetap dijabarkan padaauditsource; kalenderbroker dan seluruh gap tidak tersertifikasi. DatasetM1 bukan pengganti tickbid/ask.

SignalbarM5/M15/H1/H4/D1 sesuaiuniverse telahclosed sebelum entrynextbaropen. H4trend memakai candleclosed. Sessionwindows didefinisikan sebagai UTCtetap;WIB=UTC+7. Indikator coldstart pada2019, tidak mengklaim kesamaan denganprehistory/startupcBotnative. Tidak ada feedmacro atau syntheticmacropermissions pada strategi baru ini.

Prefixdifferential memodifikasi hanya hargamasa depan di memori dan menguji500parameter per universe: seluruh hasil akun sebelumcutoff tetap sama. Ada9fixtureeksekusi dan6aritmetika pada setiap engine. Ini cakupan regresi, bukan sertifikasi semua kemungkinanplatform.

## Asumsi model yang material

USDJPY: min/step1000USDbaseunits,max2.000.000; spread0,01JPY=1pip;slippage0,001JPY/sisi;komisiUSD0,00003/unit/sisi;financingdebit0,01%notional/hari prorata. PnLJPY dikonversi keUSD pada quoteexit.

BTC: min/step0,01BTC,max100BTC;spread5bp;slippage1bp/sisi;komisi5bp/sisi;financingdebit3bpnotional/hari prorata. Leverage10 adalah hipotesisriset, bukan bukti kontrakbroker. Fee,carry,weekendtrading,leveragehistoris,maxsize,rounding,depth danminimumstop broker belum diverifikasi.

Marginbudget10/25/50%equity,risk1–20%,integerstep dan compounding benar-benar diterapkan. SL/TP bersamaan menggunakanSTOP_FIRST; gapSL memakai openyanglebihburuk; stage ditambahkan pada openberikutnya setelah keputusancandleclosed. Break-even aktif mulai candleberikutnya. Expiry ditutup pada candletersediaberikutnya, bukan quotejamkosong. Tidak adaACK,partialfill,rejection/recovery native atau swapledgerbroker.

DD adalah statistikjalur/envelopeOHLC yang dipilihengine. Peak pada candleterkenastop dibatasi oleh aturanSTOP_FIRST; nilainya bukan batasatas matematis untuk setiap urutantick yang mungkin. Karena urutanintramenit danbid/askbroker tidak tersedia, DD<50%model tidak menjamin DDaktual<50%.

## Rekonsiliasi dan artefak

Setiap5shard berisi200.000IDinterleaved; gabungannya tepat1.000.000ID dantupleunik per universe, dengan engine daninputhash sama. Penilaian rawleader,DD50 dantrainleader direkonstruksi dariparameterCSV, dibandingkan dengan saldo semulamillion-rowfile, kemudian diuji biayadansegmen. Seluruhledger terpilih direkonsiliasi independen dari harga,volume,komisi,financing dan kas. Detailnilaierror ada diCASH_RECONCILIATION.json.

Selisihmikro pada beberapa eksporUSDJPY presisi12digit diperbaiki menjadi17digit. Regresinya membuktikan jalurfinansial,tradecount,stage dan hasilMaret tetap sama. Sourceasli dandiffexport dipertahankan. KesalahanunitDatetimePandas3 pada auditor/APIrequest awal juga diperbaiki secaraeksplisit ke nanosekon; runyanggagal/superseded tidak dipromosikan menjadi buktiprofit.

Paket perinstrumen memuat seluruhkonfigurasi,sourceexecuted,parameterpemimpin,ledger lengkap kandidat,laporanbulanan/tahunan,grafik danmanifestSHA256. Tick asli XAU/EUR,VPSarchive,cBotlive,bridge,envproduksi danstrategifrozen lama tidak diubah.

## Sumber dan reproduksi

- Bitstamp historicalOHLCAPI: https://www.bitstamp.net/api/
- HistData: https://www.histdata.com/f-a-q/
- Modelcommissionreference: https://www.fpmarkets.com/ctrader-fees-and-charges/
- Branch: research/btcusd-usdjpy-million-2019-2026.
- FullOctober universeexecution: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39213912052
- FullOctober independentaudit: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39214728591
- Positionuniverseexecution: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39216109535
- KontrolMaret/extension: Actions39213178402 dan39213656204; rawdata/sourcebuild39211599931 dan39212036090.

**Kesimpulan: target dilaporkan sesuai angkaactualmodel di atas. Pencarianhistoris tidak membuktikan keuntungan masa depan atau profitbroker. Jika target belum ditemukan, tidak ada konfigurasiUSD100.000 yang diklaim berhasil.**
'''
(OUT/'LAPORAN_BTCUSD_USDJPY_2019_2026.md').write_text(report)
dump(OUT/'FINAL_STATUS.json',{'status':status,'target_hits_across_universes':target,'global_unique_parameters':unique,'full_period_end':'2026-10-15','initial_USD_each':100,'broker_execution':'NOT_VALIDATED','research_only':True,'leaders':selected})
for symbol in ['BTCUSD','USDJPY']:
 pack=ROOT/('package_'+symbol);pack.mkdir(exist_ok=True)
 for variant in ['GENERIC','SESSIONS','POSITION']:
  src=found[(symbol,variant)];shutil.copytree(src,pack/'FULL_PERIOD'/variant,dirs_exist_ok=True)
 control=ROOT/'march_controls'
 for p in control.iterdir() if control.exists() else []:
  if symbol in p.name:shutil.copytree(p,pack/'MARCH_LOCKED_CONTROLS'/p.name,dirs_exist_ok=True)
 for name in ['LAPORAN_BTCUSD_USDJPY_2019_2026.md','FINAL_COMPARISON.csv','ALL_LEADER_RESULTS.csv','ALL_SELECTED_SCENARIOS.csv','CONFIGURATIONS.json','UNIVERSE_STATISTICS.json','CASH_RECONCILIATION.json','GLOBAL_UNIQUE_PARAMETER_COUNTS.json','FINAL_STATUS.json']:shutil.copy2(OUT/name,pack/name)
 for p in pack.rglob('*'):
  if p.is_file() and '__pycache__' in p.parts:p.unlink()
 with open(pack/'MANIFEST_SHA256.csv','w') as f:
  f.write('path,sha256,bytes\n')
  for p in sorted(pack.rglob('*')):
   if p.is_file() and p!=pack/'MANIFEST_SHA256.csv':f.write(f'{p.relative_to(pack)},{sha(p)},{p.stat().st_size}\n')
 zpath=OUT/('RIZAN_'+symbol+'_MILLION_M1_2019_2026.zip')
 with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
  for p in sorted(pack.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(pack))
 with zipfile.ZipFile(zpath) as z:assert z.testzip() is None
 print('PACKAGE_VERIFIED',zpath.name,zpath.stat().st_size,sha(zpath),flush=True)
with open(OUT/'PACKAGE_SHA256.txt','w') as f:
 for p in sorted(OUT.glob('*')):
  if p.is_file() and p.name!='PACKAGE_SHA256.txt':f.write(sha(p)+'  '+p.name+'\n')
print('FINAL_STATUS',status,'target_hits',target,flush=True)
print(pd.DataFrame(selected)[['symbol','criterion','variant','id','equity','floating_dd','pf','trades']].to_string(index=False),flush=True)
