# BTC 692365 — pencarian saldo tertinggi dengan floating DD <50%

Akun standalone USD100, tanpa top-up;2019-01-01 sampai2026-10-15. Sinyal H4 displacement BUY, trend H4, threshold0.2 dan sesi UTC00–08 tetap. Parameter risk/margin, stop,TP,holding,layering dan BE dioptimasi sebagai konfigurasi riset baru. Strategi XAU–EUR/live tidak diubah.

Diuji 112,420 konfigurasi unik. Baseline692365 direproduksi sebelum pencarian: saldo dan DD toleransi ketat,63basket. Seluruh hasil pilihan direplay ulang dan ledger semua skenario direkonsiliasi independen.

| label                |      id |       equity |   floating_dd |   balance_dd |     pf |   trades |   win_rate |   adds |   skips |   liquidations |
|:---------------------|--------:|-------------:|--------------:|-------------:|-------:|---------:|-----------:|-------:|--------:|---------------:|
| BEFORE_692365        | 2000001 | 1005025.5238 |       67.9209 |      57.1607 | 1.4052 |       63 |    52.3810 |     36 |       0 |              0 |
| AFTER_DD_LT50        | 2065842 |   53784.5409 |       49.4301 |      46.2034 | 1.5424 |       63 |    55.5556 |      8 |       0 |              0 |
| SECONDARY_DD_50_TO55 | 2020348 |   98286.5775 |       54.8317 |      51.7090 | 1.4449 |       63 |    55.5556 |      0 |       0 |              0 |

## Konfigurasi dan sensitivitas pilihan DD<50

|          id |   stop_atr |   tp_R |   hold_bars |   risk |   margin_fraction |   add_stages |   breakeven_R |
|------------:|-----------:|-------:|------------:|-------:|------------------:|-------------:|--------------:|
| 2.06584e+06 |          2 |     16 |          32 |    0.4 |              0.43 |            2 |             0 |

| case                 |     equity |   floating_dd |   trades |   adds |   skips |   liquidations |
|:---------------------|-----------:|--------------:|---------:|-------:|--------:|---------------:|
| BASE                 | 53784.5409 |       49.4301 |       63 |      8 |       0 |              0 |
| COST1_5              | 39752.3812 |       50.5873 |       63 |      7 |       0 |              0 |
| COST2                | 30112.2899 |       52.1219 |       63 |      8 |       0 |              0 |
| DELAY_NEXT_M1        | 25169.0709 |       49.4713 |       64 |      7 |       0 |              0 |
| LEVERAGE2            |   184.7771 |       11.1456 |       19 |      0 |      61 |              0 |
| LEVERAGE5            |  2950.2461 |       27.2264 |       63 |      1 |       0 |              0 |
| NO_ADDS              | 48805.2532 |       49.4471 |       63 |      0 |       0 |              0 |
| SEGMENT_2019_2022    |  5410.2474 |       47.9211 |       29 |      8 |       0 |              0 |
| SEGMENT_2023_2024    |   824.9366 |       30.4196 |       21 |      0 |       0 |              0 |
| SEGMENT_2025_OCT2026 |   100.0000 |        0.0000 |        0 |      0 |      19 |              0 |

## Pembanding ruang DD

Pilihan tertinggi yang direplay untuk DD<45:

|          id |   equity |   floating_dd |   risk |   margin_fraction |   stop_atr |   tp_R |   hold_bars |   add_stages |   breakeven_R |
|------------:|---------:|--------------:|-------:|------------------:|-----------:|-------:|------------:|-------------:|--------------:|
| 2.06558e+06 |  29152.4 |       44.3165 |   0.36 |              0.37 |          2 |     16 |          32 |            2 |             0 |

| case                 |     equity |   floating_dd |   trades |   skips |
|:---------------------|-----------:|--------------:|---------:|--------:|
| BASE                 | 29152.3621 |       44.3165 |       63 |       0 |
| COST1_5              | 20562.3103 |       45.3548 |       63 |       0 |
| COST2                | 16754.3224 |       46.6185 |       63 |       0 |
| DELAY_NEXT_M1        | 14454.7014 |       44.2112 |       64 |       0 |
| LEVERAGE2            |   174.4351 |       11.7978 |       19 |      61 |
| LEVERAGE5            |  1807.8479 |       24.2255 |       63 |       0 |
| NO_ADDS              | 25951.6563 |       44.2204 |       63 |       0 |
| SEGMENT_2019_2022    |  3733.7209 |       42.8698 |       29 |       0 |
| SEGMENT_2023_2024    |   757.9810 |       21.0691 |       21 |       0 |
| SEGMENT_2025_OCT2026 |   100.0000 |        0.0000 |        0 |      19 |

Pilihan tertinggi yang direplay untuk DD<48:

|          id |   equity |   floating_dd |   risk |   margin_fraction |   stop_atr |   tp_R |   hold_bars |   add_stages |   breakeven_R |
|------------:|---------:|--------------:|-------:|------------------:|-----------:|-------:|------------:|-------------:|--------------:|
| 2.06584e+06 |  43656.7 |        47.772 |    0.4 |              0.41 |          2 |     16 |          32 |            2 |             0 |

| case                 |     equity |   floating_dd |   trades |   skips |
|:---------------------|-----------:|--------------:|---------:|--------:|
| BASE                 | 43656.6890 |       47.7720 |       63 |       0 |
| COST1_5              | 32997.6552 |       48.9110 |       63 |       0 |
| COST2                | 24368.4491 |       50.3925 |       63 |       0 |
| DELAY_NEXT_M1        | 20124.0740 |       47.8136 |       64 |       0 |
| LEVERAGE2            |   184.7771 |       11.1456 |       19 |      61 |
| LEVERAGE5            |  2643.2161 |       25.8476 |       63 |       0 |
| NO_ADDS              | 39733.3740 |       47.7475 |       63 |       0 |
| SEGMENT_2019_2022    |  4753.3681 |       46.3680 |       29 |       0 |
| SEGMENT_2023_2024    |   802.5089 |       25.9677 |       21 |       0 |
| SEGMENT_2025_OCT2026 |   100.0000 |        0.0000 |        0 |      19 |

Semua kasus biaya/latensi memakai parameter terkunci. Segment2019–22/2023–24/2025–Okt2026 masing-masing restartUSD100; bukan OOS tak tersentuh. Seluruh periode dipakai seleksi, sehingga hasil ini optimasi historis dan rentan overfit. Batas DD<50 disaring pada BASE, bukan jaminan untuk skenario stres atau masa depan.

Model tetap: Bitstamp M1 OHLC resmi, bukan tick bid/ask broker. Leverage10 hipotesis; margin linear, minimum/step0.01BTC,max100BTC. Spread5bp,slippage1bp/sisi,komisi5bp/sisi,financing debit3bpnotional/hari. COST1_5/2 mengalikan fee/slip/carry, bukan spread. Delay NEXT_M1 minimum satu menit, bukan2detik. Financing long/short sama sesuai model sebelumnya, bukan spesifikasi broker yang dibuktikan.

DD model diperiksa tiapM1 dengan urutan intrabar konservatif/stop-first. Grafik hanya snapshotperjam, angka DD acuan dari tabel fullM1. Stop gap memakai open yang lebih buruk. BE mulai berlaku barnext. Bila layering, initialrisk40%,adds pada25/50%kedalamanstop lalu barnext; risk bukan persen kerugian pasti. NO_ADDS mengalokasikan100%initialrisk sehingga bukan ablation volume tetap. ModelSL/TP mendahului fallbackstopout; ACK/recovery/partialfills/dynamicbrokerleverage tidak divalidasi. Capital-floor permanen source dipertahankan. Tidak ada DDclamp, penghentian setelah target, reset atau top-up.

Pembanding pencarian sebelumnya: D1 structure_break USD56,582.38/DD46.75%; keluarga berbeda, bukan hasil perubahan692365. USD1juta tidak dijamin tetap tercapai dengan DD<50. Hasil standaloneBTC tidak membuktikan DD atau saldo portfolio equity bersama XAU–EUR. Profit tinggi harus diuji lagi dengan spesifikasi broker dan tick independen.

Artefak: seluruh konfigurasi, source asli+diff parameter, protokol, parity fixture, ledger semua kasus terpilih, kas,perbulan/pertahun,grafik,checksum. CanonicalinputCSV SHA256 c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504; archiveSHA1995e8a40f9fd7af043e35ae62d0b5c8bc999f3f7576f795ad8750362c210d34, Actions39233081519.
