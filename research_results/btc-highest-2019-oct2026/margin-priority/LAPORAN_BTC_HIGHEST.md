# BTCUSD — lanjutan pencarian saldo akhir tertinggi

Status: EXPLORATORY_M1_MODEL_NOT_BROKER_VALIDATED. USD100, tanpa top-up,2019-01-01 sampai2026-10-15, akun BTC terpisah. Seluruh periode diteruskan tanpa stop di100k. Dua juta konfigurasi baru; total6juta evaluasi BTC termasuk tahap sebelumnya, bukan6juta tuple global unik.

Universe baru dan pembanding lama:

| variant             |   configurations |   target_final_100k_count |    maximum_final |   top20_cutoff |   unique_tuples | source_sha256                                                    |   selected_parameters |
|:--------------------|-----------------:|--------------------------:|-----------------:|---------------:|----------------:|:-----------------------------------------------------------------|----------------------:|
| POSITION_HIGH       |          1000000 |                        50 |      2.69504e+06 |      215872    |         1000000 | ca08c70505568fff80314a5f67f71e037efb1da918c2a6ffddc9db3a2bd238d3 |                    53 |
| SESSIONS_HIGH       |          1000000 |                         0 |   6355.66        |        1280.41 |         1000000 | 1915f61871ff9d1ac6a5ba14febf0d8c5a5c7dfb92a36b17e0575c88a0703045 |                    45 |
| PREVIOUS_AGGRESSIVE |          1000000 |                        26 | 463449           |      120267    |         1000000 | ffe67c8fba086eba19c3eb894ed5e1cc24d45812af03aedf79ae230be86bd024 |                    52 |

Top20 parameter aktif unik berdasarkan saldo akhir nominal:

|   rank | variant             |     id | family              |   tf_minutes |   risk |   margin_fraction |   add_stages |       equity |   floating_dd |   balance_dd |     pf |   trades |   win_rate |
|-------:|:--------------------|-------:|:--------------------|-------------:|-------:|------------------:|-------------:|-------------:|--------------:|-------------:|-------:|---------:|-----------:|
|      1 | POSITION_HIGH       | 677395 | structure_break     |         1440 | 0.2500 |            0.7500 |            0 | 2695040.9471 |       89.2828 |      85.4417 | 1.4732 |       70 |    31.4286 |
|      2 | POSITION_HIGH       | 189293 | displacement_follow |          240 | 0.1500 |            0.9500 |            0 | 1057459.5291 |       84.5973 |      77.5614 | 1.4894 |      107 |    42.0561 |
|      3 | POSITION_HIGH       | 692365 | displacement_follow |          240 | 0.4000 |            0.9500 |            2 | 1005025.5238 |       67.9209 |      57.1607 | 1.4052 |       63 |    52.3810 |
|      4 | POSITION_HIGH       | 530769 | structure_break     |         1440 | 0.4000 |            0.9500 |            2 |  858369.2418 |       93.4255 |      83.5293 | 1.3248 |       88 |    46.5909 |
|      5 | POSITION_HIGH       | 493603 | displacement_follow |          240 | 0.4000 |            0.9500 |            0 |  735023.6937 |       82.7225 |      72.9757 | 1.2291 |       70 |    48.5714 |
|      6 | POSITION_HIGH       | 418499 | displacement_follow |          240 | 0.2000 |            0.9500 |            0 |  570332.4672 |       92.1741 |      89.0309 | 1.2801 |      104 |    48.0769 |
|      7 | POSITION_HIGH       | 883957 | displacement_follow |          240 | 0.1500 |            0.9500 |            0 |  504502.0500 |       85.2118 |      80.8545 | 1.5572 |      104 |    47.1154 |
|      8 | POSITION_HIGH       | 437556 | displacement_follow |          240 | 0.3000 |            0.9500 |            1 |  481445.4360 |       80.9112 |      73.3706 | 1.1989 |      118 |    43.2203 |
|      9 | PREVIOUS_AGGRESSIVE |  22375 | displacement_follow |          240 | 0.5000 |            0.9500 |            0 |  463448.5889 |       89.2232 |      78.7322 | 1.3761 |       66 |    50.0000 |
|     10 | POSITION_HIGH       | 249707 | displacement_follow |          240 | 0.3000 |            0.9500 |            0 |  432560.4282 |       86.5222 |      77.7747 | 1.2895 |       65 |    49.2308 |
|     11 | POSITION_HIGH       | 542857 | displacement_follow |          240 | 0.2000 |            0.9500 |            0 |  427076.5526 |       92.1195 |      87.4184 | 1.2320 |      107 |    42.0561 |
|     12 | PREVIOUS_AGGRESSIVE | 397326 | structure_break     |          240 | 0.5000 |            0.9500 |            1 |  413548.5089 |       86.3825 |      85.0129 | 1.0702 |       95 |    45.2632 |
|     13 | POSITION_HIGH       | 944533 | displacement_follow |          240 | 0.6000 |            0.7500 |            2 |  407919.8161 |       73.0871 |      71.4441 | 1.2188 |       63 |    50.7937 |
|     14 | POSITION_HIGH       | 831301 | structure_break     |         1440 | 0.2500 |            0.9500 |            0 |  405299.3593 |       94.2784 |      89.4621 | 1.2904 |       85 |    25.8824 |
|     15 | PREVIOUS_AGGRESSIVE | 327182 | displacement_follow |          240 | 0.1500 |            0.9500 |            0 |  383478.4436 |       79.9462 |      77.4645 | 1.3141 |      108 |    42.5926 |
|     16 | PREVIOUS_AGGRESSIVE | 125089 | displacement_follow |          240 | 0.4000 |            0.7500 |            2 |  380267.8847 |       71.8824 |      70.1659 | 1.2402 |       63 |    52.3810 |
|     17 | PREVIOUS_AGGRESSIVE | 301411 | displacement_follow |          240 | 0.1500 |            0.9500 |            0 |  377349.1010 |       82.8026 |      78.4134 | 1.1285 |      153 |    38.5621 |
|     18 | POSITION_HIGH       | 340573 | displacement_follow |          240 | 0.2500 |            0.9500 |            0 |  337206.6336 |       71.0738 |      67.0026 | 1.2888 |       74 |    56.7568 |
|     19 | PREVIOUS_AGGRESSIVE | 325131 | displacement_follow |          240 | 0.6000 |            0.7500 |            2 |  304469.2720 |       72.1911 |      58.8438 | 1.3947 |       67 |    62.6866 |
|     20 | POSITION_HIGH       | 128454 | displacement_follow |          240 | 0.1000 |            0.9500 |            0 |  302107.0340 |       90.0532 |      88.9478 | 1.0953 |      330 |    35.1515 |

Parameter juara lengkap:

|     id |   tf_minutes | family          |   lookback |   threshold_index |   trend_filter |   session_utc |   side |   stop_atr |   tp_R |   hold_bars |   risk |   margin_fraction |   add_stages |   breakeven_R | variant       |       equity |
|-------:|-------------:|:----------------|-----------:|------------------:|---------------:|--------------:|-------:|-----------:|-------:|------------:|-------:|------------------:|-------------:|--------------:|:--------------|-------------:|
| 677395 |         1440 | structure_break |         16 |                 0 |              1 |             0 |      1 |     0.7500 |     24 |          32 | 0.2500 |            0.7500 |            0 |             0 | POSITION_HIGH | 2695040.9471 |

Stres juara dengan parameter tetap, tanpa memilih ulang pemenang menurut stres:

| case              |       equity |   floating_dd |   trades |   adds |   skips |   liquidations |
|:------------------|-------------:|--------------:|---------:|-------:|--------:|---------------:|
| BASE              | 2695040.9471 |       89.2828 |       70 |      0 |       0 |              0 |
| COST1_5           |  137826.2886 |       93.8107 |       71 |      0 |       0 |              0 |
| COST2             |   54571.7360 |       95.8425 |       71 |      0 |       0 |              0 |
| DELAY_NEXT_M1     |  691102.7875 |       89.3580 |       70 |      0 |       0 |              0 |
| NO_ADDS           | 2695040.9471 |       89.2828 |       70 |      0 |       0 |              0 |
| LEVERAGE2         |    4616.5616 |       43.2310 |       70 |      0 |       0 |              0 |
| LEVERAGE5         |  119796.3292 |       71.0079 |       70 |      0 |       0 |              0 |
| TRAIN_2019_2022   |   27277.0761 |       89.0758 |       31 |      0 |       0 |              0 |
| VALID_2023_2024   |    1963.3486 |       92.2009 |       22 |      0 |       0 |              0 |
| TEST_2025_OCT2026 |     195.9738 |       43.1979 |        5 |      0 |      31 |              0 |

Pembanding juara sebelumnya22375 direkonstruksi, tidak diganti dengan proxy. Seluruh top20 lama ikut seleksi ulang, ditambah kandidat DD30/50/70/90 dan train-only. Pemimpin dari tiga universe awal lainnya maksimum85424,59 (POSITION),18046,40 (GENERIC),1396,68 (SESSIONS); semua berada di bawah cutoff top20 aggressive lama sehingga tidak mengubah ranking terminal global. Full tables dan laporan awal tetap tersedia pada Actions39217369074.

Kesamaan kandidat: TOP20_OVERLAP.csv memuat Jaccard timestamp sinyal dan interval posisi terbuka. Korelasi memakai return kas transaksi tertutup per hari, bukan floating-equity MTM atau bukti diversifikasi XAU/EUR. Kandidat yang serupa bukan sumber keuntungan independen. Tidak dilakukan penjumlahan saldo standalone.

Validasi:5shard200ribu tepat1juta tuple unik per universe, hash input/source sama; parameter terpilih direkonstruksi dalam source asli, kas dihitung ulang dari harga/volume/fee/financing. Uji500prefix future-price perturbation per engine. Ledger, biaya, reject/skips model, grafik, bulanan/tahunan top20 dan checksum disertakan. Ini pengujian implementasi model, bukan parity broker.

Data: official Bitstamp OHLC M1. Leverage10 hipotesis; sensitivitas2 dan5 terpisah. Model minimum/step0,01BTC,max100BTC; spread5bp,slip1bp/sisi,komisi5bp/sisi,financing debit3bpnotional/hari. Biaya1.5/2 mengalikan slip/fee/carry, tidak spread. Delay adalah minimum1menit, bukan2detik. Segmen train/valid/test restart100 setelah seleksi bukan OOS murni. NO_ADDS mengubah initial risk allocation ke100%. DD adalah statistik OHLC engine, bukan jaminan drawdown tick. Tidak ada bid/ask native broker, depth, partialfill,ACK,recovery,swap/leverage tiers historis atau stop-grid broker yang dibuktikan. Source memiliki permanent capital-floor guard; lihat source untuk kebijakan deaktivasi akun. Hasil dipilih dari jutaan percobaan dalam sampel sehingga risiko overfit besar.

Persiapan penggabungan: XAU_EUR_BTC_INTEGRATION_CONTRACT.json hanya desain. Source frozen XAU/EUR dan cBot live tidak diubah. Perlu shared equity/margin coordinator, pending-risk reservation, kontrak BTC broker, kalender24/7, konflik posisi dan settlement/checkpoint yang idempoten. Risk nominal standalone BTC tidak boleh dijumlahkan ke portfolio risk lama. Angka hasil portofolio gabungan belum dihitung; wajib replay tersinkron tiga simbol lebih dahulu. Tidak ada order broker, restart bridge, perubahan env produksi atau merge main.

Source/input/manifests dan seluruh laporan disimpan pada branch research/btc-highest-balance-2019-2026 serta VPS REPLAY_RESULTS/btc-highest-balance-2019-oct2026/run-ID. Paket REVIEW tidak memuat duplikat data M1 dan million-row tables; paket COMPLETE menyimpannya. Kedua manifest menjelaskan file yang ada; penghilangan hanya berdasarkan jenis file, bukan hasil performa.
