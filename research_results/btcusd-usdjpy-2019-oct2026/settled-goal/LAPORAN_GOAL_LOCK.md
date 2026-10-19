# Varian terpisah: berhenti setelah target kas tercapai

Aturan yang dinyatakan sebelum replay varian: sesudah seluruh basket ditutup dan semua biaya model dibayar, jika kas >= $100.000, hentikan entry selamanya. Tidak ada penutupan pada puncak floating, pemilihan tanggal, clipping saldo atau top-up. Hasil baseline tidak diganti.

Cakupan seluruh ledger kandidat raw terpilih (union top20 full, DD50, train setiap universe), bukan seluruh 6 juta lintasan konfigurasi:

| symbol   |   candidates |   cash_goal_hits |
|:---------|-------------:|-----------------:|
| BTCUSD   |          167 |                6 |
| USDJPY   |          167 |                0 |

Kandidat yang benar-benar menyentuh target kas:

| symbol   | variant   |     id |   baseline_final |   baseline_trades |   max_settled_cash | cash_goal_hit   |   goal_lock_final |   goal_trade_count | first_goal_exit_utc   |
|:---------|:----------|-------:|-----------------:|------------------:|-------------------:|:----------------|------------------:|-------------------:|:----------------------|
| BTCUSD   | POSITION  | 792291 |          85424.6 |                79 |             105968 | True            |            105968 |                 67 | 2025-08-11 00:00:00   |
| BTCUSD   | POSITION  | 960091 |          80791.2 |               104 |             121855 | True            |            121855 |                 91 | 2025-10-04 08:00:00   |
| BTCUSD   | POSITION  | 483339 |          55543.7 |               135 |             165269 | True            |            165269 |                 81 | 2024-03-11 15:06:00   |
| BTCUSD   | POSITION  | 936995 |          48810.8 |               154 |             106550 | True            |            106550 |                123 | 2025-05-12 08:00:00   |
| BTCUSD   | POSITION  | 353879 |          17513   |               680 |             201268 | True            |            106914 |                430 | 2024-03-15 08:00:00   |
| BTCUSD   | POSITION  | 817035 |          13883.5 |               136 |             199349 | True            |            199349 |                 82 | 2024-03-11 15:06:00   |

Hasil replay seluruh skenario kandidat yang menyentuh target:

| symbol   | variant   |     id | case              |     equity |   floating_dd |   trades |
|:---------|:----------|-------:|:------------------|-----------:|--------------:|---------:|
| BTCUSD   | POSITION  | 792291 | BASE              | 105968     |       58.445  |       67 |
| BTCUSD   | POSITION  | 792291 | COST1_5           |  43635.1   |       59.5956 |       80 |
| BTCUSD   | POSITION  | 792291 | COST2             |  31025.2   |       60.8965 |       80 |
| BTCUSD   | POSITION  | 792291 | DELAY_NEXT_M1     | 106425     |       55.2078 |       67 |
| BTCUSD   | POSITION  | 792291 | NO_ADDS           | 105968     |       58.445  |       67 |
| BTCUSD   | POSITION  | 792291 | LEVERAGE2         |    623.141 |       20.737  |       44 |
| BTCUSD   | POSITION  | 792291 | TRAIN_2019_2022   |   2950.87  |       53.8534 |       38 |
| BTCUSD   | POSITION  | 792291 | VALID_2023_2024   |   1431.62  |       54.1554 |       24 |
| BTCUSD   | POSITION  | 792291 | TEST_2025_OCT2026 |    100     |        0      |        0 |
| BTCUSD   | POSITION  | 960091 | BASE              | 121855     |       81.3968 |       91 |
| BTCUSD   | POSITION  | 960091 | COST1_5           |  52384.6   |       81.8735 |      104 |
| BTCUSD   | POSITION  | 960091 | COST2             |  18353.1   |       81.9665 |      105 |
| BTCUSD   | POSITION  | 960091 | DELAY_NEXT_M1     |  25843.1   |       81.0087 |      106 |
| BTCUSD   | POSITION  | 960091 | NO_ADDS           | 121855     |       81.3968 |       91 |
| BTCUSD   | POSITION  | 960091 | LEVERAGE2         |    275.147 |       14.7658 |       34 |
| BTCUSD   | POSITION  | 960091 | TRAIN_2019_2022   |   2636.26  |       81.3968 |       49 |
| BTCUSD   | POSITION  | 960091 | VALID_2023_2024   |    831.191 |       52.606  |       31 |
| BTCUSD   | POSITION  | 960091 | TEST_2025_OCT2026 |    100     |        0      |        0 |
| BTCUSD   | POSITION  | 483339 | BASE              | 165269     |       71.5108 |       81 |
| BTCUSD   | POSITION  | 483339 | COST1_5           |  22440.4   |       91.2048 |      136 |
| BTCUSD   | POSITION  | 483339 | COST2             |  11405.7   |       92.7953 |      136 |
| BTCUSD   | POSITION  | 483339 | DELAY_NEXT_M1     | 156652     |       70.3852 |       83 |
| BTCUSD   | POSITION  | 483339 | NO_ADDS           | 165269     |       71.5108 |       81 |
| BTCUSD   | POSITION  | 483339 | LEVERAGE2         |    529.216 |       29.911  |       61 |
| BTCUSD   | POSITION  | 483339 | TRAIN_2019_2022   |   8836.59  |       71.5108 |       61 |
| BTCUSD   | POSITION  | 483339 | VALID_2023_2024   |    457.132 |       76.5789 |       39 |
| BTCUSD   | POSITION  | 483339 | TEST_2025_OCT2026 |    100     |        0      |        0 |
| BTCUSD   | POSITION  | 936995 | BASE              | 106550     |       78.1481 |      123 |
| BTCUSD   | POSITION  | 936995 | COST1_5           |  25806     |       80.515  |      154 |
| BTCUSD   | POSITION  | 936995 | COST2             |   4688.55  |       82.1716 |      155 |
| BTCUSD   | POSITION  | 936995 | DELAY_NEXT_M1     | 100314     |       75.1769 |      123 |
| BTCUSD   | POSITION  | 936995 | NO_ADDS           |  16590.5   |       89.0175 |      154 |
| BTCUSD   | POSITION  | 936995 | LEVERAGE2         |    173.45  |       37.5475 |       47 |
| BTCUSD   | POSITION  | 936995 | TRAIN_2019_2022   |   3933.94  |       78.1481 |       80 |
| BTCUSD   | POSITION  | 936995 | VALID_2023_2024   |    771.492 |       42.1372 |       37 |
| BTCUSD   | POSITION  | 936995 | TEST_2025_OCT2026 |    100     |        0      |        0 |
| BTCUSD   | POSITION  | 353879 | BASE              | 106914     |       70.5098 |      430 |
| BTCUSD   | POSITION  | 353879 | COST1_5           |   2769.63  |       95.248  |      680 |
| BTCUSD   | POSITION  | 353879 | COST2             |    480.767 |       97.1936 |      680 |
| BTCUSD   | POSITION  | 353879 | DELAY_NEXT_M1     |   6144.41  |       92.8218 |      680 |
| BTCUSD   | POSITION  | 353879 | NO_ADDS           | 106914     |       70.5098 |      430 |
| BTCUSD   | POSITION  | 353879 | LEVERAGE2         |    351.655 |       24.4402 |      285 |
| BTCUSD   | POSITION  | 353879 | TRAIN_2019_2022   |  19839.2   |       50.6505 |      320 |
| BTCUSD   | POSITION  | 353879 | VALID_2023_2024   |    472.641 |       61.952  |      184 |
| BTCUSD   | POSITION  | 353879 | TEST_2025_OCT2026 |    100     |        0      |        0 |
| BTCUSD   | POSITION  | 817035 | BASE              | 199349     |       90.7087 |       82 |
| BTCUSD   | POSITION  | 817035 | COST1_5           |   3547.25  |       98.0294 |      137 |
| BTCUSD   | POSITION  | 817035 | COST2             |   1430.16  |       98.4824 |      137 |
| BTCUSD   | POSITION  | 817035 | DELAY_NEXT_M1     | 172252     |       90.353  |       84 |
| BTCUSD   | POSITION  | 817035 | NO_ADDS           | 199349     |       90.7087 |       82 |
| BTCUSD   | POSITION  | 817035 | LEVERAGE2         |    530.279 |       29.911  |       62 |
| BTCUSD   | POSITION  | 817035 | TRAIN_2019_2022   |   9103.82  |       90.7087 |       61 |
| BTCUSD   | POSITION  | 817035 | VALID_2023_2024   |    132.123 |       91.1267 |       37 |
| BTCUSD   | POSITION  | 817035 | TEST_2025_OCT2026 |    100     |        0      |        0 |

Rekonsiliasi: setiap ledger BASE varian sama persis secara numerik dengan prefix ledger baseline, berhenti pada crossing kas pertama, dan PnL/kas dihitung ulang independen. Bukti lengkap: EXACT_PREFIX_AND_CASH_PROOF.json. Diff source hanya guard kas setelah ledger basket tertutup. Remaining periode memegang kas tanpa bunga. Ini kebijakan penghentian akun baru yang ditemukan melalui riset historis, bukan validasi out-of-sample atau pembuktian broker.

Batas: candle M1 resmi Bitstamp/HistData, spread dan slippage model; BTC leverage10 belum dibuktikan, leverage2 sensitivitas terpisah. USDJPY leverage200 juga asumsi model. Tidak ada urutan tick asli/bid-ask broker, ACK, partial fill, swap historis broker atau margin dinamis. DD adalah statistik OHLC engine. Tidak ada jaminan hasil masa depan. Hasil segmen restart100 tidak sama dengan compounding kontinu.
