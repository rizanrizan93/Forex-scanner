# RIZAN — Profit Exit Challenger V3

21 Oktober2026 · `RZ-PROFIT-EXIT-V3-20261021` · **RESEARCH ONLY**

**Belum ditemukan exit challenger dengan peningkatan profit yang dapat dinyatakan tervalidasi.** Eksperimen ini menguji cara exit dengan entry dan risiko awal tetap. Semua hasil berikut benar-benar dihitung dari quote/tape yang dibaca. Tidak ada perubahan cBot beku, bridge, trading live atau merge ke main.

## Keputusan sebelum hasil tanggal baru

Delapan exit dikunci dalam `LOCKED_PROTOCOL_V3.json`, SHA256 `ca8d66734a1fce0242761d920a327c0b0cfa8882e6ca1a96bd253dc7fe8dba20`. Entry tetap **zona H1 + absorption awal V2**: detektor zona, first-touch, sweep, threshold volume15s, arrival timestamp dan stop awal tidak dituning. Risk awal dan leverage tidak dinaikkan untuk membuat profit lebih tinggi. H4 dicatat sebagai konteks, bukan filter tambahan. Tidak ada layering atau compounding akun di model ini.

Pemilihan hanya memakai **1Feb dan1Mar2024**. **1Apr dan1Mei** sudah pernah dilihat dan dilabeli `seen_diagnostic`, tidak dipakai sebagai bukti out-of-sample baru. Sebelum outcome baru direplay, pilihan `BASE_1R_60` sudah disimpan pada commit [d0fa290ba82563bc9a2573d47a7567be6ffff9d1](https://github.com/rizanrizan93/Forex-scanner/commit/d0fa290ba82563bc9a2573d47a7567be6ffff9d1). Hash file pilihan diperiksa tidak berubah setelah validasi. Lulus screen train bukan kualifikasi live.

Kriteria pemilihan: minimal5 transaksi satu-posisi pada train, mean netR>0 danPF>1 pada biaya1× dan1,5×; urutkan profit per peluang yang sama pada1,5×, lalu drawdown kumulatifR lebih kecil. Jika tidak ada yang lolos, hanya boleh mencatat kandidat diagnostik gagal. Pada sampel train kecil ini, pilihan aktual adalah `BASE_1R_60`, screen train `True`.

## Data baru yang diperoleh dan digunakan

- Venue: **Bybit linear BTCUSDT perpetual**, bukan BTCUSD CFD, XAUUSD atau EURUSD broker.
- Empat tanggal baru: **1Jul,1Agu,1Okt,1Nov2024 UTC**, ditetapkan sebelum download/outcome; semuanya hari kerja. Ini **empat hari**, bukan periode Juli–November penuh.
- Setiap tanggal memakai3 hari pemanasan L2 sebelumnya: total16 arsip L2 baru, **13,817,054 pesan**.
- Tape baru: **7,776,576 transaksi unik**, dengan sisi aggressor dan arrival timestamp. Total ukuran20 input baru: **3,837,964,750 byte**. Duplikat, lag dan coverage perhari ada di `NEW_DATA_QUALITY.json`.
- Semua ZIP dibaca penuh untuk CRC, tape gzip dibaca penuh; SHA256 dan URL asli ada di `NEW_INPUT_MANIFEST.json`. Quote invalid: **55 detik** di16 hari L2; tidak diimputasi. Snapshot/delta diproses sebelum sampling1detik.
- Transaksi baru tersedia setelah arrival. Untuk arsip L2 tanpa arrival, tetap memakai asumsi publikasi+1detik V2, bukan latency broker terukur.

Sumber: [Tardis Bybit](https://docs.tardis.dev/historical-data-details/bybit) dan arsip L2 Bybit di manifest. Hari pertama bulan tersedia sebagai sampel publik; pemilihan hari merupakan convenience sample, bukan sampel acak. Tidak ada akun Bookmap resmi, data CME berlisensi atau pembayaran yang diaktifkan. Hasil tidak berlaku otomatis pada XAU/EUR.

## Exit yang diuji

| ID | Exit | Batas waktu |
| --- | --- | --- |
| BASE_1R_60 | TP1R, stop awal tetap |60menit |
| TP15_60 | TP1,5R, stop awal tetap |60menit |
| TP2_120 | TP2R, stop awal tetap |120menit |
| STRUCT_CAP2_120 | Target=min(2R,batas H1 lawan yang sudah diketahui); fallback2R jika tidak tersedia/di belakang entry |120menit |
| PARTIAL_1R_2R_120 | Tutup50% saat1R, sisa ke2R/stop/waktu |120menit |
| BE_AFTER1R_TP2_120 | Setelah1R, stop pindah ke harga entry, efektif quote berikutnya |120menit |
| TRAIL075_AFTER1R_TP2_120 | Setelah1R, stop mengikuti peak yang sudah teramati dikurangi0,75R, efektif quote berikutnya |120menit |
| TIME_PROTECT_TP2_120 | Pada menit30, tutup jika MFE<0,5R; selain itu lanjut2R/stop |120menit |

BE harga entry tetap membayar biaya sehingga bisa rugi net. Partial exit tidak mendapat entry gratis: entry fee dikenakan sekali pada volume awal, exit fee dan financing dibebankan proporsional volume/durasi. Trailing tidak boleh memakai peak masa depan atau mengangkat stop secara retroaktif pada quote yang sama. Target struktural tidak dipindah setelah melihat masa depan.

Entry memakai ask untukBUY danbid untukSELL; exit memakai sisi executable sebaliknya pada sampel quote. Spread sudah terkandung dalam harga tersebut. Fee5,5bp/sisi, slippage debit1bp/sisi, financing debit3bp notional/hari. Biaya1,5× dan2× mengalikan fee/slippage/financing, **tidak mengalikan spread**. Ini asumsi debit biaya, bukan tarif FP tersertifikasi, funding settlement aktual, limit queue atau market-impact stress. Tidak ada perubahan fill karena biaya alternatif.

## Audit kontrol dan cohort

Paket V2 asli dipulihkan dari ZIP SHA256 `43ce4bf3874045adb4f0d78be45d669346db50c0ee80766346432e808fc4b1ae`;86 anggota ber-manifest diperiksa. `V2_REPRODUCTION_AUDIT.json` menunjukkan entry/exit, grossR, costR dan netR lama direproduksi tanpa selisih pada sinyal yang cocok. Source V2 dan strategi beku tidak diubah.

Untuk perbandingan utama semua exit, setiap entry harus mempunyai120menit quote lengkap tanpa gap. Ini filter **ketersediaan data offline**, bukan syarat entry live yang dapat mengetahui koneksi masa depan. Semua signal/exclusion tetap tersimpan di ledger; tidak memilih cohort berdasarkan untung/rugi. Batas ini menghindari pembanding60/120menit memakai peluang yang berbeda di ujung arsip. Model V2 langsung menyensor saat horizon melewati ujung dataset, bahkan jika terminal mungkin terjadi lebih awal; kontrol direproduksi apa adanya dan primary common cohort menghindari boundary tersebut.

Event study pada entry sama dan satu-posisi per exit dilaporkan terpisah. Durasi exit berbeda bisa membuat transaksi berikutnya terlewat; karena itu profit kumulatif dan profit per peluang juga disajikan, bukan hanya win rate transaksi yang tersisa. Skenario exit berbeda tidak boleh dijumlahkan sebagai satu portfolio.

## Ranking train yang dipakai sebelum validasi

| policy | training_screen_pass | n | train_mean_R_1x | train_mean_R_15x | rank_profit_per_opportunity_15x |
| --- | --- | --- | --- | --- | --- |
| BASE_1R_60 | True | 6 | 0.1456 | 0.0581 | 0.0498 |
| TP15_60 | False | 6 | 0.0005 | -0.0870 | -0.0746 |
| PARTIAL_1R_2R_120 | False | 6 | -0.3681 | -0.4563 | -0.3911 |
| TIME_PROTECT_TP2_120 | False | 7 | -0.3214 | -0.4044 | -0.4044 |
| TRAIL075_AFTER1R_TP2_120 | False | 6 | -0.4252 | -0.5134 | -0.4400 |
| STRUCT_CAP2_120 | False | 6 | -0.4305 | -0.5188 | -0.4447 |
| TP2_120 | False | 6 | -0.4305 | -0.5188 | -0.4447 |
| BE_AFTER1R_TP2_120 | False | 6 | -0.4803 | -0.5686 | -0.4874 |

## Hasil tanggal baru — satu posisi per exit, biaya normal

| policy | n | wins | win_pct | sum_net_R | mean_net_R | PF_R | max_cumulative_R_DD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BASE_1R_60 | 11 | 3 | 27.2727 | -4.1464 | -0.3769 | 0.2614 | 4.1464 |
| BE_AFTER1R_TP2_120 | 11 | 2 | 18.1818 | -6.4557 | -0.5869 | 0.2240 | 6.4557 |
| PARTIAL_1R_2R_120 | 11 | 2 | 18.1818 | -6.7271 | -0.6116 | 0.1691 | 6.7271 |
| STRUCT_CAP2_120 | 11 | 2 | 18.1818 | -7.0869 | -0.6443 | 0.2082 | 7.0869 |
| TIME_PROTECT_TP2_120 | 11 | 3 | 27.2727 | -4.1253 | -0.3750 | 0.3202 | 4.1253 |
| TP15_60 | 11 | 2 | 18.1818 | -4.2356 | -0.3851 | 0.2550 | 4.2356 |
| TP2_120 | 11 | 2 | 18.1818 | -7.0869 | -0.6443 | 0.2082 | 7.0869 |
| TRAIL075_AFTER1R_TP2_120 | 11 | 2 | 18.1818 | -6.0086 | -0.5462 | 0.2367 | 6.0086 |

Baseline pada data baru: **11 transaksi, win27.27%, total-4.1464R, mean-0.3769R**. Baris seluruh alternatif tetap ditampilkan. Alternatif dengan total normal tertinggi pada data baru adalah `TIME_PROTECT_TP2_120` dengan-4.1253R; ini **observasi post-hoc**, tidak menggantikan kandidat yang sudah dikunci atau menjadi bukti validasi kandidat tersebut.

## Apa yang menjelaskan kerugian sampel baru

Seluruh delapan exit masih mencatat total negatif pada empat tanggal baru. Kandidat yang dikunci sebelum replay juga gagal pada sampel baru. Time-protect hanya memperbaiki total normal sekitar 0,0212R terhadap baseline; perubahan sekecil ini pada 11 transaksi tidak cukup untuk menyatakan peningkatan profit konsisten.

Baseline sudah menghasilkan **-1.2431R sebelum debit komisi/slippage/financing**, lalu debit tersebut menambah **2.9033R** sehingga net menjadi **-4.1464R**. Spread aktual sampel bid/ask sudah termasuk gross. Jadi kerugian tidak bisa dijelaskan hanya oleh biaya. Rata-rata debit tambahan adalah **0.2639R per transaksi**; ini berarti biaya cukup besar relatif terhadap jarak stop awal.

| reason | n | gross_R | net_R |
| --- | --- | --- | --- |
| STOP | 4 | -4.1745 | -4.9449 |
| TARGET | 2 | 2.0721 | 1.2718 |
| TIMEOUT | 5 | 0.8593 | -0.4734 |

Kelompok timeout mempunyai gross positif tetapi net negatif setelah biaya. Stop yang gagal mengimbangi target juga memberi kontribusi rugi. Ini diagnosis pada sampel, bukan bukti penyebab universal atau alasan untuk menyaring transaksi rugi setelah melihat hasil. Entry H1 + absorption awal belum menunjukkan keunggulan yang bertahan pada empat hari baru. Menaikkan TP atau leverage tidak memperbaiki bukti tersebut.

## Stress untuk kandidat terpilih

| policy | cost_multiple | n | win_pct | sum_net_R | mean_net_R | PF_R |
| --- | --- | --- | --- | --- | --- | --- |
| BASE_1R_60 | 1.0000 | 11 | 27.2727 | -4.1464 | -0.3769 | 0.2614 |
| BASE_1R_60 | 1.5000 | 11 | 27.2727 | -5.5981 | -0.5089 | 0.1360 |
| BASE_1R_60 | 2.0000 | 11 | 18.1818 | -7.0497 | -0.6409 | 0.0627 |

Tabel biaya semua alternatif ada di `COMPARISON.csv`. Bila biaya membuat meanR negatif atau sampel tidak memadai, kandidat tidak boleh dipromosikan hanya karena hasil normal/angka win rate tampak baik.

## Efek exit pada entry yang identik

| policy | matched_events | base_same_entries_mean_R | challenger_mean_R | mean_exit_delta_R | sum_exit_delta_R |
| --- | --- | --- | --- | --- | --- |
| BASE_1R_60 | 11 | -0.3769 | -0.3769 | 0.0000 | 0.0000 |
| BE_AFTER1R_TP2_120 | 11 | -0.3769 | -0.5869 | -0.2099 | -2.3093 |
| PARTIAL_1R_2R_120 | 11 | -0.3769 | -0.6116 | -0.2346 | -2.5806 |
| STRUCT_CAP2_120 | 11 | -0.3769 | -0.6443 | -0.2673 | -2.9405 |
| TIME_PROTECT_TP2_120 | 11 | -0.3769 | -0.3750 | 0.0019 | 0.0212 |
| TP15_60 | 11 | -0.3769 | -0.3851 | -0.0081 | -0.0892 |
| TP2_120 | 11 | -0.3769 | -0.6443 | -0.2673 | -2.9405 |
| TRAIL075_AFTER1R_TP2_120 | 11 | -0.3769 | -0.5462 | -0.1693 | -1.8622 |

Ini mengisolasi perubahan exit pada peluang yang sama. Sementara tabel satu-posisi di atas juga mencakup efek transaksi terlewat karena hold lebih lama. Risiko awal setiap posisi tetap; angka R tidak sama dengan persen return akun.

## Rekonsiliasi dan batas kesimpulan

- Skenario lengkap: **195**; status seluruh baris ada di audit, termasuk censor/gap.
- Pemeriksaan fraction partial menjumlah1, cash gross/net dan fee perleg lulus. Residual cash absolut maksimum **5.68434188608e-14 USD perBTC awal**. Entry setelah keputusan dan zona tersedia sebelum touch diperiksa.
- Flag `structural_target_used` menunjukkan batas lawan tersedia; jumlah yang betul-betul menurunkan cap2R dilaporkan terpisah dalam `structural_binding_events`. Banyak fallback berarti bukan seluruh observasi menguji target struktural murni.
-15 tes V3 lulus dan12 tes baselineV2 lulus secara terpisah. Tidak ada klaim CI native/full parity atau rekaman semua paket tanpa kehilangan.
- Pemilihan sudah dikunci sebelum empat tanggal baru, tetapi train hanya dua tanggal dan kandidat entry berasal dari riset historis sebelumnya. Sampel baru ini belum cukup untuk menyatakan edge stabil di seluruh regime atau signifikan setelah banyak percobaan.
- Drawdown adalah penurunan kumulatifR, **bukan floating equity DD persen akun**. Tidak ada saldo akhir, leverage, margin bersama, layering atau compounding yang disimulasikan; tidak boleh memindahkan hasil ke statistik cBot portfolio.
- Tidak ada jaminan hasil masa depan. XAU/EUR membutuhkan L2/trades sesuai dan basis/roll yang diaudit jika memakaiGC/6E. Eksperimen ini hanya BTCUSDT Bybit.

## Berkas dan reproduksi

`EXIT_LEDGER.csv`, `FILL_LEDGER.csv`, `ONE_POSITION_LEDGER.csv`, `MATCHED_ENTRY_EXIT_ABLATION.csv`, `DAILY.csv`, `DIRECTION_CONTRIBUTIONS.csv`, protokol, pilihan train, audit, source dan grafik disertakan. Paket menyertakan input turunan quote/tape yang digunakan, sehingga replay bisa diulang tanpa download mentah lagi. Raw baru tetap terpisah; URL/hash tersimpan untuk merekonstruksi setiap delta.

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest test_profit_engine -v
python3 profit_engine.py old
# Pilihan dibuat oleh stage old; jangan ubah setelah membaca stage new.
python3 profit_engine.py new
python3 audit_profit.py
MPLBACKEND=Agg python3 plot_results.py
python3 build_report.py
# Jika ingin rekonstruksi data baru dari raw:
python3 new_inputs.py
```

Source dan hasil ada di branch riset tersendiri. cBot beku, bridge, `.env` produksi, risk live dan state eksekusi tidak disentuh; tidak merge ke main.
