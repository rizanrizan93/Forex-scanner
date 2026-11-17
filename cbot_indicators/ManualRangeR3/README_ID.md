# RIZAN Manual Range Reclaim R3 — indikator cTrader dan ForexScanner

R3 adalah bantuan trading manual XAUUSD. Tidak membuka, menutup, atau mengubah order.
Tidak mengubah Frozen V1, bridge, sizing akun, atau strategi cBot yang sedang berjalan.

## ForexScanner dari HP

Buka XAUUSD → **Manual R3**, atau URL `/XAU_Manual_R3`.
Panel berisi pita Keltner, bias H1, checklist, pemicu, rencana entry/SL/TP terkunci,
batas harga dan waktu, serta hasil replay. Tampilan mengecek 10 detik; waktu asli
candle/quote tetap ditampilkan. Keterlambatan sumber tidak dijadikan harga baru.

Sumber market R3 adalah pembaca cTrader READ ONLY tersendiri: cache hingga 12.000
M1 dan quote BID/ASK dengan timestamp broker. Kalender meminjam jadwal news publik
scanner yang sehat dan maksimal 10 menit. Tidak ada pembacaan akun/posisi/order di
collector R3. Timer independen tidak me-restart service cBot atau bridge trading.

## Instalasi cTrader

1. Unduh `releases/RizanManualRangeReclaimR3.algo`.
2. Buka di **cTrader Windows atau Mac**, lalu tambahkan indikator ke **XAUUSD M1**.
3. Tunggu riwayat M1 dan kalender siap. Default warmup 12.000 M1; pastikan broker
   menyediakan history cukup. Parameter history hanya mengatur pemanasan, bukan
   mengubah aturan entry.
4. Panah abu-abu adalah pemicu TEKNIS historis; kalender pada waktu historis tersebut
   tidak diverifikasi oleh chart. Status TRIGGER saat ini memerlukan kalender baru,
   tick simbol baru, sesi dan batas harga/waktu yang valid.
5. Entry/SL/TP adalah referensi manual, bukan posisi broker. Maksimum satu posisi,
   dua entry per tanggal, dan risk budget harus diperiksa sendiri.

Custom indicator tidak berjalan pada chart cTrader Android atau Web. Dari Android
gunakan ForexScanner. File `.algo` adalah indikator, bukan cBot untuk cloud trading.

Kalender dibaca via GET ke endpoint publik `manual-r3-news.json`. AccessRights.None
cukup untuk HTTP di API cTrader; tidak meminta akses akun atau file pribadi.
Jika kalender tidak tersedia/terlambat, status entry ditahan, sedangkan zona tetap
dapat menjadi referensi chart. Tidak ada opsi untuk mengabaikan filter news.

## Aturan dan arti status

- Keltner M15: EMA20 close ±2 ATR14 Wilder. Seluruh kalkulasi memakai candle selesai.
- Range: ADX14 H1 <20 ketika zona disentuh. Bias mengikuti slope EMA20 H1 dibanding
  tiga candle H1 sebelumnya.
- BUY: sentuh pita bawah lalu close M1 di atas garis. SELL sebaliknya. Reclaim
  maksimal lima M1 sejak sentuhan pertama per arah/sesi.
- Senin–Rabu 14.00–00.00 WIB. Hindari ±30 menit CPI/PPI/NFP dan ±60 menit FOMC.
- Entry berlaku 60 detik, maksimal satu ATR M5 dari garis. Harga/waktu lewat → EXPIRED.
- SL 3 ATR M5 (minimal dua spread), TP tiga kali jarak SL, time exit empat jam atau
  00.00 WIB. Plan terkunci selama ID pemicu sama; tidak ada trailing tambahan.
- PREPARE adalah persiapan, TRIGGER adalah syarat teknis/manual lengkap, bukan
  probabilitas menang atau bukti transaksi akun.

## Hasil penelitian dan batas

Varian dengan cap satu ATR: 249 transaksi 2019–2024, PF net-R 1,186; 29 transaksi
2025, PF 1,519; gabungan 278, PF 1,220. Tahun 2019 merugi. Stress 2025 biaya 1,5×
ditambah delay satu menit menghasilkan PF 0,94. Status tetap eksperimental.
Replay menggunakan OHLC M1 referensi dan biaya sintetis; 2025 sudah pernah diamati
di riset terdahulu. Belum ada bukti fresh OOS atau parity tick FP Markets.

Python dan C# memakai seed EWM dari observasi pertama, bukan seed SMA dari built-in
Keltner/ADX broker. Dengan input/warmup identik, parity fixture diperiksa oleh
`tests/Parity.csproj`; lihat PARITY_RESULT.json. History/warmup broker berbeda dapat
menyebabkan perbedaan kecil. Build berhasil bukan bukti indikator sudah diuji pada
terminal broker pengguna. Native terminal visual/tick validation masih terpisah.

## Build

`.NET SDK 8`, target indikator net6.0, `cTrader.Automate` 1.0.21:

```bash
dotnet build cbot_indicators/ManualRangeR3/Indicator/RizanManualRangeReclaimR3.csproj -c Release
```

Build proof dan hash `.algo` ada di BUILD_PROOF.json. Package berisi sumber dan
tidak memerlukan kredensial broker untuk build. Pengujian Python:

```bash
PYTHONPATH=src:. python -m pytest -q tests/test_manual_r3.py
```
