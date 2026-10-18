from pathlib import Path
import json,hashlib,zipfile,difflib,collections
import pandas as pd,numpy as np
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
r=Path(__file__).resolve().parent;old=Path('/tmp/previous');rows=[];audit=[];pairs=[]
expected=[f'{y}-{m:02}'for y in range(2019,2027)for m in range(1,13)if(y,m)<=(2026,3)]
def load_results(root):
 d={}
 for p in root.glob('*.json'):
  a=json.load(open(p))
  if isinstance(a,dict)and'Config'in a:d[a['Config']['Name']]=a
 return d
before=load_results(old/'replay_results');groups={'BEFORE':before,'ADAPTER_CORRECTED':load_results(r/'control_results'),'ADAPTER_AND_PARTIAL_DATA_REPAIR':load_results(r/'patched_results')}
summary=json.load(open(r/'gap_repair/GAP_REPAIR_SUMMARY.json'))
for mode,results in groups.items():
 for name,d in results.items():
  history=d['Ledger'];baskets=d['Baskets'];cash=100+sum(h['NetProfit']for h in history)-d['EndingBalance'];ids=[h['PositionId']for h in history]
  qa=json.load(open((old/'data_audit'if mode=='BEFORE'else r/('control_audit'if mode=='ADAPTER_CORRECTED'else'patched_audit'))/'data_quality.json'))
  settled=all(s['Checkpoint']['Basket']is None and not s['Checkpoint']['PendingLabel']and s['PendingAcks']==0 for s in d['TerminalStates'])
  check={'mode':mode,'scenario':name,'complete_87_months':[x['Month']for x in d['Monthly']]==expected,'tick_count':d['TotalTicks'],'tick_count_matches_data_audit':d['TotalTicks']==qa['total_ticks'],'cash_error_usd':cash,'unique_position_ids':len(set(ids))==len(ids),'source_settled':settled,'open_positions':d['OpenPositions']}
  assert check['complete_87_months']and check['tick_count_matches_data_audit']and abs(cash)<1e-6 and check['unique_position_ids']and settled and d['OpenPositions']==0,check
  audit.append(check)
  row={'mode':mode,'scenario':name,'ending_balance':d['EndingBalance'],'net_profit':d['NetProfit'],'floating_dd_pct':d['MaximumFloatingDDPct'],'balance_dd_pct':d['MaximumBalanceDDPct'],'profit_factor':d['ProfitFactor'],'win_rate_basket_pct':d['WinRate'],'baskets':d['TotalBaskets'],'broker_positions':len(history),'child_equivalent_001lot':d['TotalChildOrders'],'broker_requests':d['BrokerRequests'],'margin_rejects':d['MarginRejects'],'volume_rejects':d['VolumeRejects'],'portfolio_budget_blocks':d['PortfolioBudgetBlocks'],'stop_outs':len(d['Liquidations']),'xau_pnl':sum(x['NetProfit']for x in history if x['SymbolName']=='XAUUSD'),'eur_pnl':sum(x['NetProfit']for x in history if x['SymbolName']=='EURUSD'),'before_2025_10_balance':d['Monthly'][80]['EndBalance']}
  rows.append(row)
  if mode=='BEFORE':continue
  dest=r/'tables'/mode/name;dest.mkdir(parents=True,exist_ok=True)
  pd.DataFrame(history).to_csv(dest/'POSITION_LEDGER.csv',index=False);pd.DataFrame(baskets).to_csv(dest/'BASKET_LEDGER.csv',index=False);pd.DataFrame(d['Orders']).to_csv(dest/'ORDER_INTENTS_AND_FILLS.csv',index=False);pd.DataFrame(d.get('Decisions',[])).to_json(dest/'SIGNAL_DECISIONS.json',orient='records',indent=2)
  m=pd.DataFrame(d['Monthly']);m.to_csv(dest/'MONTHLY.csv',index=False);m['Year']=m.Month.str[:4];m.groupby('Year').agg(NetProfit=('NetProfit','sum'),EndBalance=('EndBalance','last')).to_csv(dest/'ANNUAL.csv')
  pd.DataFrame(d['SourceStatusEvents']).to_csv(dest/'SOURCE_STATUS_EVENTS.csv',index=False)
  pd.DataFrame(baskets).groupby('MaxStage').agg(Baskets=('Pnl','size'),PnL=('Pnl','sum'),Wins=('Pnl',lambda x:(x>0).sum())).to_csv(dest/'LAYERING.csv')
  eq=pd.DataFrame(d['EquityCurve']);eq['At']=pd.to_datetime(eq.At,utc=True);fig,ax=plt.subplots(2,1,figsize=(11,6),sharex=True,gridspec_kw={'height_ratios':[2,1]});ax[0].plot(eq.At,eq.Equity,label='Equity');ax[0].plot(eq.At,eq.Balance,label='Balance',alpha=.6);ax[0].set_yscale('log');ax[0].legend();ax[0].set_title(mode+' / '+name);ax[0].set_ylabel('USD (log)');ax[1].plot(eq.At,eq.get('DrawdownPct'),label='Sampled current DD');ax[1].plot(eq.At,eq.get('MaxDDPct'),'.',label='Running full-tick maximum DD');ax[1].set_ylabel('DD %');ax[1].legend();fig.tight_layout();fig.savefig(dest/'EQUITY_DRAWDOWN.png',dpi=150);plt.close(fig)
  # Gap exposure audit retains before/after entry/exit, including positions that straddle unresolved range.
  hs=pd.DataFrame(history);hs['EntryTime']=pd.to_datetime(hs.EntryTime,utc=True);hs['ExitTime']=pd.to_datetime(hs.ExitTime,utc=True);hs[(hs.EntryTime<pd.Timestamp('2025-10-20T00:00Z'))&(hs.ExitTime>pd.Timestamp('2025-10-10T20:59:58Z'))].to_csv(dest/'OCTOBER_GAP_EXPOSURES.csv',index=False)
# Pair on immutable basket signal timestamp, symbol, stage, sequence; preserve unmatched orders and size changes.
for name in before:
 for tag,new in [('ADAPTER_CORRECTED',groups['ADAPTER_CORRECTED']),('ADAPTER_AND_PARTIAL_DATA_REPAIR',groups['ADAPTER_AND_PARTIAL_DATA_REPAIR'])]:
  if name not in new:continue
  a={x['Label']:x for x in before[name]['Orders']if x.get('Status')=='FILLED'};b={x['Label']:x for x in new[name]['Orders']if x.get('Status')=='FILLED'}
  for key in sorted(a.keys()|b.keys()):
   x=a.get(key,{});y=b.get(key,{});pairs.append({'scenario':name,'comparison':tag,'label':key,'before_at':x.get('At'),'after_at':y.get('At'),'before_volume':x.get('Volume'),'after_volume':y.get('Volume'),'before_entry':x.get('Entry'),'after_entry':y.get('Entry'),'symbol':x.get('Symbol',y.get('Symbol')),'paired':bool(x and y)})
pd.DataFrame(pairs).to_csv(r/'PAIRED_BEFORE_AFTER_ORDERS.csv',index=False)
table=pd.DataFrame(rows);table.to_csv(r/'BEFORE_VS_AFTER_AUDIT.csv',index=False);json.dump(audit,open(r/'RECONCILIATION.json','w'),indent=2)
# Identify divergence in cost/delay paths, without claiming an additive decomposition of interacting effects.
comparisons=[]
for mode in ['BEFORE','ADAPTER_CORRECTED','ADAPTER_AND_PARTIAL_DATA_REPAIR']:
 a=groups[mode]
 for left,right in [('B_MODEL_2S_ARCHIVED_FLAGS','D_5S_ARCHIVED_FLAGS'),('B_MODEL_2S_ARCHIVED_FLAGS','C_COST1_5_ARCHIVED_FLAGS'),('B_MODEL_2S_ARCHIVED_FLAGS','C_COST2_ARCHIVED_FLAGS')]:
  if left not in a or right not in a:continue
  x=a[left];y=a[right];xo=[z for z in x['Orders']if z.get('Status')=='FILLED'];yo=[z for z in y['Orders']if z.get('Status')=='FILLED'];first=next((i for i,(p,q)in enumerate(zip(xo,yo))if p!=q),min(len(xo),len(yo)))
  mapx={p['Label']:p for p in xo};mapy={p['Label']:p for p in yo};div=[]
  for k in sorted(mapx.keys()|mapy.keys(),key=lambda k:int(k.split('|')[1])):
   p=mapx.get(k);q=mapy.get(k)
   if p is None or q is None or p['Volume']!=q['Volume']:div.append({'label':k,'left':p,'right':q})
  reasons=collections.Counter(z.get('Reason','')for z in y['Blocks']);status=collections.Counter(z.get('Status','')for z in y['SourceStatusEvents'])
  comparisons.append({'mode':mode,'left':left,'right':right,'first_order_difference_index':first,'left_first_different':xo[first]if first<len(xo)else None,'right_first_different':yo[first]if first<len(yo)else None,'first_20_presence_or_volume_differences':div[:20],'all_block_reasons':dict(reasons),'source_status_transition_counts':dict(status)})
json.dump(comparisons,open(r/'CAUSAL_PATH_DIVERGENCES.json','w'),indent=2)
# Cold start identical dates: original archived OHLC path, no pre-2019 cached tape or deposits.
m1=json.load(open(r/'engine/critical/OLD_M1_RESULTS.json'));m1rows=[]
for report in m1['Reports']:
 s=report['Summary'];m1rows.append({'scenario':s['cfg']['Name'],'ending_balance':s['EndingBalance'],'floating_dd_pct':s['MaxEquityDDPct'],'profit_factor':s['PF'],'baskets':s['Baskets'],'broker_requests':s['Orders'],'forced_closes':s['TerminalForcedCloses']})
pd.DataFrame(m1rows).to_csv(r/'OLD_M1_IDENTICAL_PERIOD.csv',index=False)
# Pair original M1 vs tick on signal-time basket label, stage and sequence, retaining differences.
mp=[]
for oldcase,newcase in zip(m1['Reports'],['A_IDEAL_ARCHIVED_FLAGS','B_MODEL_2S_ARCHIVED_FLAGS']):
 a={x['Label']:x for x in oldcase['OrderEvents']};b={x['Label']:x for x in groups['ADAPTER_AND_PARTIAL_DATA_REPAIR'].get(newcase,groups['ADAPTER_CORRECTED'][newcase])['Orders']if x.get('Status')=='FILLED'}
 for k in sorted(a.keys()|b.keys()):
  p=a.get(k,{});q=b.get(k,{});mp.append({'scenario':newcase,'label':k,'old_at':p.get('At'),'tick_at':q.get('At'),'old_volume':p.get('Volume'),'tick_volume':q.get('Volume'),'old_fill':p.get('Entry'),'tick_fill':q.get('Entry'),'paired':bool(p and q)})
pd.DataFrame(mp).to_csv(r/'PAIRED_OLD_M1_VS_TICK.csv',index=False)
macro={'ARCHIVED_FLAGS':{'status':'RECONSTRUCTED_NOT_VERIFIED','yield_source':'Latest-vintage macro_daily.csv used with assumed two US-business-day lag in prior prepare_xau.py','yield_series':['DFII10','DGS10'],'event_sources':['Forex Factory','BLS','FOMC scope'],'event_categories':['NFP','CPI','PPI','JOLTS','ECI','FOMC'],'availability_proof':'No historical per-decision retrieval receipt or original snapshot envelope. Synthetic permission envelope is NOT an original historical feed.'},'VERIFIED_POINT_IN_TIME':{'status':'NOT_AVAILABLE_NOT_RUN','reason':'No complete original source-compatible point-in-time yield/event snapshots with capture/publication timestamps. ALFRED and official schedule archives identified, but do not prove historical ForexFactoryOk/BlsOk coverage or that schedule changes were known at each entry.'},'STRICT_NO_SNAPSHOT':{'status':'EXECUTED','engine_name':'STRICT_MISSING_MACRO_XAU_BLOCKED','behavior':'Original ExternalOk blocks all XAU; EUR remains enabled.'},'gate_details':{'produced_freshness_seconds':180,'future_tolerance_seconds':5,'coverage_minutes_before':30,'coverage_minutes_after':495,'macro_max_age_days':7,'buy':'DFII10 delta <=0','sell':'DGS10 delta >=0','event_block':'any scoped event inside planned hold window'},'primary_sources':['https://alfred.stlouisfed.org/series?seid=DFII10','https://alfred.stlouisfed.org/series?seid=DGS10','https://www.bls.gov/schedule/2025/','https://www.federalreserve.gov/monetarypolicy/fomchistorical2025.htm']}
json.dump(macro,open(r/'MACRO_VINTAGE_AUDIT.json','w'),indent=2)
broker={'current_commission_public_evidence':'https://www.fpmarkets.com/ctrader-fees-and-charges/','current_published_raw':'Forex/metals $3 USD per lot per side; matches modeled EUR .00003/unit and gold .03/oz assuming 100oz/lot. Historical user account tariff and full contract spec unproven.','margin':'Linear notional/200, ask valued, both instruments, assumed 50% stopout; no evidence of historical dynamic leverage tiers or large size/depth execution.','slippage':'Fixed EUR .00001 and gold .05 per side, model assumptions not empirically calibrated. Stress multiplies commission/slippage only; actual spread unchanged.','min_lot_step':'Assumed .01 lots; EUR 1000 units, XAU1oz; historical symbol specs not proven.','native_lifecycle':'Adapter unit tests use source and fake broker; no native broker matching certification or stochastic fills.'}
json.dump(broker,open(r/'BROKER_SPEC_AUDIT.json','w'),indent=2)
text=['# RIZAN — Critical audit & revalidation','', '**Status: PARTIAL_PARITY. Kualitas data: PARTIAL / DATA_GAP_UNRESOLVED.**','', 'Source strategi dan parameter frozen tetap; yang diperbaiki adalah urutan checkpoint EUR dalam adapter. Source asli menyimpan checkpoint sebelum ProcessQueue EUR. Adapter lama menyimpan sesudahnya. Fixture entry EUR 2019-01-23 08:30 UTC pada request/ACK 2s berubah dari fill +4s menjadi +6s, sesuai source. Keempat fixture XAU/EUR × 0/2s lulus setelah koreksi. Ini bukan sertifikasi keseluruhan native lifecycle.','', '## BEFORE_VS_AFTER_AUDIT','', '| Skenario | Sebelum USD | Adapter dikoreksi USD | Adapter + pemulihan parsial USD | Floating DD setelah |','|---|---:|---:|---:|---:|']
for name in before:
 v=table[table.scenario==name].set_index('mode');a=v.loc['BEFORE'];b=v.loc['ADAPTER_CORRECTED'];c=v.loc['ADAPTER_AND_PARTIAL_DATA_REPAIR']if'ADAPTER_AND_PARTIAL_DATA_REPAIR'in v.index else b
 text.append(f"| {name} | {a.ending_balance:,.2f} | {b.ending_balance:,.2f} | {c.ending_balance:,.2f} | {c.floating_dd_pct:.2f}% |")
text+=['','## Gap historis','',f"Pemeriksaan original BI5 memulihkan **{summary.get('ticks_added',0):,} tick**. HTTP gagal tidak dianggap sebagai jam pasar tutup. Dataset asli tidak ditimpa; hanya overlay deterministik dalam interval kosong. Pemulihan belum membuktikan cakupan lengkap minggu 13–17 Oktober 2025. Lihat HOURLY_PROVENANCE.json, RECLASSIFIED_GAPS.json dan GAP_REPAIR_SUMMARY.json.",'','Auditor lama keliru menggunakan durasi >36 jam sebagai alasan weekend/libur. Semua gap panjang dengan jam sesi weekday internal diperiksa ulang; gap lain tetap kandidat kalender, bukan PASS otomatis. Semua 358 gap unexplained sebelumnya tetap terbuka untuk review kecuali ada bukti per jam.','', 'OCTOBER_GAP_EXPOSURES.csv mencatat posisi yang melewati rentang dan entry/exit baru selama rentang; tidak adanya posisi lama yang melintasi gap tidak membuktikan tidak ada sinyal/trade yang hilang. Perbandingan sampai September 2025 disertakan dalam before_2025_10_balance untuk periode pembanding tanpa gap besar ini.','', '## Old M1 pada tanggal identik','', '| Model M1/OHLC arsip | Saldo USD | Floating DD | PF | Basket |','|---|---:|---:|---:|---:|']
for v in m1rows:text.append(f"| {v['scenario']} | {v['ending_balance']:,.2f} | {v['floating_dd_pct']:.2f}% | {v['profit_factor']:.3f} | {v['baskets']} |")
text+=['','Kedua M1 controls memakai 2019-01-01–2026-03-31, $100, tanpa topup/prehistory tape. OHLC arsip dan spread model lama berbeda dari OHLC/spread bid/ask Dukascopy. Lintasan O-L-H-C/O-H-L-C dari hash timestamp adalah **sintetis, khusus pembanding**, bukan tick yang diperbaiki. Source, parameter, dan shared wallet sama, tetapi scheduler M1 lama memiliki asumsi berbeda, termasuk eksekusi hanya pada bar instrumen yang tersedia; hasil M1 bukan bukti validitas live.','', '## Isolasi kausal','', 'PAIRED_BEFORE_AFTER_ORDERS.csv dan PAIRED_OLD_M1_VS_TICK.csv memasangkan label basket timestamp/simbol/stage/sequence, mempertahankan intent yang tidak berpasangan dan ukuran yang berubah. CAUSAL_PATH_DIVERGENCES.json memuat divergensi awal harga, kehadiran order, volume serta alasan integer budget block. Delay 5s bukan perbaikan strategi; perubahan urutan fill/ACK, hasil basket, cooldown dan compounding menghasilkan jalur nonmonotonik.','', 'LOCKED_SCHEDULE_RESULTS.json mengunci jadwal request/exit dan volume B lama untuk mengukur perubahan quote/biaya tanpa compounding. Ini counterfactual aritmetis: tidak menguji ulang SL/TP atau membatasi margin, sehingga bukan saldo akun feasible atau strategi alternatif. Interaksi sinyal, layering, biaya, margin dan compounding tidak dijumlahkan seolah-olah efeknya aditif.','', '## Makro dan broker','', 'ARCHIVED_FLAGS memakai flag rekonstruksi dan synthetic snapshot permissions, bukan macro feed historis asli. VERIFIED_POINT_IN_TIME **NOT_AVAILABLE / NOT_RUN**; sumber primer yield/event telah diidentifikasi tetapi provenance per keputusan belum lengkap. STRICT_NO_SNAPSHOT dijalankan dan memblokir XAU dengan source gate asli.','', 'Tarif publik cTrader RAW saat audit $3/lot/sisi mendukung angka komisi model saat ini, tetapi tidak membuktikan tarif historis akun. Margin linear 1:200, kontrak/step/max volume, stopout 50%, fixed slippage, kedalaman likuiditas dan rounding platform tetap asumsi. Sumber primer: https://www.fpmarkets.com/ctrader-fees-and-charges/ ; https://alfred.stlouisfed.org/ ; https://www.bls.gov/schedule/2025/ .','', '## Kesimpulan validitas','', 'Keuntungan dapat bertahan pada sebagian model tick, tetapi klaim keuntungan besar yang telah diverifikasi konsisten untuk data lengkap, makro vintage, margin broker dan seluruh settlement native **belum terbukti**. Jangan menyamakan hasil ini dengan $90 juta 2016–Oktober 2026. Kepekaan biaya, delay, pembulatan volume dan compounding sangat besar; laporan ini tidak memilih parameter terbaik.','', 'Seluruh replay lengkap memiliki 87 bulan berurutan, tick count cocok dengan audit/overlay, kas direkonsiliasi dan posisi akhir nol. Keterbatasan no-lookahead: candle/signal cached closed-only memakai data <= waktu keputusan; fixture terpilih bukan sertifikasi semua startup/history/platform. Tidak ada order/live cBot/bridge/.env produksi yang diubah.']
(r/'LAPORAN_CRITICAL_REVALIDATION.md').write_text('\n'.join(text)+'\n')
# Record exact adapter diff including observation hooks; frozen source manifest unchanged.
(r/'ADAPTER_DIFF.patch').write_text(''.join(difflib.unified_diff((old/'TickReplay.cs').read_text().splitlines(True),(r/'engine/TickReplay.cs').read_text().splitlines(True),fromfile='8fdfe44/TickReplay.cs',tofile='corrected/TickReplay.cs')))
manifest={}
for p in r.rglob('*'):
 if p.is_file()and p.name not in ['MANIFEST_SHA256.json','RIZAN_CRITICAL_REVALIDATION.zip','PACKAGE_SHA256.txt']and not p.suffix in ['.parquet','.dll']and'/incoming/'not in str(p):manifest[str(p.relative_to(r))]=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
json.dump(manifest,open(r/'MANIFEST_SHA256.json','w'),indent=2)
with zipfile.ZipFile(r/'RIZAN_CRITICAL_REVALIDATION.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6)as z:
 for p in r.rglob('*'):
  if p.is_file()and p.name not in ['RIZAN_CRITICAL_REVALIDATION.zip','PACKAGE_SHA256.txt']and'/incoming/'not in str(p)and p.suffix!='.dll':z.write(p,p.relative_to(r))
f=r/'RIZAN_CRITICAL_REVALIDATION.zip';(r/'PACKAGE_SHA256.txt').write_text(hashlib.file_digest(f.open('rb'),'sha256').hexdigest()+'  '+f.name+'\n');print(table.to_string(index=False));print('FINAL_PACKAGE',f.stat().st_size)
