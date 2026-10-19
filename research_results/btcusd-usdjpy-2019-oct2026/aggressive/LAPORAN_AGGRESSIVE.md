# Pencarian agresif terpisah — hasil aktual

Satu juta konfigurasi aktif unik per instrumen; grid dinyatakan sebelum eksekusi, mengubah hanya ruang pencarian strategi baru, tidak menyentuh frozen XAU/EUR atau hasil pencarian awal. Akun $100 terpisah, tanpa top-up; periode2019–15Oktober2026. Risiko10–60%, margin50–95%: dapat menyebabkan drawdown ekstrem.

| symbol   |   configurations |   target_final_any_trade_count |   target_final_dd50 |   maximum_final | dataset_sha256                                                   | engine_sha256                                                    |
|:---------|-----------------:|-------------------------------:|--------------------:|----------------:|:-----------------------------------------------------------------|:-----------------------------------------------------------------|
| BTCUSD   |          1000000 |                             26 |                   0 |        463449   | c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504 | ffe67c8fba086eba19c3eb894ed5e1cc24d45812af03aedf79ae230be86bd024 |
| USDJPY   |          1000000 |                              0 |                   0 |         69856.6 | aa92c0d449860f86026df7840be9ab583be99aa017c7cac5abe546cfd84845b5 | ffe67c8fba086eba19c3eb894ed5e1cc24d45812af03aedf79ae230be86bd024 |

Hasil pemimpin dan satu parameter identik lintas instrumen:

| symbol   | criterion       |     id | family              |   tf_minutes |   risk |   margin_fraction |    equity |   floating_dd |      pf |   trades |   win_rate |
|:---------|:----------------|-------:|:--------------------|-------------:|-------:|------------------:|----------:|--------------:|--------:|---------:|-----------:|
| BTCUSD   | FULL            |  22375 | displacement_follow |          240 |   0.5  |              0.95 | 463449    |       89.2232 | 1.37609 |       66 |    50      |
| BTCUSD   | SAME_PARAMETERS |  79716 | displacement_follow |          240 |   0.25 |              0.95 |   1015.23 |       77.8292 | 1.12823 |       82 |    41.4634 |
| USDJPY   | FULL            | 823347 | break_retest        |           60 |   0.3  |              0.75 |  69856.6  |       90.8938 | 1.5378  |      134 |    42.5373 |
| USDJPY   | SAME_PARAMETERS |  79716 | displacement_follow |          240 |   0.25 |              0.95 |   1397.84 |       75.9893 | 4.59091 |       22 |    45.4545 |

Jumlah konfigurasi parameter identik yang mencapai saldo akhir>=100k di KEDUA instrumen: 0. Seluruh 1juta parameter dipasangkan berdasarkan tuple yang sama, bukan hanya ID atau hasil akhir.

BTCUSD FULL stres dan segmen restart100:

| case              |     equity |   floating_dd |   trades |   skips |   liquidations |
|:------------------|-----------:|--------------:|---------:|--------:|---------------:|
| BASE              | 463449     |       89.2232 |       66 |       0 |              0 |
| COST1_5           | 266665     |       89.7349 |       66 |       0 |              0 |
| COST2             |  37315.3   |       90.057  |       67 |       0 |              0 |
| DELAY_NEXT_M1     | 304690     |       89.139  |       66 |       0 |              0 |
| NO_ADDS           | 463449     |       89.2232 |       66 |       0 |              0 |
| LEVERAGE2         |   1099.81  |       33.672  |       66 |       0 |              0 |
| TRAIN_2019_2022   |   8494.47  |       89.2232 |       31 |       0 |              0 |
| VALID_2023_2024   |   4496.92  |       50.1901 |       22 |       0 |              0 |
| TEST_2025_OCT2026 |    117.856 |       54.024  |       13 |       0 |              0 |

BTCUSD SAME_PARAMETERS stres dan segmen restart100:

| case              |    equity |   floating_dd |   trades |   skips |   liquidations |
|:------------------|----------:|--------------:|---------:|--------:|---------------:|
| BASE              | 1015.23   |       77.8292 |       82 |       0 |              0 |
| COST1_5           |  272.939  |       79.2886 |       83 |       0 |              0 |
| COST2             |  211.214  |       81.2373 |       83 |       0 |              0 |
| DELAY_NEXT_M1     |  677.492  |       73.8349 |       81 |       0 |              0 |
| NO_ADDS           |  675.685  |       79.0406 |       82 |       0 |              0 |
| LEVERAGE2         |  200.638  |       18.8784 |       40 |      44 |              0 |
| TRAIN_2019_2022   |  795.269  |       69.7213 |       39 |       0 |              0 |
| VALID_2023_2024   |  298.868  |       39.6388 |       24 |       0 |              0 |
| TEST_2025_OCT2026 |   76.5219 |       26.4662 |        5 |      14 |              0 |

USDJPY FULL stres dan segmen restart100:

| case              |      equity |   floating_dd |   trades |   skips |   liquidations |
|:------------------|------------:|--------------:|---------:|--------:|---------------:|
| BASE              | 69856.6     |       90.8938 |      134 |       0 |              0 |
| COST1_5           | 38613.6     |       94.213  |      134 |       0 |              0 |
| COST2             |  7388.33    |       94.4608 |      134 |       0 |              0 |
| DELAY_NEXT_M1     |   461.673   |       98.7767 |      134 |       0 |              0 |
| NO_ADDS           | 69856.6     |       90.8938 |      134 |       0 |              0 |
| TRAIN_2019_2022   |    96.9409  |       90.8938 |       61 |       0 |              0 |
| VALID_2023_2024   | 76593.9     |       55.5478 |       35 |       0 |              0 |
| TEST_2025_OCT2026 |     7.93773 |       97.9701 |       38 |       0 |              0 |

USDJPY SAME_PARAMETERS stres dan segmen restart100:

| case              |   equity |   floating_dd |   trades |   skips |   liquidations |
|:------------------|---------:|--------------:|---------:|--------:|---------------:|
| BASE              | 1397.84  |       75.9893 |       22 |       1 |              0 |
| COST1_5           |  898.988 |       77.7153 |       22 |       1 |              0 |
| COST2             |  703.65  |       78.6353 |       22 |       1 |              0 |
| DELAY_NEXT_M1     | 1596.99  |       72.7857 |       22 |       1 |              0 |
| NO_ADDS           | 1427.9   |       82.4808 |       23 |       0 |              0 |
| TRAIN_2019_2022   |  163.77  |       74.969  |       11 |       1 |              0 |
| VALID_2023_2024   |  222.174 |       63.446  |        8 |       0 |              0 |
| TEST_2025_OCT2026 |  377.65  |       45.5616 |        3 |       0 |              0 |

Batas validitas: hasil terbaik dipilih dari periode penuh sehingga overfit/selection bias besar. Uji segmen setelah pemilihan bukan OOS murni. BTC data OHLC resmi Bitstamp, USDJPY HistData M1, bukan bid/ask tick broker. Leverage BTC10, spread, slippage, komisi, financing, batas volume dan stop-out adalah asumsi riset, bukan kontrak historis broker yang diverifikasi. USDJPY leverage200 juga model. Biaya1.5/2 tidak mengalikan spread; DELAY_NEXT_M1 adalah penundaan minimum1menit, bukan2detik. NO_ADDS mengalokasikan100% initialrisk. DD OHLC bukan jaminan DDtick. Seluruh input/sourcehash, million-row tables, rawledgers, cashproof dan500prefix regression perinstrumen disertakan. Hasil nominal100k, bila ada, hanya sukses modelhistoris dan harus dibedakan dari bukti ketahanan biaya/leverage atau penggunaan live.
