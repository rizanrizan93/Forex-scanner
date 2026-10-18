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
if 'october_expected_open_hours' in summary:
 summary.pop('full_gap_resolved',None);summary['october_normal_open_archives_recovered']=summary['october_verified_open_hours']==summary['october_expected_open_hours']
 ext=r/'extended_hour_recovery/EXTENDED_HOURS.json'
 if ext.exists():
  eh=json.load(open(ext));dec=[x for x in eh if x['hour_utc'].startswith('2025-12-31')];summary['december31_verified_nonempty_hours']=sum(x['status']=='VERIFIED_DECODE'for x in dec);summary['december31_verified_empty_hours']=sum(x['status']=='EMPTY_NO_TICKS'for x in dec);summary['december31_unresolved_hours']=[x['hour_utc']for x in dec if x['status']=='DATA_GAP_UNRESOLVED']
 summary['all_other_gap_calendar_certified']=False
 json.dump(summary,open(r/'gap_repair/GAP_REPAIR_SUMMARY.json','w'),indent=2)
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
  pd.DataFrame(history).to_csv(dest/'POSITION_LEDGER.csv',index=False)
  corrected_baskets=[]
  for basket in baskets:
   h=[p for p in history if '|'.join(p['Label'].split('|')[:2])==basket['Id']];item=dict(basket);item['SourceReportedEntry_FirstClosedChild']=item['Entry'];item['SignalUTC']=str(pd.Timestamp((int(item['Id'].split('|')[1])-621355968000000000)*100,unit='ns',tz='UTC'));item['Entry']=min((p['EntryTime']for p in h),key=pd.Timestamp);item['Exit']=max((p['ExitTime']for p in h),key=pd.Timestamp);corrected_baskets.append(item)
  pd.DataFrame(corrected_baskets).to_csv(dest/'BASKET_LEDGER.csv',index=False);pd.DataFrame(d['Orders']).to_csv(dest/'ORDER_INTENTS_AND_FILLS.csv',index=False);pd.DataFrame(d.get('Decisions',[])).to_json(dest/'SIGNAL_DECISIONS.json',orient='records',indent=2)
  m=pd.DataFrame(d['Monthly']);m.to_csv(dest/'MONTHLY.csv',index=False);m['Year']=m.Month.str[:4];m.groupby('Year').agg(NetProfit=('NetProfit','sum'),EndBalance=('EndBalance','last')).to_csv(dest/'ANNUAL.csv')
  pd.DataFrame(d['SourceStatusEvents']).to_csv(dest/'SOURCE_STATUS_EVENTS.csv',index=False)
  pd.DataFrame(baskets).groupby('MaxStage').agg(Baskets=('Pnl','size'),PnL=('Pnl','sum'),Wins=('Pnl',lambda x:(x>0).sum())).to_csv(dest/'LAYERING.csv')
  eq=pd.DataFrame(d['EquityCurve']);eq['At']=pd.to_datetime(eq.At,utc=True,format="mixed");fig,ax=plt.subplots(2,1,figsize=(11,6),sharex=True,gridspec_kw={'height_ratios':[2,1]});ax[0].plot(eq.At,eq.Equity,label='Equity');ax[0].plot(eq.At,eq.Balance,label='Balance',alpha=.6);ax[0].set_yscale('log');ax[0].legend();ax[0].set_title(mode+' / '+name);ax[0].set_ylabel('USD (log)');ax[1].plot(eq.At,eq.get('DrawdownPct'),label='Sampled current DD');ax[1].plot(eq.At,eq.get('MaxDDPct'),'.',label='Running full-tick maximum DD');ax[1].set_ylabel('DD %');ax[1].legend();fig.tight_layout();fig.savefig(dest/'EQUITY_DRAWDOWN.png',dpi=150);plt.close(fig)
  # Gap exposure audit retains before/after entry/exit, including positions that straddle unresolved range.
  hs=pd.DataFrame(history);hs['EntryTime']=pd.to_datetime(hs.EntryTime,utc=True,format="mixed");hs['ExitTime']=pd.to_datetime(hs.ExitTime,utc=True,format="mixed");hs[(hs.EntryTime<pd.Timestamp('2025-10-20T00:00Z'))&(hs.ExitTime>pd.Timestamp('2025-10-10T20:59:58Z'))].to_csv(dest/'OCTOBER_GAP_EXPOSURES.csv',index=False);hs[(hs.EntryTime<pd.Timestamp('2026-01-01T23:00:00Z'))&(hs.ExitTime>pd.Timestamp('2025-12-30T23:59:59Z'))].to_csv(dest/'DECEMBER_GAP_EXPOSURES.csv',index=False)
# Pair on immutable basket signal timestamp, symbol, stage, sequence; preserve unmatched orders and size changes.
for name in before:
 for tag,new in [('ADAPTER_CORRECTED',groups['ADAPTER_CORRECTED']),('ADAPTER_AND_PARTIAL_DATA_REPAIR',groups['ADAPTER_AND_PARTIAL_DATA_REPAIR'])]:
  if name not in new:continue
  a={'|'.join(x['Label'].split('|')[:4]):x for x in before[name]['Orders']if x.get('Status')=='FILLED'};b={'|'.join(x['Label'].split('|')[:4]):x for x in new[name]['Orders']if x.get('Status')=='FILLED'}
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
 a={'|'.join(x['Label'].split('|')[:4]):x for x in oldcase['OrderEvents']};b={'|'.join(x['Label'].split('|')[:4]):x for x in groups['ADAPTER_AND_PARTIAL_DATA_REPAIR'].get(newcase,groups['ADAPTER_CORRECTED'][newcase])['Orders']if x.get('Status')=='FILLED'}
 for k in sorted(a.keys()|b.keys()):
  p=a.get(k,{});q=b.get(k,{});mp.append({'scenario':newcase,'label':k,'old_at':p.get('At'),'tick_at':q.get('At'),'old_volume':p.get('Volume'),'tick_volume':q.get('Volume'),'old_fill':p.get('Entry'),'tick_fill':q.get('Entry'),'paired':bool(p and q)})
pd.DataFrame(mp).to_csv(r/'PAIRED_OLD_M1_VS_TICK.csv',index=False)
macro={'ARCHIVED_FLAGS':{'status':'RECONSTRUCTED_NOT_VERIFIED','yield_source':'Latest-vintage macro_daily.csv used with assumed two US-business-day lag in prior prepare_xau.py','yield_series':['DFII10','DGS10'],'event_sources':['Forex Factory','BLS','FOMC scope'],'event_categories':['NFP','CPI','PPI','JOLTS','ECI','FOMC'],'availability_proof':'No historical per-decision retrieval receipt or original snapshot envelope. Synthetic permission envelope is NOT an original historical feed.'},'VERIFIED_POINT_IN_TIME':{'status':'NOT_AVAILABLE_NOT_RUN','reason':'No complete original source-compatible point-in-time yield/event snapshots with capture/publication timestamps. ALFRED and official schedule archives identified, but do not prove historical ForexFactoryOk/BlsOk coverage or that schedule changes were known at each entry.'},'STRICT_NO_SNAPSHOT':{'status':'EXECUTED','engine_name':'STRICT_MISSING_MACRO_XAU_BLOCKED','behavior':'Original ExternalOk blocks all XAU; EUR remains enabled.'},'gate_details':{'produced_freshness_seconds':180,'future_tolerance_seconds':5,'coverage_minutes_before':30,'coverage_minutes_after':495,'macro_max_age_days':7,'buy':'DFII10 delta <=0','sell':'DGS10 delta >=0','event_block':'any scoped event inside planned hold window'},'primary_sources':['https://alfred.stlouisfed.org/series?seid=DFII10','https://alfred.stlouisfed.org/series?seid=DGS10','https://www.bls.gov/schedule/2025/','https://www.federalreserve.gov/monetarypolicy/fomchistorical2025.htm']}
json.dump(macro,open(r/'MACRO_VINTAGE_AUDIT.json','w'),indent=2)
broker={'current_commission_public_evidence':'https://www.fpmarkets.com/ctrader-fees-and-charges/','current_published_raw':'Forex/metals $3 USD per lot per side; matches modeled EUR .00003/unit and gold .03/oz assuming 100oz/lot. Historical user account tariff and full contract spec unproven.','margin':'Linear notional/200, ask valued, both instruments, assumed 50% stopout; no evidence of historical dynamic leverage tiers or large size/depth execution.','slippage':'Fixed EUR .00001 and gold .05 per side, model assumptions not empirically calibrated. Stress multiplies commission/slippage only; actual spread unchanged.','min_lot_step':'Assumed .01 lots; EUR 1000 units, XAU1oz; historical symbol specs not proven.','native_lifecycle':'Adapter unit tests use source and fake broker; no native broker matching certification or stochastic fills.'}
json.dump(broker,open(r/'BROKER_SPEC_AUDIT.json','w'),indent=2)
text=['# RIZAN — Critical audit & revalidation','', '**Status: PARTIAL_PARITY. Kualitas data: PARTIAL.**','', 'Source strategi dan parameter frozen tetap; yang diperbaiki adalah urutan checkpoint EUR dalam adapter. Source asli menyimpan checkpoint sebelum ProcessQueue EUR. Adapter lama menyimpan sesudahnya. Fixture entry EUR 2019-01-23 08:30 UTC pada request/ACK 2s berubah dari fill +4s menjadi +6s, sesuai source. Keempat fixture XAU/EUR × 0/2s lulus setelah koreksi. Ini bukan sertifikasi keseluruhan native lifecycle. Setiap request/ACK jaringan pada modelB tetap2s; EUR pertama membutuhkan dua siklus checkpoint/ACK sebelum broker request sehingga total entry6s, sedangkan XAU4s. Model5s berarti EUR15s/XAU10s pada fixture awal, bukan mengubah latensi per pesan.','', '## BEFORE_VS_AFTER_AUDIT','', '| Skenario | Sebelum USD | Adapter dikoreksi USD | Adapter + pemulihan parsial USD | Floating DD setelah |','|---|---:|---:|---:|---:|']
for name in before:
 v=table[table.scenario==name].set_index('mode');a=v.loc['BEFORE'];b=v.loc['ADAPTER_CORRECTED'];c=v.loc['ADAPTER_AND_PARTIAL_DATA_REPAIR']if'ADAPTER_AND_PARTIAL_DATA_REPAIR'in v.index else b
 text.append(f"| {name} | {a.ending_balance:,.2f} | {b.ending_balance:,.2f} | {c.ending_balance:,.2f} | {c.floating_dd_pct:.2f}% |")
text+=['','## Gap historis','',f"Pemeriksaan original BI5 memulihkan **{summary.get('ticks_added',0):,} tick**. HTTP gagal tidak dianggap sebagai jam pasar tutup. Dataset asli tidak ditimpa; hanya overlay deterministik dalam interval kosong. Status cakupan lengkap diperinci dalam bagian bukti tambahan di bawah; HTTP gagal pada jam perdagangan tetap DATA_GAP_UNRESOLVED. Lihat HOURLY_PROVENANCE.json, RECLASSIFIED_GAPS.json dan GAP_REPAIR_SUMMARY.json.",'','Auditor lama keliru menggunakan durasi >36 jam sebagai alasan weekend/libur. Semua gap panjang dengan jam sesi weekday internal diperiksa ulang; gap lain tetap kandidat kalender, bukan PASS otomatis. Semua 358 gap unexplained sebelumnya tetap terbuka untuk review kecuali ada bukti per jam.','', 'OCTOBER_GAP_EXPOSURES.csv mencatat posisi yang melewati rentang dan entry/exit baru selama rentang; tidak adanya posisi lama yang melintasi gap tidak membuktikan tidak ada sinyal/trade yang hilang. Perbandingan sampai September 2025 disertakan dalam before_2025_10_balance untuk periode pembanding tanpa gap besar ini.','', '## Old M1 pada tanggal identik','', '| Model M1/OHLC arsip | Saldo USD | Floating DD | PF | Basket |','|---|---:|---:|---:|---:|']
for v in m1rows:text.append(f"| {v['scenario']} | {v['ending_balance']:,.2f} | {v['floating_dd_pct']:.2f}% | {v['profit_factor']:.3f} | {v['baskets']} |")
text+=['','Kedua M1 controls memakai 2019-01-01–2026-03-31, $100, tanpa topup/prehistory tape. OHLC arsip dan spread model lama berbeda dari OHLC/spread bid/ask Dukascopy. Lintasan O-L-H-C/O-H-L-C dari hash timestamp adalah **sintetis, khusus pembanding**, bukan tick yang diperbaiki. Source, parameter, dan shared wallet sama, tetapi scheduler M1 lama memiliki asumsi berbeda, termasuk eksekusi hanya pada bar instrumen yang tersedia; hasil M1 bukan bukti validitas live.','', '## Isolasi kausal','', 'PAIRED_BEFORE_AFTER_ORDERS.csv dan PAIRED_OLD_M1_VS_TICK.csv memasangkan label basket timestamp/simbol/stage/sequence, mempertahankan intent yang tidak berpasangan dan ukuran yang berubah. CAUSAL_PATH_DIVERGENCES.json memuat divergensi awal harga, kehadiran order, volume serta alasan integer budget block. Delay 5s bukan perbaikan strategi; perubahan urutan fill/ACK, hasil basket, cooldown dan compounding menghasilkan jalur nonmonotonik.','', 'LOCKED_SCHEDULE_RESULTS.json mengunci jadwal request/exit dan volume B lama untuk mengukur perubahan quote/biaya tanpa compounding. Ini counterfactual aritmetis: tidak menguji ulang SL/TP atau membatasi margin, sehingga bukan saldo akun feasible atau strategi alternatif. Interaksi sinyal, layering, biaya, margin dan compounding tidak dijumlahkan seolah-olah efeknya aditif.','', '## Makro dan broker','', 'ARCHIVED_FLAGS memakai flag rekonstruksi dan synthetic snapshot permissions, bukan macro feed historis asli. VERIFIED_POINT_IN_TIME **NOT_AVAILABLE / NOT_RUN**; sumber primer yield/event telah diidentifikasi tetapi provenance per keputusan belum lengkap. STRICT_NO_SNAPSHOT dijalankan dan memblokir XAU dengan source gate asli.','', 'Tarif publik cTrader RAW saat audit $3/lot/sisi mendukung angka komisi model saat ini, tetapi tidak membuktikan tarif historis akun. Margin linear 1:200, kontrak/step/max volume, stopout 50%, fixed slippage, kedalaman likuiditas dan rounding platform tetap asumsi. Sumber primer: https://www.fpmarkets.com/ctrader-fees-and-charges/ ; https://alfred.stlouisfed.org/ ; https://www.bls.gov/schedule/2025/ .','', '## Kesimpulan validitas','', 'Keuntungan dapat bertahan pada sebagian model tick, tetapi klaim keuntungan besar yang telah diverifikasi konsisten untuk data lengkap, makro vintage, margin broker dan seluruh settlement native **belum terbukti**. Jangan menyamakan hasil ini dengan $90 juta 2016–Oktober 2026. Kepekaan biaya, delay, pembulatan volume dan compounding sangat besar; laporan ini tidak memilih parameter terbaik.','', 'Seluruh replay lengkap memiliki 87 bulan berurutan, tick count cocok dengan audit/overlay, kas direkonsiliasi dan posisi akhir nol. Keterbatasan no-lookahead: candle/signal cached closed-only memakai data <= waktu keputusan; fixture terpilih bukan sertifikasi semua startup/history/platform. Tidak ada order/live cBot/bridge/.env produksi yang diubah.']

if 'october_expected_open_hours' in summary:
 text+=['','## Cakupan perbaikan dua interval','',f"Oktober: {summary['october_verified_open_hours']} dari {summary['october_expected_open_hours']} arsip per jam pada jadwal open normal telah didekode. Jam open tersisa: {len(summary['october_missing_open_hours'])}. Tambahan per bulan: {summary['by_month']}. Jadwal weekend/maintenance ditandai sebagai asumsi kalender eksplisit, bukan disimpulkan dari error HTTP.",'','Kalibrasi overlap pada kedua batas gap: 40.518 tuple timestamp UTC milidetik + bid integer + ask integer cocok 100% dengan Parquet asli; skala 1000 terkonfirmasi. Volume tidak termasuk dalam perbandingan overlap, tetapi semua volume tambahan diperiksa finite/nonnegatif.','', 'Gap kedua 2025-12-30 23:59:59.455–2026-01-01 23:00:00.596 UTC juga mengandung tick 31 Desember yang hilang. EXTENDED_HOURS.json mencatat setiap jam asli yang berhasil/gagal/kosong; arsip kosong tidak diisi. OVERLAY_QA_XAUUSD_2025-10/12.json memuat audit tick setelah merge, gap tersisa dan sebaran spread per sesi. Kualitas seluruh dataset tetap PARTIAL karena kalender gap lain dan kondisi broker belum tersertifikasi.']
controls=r/'executed_controls'
if controls.exists():
 diff=json.load(open(controls/'differential/ENTRY_CYCLE_DIFFERENTIAL.json'));feedback=json.load(open(controls/'feedback-differential/EUR_FEEDBACK_DIFFERENTIAL.json'));fixtures=json.load(open(controls/'critical-fixtures/CRITICAL_FIXTURES.json'))
 assert len(diff)==32 and all(x['EqualOrders'] and x['AdapterBasket']==x['SourceBasket']for x in diff)
 assert feedback['Status']=='PASS'and feedback['SignalsCompared']==189 and all(x['Equal']for x in feedback['DispersedFeatureChecks'])and fixtures['Pass']
 json.dump({'entry_order_and_basket_fixtures':32,'entry_order_and_basket_passed':32,'years':[2019,2021,2023,2025],'starting_balances':[100,10000],'delays':[0,2],'critical_fixture_checks':fixtures['Checks'],'eur_virtual_feedback_signals':189,'eur_closed_m1_processed':feedback['ClosedM1Bars'],'dispersed_feature_checks':8,'full_native_certification':False},open(r/'DIFFERENTIAL_TEST_SUMMARY.json','w'),indent=2)
 tickm1=json.load(open(controls/'tick_m1_controls/results.json'));chain=[]
 for i,name in enumerate(['A_IDEAL_ARCHIVED_FLAGS','B_MODEL_2S_ARCHIVED_FLAGS']):
  a=m1['Reports'][i]['Summary'];b=tickm1['Reports'][i]['Summary'];c=before[name];d=groups['ADAPTER_CORRECTED'][name];e=groups['ADAPTER_AND_PARTIAL_DATA_REPAIR'].get(name,d)
  chain.append({'scenario':name,'old_feed_old_ohlc_engine':a['EndingBalance'],'tick_candles_old_ohlc_engine':b['EndingBalance'],'real_ticks_old_adapter':c['EndingBalance'],'real_ticks_corrected_adapter':d['EndingBalance'],'real_ticks_corrected_partial_overlay':e['EndingBalance']})
 pd.DataFrame(chain).to_csv(r/'CONTROLLED_M1_TICK_CHAIN.csv',index=False)
 text+=['','## Validasi tambahan yang benar-benar dijalankan','',f"32 fixture entry (XAU/EUR, 2019/2021/2023/2025, saldo $100/$10.000, delay 0/2s) cocok pada order dan seluruh basket setelah adapter diperbaiki. Tambahan {fixtures['Checks']} pemeriksaan kritis lulus; stage 1/2 EUR benar-benar mengisi 24/29 child pada fixture, bukan hanya stage kosong. Suite source lama 171+827+121 = 1.119 pemeriksaan dijalankan ulang di runner.",'',f"Virtual feedback EUR diperiksa dengan source AdvanceVirtual secara incremental pada {feedback['ClosedM1Bars']:,} candle closed dan seluruh 189 timestamp sinyal; fast/slow sama, tanpa perbedaan. Fitur/sinyal pada 8 tanggal yang tersebar juga cocok. Fixture memakai quote sintetis unit-test yang tidak pernah ditambahkan ke dataset historis.",'','## Rantai pembanding terkontrol','', '| Skenario | M1 feed lama / engine OHLC lama | M1 dari tick / engine OHLC lama | Tick / adapter lama | Tick / adapter dikoreksi |','|---|---:|---:|---:|---:|']
 for x in chain:text.append(f"| {x['scenario']} | ${x['old_feed_old_ohlc_engine']:,.2f} | ${x['tick_candles_old_ohlc_engine']:,.2f} | ${x['real_ticks_old_adapter']:,.2f} | ${x['real_ticks_corrected_adapter']:,.2f} |")
 text+=['','Kolom M1 dari tick memakai OHLC bid Dukascopy, spread XAU rerata tick per menit dan EUR spread tetap .00001 dari engine lama, serta flag arsip yang sama; bukan spread tick aktual. Perbandingan pertama menahan engine/lintasan OHLC, namun feed mengubah candle, sinyal, ATR, spread model terkait input, feedback dan compounding. Perbandingan berikutnya menahan candle sinyal tetapi sekaligus mengubah urutan intrabar/spread aktual/scheduler ke adapter tick lama. Karena beberapa faktor berubah bersama, selisih angka tidak boleh disebut efek kausal murni satu faktor. Pembanding locked schedule menahan jadwal/volume dan memisahkan pengaruh quote/biaya secara aritmetis; ia bukan replay strategi yang feasible.','', '## Batas cakupan diferensial','', 'Fixture recovery/reconnect/ACK terlambat menggunakan source asli dan fake broker. Tidak ada sertifikasi matching engine cTrader, queue jaringan asli, histori swap akun, partial fill, kedalaman pasar, startup native beserta seluruh histori, atau prioritas tick simultan antar-simbol. FULL_PARITY tetap tidak diklaim.']

 # Remove impossible entry-after-fixed-exit counterfactuals using a common cohort for ALL delays/costs.
 locked_csv=r/'locked_schedule/LOCKED_QUOTES_AND_PNL.csv'
 if locked_csv.exists():
  trades=before['B_MODEL_2S_ARCHIVED_FLAGS']['Ledger'];valid={p['Label']for p in trades if pd.Timestamp(p['ExitTime'])>=pd.Timestamp(p['EntryTime'])+pd.Timedelta(seconds=8)}
  ld=pd.read_csv(locked_csv);original=len(ld);ld=ld[ld.label.isin(valid)].copy()
  # An SL may fire on the FIRST tick among equal-millisecond timestamps. Recover the exact exit quote from the audited fill, avoiding later equal-time ticks.
  bylabel={p['Label']:p for p in trades}
  for idx,row in ld.iterrows():
   p=bylabel[row.label];side=1 if p['TradeType']==0 else -1;base_slip=.05 if p['SymbolName']=='XAUUSD'else .00001;fee_unit=.03 if p['SymbolName']=='XAUUSD'else .00003;volume=p['VolumeInUnits'];exit_quote=p['ExitPrice']+side*base_slip
   ld.at[idx,'exit']=exit_quote-side*base_slip*row.cost;ld.at[idx,'net']=side*volume*(ld.at[idx,'exit']-row.entry)-2*volume*fee_unit*row.cost
  ld.to_csv(locked_csv,index=False)
  expected=sum(p['NetProfit']for p in trades if p['Label']in valid);observed=float(ld[(ld.delay==2)&(ld.cost==1)].net.sum());exit_error=observed-expected
  assert abs(exit_error)<1e-6,('LOCKED_B_REFERENCE_RECONCILIATION',observed,expected,exit_error)
  json.dump({'status':'PASS','reference_delay':2,'reference_cost':1,'retained_positions':len(valid),'expected_original_ledger_pnl':expected,'recomputed_pnl':observed,'error_usd':exit_error,'equal_timestamp_exit_rule':'Use actual B exit quote reconstructed from fill plus adverse baseline slippage; never substitute later equal-timestamp tick.'},open(r/'LOCKED_REFERENCE_RECONCILIATION.json','w'),indent=2)
  sums=[]
  for (delay,cost),g in ld.groupby(['delay','cost']):
   gain=g.net.clip(lower=0).sum();loss=-g.net.clip(upper=0).sum();sums.append({'delay':int(delay),'cost':float(cost),'fixed_volume_total_pnl':float(g.net.sum()),'arithmetic_100_plus_pnl_NOT_feasible_equity':float(100+g.net.sum()),'position_profit_factor':float(gain/loss)if loss else None,'positions':len(g)})
  lp=r/'locked_schedule/LOCKED_SCHEDULE_RESULTS.json';lm=json.load(open(lp));lm['summaries']=sums;lm['exit_quote_source']='Exact audited B exit fill plus signed baseline slippage; preserves tick ordinal at equal timestamps. No later equal-time tick substituted.';lm['common_ordering_filter']='Same positions across all cases: exclude exits earlier than old B entry+8s (request+10s), preventing a delayed entry after fixed exit.';lm['excluded_short_or_rejected_positions']=len(trades)-len(valid);lm['original_positions']=len(trades);json.dump(lm,open(lp,'w'),indent=2)
  text+=['','## Locked schedule — hasil numerik','',f"Kohort bersama: {len(valid)} posisi; {len(trades)-len(valid)} posisi berumur pendek/rejected fill dikeluarkan dari SEMUA kasus agar entry setelah delay 10s tidak berada sesudah exit yang dikunci. Tidak ada perubahan spread asli.",'','| Delay entry | Biaya | PnL aritmetis volume tetap USD |','|---|---|---:|']
  for x in sums:text.append(f"| {x['delay']}s | {x['cost']}x | {x['fixed_volume_total_pnl']:,.2f} |")

 # Full position excursion fields already measured every tick; add explicit per-position R and WIB timestamps.
 for ledger in(r/'tables').rglob('POSITION_LEDGER.csv'):
  df=pd.read_csv(ledger)
  if df.empty:continue
  stop=df.Comment.str.split(';').str[4].astype(float);risk=(df.EntryPrice-stop).abs()*df.VolumeInUnits
  df['MFE_R_gross_position']=df.Mfe/risk;df['MAE_R_gross_position']=df.Mae/risk
  for k in ['EntryTime','ExitTime']:df[k+'_WIB']=pd.to_datetime(df[k],utc=True,format="mixed").dt.tz_convert('Asia/Jakarta').astype(str)
  df.to_csv(ledger,index=False)
 for path in [r/'engine/SourceTape.cs',r/'engine/ApiStubs.cs']:
  (r/(path.name+'.diff')).write_text(''.join(difflib.unified_diff((old/path.name).read_text().splitlines(True),path.read_text().splitlines(True),fromfile='8fdfe44/'+path.name,tofile='corrected/'+path.name)))


# Concrete early causal examples come from the completed corrected-adapter control, before the 2025 data repairs.
control=groups['ADAPTER_CORRECTED'];examples=[]
for name in ['B_MODEL_2S_ARCHIVED_FLAGS','D_5S_ARCHIVED_FLAGS']:
 d=control[name]
 examples.append({'scenario':name,'xau_june20':[{k:p[k]for k in ['Label','EntryTime','ExitTime','EntryPrice','ExitPrice','VolumeInUnits','NetProfit']}for p in d['Ledger']if p['EntryTime'].startswith('2019-06-20')],'eur_january23':[{k:p[k]for k in ['Label','EntryTime','ExitTime','EntryPrice','ExitPrice','VolumeInUnits','NetProfit']}for p in d['Ledger']if p['EntryTime'].startswith('2019-01-23')],'source_status_june20':[e for e in d['SourceStatusEvents']if e['At'].startswith('2019-06-20')],'january23_stage_status':[e for e in d['SourceStatusEvents']if e['At'].startswith('2019-01-23')]})
json.dump(examples,open(r/'CONCRETE_DELAY_SEQUENCE_CASES.json','w'),indent=2)
text+=['','## Contoh penyebab jalur delay berbeda','', 'Pada EUR 23 Januari 2019, model2s mengisi stage0 3child pukul08:30:06 UTC lalu stage2 5child pukul10:13:26; basket PnL $10,71. Model5s mengisi stage0 3child pukul08:30:15 dengan harga entry yang sama, tetapi tidak mendapat fill tambahan; PnL $3,21. Ini perbedaan layering meskipun harga awal sama.','', 'Pada XAU20 Juni2019, model2s fill1381,172 pukul12:45:04 lalu langsung ditutup pada tick/clock yang sama dengan status source BATCH_BUDGET_REJECTED_CLOSED; PnL−$0,467. Model5s fill1381,102 pukul12:45:10 diterima dan bertahan hingga19:59UTC, PnL+$8,086. Harga fill mengubah keputusan budget setelah fill dan jalur cooldown/ukuran berikutnya. Kasus ini tidak membuktikan delay5s selalu lebih baik; beberapa basket lain justru menang di2s dan rugi di5s.','', 'Koreksi pelaporan basket: field Entry pada JSON engine lama merekam entry dari child yang paling awal MASUK HISTORY, yang belum tentu child yang pertama dibuka. BASKET_LEDGER.csv kini memakai minimum EntryTime posisi, menyimpan SourceReportedEntry_FirstClosedChild untuk audit dan SignalUTC dari ID basket. Ini hanya koreksi label waktu laporan; PnL, source dan urutan transaksi tidak berubah.']
extra=r/'causal_extended'
if extra.exists():
 offsets=json.load(open(extra/'TIMESTAMP_OFFSET_DIFFERENTIAL.json'));feed=json.load(open(extra/'M1_FEED_COMPARISON.json'));signals=json.load(open(extra/'SIGNAL_FEED_DIFFERENCES.json'));clock=json.load(open(extra/'old_m1_timestamp_corrected_controls/results.json'));held=json.load(open(extra/'tick_m1_locked_spread_controls/results.json'))
 text+=['','## Temuan kritis: perbedaan label timestamp musiman','', 'Perbandingan seluruh OHLC mengungkap offset sistematis, bukan sekadar noise spread. Pada periode Europe/London DST, candle arsip lama berlabel T cocok dengan candle tick berlabel T−1 jam. Di luar DST, harga cocok pada label T. Pola ini ditemukan secara diferensial pada seluruh periode, bukan dipilih berdasarkan profit. Penyebab di sisi penyedia/pipeline lama belum tersertifikasi; persiapan lama menyatakan EST tetap dan menambah 5 jam, sehingga kontradiksi timestamp perlu ditandai. Waktu tick telah dikalibrasi dengan arsip BI5 asli.','', '| Simbol | Cocok T−1h saat DST | Cocok T di luar DST |','|---|---:|---:|']
 for symbol in ['XAUUSD','EURUSD']:
  a=next(x for x in offsets if x['symbol']==symbol and x['new_timestamp_minus_old_timestamp_hours']==-1);b=next(x for x in offsets if x['symbol']==symbol and x['new_timestamp_minus_old_timestamp_hours']==0);text.append(f"| {symbol} | {a['matches_during_London_DST']:,} | {b['matches_outside_London_DST']:,} |")
 text+=['','Ini dapat menggeser jam pasar entry dan sinkronisasi event macro satu jam pada model lama. Baseline tick tetap memakai jam UTC source frozen (EUR07–12, XAU12–17), tanpa optimasi atau pergeseran sesi. Data tick tidak diubah mengikuti timestamp lama. Sumber primer UTC Dukascopy: https://www.dukascopy.com/swiss/english/forex/jforex/forum/viewtopic.php?t=50132 .','', '## Perbandingan sinyal sebelum repair','', '| Simbol | Kandidat lama | Kandidat candle tick | Timestamp+arah sama | Hanya lama | Hanya tick |','|---|---:|---:|---:|---:|---:|']
 for a in signals:text.append(f"| {a['symbol']} | {a['old_raw_signals']} | {a['tick_derived_raw_signals']} | {a['same_timestamp_and_side']} | {a['old_only']} | {a['tick_only']} |")
 text+=['','Ini kandidat teknikal sebelum macro/posisi/cooldown/risk/margin, bukan basket dieksekusi. Perbandingan memakai candle tick sebelum dua gap diperbaiki, agar sama dengan laporan BEFORE.','', '## Kontrol OHLC tambahan yang telah dieksekusi','', '| Skenario | Lama, timestamp asli | Lama, timestamp dikoreksi | Candle tick, spread lama dikunci | Candle tick, spread XAU rerata tick |','|---|---:|---:|---:|---:|']
 extra_rows=[]
 for i,name in enumerate(['Ideal0s','RequestACK2s']):
  a=m1['Reports'][i]['Summary'];b=clock['Reports'][i]['Summary'];c=held['Reports'][i]['Summary'];d=tickm1['Reports'][i]['Summary'];text.append(f"| {name} | ${a['EndingBalance']:,.2f} | ${b['EndingBalance']:,.2f} | ${c['EndingBalance']:,.2f} | ${d['EndingBalance']:,.2f} |")
  extra_rows.append({'scenario':name,'old_original_timestamp':a['EndingBalance'],'old_timestamp_remapped':b['EndingBalance'],'tick_candles_original_spread_held':c['EndingBalance'],'tick_candles_xau_mean_tick_spread':d['EndingBalance']})
 pd.DataFrame(extra_rows).to_csv(r/'EXTENDED_CONTROLLED_OHLC_COMPARISON.csv',index=False)
 text+=['','Semua kontrol mulai $100 pada 2019-01-01 dan berhenti 2026-03-31. Koreksi timestamp mengurangi satu jam hanya saat DST London, mempertahankan OHLC dan source. Spread/roll/flag arsip XAU diambil asof UTC yang dikoreksi, bukan dari masa depan. Fungsi hash lintasan OHLC lama tetap sama dan menerima timestamp baru, sehingga pemilihan urutan OHLC sintetis juga dapat berubah. Angka ini bukan efek waktu murni yang aditif atau bukti feed macro vintage.','', 'Kontrol candle tick dengan spread lama mempertahankan seri spread XAU arsip secara asof; 109.448 menit yang tidak ada di arsip memakai nilai model terakhir, maksimum umur266.460 detik. Ini interpolasi TIDAK dilakukan pada tick atau harga: hanya carry-forward asumsi spread pada eksperimen OHLC terpisah. Kebijakan dan checksum input/output ada di SPREAD_HOLD_POLICY.json. EUR engine OHLC tetap memakai spread .00001; engine tick memakai bid/ask aktual.','', 'Temuan ini menunjukkan bahwa $90 juta lama tidak boleh dijelaskan sebagai efek resolusi M1 versus tick saja. Label waktu, cakupan candle, sinyal, spread, eksekusi, pembulatan ukuran dan compounding berubah bersama. Hasil old-M1 mentah harus dianggap tidak tervalidasi sebagai replay UTC yang konsisten.']
 # Full post-audit metrics in the report as well as machine-readable CSVs.
 text+=['','## Metrik setelah koreksi terakhir','', '| Skenario | PF basket | Win rate | Basket | Posisi broker tertutup | PnL XAU USD | PnL EUR USD |','|---|---:|---:|---:|---:|---:|---:|']
 for a in rows:
  if a['mode']=='ADAPTER_AND_PARTIAL_DATA_REPAIR':text.append(f"| {a['scenario']} | {a['profit_factor']:.3f} | {a['win_rate_basket_pct']:.2f}% | {a['baskets']} | {a['broker_positions']} | {a['xau_pnl']:,.2f} | {a['eur_pnl']:,.2f} |")

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
