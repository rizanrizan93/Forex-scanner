# RIZAN — Validasi gabungan EUR/BTC R2

Tanggal: 28 Oktober 2026. BUFFER V1 dipertahankan; tidak ada perubahan LIVE.

Kriteria portofolio dan kenaikan PnL instrumen pada jalur normal: **LULUS**.
Interpretasi konservatif yang juga mewajibkan kenaikan PnL EUR/BTC pada semua stress: **GAGAL**. Perbandingan lengkap di bawah menjelaskan perbedaannya.

|Jalur|Biaya|Saldo akhir USD|Max DD %|PF|Win rate basket %|Basket|Opening order|
|---|---:|---:|---:|---:|---:|---:|---:|
|A|1×|1,051,126,595.70|65.837313|2.647051|49.572650|585|119955|
|B|1×|992,612,612.15|65.886012|2.562260|49.914237|583|120205|
|A|1.5×|977,009,626.73|67.794592|2.645233|49.143836|584|106980|
|B|1.5×|922,340,948.45|68.073176|2.559201|49.399657|583|106943|
|A|2×|896,369,444.82|72.064348|2.638552|48.801370|584|94768|
|B|2×|843,903,457.61|72.112588|2.533447|48.885077|583|96355|

## Kriteria yang dibekukan

- control_r2_full_parity: PASS
- full_audits: PASS
- six_scenarios: PASS
- normal_A_improves: PASS
- normal_B_improves: PASS
- worst_dd_ceiling: PASS
- cost2_floor: PASS
- normal_A_EURUSD_pnl_improves: PASS
- normal_A_BTCUSD_pnl_improves: PASS
- normal_B_EURUSD_pnl_improves: PASS
- normal_B_BTCUSD_pnl_improves: PASS
- own_pnl_A_cost1_EURUSD_improves: PASS
- own_pnl_A_cost1_BTCUSD_improves: PASS
- own_pnl_A_cost1.5_EURUSD_improves: FAIL
- own_pnl_A_cost1.5_BTCUSD_improves: PASS
- own_pnl_A_cost2_EURUSD_improves: FAIL
- own_pnl_A_cost2_BTCUSD_improves: PASS
- own_pnl_B_cost1_EURUSD_improves: PASS
- own_pnl_B_cost1_BTCUSD_improves: PASS
- own_pnl_B_cost1.5_EURUSD_improves: FAIL
- own_pnl_B_cost1.5_BTCUSD_improves: PASS
- own_pnl_B_cost2_EURUSD_improves: FAIL
- own_pnl_B_cost2_BTCUSD_improves: PASS

## Perbandingan dengan BUFFER V1

|Jalur|Biaya|Selisih saldo akhir USD|Selisih Max DD poin persentase|
|---|---:|---:|---:|
|A|1×|+62,379,178.43|+0.563736|
|B|1×|+54,146,411.93|+0.988449|
|A|1.5×|+30,054,331.77|+0.317055|
|B|1.5×|+25,094,094.87|+0.127169|
|A|2×|+2,302,625.32|+0.061893|
|B|2×|+1,049,799.99|-0.100616|

Sumber serta parameter XAU identik dengan beku. Selisih PnL XAU tetap dapat terjadi melalui equity, sizing, pengisian, dan perebutan margin shared wallet. Selisih per instrumen adalah dekomposisi hasil, bukan pembuktian sebab tunggal. Syarat kenaikan PnL EUR/BTC dibaca konservatif untuk keenam skenario terhadap jalur dan biaya yang sama, karena master prompt tidak menyebut pengecualian stress. Kriteria normal dipisahkan agar perbedaan interpretasi terlihat; ambang saldo dan DD tidak diubah. Semua perbandingan tersedia dalam COMBINED_PNL_COMPARISON.csv.

## Kontribusi dan timing

|Jalur|Biaya|XAU PnL USD|EUR PnL USD|BTC PnL USD|First fill maks detik|BTC child maks detik|Risiko maks %|Margin maks %|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|A|1×|1,006,395,715.42|20,926,994.17|23,803,786.10|6.0|140.0|24.286240|56.032226|
|B|1×|946,396,113.32|22,212,905.86|24,003,492.97|6.0|162.0|24.269503|56.319329|
|A|1.5×|949,059,454.16|14,032,253.60|13,917,818.97|6.0|140.0|24.314465|56.434300|
|B|1.5×|893,038,192.91|14,864,836.53|14,437,819.00|6.0|162.0|24.289217|56.420027|
|A|2×|881,574,704.63|8,421,911.18|6,372,729.01|6.0|140.0|24.327368|56.447877|
|B|2×|827,750,328.96|9,393,798.81|6,759,229.84|6.0|162.0|24.314421|56.537012|

## Saldo akhir tahunan normal

|Tahun|Jalur A USD|Jalur B USD|
|---|---:|---:|
|2019|6,405.15|5,463.95|
|2020|100,582.97|86,053.09|
|2021|781,018.53|728,583.21|
|2022|2,626,157.16|2,561,954.35|
|2023|9,081,240.31|8,342,518.20|
|2024|58,603,473.34|57,126,191.18|
|2025|397,381,028.62|396,491,796.80|
|2026 parsial|1,051,126,595.70|992,612,612.15|

## EUR saat biaya 2x

|Jalur|Order BUFFER|Order kandidat|Delta gross USD|Delta komisi dan funding USD|Delta net EUR USD|
|---|---:|---:|---:|---:|---:|
|A|23168|40992|-1,104,596.81|-3,874,802.76|-4,979,399.57|
|B|24011|42120|+23,263.51|-3,933,669.24|-3,910,405.73|

GrossProfit sudah mencakup efek harga eksekusi, spread dan slippage; tabel tidak mengisolasi slippage sebagai biaya eksplisit. Dekomposisi ini merekonsiliasi perubahan net PnL, tetapi tidak memisahkan sebab parameter EUR, BTC, dan jalur compounding tanpa eksperimen tambahan.

## Batas kesimpulan

Modal $100, tanpa top-up, 2019-01-01 sampai cutoff 2026-10-09T21:59:00Z. Satu wallet, model leverage 1:200. Biaya stress hanya komisi/slippage/funding; spread tetap. Dua jalur OHLC M1 sintetis dan delay broker 2 detik. Bukan native tick, hasil LIVE, pengujian OOS, atau bukti kapasitas likuiditas broker. Macro belum tersertifikasi point-in-time vintage. Risiko dan margin maksimum teramati dapat melampaui cap saat sizing.

Data tahunan semua skenario ada di COMBINED_ANNUAL.csv; 94 bulan cash PnL per skenario ada di COMBINED_MONTHLY.csv. PnL basket berdasarkan bulan entry terpisah dalam AGGREGATED_HISTORY.json. Audit dan kontrol field lengkap disimpan sebagai JSON. Rincian distribusi waktu ada dalam COMBINED_TIMING.csv.

Dua upaya pemuatan input gagal karena memori. Pengulangan terakhir B biaya2x juga diperlukan setelah lingkungan terputus sebelum laporan akhir. Semua pengulangan memakai konfigurasi, input dan DLL yang sama; lima hasil lengkap tidak diulang saat lingkungan terputus. Hanya hasil lengkap yang diaudit masuk penilaian. Pemakaian ulang hasil oleh penjadwal tidak dihitung sebagai replay baru.

Kandidat tidak menggantikan BUFFER V1 dan tidak dipromosikan ke LIVE.


Paket lengkap kode, ledger mentah, audit dan input BTC: [RIZAN_R2_COMBINED_VALIDATION_20261028.zip](https://chatgpt.com/library?file_id=libfile_583f19ae940c8191a192731d6e8c7274&account_id=personal).
