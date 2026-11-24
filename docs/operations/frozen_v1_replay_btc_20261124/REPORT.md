# Restored Frozen V1 source-model replay

Modal awal $100, compounding berkelanjutan, leverage model 1:200, biaya dasar 1x, jalur M1 A/B. Cutoff data: 13 November 2026 09.59 WIB.

| Rentang awal | Jalur | Saldo akhir USD | DD equity | Basket | Order | Error |
|---|---|---:|---:|---:|---:|---:|
| 2019–2026 | A | 1,392,645,692.94 | 57.89% | 1040 | 147586 | 0 |
| 2019–2026 | B | 1,662,133,293.08 | 56.67% | 1047 | 187560 | 0 |
| 2012–2026 | A | 1,392,645,692.94 | 57.89% | 1040 | 147586 | 0 |
| 2012–2026 | B | 1,662,133,293.08 | 56.67% | 1047 | 187560 | 0 |

## Provenance dan batas interpretasi

Tiga input CSV dipulihkan dari arsip pengguna dan SHA-256 semuanya sama dengan input asli. Sebanyak 34 file sumber runner/strategi cocok dengan manifest arsip lama.

Ini menjalankan ulang model C# penelitian lama dengan API stub, jalur M1 sintetis, heartbeat/ACK sintetis, dan snapshot izin XAU sintetis dari runner asli. Biner .algo tidak dijalankan; ini bukan replay tick FP Markets atau bukti eksekusi bridge/live. Flag historis XAU dan snapshot makro tetap tidak tersertifikasi.

Mode makro off menggunakan timeline kosong yang tidak memengaruhi filter makro tambahan. Runner asli tetap menyuntikkan snapshot izin XAU; pembatasan ini tidak dihapus atau disamarkan.

XAU/EUR tersedia mulai 2011 sebagai warmup. BTC mulai 2019. Generator seed asli membatasi kandidat sejak 2019; rentang 2012 tidak berarti tiga aset aktif sejak 2012. Tidak ada perubahan strategi untuk memaksa aktivitas sebelum 2019.

Benchmark lama jalur B berhasil direproduksi: saldo akhir $1.662.133.293,08, DD 56,6721%, dan 1.047 basket. Kedua rentang awal memiliki ledger order identik pada masing-masing jalur; entry pertama 2 Januari 2019, tanpa order sebelum 2019. Hasil ini berbeda dari reset modal $100 per tahun. Margin teramati maksimum A/B adalah 54,44%/54,07%, risiko terbuka teramati maksimum 26,22%/27,21%, dan menit tanpa data instrumen aktif tercatat 6.748/7.045; batas entry nominal bukan batas keras untuk seluruh perjalanan equity. Tidak ada order LIVE dikirim.
