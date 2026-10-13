# Riset reversal utama harian XAU — 13 Oktober 2026

**Hasil: belum ditemukan konfigurasi yang memenuhi seluruh kriteria profit bersih dan kestabilan.**
Status akhir `RESEARCH_ONLY`. Tidak ada konfigurasi yang dipromosikan menjadi zona entry/TP/SL utama harian. Tujuan menemukan konfigurasi yang lebih profit belum tercapai untuk keluarga pola yang diuji.

## Cakupan dan sumber

- Scanner saja; tidak memiliki authority atau influence untuk execution cBot.
- Contract penelitian: `RIZAN_XAU_MAJOR_DAILY_REVERSAL_NET_V6`.
- 10.000.000 kombinasi parameter pada replay 2016–2025; kombinasi dapat berbagi keputusan yang sama. Ini bukan 10 juta strategi independen.
- 3.492.721 bar M1 pada tahun-tahun tersebut; masing-masing shard juga memuat warm-up sebelum tahun dan buffer setelah tahun. Hanya trigger pada tahun shard yang dihitung.
- Data historis bid M1 HistData. SHA256 setiap file sumber dan rentang UTC ada di [hasil lengkap](../calibration/major_reversal_results.json).
- Data 2016–2021 untuk training; 2022–2025 untuk validation. Riwayat 2024–2025 sudah pernah dilihat; tidak diperlakukan sebagai holdout yang belum tersentuh.
- Rolling walk-forward 2020–2025 memilih hanya dari tahun sebelum tahun test; semua fold tidak memilih kandidat. Desain keluarga pola tetap eksploratif.
- Pipeline Januari–September 2026 berjalan setelah candidate lock, tetapi kandidat kosong. **Tidak ada hasil trade kandidat pada 2026 yang dapat diklaim sebagai bukti validasi.**
- Event/macro tidak dimasukkan: belum ada dataset historical dengan waktu publikasi pertama yang diverifikasi untuk pengujian ini.

## Definisi zona dan pengujian

| Dimensi | Nilai yang diuji |
|---|---|
| Arah | BUY / SELL |
| Sumber | Re-entry regression channel M5 24/32/48/64 bar; sweep/reclaim M5 24 bar dengan konfirmasi breakout |
| Lebar setengah zona | 0; 0,1; 0,2; 0,35; 0,5 ATR H1 |
| SL di luar anchor zona | 0,5; 0,75; 1; 1,5; 2 ATR H1 |
| Target dari harga entry | 1,5; 2; 3; 4; 6 ATR H1 |
| Batas holding | 120; 240; 360; 480 menit |
| Minimum wick fraction | 0; 0,1; 0,2; 0,3; 0,4 |
| Konteks trend H1/M15 | ANY / ALIGNED / OPPOSED / FLAT |
| Minimum approach | 0; 0,5; 1; 1,5; 2 ATR |
| Minimum net reward/risk | 1,5; 2; 2,5; 3; 4 |
| Sesi WIB | 07–13; 13–19; 19–01; 01–07 |

Target minimal 25% ADR20 dari hari yang sudah selesai. Target dalam ATR tidak sama dengan R: risiko aktual bergantung jarak harga fill terhadap SL anchor. ATR H1 menggunakan periode 20 pada fitur dasar.

Entry pada open M1 setelah trigger M5 selesai. Regression channel menggunakan fitted endpoint dan population standard deviation harga close, dengan band periode sebelumnya yang sudah diketahui. Konteks H1/M15 menggunakan bar tertutup dan EMA200/arah EMA50. Fitur yang tersedia hanya sesudah trigger tidak boleh dipakai sebelum trigger.

Satu trigger **pertama yang eligible untuk masing-masing konfigurasi** per hari UTC dalam sesi terpilih. Filter wick/trend/approach/net-RR diterapkan sebelum memilih trigger. Trigger pertama yang kemudian censored tetap mengklaim hari tersebut; tidak diganti oleh trigger yang hasilnya baru diketahui di masa depan. Ini membatasi frekuensi, bukan menjamin ada reversal setiap hari.

Trade ditutup paling lambat 20:55 UTC untuk menghindari holding overnight. Pada timeout diperlukan bar tepat di deadline dan fill memakai open bar tersebut. Gap data >300 detik atau deadline yang hilang menjadi censored. Bila TP dan SL tersentuh dalam M1 yang sama, SL diprioritaskan. Stop dengan gap merugikan dapat menghasilkan kerugian lebih dari 1R.

## Model biaya

| Skenario | Spread XAUUSD | Slippage tiap sisi |
|---|---:|---:|
| Reference | 0,25 | 0,05 |
| Cautious, ranking utama | 0,50 | 0,10 |
| Stress | 1,00 | 0,20 |

Angka dalam unit harga XAUUSD (USD per ounce), bukan persentase akun. Spread/slippage adalah asumsi model, bukan historical bid/ask broker. Model memakai komisi nol sebagai proxy akun Standard; tidak mengklaim biaya akun pengguna identik. Swap tidak dimodelkan karena tidak overnight. Minimum RR menghitung biaya entry/exit pada fill normal, tetapi gap dapat memperbesar loss.

R dan profit factor menggunakan nominal risk per trade, tanpa lot sizing, leverage, compounding, equity scaling, layering, atau batch cBot. Ini **bukan backtest cBot frozen**.

## Hasil penyaringan

Jumlah pada tabel berikut adalah kumulatif, sehingga setiap baris harus lolos baris sebelumnya.

| Kriteria | Kombinasi tersisa |
|---|---:|
| Training minimal 180 trade | 1.225.653 |
| Validation minimal 60 trade | 1.225.653 |
| Net R training positif | 1.439 |
| Profit factor training ≥1,15 | 68 |
| Profit factor validation ≥1,20 | **0** |
| Stress validation positif; lower bound mean R >0; konsistensi tahun; censoring ≤2% | 0 |

Syarat tahun: minimal lima tahun training positif, tiga tahun validation positif, masing-masing tahun dengan minimal 15 trade. Lower bound mean R bersifat deskriptif; tidak diklaim menjadi confidence yang mengoreksi pencarian jutaan parameter.

Penyebab paling awal habisnya kandidat adalah **profit yang tidak bertahan antarperiode**, bukan hanya filter censoring. Temuan nol kandidat tidak membuktikan semua pola reversal atau seluruh 10 juta kombinasi selalu rugi.

## Contoh yang tampak bagus pada validation tetapi ditolak

Contoh dipilih setelah melihat validation untuk diagnosis. **Bukan kandidat tervalidasi atau rekomendasi entry.**

| Contoh | Trade training | PF training | Mean net R training | Trade validation | PF validation | Mean net R validation |
|---|---:|---:|---:|---:|---:|---:|
| BUY channel64 | 206 | 0,665 | −0,188R | 145 | 1,622 | +0,290R |
| SELL channel24 | 210 | 0,520 | −0,224R | 103 | 1,851 | +0,204R |

BUY: sesi 07–13 WIB, lebar zona 0 ATR, SL extension 1 ATR, target 6 ATR, horizon 480 menit, wick ≥0,1, approach ≥1 ATR, trend ANY, net RR minimum 1,5. Training hanya satu tahun positif; validation censoring 3/(145+3)=2,027%.

SELL: sesi 19–01 WIB, lebar zona 0,1 ATR, SL extension 2 ATR, target 4 ATR, horizon 480 menit, wick ≥0,2, approach ≥1 ATR, trend ALIGNED, net RR minimum 1,5. Training hanya satu tahun positif; validation censoring 6/(103+6)=5,505%.

Contoh ini memperlihatkan risiko memilih konfigurasi hanya dari periode terbaru. Tidak ada angka probabilitas reversal, jam terbaik, TP/SL harga live, frekuensi harian, atau drawdown akun yang layak dipromosikan dari hasil ini.

## Perubahan dashboard

Panel default XAU menampilkan jumlah penelitian, status `RESEARCH_ONLY`, nol kandidat lolos, dan alasan penolakan. Zona/TP/SL contoh pantulan 0,5 ATR lama dipindahkan menjadi tautan arsip penelitian, agar tidak terbaca sebagai rekomendasi reversal utama.

Publikasi source/result ke main dapat diperiksa di GitHub. **Tampilan runtime Streamlit belum dapat diverifikasi langsung pada akhir pekerjaan karena workspace/browser terputus.** Tidak mengklaim deploy runtime dashboard sudah teramati. Tidak diperlukan restart bridge VPS atau cBot untuk penelitian ini.

## Validasi dan perlindungan cBot

- [Replay penelitian](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38374344264): PASS seluruh matrix tahun, lock, ledger, verify.
- Unit regression: **30 passed**. Memeriksa causal prefix, next-bar fills/cost, normal RR, gap/ambiguous stop, timeout open, first eligible selection, dan censored-day claim.
- [Audit penolakan](https://github.com/rizanrizan93/Forex-scanner/actions/runs/38379190882): PASS; diagnosis dibangun ulang dari seluruh sepuluh shard terkunci.
- Scope verification XAU: PASS, 17 method strategy/execution unchanged, contract `7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf`.
- Scope verification EUR: PASS, 24 method unchanged, contract `4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976`.
- Compare main dari `5563e1fc` sampai `43bd3d8a` hanya menyentuh riset/scanner/workflow/test. Tidak menyentuh `cbot_sources`, `cbot_connectivity`, `cbot_bridge`, `src/fx_scanner/execution`, atau `config/frozen`.
- CI umum masih FAIL saat test collection: import `OrderSide` dari `fx_scanner.execution.models` gagal. File execution tersebut tidak diubah dalam tugas ini; tidak menyamakan PASS pipeline penelitian dengan PASS seluruh repository.
- Pemeriksaan tambahan pada commit publikasi: syntax main/dashboard, JSON parity terhadap artifact audit, dan scope cBot dijalankan melalui workflow audit. Status run terakhir dapat dilihat pada halaman Actions.

## File utama

- `src/fx_scanner/major_reversal.py`: fitur/parameter riset terpisah.
- `scripts/research_major_reversal.py`: replay net-cost, seleksi, walk-forward, candidate lock, ledger.
- `scripts/audit_major_reversal.py`: diagnosis rejection read-only.
- `tests/test_major_reversal.py`: regression penelitian.
- `.github/workflows/research-major-reversal.yml`, `.github/workflows/audit-major-reversal.yml`.
- `calibration/major_reversal_results.json`, `calibration/major_reversal_diagnostics.json`: bukti hasil.
- `src/fx_scanner/major_reversal_dashboard.py`, `main.py`: status/arsip scanner.
- Arsip V2/V3 dipertahankan, tetapi superseded oleh perbaikan first-eligible sampling pada V6.

## Penggunaan dan rollback

Gunakan status riset ini sebagai hasil negatif yang terukur; belum sebagai zona trading utama. Menemukan konfigurasi yang selalu profit atau reversal setiap hari bukan hasil yang bisa dipaksakan dengan mengganti kriteria setelah melihat kegagalan.

Rollback tampilan: pulihkan hanya `main.py` dan `src/fx_scanner/major_reversal_dashboard.py` dari commit UI sebelumnya melalui commit baru. Simpan hasil penelitian untuk audit. Jangan reset seluruh repository atau mengubah strategy cBot. Tidak ada perubahan service VPS, checkpoint, account binding, atau session trading untuk di-rollback.
