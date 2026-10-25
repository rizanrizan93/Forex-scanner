# RIZAN XAU cBot Indicator v1.0.1

Konversi **aturan entry teknis XAU cBot V1.3.0** menjadi indikator chart cTrader
dan indikator di dashboard scanner. Bukan strategi reversal baru dan bukan bukti
tambahan bahwa strategi cBot profitabel. EUR/BTC tetap menggunakan monitor lama.

## Hasil pembongkaran aturan

| Komponen | Aturan sumber yang dipertahankan |
|---|---|
| BUY | Regression channel re-entry pada M5. Close saat ini kembali di atas lower band regression 48 candle sebelumnya −1,5 standar deviasi; close candle sebelumnya berada di/bawah band sebelumnya lagi; candle saat ini bullish. |
| SELL | Sweep high 24 candle M5 sebelumnya dan close kembali di bawahnya; dalam 1–3 candle berikutnya close bearish di bawah low candle sweep −0,05 ATR M5. Setup dapat diganti oleh sweep baru sesuai sumber. |
| Bias | H1 dan M15 sama arah. BUY: close di atas EMA200 dan EMA50 tidak menurun dibanding dua candle sebelumnya. SELL: kebalikannya. |
| Sesi efektif | 12:00–17:00 UTC = 19:00–00:00 WIB, hari kerja. Batas ini mengikuti admission gate aktual XauSignal, bukan batas luar 20:00 UTC pada kontrak lama. |
| SL asli | Maksimum dari $0,50, 2,4 ATR M5, serta jarak ke anchor struktural; spread/penyesuaian entry mengikuti referensi monitor. |
| Exit asli | TP 5,5R, hold maksimal 480 menit. Tidak ada trailing pada aturan ini. |
| Layer asli | Kedalaman 0 / 0,2 / 0,4R, penambahan memerlukan konfirmasi baru. Indikator tidak membuka layer. |
| Gate eksekusi XAU | BUY memerlukan delta DFII10 tidak positif; SELL delta DGS10 tidak negatif. Kalender berita, freshness, cooldown, exposure, basket, margin, checkpoint dan ACK tetap relevan pada cBot. |

Kode teknis dipakai langsung melalui link ke `cbot_manual/source/xau/FrozenCore.cs`,
tanpa mengubah berkas tersebut. Manifest lima core monitor tetap sama. Sumber
dipin pada commit `e357272fec03411a6e7c4d2397faf742d1a11047`; kontrak XAU
`44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c`.
Ini adalah konversi core yang dipin monitor, bukan pemeriksaan binary yang sedang
berjalan pada VPS pengguna.

## Cara membaca indikator

- **ABA-ABA BUY**: prasyarat candle sebelumnya dan bias tersedia. Angka BUY
  adalah ambang close **candle M5 berikutnya**, bukan limit order.
- **ABA-ABA SELL**: sweep terdeteksi dan bias mendukung. Ambang konfirmasi SELL
  masih estimasi karena ATR candle konfirmasi belum selesai; masa berlaku terlihat.
- **Panah BUY/SELL**: aturan teknis lengkap pada penutupan M5. Panah tidak
  membuktikan macro/news lolos atau order diterima cBot.
- **Data terlambat / pemanasan / di luar sesi**: tidak ada acuan entry baru.

Perbaikan terhadap tampilan level monitor lama: band untuk menilai candle yang
baru selesai dipisahkan dari band yang akan dipakai candle berikutnya. Tidak ada
aturan core yang diganti. Riwayat chart tidak mengubah frame lama ketika candle
masa depan ditambahkan, selama history/seed yang diberikan sama.

## Dashboard Android

Buka dashboard scanner → **cBots** → **XAUUSD**. Chart menampilkan 96 candle M5,
ambang indikator, bias H1/M15, aba-aba dan panah teknis historis. Sinyal entry
manual tetap memakai gate macro/checkpoint/quote yang telah ada pada monitor.
Publikasi fresh tidak otomatis membuktikan kesiapan order cBot LIVE.

Exit mengikuti kontrak asli: SL struktural/2,4 ATR M5 dengan floor $0,50,
TP 5,5R dan hold maksimal 480 menit. **Tidak ada opsi trailing manual, input
setup baru atau entry sebelum konfirmasi.** Aba-aba hanya informasi persiapan.

## Indikator chart cTrader

Custom indicator hanya didukung cTrader **Windows/Mac**, bukan chart Android,
Web atau cloud indicator. Android menggunakan dashboard di atas.

1. Unduh `releases/RizanXauCbotIndicator_v1.0.1.algo`.
2. Buka file di cTrader Windows/Mac dan pasang pada chart **XAUUSD M5**.
3. Tunggu pemanasan setidaknya 200 candle H1. Indikator mencoba memuat 16.000
   candle M1; jika tidak mencukupi, tampilannya tetap WARMUP.
4. Panah merupakan konfirmasi teknis; baca macro/news dan readiness melalui
   dashboard. Indikator chart tidak tersambung ke bridge atau checkpoint cBot.

Versi 1.0.1 menghapus opsi tracking/trailing tambahan dari versi 1.0.0.
Tidak ada parameter untuk meracik ulang entry atau exit. Satu-satunya parameter
indikator adalah jumlah history M1 untuk pemanasan. Garis pemicu dan panah tetap
mengikuti core asli; harga entry/SL/TP adalah referensi teknis dari quote saat
konfirmasi, bukan bukti posisi broker.

## Batas parity dan timing

Core entry, ATR dan anchor dibandingkan terhadap FrozenCore asli menggunakan
input candle yang sama. Perbedaan history pemanasan antara terminal, indikator
chart, dan collector 14 hari tetap dapat menghasilkan bias/sinyal berbeda.
Ini bukan parity penuh terhadap bot berjalan, account sizing, posisi, gate bridge,
atau tick broker. Tidak ada klaim win rate/PF baru dan tidak ada replay akun baru.

Aba-aba tersedia sebelum konfirmasi jika prasyarat terbentuk; panah final tetap
menunggu close M5 sesuai sumber. Collector existing menargetkan sekitar 30 detik
ditambah waktu pembacaan/publikasi, UI 10 detik. Indikator desktop memeriksa timer
1 detik dengan data lokal terminal. Tidak ada jaminan menangkap setiap jendela
entry 60 detik. Koneksi, history dan spread harus cukup baru.

## Build dan validasi

Build menggunakan .NET SDK 8 serta `cTrader.Automate` 1.0.21; project indikator
menargetkan net6.0 sesuai sumber cBot. Tidak perlu kredensial broker untuk build.

```bash
dotnet build cbot_indicators/XauCbotIndicator/RizanXauCbotIndicator.csproj -c Release
dotnet build cbot_manual/Monitor.csproj -c Release
dotnet run --project cbot_indicators/tests/Parity.csproj -c Release -- fixture.csv
PYTHONPATH=src:. python3 -m pytest -q tests/test_cbot_indicator.py tests/test_cbot_manual.py tests/test_runtime_telemetry_labels.py
```

Fixture parity adalah 60.000 M1 pertama tahun 2022 dari arsip XAU yang sudah
digunakan sebelumnya; header `timestamp,open,high,low,close`. Hasil: 12.000 frame,
9.601 frame sesudah warmup, 33 perbandingan prefix termasuk 15 BUY dan 5 SELL
terkonfirmasi; parity side/ATR/anchor dan invariansi prefix lulus. Referensi SL/TP juga dibandingkan dengan parameter FrozenContract asli.
Adapter lama dibanding adapter baru menghasilkan semua field lama identik;
field tambahan adalah indikator dan history. Metadata paket menandai `Indicator`,
bukan Robot, dengan capabilities kosong.

Tes Python terkait indikator, monitor dan telemetry diperiksa ulang untuk versi ini. Satu assertion test navigasi lama diperbarui dari
tab ke radio yang sudah digunakan main.py; kode navigasi tidak diubah. SDK build
lulus tanpa error. Belum diuji interaktif pada aplikasi Windows/Mac atau chart
broker pengguna. Bukti build dan hash paket terdapat dalam `BUILD_PROOF.json`.

Tidak ada perubahan cBot source, bridge, VPS service, credential, order API,
jadwal workflow, atau protokol reader. Perubahan runtime hanya pada monitor
baca-saja dan tampilan dashboard. Workflow monitor yang sudah ada akan memuat
adapter baru setelah main diperbarui; freshness feed tetap harus diperiksa.
