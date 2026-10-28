# RIZAN R2 — checkpoint 5/6, 28 Oktober 2026

**Status: lima dari enam replay gabungan selesai dan lulus audit. Skenario B biaya 2× belum terverifikasi karena lingkungan eksekusi terputus saat pemeriksaan akhir.**

BUFFER FROZEN V1 tetap immutable. Tidak ada perubahan LIVE, main, bridge, dashboard, workflow produksi, atau order nyata.

## Pemulihan dan kontrol

- Empat arsip dipulihkan; checksum referensi dan R2 cocok. Manifest 169 dan 66 entri tidak memiliki mismatch.
- Ketiga input CSV dan DLL R2 cocok dengan SHA256 master prompt.
- Runtime .NET 8.0.32 dan compiler 4.11.0 cocok dengan paket yang dirujuk.
- 1.247 tes lama dan 474 tes batch lulus ulang: total 1.721, hanya fake broker.
- CONTROL_R2 identik pada seluruh sepuluh field asli: Summary, CashFlows, Annual, Monthly, Ledger, Curve, BrokerHistory, CashEvents, Open, Errors.
- BtcResearchStatus: Faulted=false, QueuedAtEnd=false, ExitPendingAtEnd=false.
- Kontrol saldo US$938.466.200,2239354 dan DD 64,89756276978311%.

## Hasil gabungan yang terverifikasi

Modal US$100, tanpa top-up, leverage model 1:200, 2019-01-01 sampai cutoff 2026-10-09T21:59:00Z.

|Jalur|Biaya|Saldo akhir USD|Max DD %|Audit|
|---|---:|---:|---:|---|
|A|1×|1,051,126,595.699221|65.83731286743308|PASS|
|B|1×|992,612,612.1518544|65.88601151219306|PASS|
|A|1.5×|977,009,626.7332854|67.79459182390943|PASS|
|B|1.5×|922,340,948.4453279|68.073176029848|PASS|
|A|2×|896,369,444.8155998|72.06434784309153|PASS|
|B|2×|Belum terverifikasi|Belum terverifikasi|PENDING|

Normal A meningkat sekitar 6,31% dari BUFFER, normal B sekitar 5,77%. Target US$1 miliar tercapai pada A; B masih kurang US$7.387.387,8481456.

Normal A: PF 2.647050647285777, 585 basket, 119955 opening order, risiko teramati maksimum 24.286240279752068%, margin 56.03222636843323%.
Normal B: PF 2.562260486087672, 583 basket, 120205 opening order, risiko maksimum 24.269503304924235%, margin 56.319329002906365%.
Order hasil split/layer bukan sinyal independen. Cap risiko/margin berlaku saat sizing; rasio teramati setelah harga bergerak dapat melampauinya.

A biaya2×: PF 2.638552212936907, 584 basket, 94768 opening order, first fill maksimum6detik, child BTC terakhir140detik.

## Tradeoff EUR pada stress

A biaya2×:
- XAU PnL US$881.574.704,6278994.
- EUR PnL US$8.421.911,182005776, turun dari BUFFER US$13.401.310,754477095.
- BTC PnL US$6.372.729,005708854, naik dari BUFFER US$2.132.879,757226133.

Kenaikan saldo portofolio tidak membuktikan EUR dan BTC sama-sama membaik pada seluruh tingkat biaya. Acceptance gabungan belum dapat disimpulkan sebelum B biaya2× tersedia dan seluruh perbandingan instrumen selesai.

## Titik lanjut

1. Periksa apakah proses terakhir masih hidup dan apakah laporan final B biaya2× sudah terbentuk. Log terakhir terverifikasi mencapai September2026. Jangan menganggap proses selesai atau berhenti tanpa pemeriksaan.
2. Jangan ulang kontrol dan lima skenario yang sudah lulus. Ulang hanya B biaya2× jika proses benar-benar hilang dan tidak ada laporan valid.
3. Audit, agregasi tahunan/bulanan, dekomposisi biaya, timing, serta acceptance keenam skenario.
4. Pertahankan ambang DD72.21320348415222%, floor saldo minimum biaya2× US$842853657.6189626 dan semua syarat master prompt.
5. Jangan ubah BUFFER V1 atau LIVE.

Dua pemuatan input sempat gagal karena memori. B biaya2× diulang satu kali setelah interupsi; 78 baris bulanan yang beririsan cocok persis. Interupsi transport berikutnya tidak membuktikan proses mati.

## Artefak dan batas bukti

Paket lokal lima hasil: RIZAN_R2_CHECKPOINT_5OF6_20261028.zip, 92910831byte, SHA256 9a056395010635f82959f4076f77d20eb732a65b30b8458681e9984d13621ad4, 162 entri terverifikasi, termasuk raw lima hasil + kontrol dan input BTC asli. Penyimpanan paket tersebut gagal pada prepare_uploads; tidak ada Library ID baru yang terkonfirmasi. File lokal dapat dipulihkan hanya jika workspace kembali tersedia. JSON dan laporan GitHub ini menyimpan hasil teks terverifikasi, bukan ledger mentah.

Sumber R2 tetap pada arsip libfile_f88b25751d188191903a8c06d2d0e27f versi1; BUFFER pada libfile_65af9c91f2c08191b6aa3d1c00dca925 versi0; raw referensi libfile_56be77c4e0408191a8b45d2aae5fa7a6 versi5.

Harga intrabar M1 sintetis A/B, delay broker2detik. Stress komisi/slippage/funding, spread tetap. Native tick, OOS, macro point-in-time vintage dan likuiditas broker belum tersertifikasi.
