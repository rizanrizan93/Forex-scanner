# BTC — prioritas DD di bawah50%, maksimum55%

USD100 standalone, tanpa top-up atau stop setelah target,2019-01-01 sampai2026-10-15. Screen seluruh6juta baris penelitian lama, kemudian sizing sweep terarah 7488 kasus unik per source universe. Ini bukan jutaan keluarga independen dan bukan OOS murni.

DD yang dibatasi adalah floating DD model OHLC, bukan balance DD atau jaminan tick/broker. Kelompok utama DD<50; kelompok cadangan50–55 dipisah.

| criterion   | variant       |      id | family              |   tf_minutes |   risk |   margin_fraction |   add_stages |     equity |   floating_dd |   balance_dd |     pf |   trades |   win_rate |
|:------------|:--------------|--------:|:--------------------|-------------:|-------:|------------------:|-------------:|-----------:|--------------:|-------------:|-------:|---------:|-----------:|
| DD_50_TO55  | POSITION_HIGH | 1000184 | structure_break     |         1440 | 0.1200 |            0.9500 |            2 | 79912.9540 |       54.3322 |      38.3499 | 2.2961 |       77 |    53.2468 |
| DD_50_TO55  | POSITION_HIGH | 1000183 | structure_break     |         1440 | 0.1200 |            0.7500 |            2 | 63692.1729 |       54.3322 |      38.2738 | 2.3145 |       77 |    53.2468 |
| DD_50_TO55  | POSITION_HIGH | 1000502 | displacement_follow |          240 | 0.1500 |            0.6000 |            0 | 63466.5663 |       51.7478 |      49.2099 | 1.6248 |       66 |    60.6061 |
| DD_50_TO55  | POSITION_HIGH | 1000182 | structure_break     |         1440 | 0.1200 |            0.6000 |            2 | 51727.1177 |       53.6171 |      38.2914 | 2.4550 |       77 |    53.2468 |
| DD_50_TO55  | POSITION_HIGH | 1000590 | displacement_follow |          240 | 0.1000 |            0.6000 |            0 | 44981.3983 |       54.7535 |      50.3584 | 1.5581 |       73 |    46.5753 |
| DD_LT50     | POSITION_HIGH | 1000072 | structure_break     |         1440 | 0.1000 |            0.9500 |            1 | 56582.3842 |       46.7545 |      31.6107 | 2.2974 |       88 |    46.5909 |
| DD_LT50     | POSITION_HIGH | 1000070 | structure_break     |         1440 | 0.1000 |            0.6000 |            1 | 56582.3842 |       46.7545 |      31.6107 | 2.2974 |       88 |    46.5909 |
| DD_LT50     | POSITION_HIGH | 1000071 | structure_break     |         1440 | 0.1000 |            0.7500 |            1 | 56582.3842 |       46.7545 |      31.6107 | 2.2974 |       88 |    46.5909 |
| DD_LT50     | POSITION_HIGH | 1000069 | structure_break     |         1440 | 0.1000 |            0.5000 |            1 | 49989.8614 |       46.7545 |      31.6107 | 2.2938 |       88 |    46.5909 |
| DD_LT50     | POSITION_HIGH | 1000068 | structure_break     |         1440 | 0.1000 |            0.4000 |            1 | 41988.5528 |       46.7545 |      31.6107 | 2.2510 |       88 |    46.5909 |

## DD_LT50 1000072

|      id |   tf_minutes | family          |   lookback |   threshold_index |   trend_filter |   session_utc |   side |   stop_atr |   tp_R |   hold_bars |   risk |   margin_fraction |   add_stages |   breakeven_R |   equity |   floating_dd |
|--------:|-------------:|:----------------|-----------:|------------------:|---------------:|--------------:|-------:|-----------:|-------:|------------:|-------:|------------------:|-------------:|--------------:|---------:|--------------:|
| 1000072 |         1440 | structure_break |          8 |                 1 |              1 |             0 |      1 |       0.75 |     24 |          32 |    0.1 |              0.95 |            1 |             1 |  56582.4 |       46.7545 |

| case              |      equity |   floating_dd |   trades |   adds |   skips |   liquidations |
|:------------------|------------:|--------------:|---------:|-------:|--------:|---------------:|
| BASE              |  56582.3842 |       46.7545 |       88 |     70 |       0 |              0 |
| COST1_5           |  23887.1435 |       46.8714 |       82 |     64 |      11 |              0 |
| COST2             |  17328.3813 |       46.9955 |       82 |     64 |      11 |              0 |
| DELAY_NEXT_M1     |  62504.4638 |       46.7607 |       88 |     69 |       0 |              0 |
| NO_ADDS           | 288965.5230 |       73.5704 |       88 |      0 |       0 |              0 |
| LEVERAGE2         |   8273.3001 |       41.4830 |       81 |     45 |      12 |              0 |
| LEVERAGE5         |  48036.3624 |       46.7545 |       88 |     70 |       0 |              0 |
| TRAIN_2019_2022   |   1331.8379 |       46.7545 |       44 |     35 |       0 |              0 |
| VALID_2023_2024   |   1700.4040 |       27.9090 |       24 |     17 |       0 |              0 |
| TEST_2025_OCT2026 |    100.0000 |        0.0000 |        0 |      0 |      43 |              0 |

## DD_50_TO55 1000184

|      id |   tf_minutes | family          |   lookback |   threshold_index |   trend_filter |   session_utc |   side |   stop_atr |   tp_R |   hold_bars |   risk |   margin_fraction |   add_stages |   breakeven_R |   equity |   floating_dd |
|--------:|-------------:|:----------------|-----------:|------------------:|---------------:|--------------:|-------:|-----------:|-------:|------------:|-------:|------------------:|-------------:|--------------:|---------:|--------------:|
| 1000184 |         1440 | structure_break |          8 |                 2 |              1 |             0 |      1 |       0.75 |     24 |          32 |   0.12 |              0.95 |            2 |             1 |    79913 |       54.3322 |

| case              |      equity |   floating_dd |   trades |   adds |   skips |   liquidations |
|:------------------|------------:|--------------:|---------:|-------:|--------:|---------------:|
| BASE              |  79912.9540 |       54.3322 |       77 |     97 |       5 |              0 |
| COST1_5           |  50597.1002 |       55.2700 |       76 |     95 |       7 |              0 |
| COST2             |  27741.1618 |       56.0570 |       74 |     92 |       9 |              0 |
| DELAY_NEXT_M1     |  93901.9229 |       49.6939 |       81 |    106 |       0 |              0 |
| NO_ADDS           | 353853.7229 |       69.4796 |       81 |      0 |       0 |              0 |
| LEVERAGE2         |   6434.2870 |       33.5044 |       74 |     30 |       9 |              0 |
| LEVERAGE5         |  36678.2457 |       50.4559 |       77 |     94 |       5 |              0 |
| TRAIN_2019_2022   |   1244.0307 |       54.3322 |       36 |     45 |       5 |              0 |
| VALID_2023_2024   |   2725.5355 |       46.4245 |       25 |     30 |       0 |              0 |
| TEST_2025_OCT2026 |    100.0000 |        0.0000 |        0 |      0 |      35 |              0 |

Batas: data official Bitstamp M1, bukan tick bid/ask broker. Leverage10 hipotesis; sensitivitas2/5 terpisah. Spread5bp,slip1bp/sisi,fee5bp/sisi,financing debit3bpnotional/hari prorata. Biaya1.5/2 mengalikan slip/fee/carry, bukan spread. Delay minimum1menit, bukan2detik. NO_ADDS mengalokasikan100% initialrisk, bukan ablation volume tetap. Angka stres dan segmen restart100 bukan hasil gabungan dan bukan OOS yang tak tersentuh. DD nominal<50 atau<=55 tidak menjamin batas bertahan saat biaya/spread/urutan tick berubah. Tidak ada DD kill switch retroaktif atau reset akun.

Seluruh seed awal direkonsiliasi dengan hasil source lama setelah hanya memperluas array numerik risk/margin. Replikasi baseline kandidat terpilih dicek ulang; PnL dan kas dihitung independen dari ledger. Source asli, source sizing-grid, seluruh sizing cases, ledger, grafik dan bulanan/tahunan dipertahankan. Input SHA256c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504 tersimpan pada arsip rujukan Actions39218690359 dan39233081519. Input tidak diinterpolasi atau dimodifikasi. Batas engine stop-first/capital-floor/ACK/nativebroker seperti laporan sebelumnya tetap berlaku.

XAU/EUR dan trading live tidak diubah. DD akun BTC standalone tidak dapat disamakan dengan DD portfolio bersama. Hasil dipilih setelah banyak percobaan pada periode sama; wajib bedakan optimasi historis dan bukti ketahanan masa depan.
