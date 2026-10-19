# BTC — saldo tertinggi dengan floating DD <60%

**Hasil tertinggi dari ruang uji tahap ini: $955,554.24, floating DD 59.93%.** Modal awal $100 tanpa top-up, BTC standalone,1 Januari2019–15 Oktober2026.

Saldo $1 juta dengan DD<60% belum ditemukan pada ruang uji ini. Baseline692365 $1.005.025,52/DD67,92% tidak memenuhi batas.

| Kelompok | ID | Saldo akhir | Floating DD | PF | Basket | Win rate |
|---|---|---|---|---|---|---|
| 10 juta komposit baru | 5937693 | $32,278.10 | 58.93% | 1.386 | 265 | 41.13% |
| Legacy + fine sizing DD<60 | 1004209 | $955,554.24 | 59.93% | 1.408 | 63 | 55.56% |
| Legacy + fine sizing DD<50 | 1003442 | $56,582.38 | 46.75% | 2.297 | 88 | 46.59% |

## Hitungan penelitian

Tepat10.000.000 konfigurasi komposit unik berasal dari1.000.000 definisi resep sinyal, masing-masing10 konfigurasi eksekusi. Resep dibentuk dari12keluarga dasar, bukan1juta konsep fundamental independen. 542005 resep tidak menghasilkan sinyal diterima; aturan berbeda juga dapat menghasilkan sinyal identik pada sampel. Kandidat utama disaring minimum30basket.

Secara terpisah,6.000.000 baris hasil lama ditinjau ulang pada batasDD60, kemudian 157320 kasus fine sizing baru dijalankan. Kasus sizing dideduplikasi per source universe; ini bukan klaim unik global. Enam juta hasil lama tidak dihitung sebagai replay baru. Hasil tertinggi bukan bukti optimum global.

## Konfigurasi hasil tertinggi

| Parameter | Nilai |
|---|---|
| variant | PREVIOUS_AGGRESSIVE |
| family | displacement_follow |
| tf_minutes | 240 |
| lookback | 8 |
| threshold_index | 2 |
| trend_filter | 1 |
| session_utc | 1 |
| side | 1 |
| stop_atr | 2.0 |
| tp_R | 12 |
| hold_bars | 32 |
| risk | 0.2099999999999999 |
| margin_fraction | 0.95 |
| add_stages | 0 |
| breakeven_R | 0 |

Sisi0=BUY+SELL,1=BUY,2=SELL. TrendH4 0=off,1=searah,2=berlawanan. SesiUTC 0=semua,1=00–08,2=07–16,3=12–21,akhir eksklusif. Risk/margin adalah budgetmodel, bukan kerugian pasti atau alokasi portofolio yang telah diuji. Layered entry memakai40%riskbudget awal lalu depthadds sesuai source.

## Sensitivitas parameter terkunci

| Kasus | Saldo akhir | Floating DD | Basket | Add | Skip | Model stop-out |
|---|---|---|---|---|---|---|
| BASE | $955,554.24 | 59.93% | 63 | 0 | 0 | 0 |
| COST1_5 | $383,319.93 | 76.36% | 63 | 0 | 0 | 0 |
| COST2 | $211,576.31 | 79.33% | 63 | 0 | 0 | 0 |
| DELAY_NEXT_M1 | $224,606.68 | 76.48% | 64 | 0 | 0 | 0 |
| NO_ADDS | $955,554.24 | 59.93% | 63 | 0 | 0 | 0 |
| LEVERAGE2 | $2,176.02 | 24.84% | 63 | 0 | 0 | 0 |
| LEVERAGE5 | $62,813.59 | 53.04% | 63 | 0 | 0 | 0 |
| TRAIN_2019_2022 | $23,052.86 | 58.86% | 29 | 0 | 0 | 0 |
| VALID_2023_2024 | $3,312.87 | 45.04% | 21 | 0 | 0 | 0 |
| TEST_2025_OCT2026 | $72.55 | 42.11% | 2 | 0 | 17 | 0 |

Cost1,5/2 mengalikan fee/slip/financing, bukan spread. Delay minimum1M1 bukan2detik. NO_ADDS memakai100%initialrisk sehingga bukan ablation volume awal terkunci. Segmen restart100 tidak dijumlahkan dan bukan OOS tak tersentuh. DD0% dari nol transaksi tidak menunjukkan ketahanan.

## Kepekaan lokal kandidat nominal

Checkpoint fine-sizing run39252456294 sudah lengkap157.320baris saat pemeriksa BASE lama gagal karena ikut membaca ledger stres. Audit dipulihkan dari CSV dengan SHA256identik7d97759d0bc498d64e9c81380a0526a7a4b2ca7be1093eb55cf5baa8fadb0e4e; toleransi dan engine keuangan tidak dilonggarkan. Semua seed dan ledger diperiksa kembali. Label statistik universe juga dirapikan dari DD50/55 lama menjadi DD60 yang benar.

Kandidat PREVIOUS_AGGRESSIVE1004209 berada dekat batas: risk21%,margin95% menghasilkan $955.554,24/DD59,9260%. Pada margin95%,risk20% menghasilkan $745.975,27/DD65,6173% dan risk22% $1.204.245,78/DD60,4464%. Pada risk21%,margin94% menghasilkan $887.361,13/DD61,6903%. Perubahan sizing kecil mengubah jalur pembulatan volume dan compounding; kelolosan DD60 ini rapuh, bukan bukti stabilitas. Tabel ini berasal dari grid yang sama, bukan forward/OOS.

## Hasil yang ditolak dan validitas

Komposit tanpa batasDD mencapai $2,369,723.36/DD89.87% dan ditolak untuk targetDD<60. Juara komposit yang lolos nominal $32,278.10/DD58.93%; biaya2× menghasilkan $8.036,57/DD61,43%, dan delay1M1 DD60,56%. Menambah filter belum mengungguli kandidat lama.

Seluruh rentang dipakai untuk seleksi setelah banyak percobaan: optimasi historis ini rentan overfit dan tidak menjamin profit atau DD masa depan. Baseline692365 direproduksi sebelum penelitian; sembilan fixture engine lulus. Semua ID10juta lengkap/disjoint,10tuples per resep unik,source/inputhash sama. Seluruh kandidat terpilih direplay ulang dan semua ledger kasus direkonsiliasi independen dari harga,volume,fee,financing dan kas. Sebanyak28kandidat komposit lolos future-price prefix invariance pada15Mei2023 13:30UTC. Perturbasi hanya di memori uji, tidak disimpan sebagai data pasar. Semua seedlegacy direproduksi sebelum sizing.

Data **officialBitstampOHLC M1, bukan tick bid/ask broker**. Leverage10 hipotesis,min/step0,01BTC,max100BTC;spread5bp,slip1bp/sisi,fee5bp/sisi,financingdebit3bpnotional/hari. KontrakRAW/leverage tiers/swap historis broker belum dibuktikan. Sinyal memakai candleclosed,entrynextopen;trendH4/D1closed;warmup source tetap. Tidak ada makro historis sintetis.

Stop-first pada bar ambigu,gapSL pada open lebih buruk. DD diperiksa setiapM1,grafik snapshotperjam. PrioritasSL/TP sebelum fallbackstopout dan capital-floorpermanen source lama tetap. ACK,reconnect,partialfill,depth dan spesifikasi broker native belum divalidasi. Tidak ada top-up,reset,DDclamp atau stop setelah target.

**BTC belum diuji dengan equity/margin bersama XAU–EUR.** Saldo standalone tidak dijumlahkan. cBotlive/frozenXAU-EUR,bridge dan envproduksi tidak diubah;tidak ada order atau merge main.

Publikasi ringkasan pada run39256137521 gagal dengan GitHubHTTP403/rule-timeout setelah pengujian dan verifikasiVPS sukses. Finalisasi ini memeriksa ulang manifest dan menerbitkan bukti ringkas; tidak mengubah hasil keuangan.

## Artefak

Run10juta: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39251677841

Runlegacy: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39256137521

Commit10juta: 52c55e9c15273cf8f8d7412a60f4669a8d0b245b

Commitlegacy audit/recovery:d81470688b94a78b6c845e0f8c38e301672dd297; original fine-sizing commit:0d6c1065aff3cfb6c838372dada44e097f193b7e

CSVinputSHA256:c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504.

VPS10juta:/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/btc-ten-million-dd60-2019-oct2026/run-39251677841/

VPSlegacy:/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/btc-dd60-legacy-2019-oct2026/run-39256137521/

FINAL_REVIEW memuat laporan ini,ZIPreview10juta,danZIPlegacy review(source,config,ledger,rekonsiliasi,bulanan/tahunan,grafik,manifest). Seluruh10tabel million-row berada di RIZAN_BTC_TEN_MILLION_COMPLETE.zip pada Actions/VPS10juta,SHA256efd72e0ba283a726d99f1186a57dd5a4a8aaea83c7853f1a3cc596410ff91a91. Review tidak menduplikasi10juta tabel/curveCSV besar. ZIPlegacy asli dengan seluruhcurveCSV tetap tersimpan di Actions/VPS; review hanya menghilangkan filecurve, bukan ledger atau kasus menurut performa. Semua manifest telah diverifikasi ulang.
