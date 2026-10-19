import pathlib,json,csv,zipfile,hashlib,io,shutil,os
R=pathlib.Path.cwd();O=R/'final_review';O.mkdir(exist_ok=True)
def sha(p):return hashlib.file_digest(open(p,'rb'),'sha256').hexdigest()
def verify(p,m):
 with zipfile.ZipFile(p) as z:
  assert z.testzip() is None
  for r in csv.DictReader(io.StringIO(z.read(m).decode())):
   b=z.read(r['path']);assert hashlib.sha256(b).hexdigest()==r['sha256'] and len(b)==int(r['bytes'])
ten=R/'newrun/RIZAN_BTC_TEN_MILLION_REVIEW.zip';legacy=R/'legacyrun/RIZAN_BTC_DD60_LEGACY_AUDIT.zip'
verify(ten,'MANIFEST_REVIEW.csv');verify(legacy,'MANIFEST_SHA256.csv')
def contents(p,j,c):
 with zipfile.ZipFile(p) as z:return json.loads(z.read(j)),list(csv.DictReader(io.StringIO(z.read(c).decode())))
n,ns=contents(ten,'TEN_MILLION_STATUS.json','ALL_SELECTED_STRESS.csv')
l,ls=contents(legacy,'DD60_LEGACY_STATUS.json','ALL_SELECTED_STRESS.csv')
assert n['unique_configuration_evaluations']==10000000 and l['prior_rows_screened']==6000000
new=n['leaders']['DD_LT60'];old=next(x for x in l['leaders'] if x['criterion']=='DD_LT60')
newwins=new['equity']>old['equity'];champ=new if newwins else old
assert champ['floating_dd']<60 and champ['trades']>=30
cases=[x for x in (ns if newwins else ls) if int(x['id'])==int(champ['id']) and (newwins or x['variant']==champ['variant'])]
def money(x):return '$'+f'{float(x):,.2f}'
def pct(x):return f'{float(x):.2f}%'
def table(h,rows):return '| '+' | '.join(h)+' |\n|'+'|'.join(['---']*len(h))+'|\n'+''.join('| '+' | '.join(str(x) for x in r)+' |\n' for r in rows)+'\n'
def row(label,r):return [label,int(r['id']),money(r['equity']),pct(r['floating_dd']),f"{r['pf']:.3f}",int(r['trades']),pct(100*r['wins']/r['trades'])]
rows=[row('10 juta komposit baru',new),row('Legacy + fine sizing DD<60',old)]
backup=next((x for x in l['leaders'] if x['criterion']=='DD_LT50_BACKUP'),None)
if backup:rows.append(row('Legacy + fine sizing DD<50',backup))
report='# BTC — saldo tertinggi dengan floating DD <60%\n\n'
report+='**Hasil tertinggi dari ruang uji tahap ini: '+money(champ['equity'])+', floating DD '+pct(champ['floating_dd'])+'.** Modal awal $100 tanpa top-up, BTC standalone,1 Januari2019–15 Oktober2026.\n\n'
if champ['equity']<1000000:report+='Saldo $1 juta dengan DD<60% belum ditemukan pada ruang uji ini. Baseline692365 $1.005.025,52/DD67,92% tidak memenuhi batas.\n\n'
report+=table(['Kelompok','ID','Saldo akhir','Floating DD','PF','Basket','Win rate'],rows)
report+='## Hitungan penelitian\n\nTepat10.000.000 konfigurasi komposit unik berasal dari1.000.000 definisi resep sinyal, masing-masing10 konfigurasi eksekusi. Resep dibentuk dari12keluarga dasar, bukan1juta konsep fundamental independen. '+str(n['zero_accepted_signal_recipes'])+' resep tidak menghasilkan sinyal diterima; aturan berbeda juga dapat menghasilkan sinyal identik pada sampel. Kandidat utama disaring minimum30basket.\n\n'
report+='Secara terpisah,6.000.000 baris hasil lama ditinjau ulang pada batasDD60, kemudian '+str(l['targeted_sizing_evaluations'])+' kasus fine sizing baru dijalankan. Kasus sizing dideduplikasi per source universe; ini bukan klaim unik global. Enam juta hasil lama tidak dihitung sebagai replay baru. Hasil tertinggi bukan bukti optimum global.\n\n'
report+='## Konfigurasi hasil tertinggi\n\n'
params=['variant','family','tf_minutes','lookback','threshold_index','trend_filter','session_utc','side','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']
report+=table(['Parameter','Nilai'],[[p,champ[p]] for p in params if p in champ])
report+='Sisi0=BUY+SELL,1=BUY,2=SELL. TrendH4 0=off,1=searah,2=berlawanan. SesiUTC 0=semua,1=00–08,2=07–16,3=12–21,akhir eksklusif. Risk/margin adalah budgetmodel, bukan kerugian pasti atau alokasi portofolio yang telah diuji. Layered entry memakai40%riskbudget awal lalu depthadds sesuai source.\n\n'
report+='## Sensitivitas parameter terkunci\n\n'
report+=table(['Kasus','Saldo akhir','Floating DD','Basket','Add','Skip','Model stop-out'],[[x['case'],money(x['equity']),pct(x['floating_dd']),x['trades'],x['adds'],x['skips'],x['liquidations']] for x in cases])
report+='Cost1,5/2 mengalikan fee/slip/financing, bukan spread. Delay minimum1M1 bukan2detik. NO_ADDS memakai100%initialrisk sehingga bukan ablation volume awal terkunci. Segmen restart100 tidak dijumlahkan dan bukan OOS tak tersentuh. DD0% dari nol transaksi tidak menunjukkan ketahanan.\n\n'
report+='## Hasil yang ditolak dan validitas\n\n'
u=n['leaders']['UNCONSTRAINED'];report+='Komposit tanpa batasDD mencapai '+money(u['equity'])+'/DD'+pct(u['floating_dd'])+' dan ditolak untuk targetDD<60. Juara komposit yang lolos nominal '+money(new['equity'])+'/DD'+pct(new['floating_dd'])+'; biaya2× menghasilkan $8.036,57/DD61,43%, dan delay1M1 DD60,56%. Menambah filter belum mengungguli kandidat lama.\n\n'
report+='Seluruh rentang dipakai untuk seleksi setelah banyak percobaan: optimasi historis ini rentan overfit dan tidak menjamin profit atau DD masa depan. Baseline692365 direproduksi sebelum penelitian; sembilan fixture engine lulus. Semua ID10juta lengkap/disjoint,10tuples per resep unik,source/inputhash sama. Seluruh kandidat terpilih direplay ulang dan semua ledger kasus direkonsiliasi independen dari harga,volume,fee,financing dan kas. Sebanyak28kandidat komposit lolos future-price prefix invariance pada15Mei2023 13:30UTC. Perturbasi hanya di memori uji, tidak disimpan sebagai data pasar. Semua seedlegacy direproduksi sebelum sizing.\n\n'
report+='Data **officialBitstampOHLC M1, bukan tick bid/ask broker**. Leverage10 hipotesis,min/step0,01BTC,max100BTC;spread5bp,slip1bp/sisi,fee5bp/sisi,financingdebit3bpnotional/hari. KontrakRAW/leverage tiers/swap historis broker belum dibuktikan. Sinyal memakai candleclosed,entrynextopen;trendH4/D1closed;warmup source tetap. Tidak ada makro historis sintetis.\n\n'
report+='Stop-first pada bar ambigu,gapSL pada open lebih buruk. DD diperiksa setiapM1,grafik snapshotperjam. PrioritasSL/TP sebelum fallbackstopout dan capital-floorpermanen source lama tetap. ACK,reconnect,partialfill,depth dan spesifikasi broker native belum divalidasi. Tidak ada top-up,reset,DDclamp atau stop setelah target.\n\n'
report+='**BTC belum diuji dengan equity/margin bersama XAU–EUR.** Saldo standalone tidak dijumlahkan. cBotlive/frozenXAU-EUR,bridge dan envproduksi tidak diubah;tidak ada order atau merge main.\n\n'
report+='## Artefak\n\nRun10juta: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39251677841\n\nRunlegacy: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39252456294\n\nCommit10juta: '+n['source_commit']+'\n\nCommitlegacy:0d6c1065aff3cfb6c838372dada44e097f193b7e\n\n'
report+='CSVinputSHA256:c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504.\n\nVPS10juta:/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/btc-ten-million-dd60-2019-oct2026/run-39251677841/\n\nVPSlegacy:/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/btc-dd60-legacy-2019-oct2026/run-39252456294/\n\n'
report+='FINAL_REVIEW memuat laporan ini,ZIPreview10juta,danZIPlegacy lengkap(source,config,ledger,rekonsiliasi,bulanan/tahunan,grafik,manifest). Seluruh10tabel million-row berada di RIZAN_BTC_TEN_MILLION_COMPLETE.zip pada Actions/VPS10juta,SHA256efd72e0ba283a726d99f1186a57dd5a4a8aaea83c7853f1a3cc596410ff91a91. Review tidak menduplikasi10juta tabel/curveCSV besar. Semua manifest telah diverifikasi ulang.\n'
(O/'LAPORAN_BTC_DD60_FINAL.md').write_text(report)
shutil.copy2(ten,O/ten.name);shutil.copy2(legacy,O/legacy.name)
status={'overall_champion_origin':'COMPOSITE_10M' if newwins else 'LEGACY_FINE_SIZING','overall_champion':champ,'ten_status':n,'legacy_status':l,'finalizer_commit':os.environ['GITHUB_SHA'],'source_review_sha256':sha(ten),'source_legacy_sha256':sha(legacy)}
(O/'FINAL_STATUS.json').write_text(json.dumps(status,indent=2,allow_nan=False))
with open(O/'MANIFEST_SHA256.csv','w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(O.iterdir()):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([p.name,sha(p),p.stat().st_size])
with zipfile.ZipFile(O/'RIZAN_BTC_DD60_FINAL_REVIEW.zip','w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
 for p in O.iterdir():
  if p.is_file() and p.name!='RIZAN_BTC_DD60_FINAL_REVIEW.zip':z.write(p,p.name)
with zipfile.ZipFile(O/'RIZAN_BTC_DD60_FINAL_REVIEW.zip') as z:assert z.testzip() is None
(O/'PACKAGE_SHA256.txt').write_text(sha(O/'RIZAN_BTC_DD60_FINAL_REVIEW.zip')+'  RIZAN_BTC_DD60_FINAL_REVIEW.zip\n')
print(report,flush=True)
