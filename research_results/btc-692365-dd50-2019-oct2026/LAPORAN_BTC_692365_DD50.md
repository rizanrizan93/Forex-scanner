# BTC 692365 — pencarian saldo tertinggi dengan floating DD <50%

Akun standalone USD100, tanpa top-up;2019-01-01 sampai2026-10-15. Sinyal H4 displacement BUY, trend H4, threshold0.2 dan sesi UTC00–08 tetap. Parameter risk/margin, stop,TP,holding,layering dan BE dioptimasi sebagai konfigurasi riset baru. Strategi XAU–EUR/live tidak diubah.

Diuji 34,340 konfigurasi unik. Baseline692365 direproduksi sebelum pencarian: saldo dan DD toleransi ketat,63basket. Seluruh hasil pilihan direplay ulang dan ledger semua skenario direkonsiliasi independen.

| label                |      id |       equity |   floating_dd |   balance_dd |     pf |   trades |   win_rate |   adds |   skips |   liquidations |
|:---------------------|--------:|-------------:|--------------:|-------------:|-------:|---------:|-----------:|-------:|--------:|---------------:|
| BEFORE_692365        | 2000001 | 1005025.5238 |       67.9209 |      57.1607 | 1.4052 |       63 |    52.3810 |     36 |       0 |              0 |
| AFTER_DD_LT50        | 2020724 |   48153.1206 |       49.9301 |      47.1585 | 1.6082 |       66 |    68.1818 |     45 |       0 |              0 |
| SECONDARY_DD_50_TO55 | 2020348 |   98286.5775 |       54.8317 |      51.7090 | 1.4449 |       63 |    55.5556 |      0 |       0 |              0 |

## Konfigurasi dan sensitivitas pilihan DD<50

|          id |   stop_atr |   tp_R |   hold_bars |   risk |   margin_fraction |   add_stages |   breakeven_R |
|------------:|-----------:|-------:|------------:|-------:|------------------:|-------------:|--------------:|
| 2.02072e+06 |          2 |     16 |          32 |   0.25 |               0.6 |            2 |             1 |

| case                 |      equity |   floating_dd |   trades |   adds |   skips |   liquidations |
|:---------------------|------------:|--------------:|---------:|-------:|--------:|---------------:|
| BASE                 |  48153.1206 |       49.9301 |       66 |     45 |       0 |              0 |
| COST1_5              |  36825.9184 |       51.4607 |       67 |     47 |       0 |              0 |
| COST2                |  14250.5376 |       52.5557 |       68 |     49 |       0 |              0 |
| DELAY_NEXT_M1        |  15049.4261 |       49.8362 |       66 |     45 |       0 |              0 |
| LEVERAGE2            |    314.9946 |       16.9049 |       33 |      0 |      44 |              0 |
| LEVERAGE5            |   7417.6723 |       40.0821 |       66 |     12 |       0 |              0 |
| NO_ADDS              | 134683.1612 |       66.2112 |       66 |      0 |       0 |              0 |
| SEGMENT_2019_2022    |   7278.3874 |       49.9301 |       31 |     22 |       0 |              0 |
| SEGMENT_2023_2024    |    364.6658 |       34.6760 |       22 |     11 |       0 |              0 |
| SEGMENT_2025_OCT2026 |    100.0000 |        0.0000 |        0 |      0 |      19 |              0 |

Semua kasus biaya/latensi memakai parameter terkunci. Segment2019–22/2023–24/2025–Okt2026 masing-masing restartUSD100; bukan OOS tak tersentuh. Seluruh periode dipakai seleksi, sehingga hasil ini optimasi historis dan rentan overfit. Batas DD<50 disaring pada BASE, bukan jaminan untuk skenario stres atau masa depan.

Model tetap: Bitstamp M1 OHLC resmi, bukan tick bid/ask broker. Leverage10 hipotesis; margin linear, minimum/step0.01BTC,max100BTC. Spread5bp,slippage1bp/sisi,komisi5bp/sisi,financing debit3bpnotional/hari. COST1_5/2 mengalikan fee/slip/carry, bukan spread. Delay NEXT_M1 minimum satu menit, bukan2detik. Financing long/short sama sesuai model sebelumnya, bukan spesifikasi broker yang dibuktikan.

DD model diperiksa tiapM1 dengan urutan intrabar konservatif/stop-first. Grafik hanya snapshotperjam, angka DD acuan dari tabel fullM1. Stop gap memakai open yang lebih buruk. BE mulai berlaku barnext. Bila layering, initialrisk40%,adds pada25/50%kedalamanstop lalu barnext; risk bukan persen kerugian pasti. NO_ADDS mengalokasikan100%initialrisk sehingga bukan ablation volume tetap. ModelSL/TP mendahului fallbackstopout; ACK/recovery/partialfills/dynamicbrokerleverage tidak divalidasi. Capital-floor permanen source dipertahankan. Tidak ada DDclamp, penghentian setelah target, reset atau top-up.

Pembanding pencarian sebelumnya: D1 structure_break USD56,582.38/DD46.75%; keluarga berbeda, bukan hasil perubahan692365. USD1juta tidak dijamin tetap tercapai dengan DD<50. Hasil standaloneBTC tidak membuktikan DD atau saldo portfolio equity bersama XAU–EUR. Profit tinggi harus diuji lagi dengan spesifikasi broker dan tick independen.

Artefak: seluruh konfigurasi, source asli+diff parameter, protokol, parity fixture, ledger semua kasus terpilih, kas,perbulan/pertahun,grafik,checksum. CanonicalinputCSV SHA256 c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504; archiveSHA1995e8a40f9fd7af043e35ae62d0b5c8bc999f3f7576f795ad8750362c210d34, Actions39233081519.
