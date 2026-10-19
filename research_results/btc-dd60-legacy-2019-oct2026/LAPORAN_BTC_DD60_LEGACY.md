# BTC — legacy DD60 dan fine sizing

Penyaringan ulang seluruh6.000.000 konfigurasi BTC lama dengan batas floatingDD<60%, lalu fine sizing 157320 tuple baru. Ini terpisah dari10juta konfigurasi komposit baru; tidak boleh dihitung sebagai10juta keluarga baru. Semua dimulaiUSD100 pada2019-01-01 sampai2026-10-15. Source keluarga lama tidak diganti; hanya gridnumerik sizing diperluas.

| criterion      | variant             |      id | family              |   tf_minutes |     risk |   margin_fraction |   add_stages |        equity |   floating_dd |   balance_dd |       pf |   trades |   win_rate |
|:---------------|:--------------------|--------:|:--------------------|-------------:|---------:|------------------:|-------------:|--------------:|--------------:|-------------:|---------:|---------:|-----------:|
| DD_LT50_BACKUP | POSITION_HIGH       | 1003442 | structure_break     |         1440 | 0.100000 |          0.870000 |            1 |  56582.384152 |     46.754520 |    31.610742 | 2.297414 |       88 |  46.590909 |
| DD_LT50_BACKUP | POSITION_HIGH       | 1003441 | structure_break     |         1440 | 0.100000 |          0.860000 |            1 |  56582.384152 |     46.754520 |    31.610742 | 2.297414 |       88 |  46.590909 |
| DD_LT50_BACKUP | POSITION_HIGH       | 1003444 | structure_break     |         1440 | 0.100000 |          0.890000 |            1 |  56582.384152 |     46.754520 |    31.610742 | 2.297414 |       88 |  46.590909 |
| DD_LT50_BACKUP | POSITION_HIGH       | 1003440 | structure_break     |         1440 | 0.100000 |          0.850000 |            1 |  56582.384152 |     46.754520 |    31.610742 | 2.297414 |       88 |  46.590909 |
| DD_LT50_BACKUP | POSITION_HIGH       | 1003449 | structure_break     |         1440 | 0.100000 |          0.940000 |            1 |  56582.384152 |     46.754520 |    31.610742 | 2.297414 |       88 |  46.590909 |
| DD_LT60        | PREVIOUS_AGGRESSIVE | 1004209 | displacement_follow |          240 | 0.210000 |          0.950000 |            0 | 955554.242191 |     59.926010 |    54.339761 | 1.407940 |       63 |  55.555556 |
| DD_LT60        | PREVIOUS_AGGRESSIVE | 1005482 | displacement_follow |          240 | 0.400000 |          0.570000 |            0 | 158312.984920 |     59.668826 |    56.721939 | 1.368023 |       63 |  55.555556 |
| DD_LT60        | PREVIOUS_AGGRESSIVE | 1005413 | displacement_follow |          240 | 0.390000 |          0.570000 |            0 | 157233.225175 |     59.669808 |    56.722416 | 1.367960 |       63 |  55.555556 |
| DD_LT60        | PREVIOUS_AGGRESSIVE | 1005344 | displacement_follow |          240 | 0.380000 |          0.570000 |            0 | 156402.438234 |     59.685625 |    56.722791 | 1.367927 |       63 |  55.555556 |
| DD_LT60        | PREVIOUS_AGGRESSIVE | 1005275 | displacement_follow |          240 | 0.370000 |          0.570000 |            0 | 155224.420908 |     59.693538 |    56.719533 | 1.367921 |       63 |  55.555556 |

## DD_LT60

|      id |   tf_minutes | family              |   lookback |   threshold_index |   trend_filter |   session_utc |   side |   stop_atr |   tp_R |   hold_bars |     risk |   margin_fraction |   add_stages |   breakeven_R |        equity |   floating_dd |
|--------:|-------------:|:--------------------|-----------:|------------------:|---------------:|--------------:|-------:|-----------:|-------:|------------:|---------:|------------------:|-------------:|--------------:|--------------:|--------------:|
| 1004209 |          240 | displacement_follow |          8 |                 2 |              1 |             1 |      1 |   2.000000 |     12 |          32 | 0.210000 |          0.950000 |            0 |             0 | 955554.242191 |     59.926010 |

| case              |      equity |   floating_dd |   trades |   adds |   skips |   liquidations |
|:------------------|------------:|--------------:|---------:|-------:|--------:|---------------:|
| BASE              | 955554.2422 |       59.9260 |       63 |      0 |       0 |              0 |
| COST1_5           | 383319.9291 |       76.3599 |       63 |      0 |       0 |              0 |
| COST2             | 211576.3060 |       79.3310 |       63 |      0 |       0 |              0 |
| DELAY_NEXT_M1     | 224606.6817 |       76.4783 |       64 |      0 |       0 |              0 |
| NO_ADDS           | 955554.2422 |       59.9260 |       63 |      0 |       0 |              0 |
| LEVERAGE2         |   2176.0163 |       24.8446 |       63 |      0 |       0 |              0 |
| LEVERAGE5         |  62813.5910 |       53.0431 |       63 |      0 |       0 |              0 |
| TRAIN_2019_2022   |  23052.8624 |       58.8586 |       29 |      0 |       0 |              0 |
| VALID_2023_2024   |   3312.8703 |       45.0374 |       21 |      0 |       0 |              0 |
| TEST_2025_OCT2026 |     72.5521 |       42.1126 |        2 |      0 |      17 |              0 |

## DD_LT50_BACKUP

|      id |   tf_minutes | family          |   lookback |   threshold_index |   trend_filter |   session_utc |   side |   stop_atr |   tp_R |   hold_bars |     risk |   margin_fraction |   add_stages |   breakeven_R |       equity |   floating_dd |
|--------:|-------------:|:----------------|-----------:|------------------:|---------------:|--------------:|-------:|-----------:|-------:|------------:|---------:|------------------:|-------------:|--------------:|-------------:|--------------:|
| 1003442 |         1440 | structure_break |          8 |                 1 |              1 |             0 |      1 |   0.750000 |     24 |          32 | 0.100000 |          0.870000 |            1 |             1 | 56582.384152 |     46.754520 |

| case              |      equity |   floating_dd |   trades |   adds |   skips |   liquidations |
|:------------------|------------:|--------------:|---------:|-------:|--------:|---------------:|
| BASE              |  56582.3842 |       46.7545 |       88 |     70 |       0 |              0 |
| COST1_5           |  23887.1435 |       46.8714 |       82 |     64 |      11 |              0 |
| COST2             |  17328.3813 |       46.9955 |       82 |     64 |      11 |              0 |
| DELAY_NEXT_M1     |  62504.4638 |       46.7607 |       88 |     69 |       0 |              0 |
| NO_ADDS           | 288965.5230 |       73.5704 |       88 |      0 |       0 |              0 |
| LEVERAGE2         |   7485.8919 |       42.7642 |       81 |     42 |      12 |              0 |
| LEVERAGE5         |  45754.9751 |       46.7545 |       88 |     70 |       0 |              0 |
| TRAIN_2019_2022   |   1331.8379 |       46.7545 |       44 |     35 |       0 |              0 |
| VALID_2023_2024   |   1700.4040 |       27.9090 |       24 |     17 |       0 |              0 |
| TEST_2025_OCT2026 |    100.0000 |        0.0000 |        0 |      0 |      43 |              0 |

Fine sizing diselesaikan pada run39252456294; seluruh157.320baris dipulihkan dengan SHA256identik. Seluruh seed original direproduksi kembali saat pemulihan. Kandidat terpilih direplay ulang dan ledger seluruh skenario direkonsiliasi independen. Source/diff parameter dan semua hasil sizing disimpan. Seleksi minimum30basket, konsisten dengan10juta replay komposit. Tidak ada top-up, reset, stop setelah target, atau DDclamp.

Batas tetap: officialBitstampM1 bukan tick bid/ask broker, leverage10 hipotesis; step/min0,01BTC,max100BTC; spread5bp,slip1bp/sisi,fee5bp/sisi,financing3bpnotional/hari. Cost1.5/2 mengalikan fee/slip/carry tanpa menggandakan spread. Delayminimum1menit bukan2detik. Closed-only signals,nextopen,stop-first,gapopenlebihburuk. Modelstopoutpriority dancapital-floorlama dipertahankan. Segmen restart100 dan pemilihanfullperiod bukan untouchedOOS. Hasil portfolio BTC+XAU/EUR belum diuji. Konfigurasi risk nominal bukan alokasi portofolio. Live/frozenXAU-EUR tidak diubah.

Sumber lengkap6universe dan manifestinput tersedia pada Actions39218690359 serta39233081519. SHA256uncompressedCSV c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504. Label parity adalah konsistensi model, bukan broker-nativeparity.
