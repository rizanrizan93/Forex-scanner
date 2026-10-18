"""Independent accounting checks and Indonesian review report; no strategy mutation."""
from pathlib import Path
import json,csv,hashlib,zipfile,sys,math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

root=Path(sys.argv[1]);engine_commit=sys.argv[2];run_id=int(sys.argv[3]);audit_run=39136481123
files=sorted((root/'replay_results').glob('*.json'));reports={}
for p in files:
 d=json.loads(p.read_text())
 if 'Config' in d:reports[d['Config']['Name']]=d
assert len(reports)==8
quality=json.loads((root/'data_audit/data_quality.json').read_text());fresh=json.loads((root/'data_audit/fresh_vps_checksums.json').read_text())
assert quality['processed_files']==174 and len(fresh)==174
expected={f'{s}_{y}-{m:02}.parquet' for y in range(2019,2027) for m in range(1,13) if (y,m)<=(2026,3) for s in ['XAUUSD','EURUSD']}
assert {x['file'] for x in quality['files']}==expected
fresh_sha={x['file']:x['sha256'] for x in fresh}
assert all(fresh_sha[x['file']]==x['sha256'] for x in quality['files'])
checks=[]
for name,d in reports.items():
 assert d['ProcessedThrough']=='2026-03' and len(d['Monthly'])==87
 assert [x['Month'] for x in d['Monthly']]==[f'{y}-{m:02}' for y in range(2019,2027) for m in range(1,13) if (y,m)<=(2026,3)]
 assert d['TotalTicks']==quality['total_ticks']
 error=100+sum(h['NetProfit'] for h in d['Ledger'])-d['EndingBalance']
 assert d['OpenPositions']==0 and abs(error)<max(.00001,abs(d['EndingBalance'])*1e-10)
 positions=[h['PositionId'] for h in d['Ledger']];assert len(positions)==len(set(positions))
 grouped={}
 for h in d['Ledger']:
  key='|'.join(h['Label'].split('|')[:2]);grouped[key]=grouped.get(key,0)+h['NetProfit']
 assert len(grouped)==d['TotalBaskets']
 assert all(abs(grouped[b['Id']]-b['Pnl'])<max(.00001,abs(b['Pnl'])*1e-10) for b in d['Baskets'])
 gains=sum(max(0,v) for v in grouped.values());losses=sum(max(0,-v) for v in grouped.values())
 assert (losses==0 and d['ProfitFactor'] is None) or (losses>0 and abs(gains/losses-d['ProfitFactor'])<1e-9)
 source_states=d['TerminalStates'];settled=all(x['Checkpoint']['Basket'] is None and x['Checkpoint']['PendingLabel']=='' and x['PendingAcks']==0 and not x['Checkpoint']['Quarantined'] for x in source_states)
 assert settled,(name,'UNRESOLVED_TERMINAL_SETTLEMENT')
 solo=name.startswith('E_')
 if solo:assert not any(h['SymbolName']=='EURUSD' for h in d['Ledger'])
 if name.startswith('STRICT'):assert not any(h['SymbolName']=='XAUUSD' for h in d['Ledger'])
 checks.append({'scenario':name,'period_complete':True,'tick_count_equal_to_audit':True,'cash_error_usd':error,'unique_broker_position_ids':True,'source_baskets_settled':settled,'open_positions':d['OpenPositions']})
 for h in d['Ledger']:
  try:
   stop=float(h['Comment'].split(';')[4]);sign=1 if h['TradeType']==0 else -1;risk=sign*(h['EntryPrice']-stop)*h['VolumeInUnits']
   h['InitialRiskUsdFromSourceComment']=risk if risk>0 else None;h['MFE_R']=h['Mfe']/risk if risk>0 else None;h['MAE_R']=h['Mae']/risk if risk>0 else None
  except Exception:h['InitialRiskUsdFromSourceComment']=h['MFE_R']=h['MAE_R']=None
 out=root/'replay_results'/name;out.mkdir(exist_ok=True)
 with (out/'position_ledger_with_excursions.csv').open('w',newline='') as f:
  if d['Ledger']:
   w=csv.DictWriter(f,fieldnames=d['Ledger'][0].keys());w.writeheader();w.writerows(d['Ledger'])
 q=d['EquityCurve'];ts=[datetime.fromisoformat(x['At'].replace('Z','+00:00')) for x in q];equity=np.array([x['Equity'] for x in q]);peak=np.maximum.accumulate(np.r_[100,equity])[1:];drawdown=100*(peak-equity)/peak
 fig,ax=plt.subplots(2,1,figsize=(11,7),sharex=True);ax[0].plot(ts,equity,lw=.8);ax[0].set_title(name+' — PARTIAL PARITY');ax[0].set_ylabel('Equity USD');ax[0].grid(alpha=.2);ax[1].fill_between(ts,drawdown,color='#b94453',alpha=.5);ax[1].set_ylabel('DD sampled (%)');ax[1].invert_yaxis();fig.tight_layout();fig.savefig(out/'equity_drawdown.png',dpi=150);plt.close(fig)
(root/'INDEPENDENT_RECONCILIATION.json').write_text(json.dumps(checks,indent=2))
order=[('A_IDEAL_ARCHIVED_FLAGS','A Ideal'),('B_MODEL_2S_ARCHIVED_FLAGS','B Model 2s'),('C_COST1_5_ARCHIVED_FLAGS','C Biaya 1,5x'),('C_COST2_ARCHIVED_FLAGS','C Biaya 2x'),('D_5S_ARCHIVED_FLAGS','D Delay 5s'),('D_10S_ARCHIVED_FLAGS','D Delay 10s')]
text=['# RIZAN — Hasil audit tick dan strategi frozen','','**Status: PARTIAL_PARITY. Full frozen parity belum terbukti.**','','Seluruh eksperimen di bawah memproses 1 Januari 2019–31 Maret 2026, modal awal $100, tanpa top-up, leverage model 1:200. XAU dan EUR berbagi satu wallet, equity, margin, dan batas risiko. Source strategi tidak dioptimasi.','',
f"Sebanyak **174 file / {quality['total_ticks']:,} tick per skenario** telah didekode dan diperiksa. SHA-256 file di runner sama dengan hash yang dihitung ulang dari file VPS. Timestamp duplikat dipertahankan; tidak ada tick sintetis atau interpolasi.",'',
'Hasil gabungan memakai **flag macro rekonstruksi dari penelitian lama**. Ini eksperimen terpisah dari kontrol STRICT tanpa snapshot macro. Tarif biaya adalah model arsip; belum membuktikan tarif akun RAW historis pengguna. Adapter menjalankan metode internal source, bukan seluruh lifecycle platform cTrader. Karena itu angka di bawah bukan hasil full frozen parity atau proyeksi live.','',
'## Perbandingan skenario gabungan','','| Metrik | '+' | '.join(label for _,label in order)+' |','|---|'+'---:|'*len(order)]
metrics=[('Saldo akhir USD',lambda d:f"{d['EndingBalance']:,.2f}"),('Net profit USD',lambda d:f"{d['NetProfit']:,.2f}"),('Maximum floating DD',lambda d:f"{d['MaximumFloatingDDPct']:.2f}%"),('Maximum balance DD',lambda d:f"{d['MaximumBalanceDDPct']:.2f}%"),('Profit factor',lambda d:f"{d['ProfitFactor']:.3f}" if d['ProfitFactor'] is not None else 'n/a'),('Win rate basket',lambda d:f"{d['WinRate']:.2f}%"),('Total basket terealisasi',lambda d:str(d['TotalBaskets'])),('Total child ekuivalen 0,01 lot',lambda d:str(d['TotalChildOrders'])),('Request broker',lambda d:str(d['BrokerRequests'])),('Basket/bulan',lambda d:f"{d['TotalBaskets']/87:.2f}"),('Broker margin rejection',lambda d:str(d['MarginRejects'])),('Portfolio budget blocks',lambda d:str(d['PortfolioBudgetBlocks'])),('Stop-out model',lambda d:str(len(d['Liquidations'])))]
for label,fn in metrics:text.append('| '+label+' | '+' | '.join(fn(reports[n]) for n,_ in order)+' |')
text+=['','Delay B berarti request 2 detik dan ACK 2 detik. D memakai request dan ACK masing-masing 5/10 detik. Stress biaya menaikkan komisi dan slippage model; spread bid/ask asli tetap. Stop-out memakai asumsi margin level 50%; riwayat margin call dan aturan broker historis belum tersertifikasi. Child ekuivalen menghitung volume fill tertutup/.01 lot, termasuk fill yang ditolak setelah budget recheck; berbeda dari jumlah request broker.','',
'## Pembanding terpisah','','| Eksperimen | Saldo akhir USD | Floating DD | Basket |','|---|---:|---:|---:|']
for n,label in [('E_XAU_ONLY_ARCHIVED_FLAGS','XAU standalone + flag arsip'),('STRICT_MISSING_MACRO_XAU_BLOCKED','Snapshot macro tidak tersedia; XAU terblokir')]:
 d=reports[n];text.append(f"| {label} | {d['EndingBalance']:,.2f} | {d['MaximumFloatingDDPct']:.2f}% | {d['TotalBaskets']} |")
text+=['','Kedua pembanding mulai lagi dari $100. Kontrol STRICT bukan XAU teknikal yang macro gate-nya dimatikan. Source XAU benar-benar menolak entry tanpa snapshot.','',
'## Kualitas data','','| Simbol | Tick | Timestamp duplikat | Timestamp mundur | Bid > ask | Gap >5 menit perlu review |','|---|---:|---:|---:|---:|---:|']
for s in ['XAUUSD','EURUSD']:
 a=[x for x in quality['files'] if x['file'].startswith(s)];text.append(f"| {s} | {sum(x['ticks'] for x in a):,} | {sum(x['duplicate_timestamps'] for x in a):,} | {sum(x['backward_timestamps'] for x in a)} | {sum(x['invalid_bid_ask'] for x in a)} | {sum(x['unexplained_gaps'] for x in a):,} |")
text+=['','Gap diklasifikasikan sebagai kandidat weekend/libur, maintenance emas, atau belum terjelaskan. Kalender pasar/libur lengkap belum menyertifikasi semua gap. Baca `data_audit/gaps.json`; jangan menyamakan seluruh gap dengan data rusak atau menganggapnya telah ditutup. Distribusi spread per file dan sesi WIB tersedia di data_quality.json.','',
'## Kinerja bulanan, tahunan, kontribusi dan layering','']
for name,label in order+[('E_XAU_ONLY_ARCHIVED_FLAGS','XAU standalone'),('STRICT_MISSING_MACRO_XAU_BLOCKED','STRICT')]:
 d=reports[name];ms=d['Monthly'];best=max(ms,key=lambda x:x['NetProfit']);worst=min(ms,key=lambda x:x['NetProfit']);contrib={s:sum(h['NetProfit'] for h in d['Ledger'] if h['SymbolName']==s) for s in ['XAUUSD','EURUSD']}
 text += [f"### {label}",'',f"Bulan terbaik: {best['Month']} **${best['NetProfit']:,.2f}**; terburuk: {worst['Month']} **${worst['NetProfit']:,.2f}**. PnL XAU **${contrib['XAUUSD']:,.2f}**, EUR **${contrib['EURUSD']:,.2f}**. Ini atribusi nominal; keuntungan satu leg juga membiayai ukuran leg lain.",'','| Stage terdalam terisi | Basket | PnL USD |','|---|---:|---:|']
 for stage in range(3):
  bs=[b for b in d['Baskets'] if b['MaxStage']==stage];text.append(f"| {stage} | {len(bs)} | {sum(b['Pnl'] for b in bs):,.2f} |")
 text+=['',f"Komisi posisi tertutup ${sum(h['TotalCommission'] for h in d['Ledger']):,.2f}; slippage model ${sum(h.get('SlippageDollars',0) for h in d['Ledger']):,.2f}; biaya spread relatif benchmark mid ${sum(h.get('SpreadVsMidDollars',0) for h in d['Ledger']):,.2f}. Komponen ini sudah tercermin pada harga/PnL, tidak dibebankan ulang.",'']
 for k,title in [('MFE_R','MFE'),('MAE_R','MAE')]:
  v=[h[k] for h in d['Ledger'] if h[k] is not None];text.append(f"{title} per posisi broker, relatif risiko stop awal: median {np.median(v):.3f}R, rerata {np.mean(v):.3f}R." if v else f'{title}: tidak ada posisi yang memenuhi definisi risiko awal.')
 text+=['','MFE/MAE adalah gross excursion tiap posisi batch, bukan gabungan extrema basket yang terjadi serentak. Layering di atas bersifat deskriptif, bukan bukti kausal bahwa menambah layer meningkatkan hasil. Annual/monthly CSV dan ledger lengkap disertakan.','']
text+=['## Rekonsiliasi dan batas kesimpulan','',
'Seluruh kas direkonsiliasi ulang dari ledger independen. Tidak ada posisi akhir tersisa, ID posisi unik, basket source telah settled, pending label kosong dan ACK queue kosong. Bukti ada pada INDEPENDENT_RECONCILIATION.json dan TerminalStates di tiap hasil. Pemeriksaan source dan unit test mencakup 1.119 assert; pilot Q1 dibandingkan lagi dengan tiga bulan awal run penuh. Pemeriksaan causal signal/confirmation juga tercatat di log. Ini tidak menggantikan validasi lifecycle native lengkap.','',
'Candle berasal dari BID asli dan hanya candle closed yang digunakan untuk sinyal. Virtual feedback EUR tetap mengikuti algoritme M1/stop-first asli frozen; tidak diubah menjadi feedback tick baru. Tidak ada warmup tick sebelum 2019. Counterfactual feedback, startup history, fixture recovery/bridge, margin linear dan keterbatasan vintage macro dijelaskan lebih rinci di REPORT.md.','',
'Angka lama sekitar $90,73 juta mencakup 2016–Oktober 2026, input OHLC sintetis, prehistory dan jalur compounding berbeda. Hasil mulai 2019 ini tidak mengisolasi penyebab perbedaan menjadi satu faktor. Jangan memakai selisihnya sebagai estimasi pengaruh tick saja atau target return live.','',
f"Engine commit: `{engine_commit}`. [Actions replay](https://github.com/rizanrizan93/Forex-scanner/actions/runs/{run_id}); [Actions data audit](https://github.com/rizanrizan93/Forex-scanner/actions/runs/{audit_run}). Tidak ada perubahan cBot live, broker order, restart bridge, perubahan .env produksi, atau merge main dalam pekerjaan ini."]
(root/'LAPORAN_RIZAN_TICK_2019_2026.md').write_text('\n'.join(text))
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.suffix not in ['.tgz','.zip','.dll'] and p.name not in ['MANIFEST_SHA256.json','month.bin']}
(root/'MANIFEST_SHA256.json').write_text(json.dumps(manifest,indent=2))
with zipfile.ZipFile(root/'RIZAN_FROZEN_TICK_AUDIT.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in root.rglob('*'):
  if p.is_file() and p.name!='month.bin' and p.suffix not in ['.tgz','.zip','.dll']:z.write(p,str(p.relative_to(root)))
print(json.dumps({'status':'PARTIAL_PARITY','independent_checks':checks,'zip_bytes':(root/'RIZAN_FROZEN_TICK_AUDIT.zip').stat().st_size},indent=2))
