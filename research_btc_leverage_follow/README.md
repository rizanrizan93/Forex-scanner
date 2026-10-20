# LF122 — BTC mengikuti margin engine XAU/EUR

Varian riset terpisah dari FROZEN WEEKEND V1.2.1. Replay memakai leverage 200× pada XAU, EUR dan BTC; native memakai GetEstimatedMargin broker untuk masing-masing simbol. Tidak ada asumsi bahwa leverage akun 200× menjamin leverage simbol BTC 200× di broker. Tidak ada deployment atau order live.

Floor BTC 10× dihapus dari perhitungan ukuran awal, reservasi margin dan gate gabungan. Account.Margin menjadi reservasi margin bersama seperti instrumen lain; binary search menghormati GetEstimatedMargin aktual, termasuk leverage simbol lebih rendah. Profil BUY/SELL, risk 23%/18%, margin budget 95%/30%, cap risiko gabungan 20,75%, margin gabungan 50%, entry/SL/TP/hold/sinyal dan pengaman weekend tetap. Native identitas robot baru RizanXauEurBtcLeverageFollow, assembly 1.2.2.0 dan checkpoint terpisah; default EnableTrading=false.

Modal $100 tanpa top-up. Periode 2019-01-01 sampai bar 2026-10-09 21:58 UTC. Input/checksum, biaya normal, spread, delay dua detik, indikator weekday dan dua path sama dengan audit sebelumnya.

| Ukuran | PATH A | PATH B |
|---|---:|---:|
| Saldo akhir USD | 20,347,817.71 | 20,808,380.46 |
| Floating DD % | 65.04314 | 65.47920 |
| Balance DD % | 56.14843 | 50.80141 |
| Profit factor | 2.44892 | 2.26716 |
| Win rate basket % | 47.69 | 49.47 |
| Basket | 562 | 566 |
| BTC BUY | 40 | 40 |
| BTC SELL | 55 | 55 |

Kedua path masih gagal floating DD ≤56%; bukan promosi pengganti baseline beku. Saldo V1.2.1 tetap $14.168.707,28/$18.043.274,23 dengan DD 62,94884%/63,77678%; angka baru tidak mengubah rekaman versi lama.

Seluruh 1.357 pemeriksaan lulus: 1.326 regresi sebelumnya dan 31 pemeriksaan leverage/margin tambahan. Fixture recovery menunjuk checkpoint LF122 yang terisolasi; syarat keselamatan regresi tidak dilonggarkan. Build native resmi 0 error/0 warning. Tidak ada posisi akhir, terminal forced close, error runtime, quarantine atau accounting block; cash residual < $0,00001 dan audit cutoff weekend lolos.

Tes khusus membuktikan account leverage 200× tidak mengalahkan leverage simbol BTC: broker 2×/5×/10×/200× menghasilkan batas volume berbeda, tetap mematuhi risiko/margin bersama. Margin invalid (NaN atau leverage nol) memblokir order; OFF tidak mengirim order.

Ini source replay OHLC dengan fake broker, bukan tick parity native/FULL_PARITY. Kalender replay Senin00–Jumat22 UTC belum tersertifikasi historis broker/DST; macro belum vintage-certified. Stress biaya/delay versi LF122 belum dijalankan; hasil stress V1.2.1 tidak dipindahkan ke sini.

Reproduksi: paket menyertakan work/source, work/replay, run_local.py, native build tools dan source tests. Gunakan SDK 8.0.426/runtime 8.0.32; input dan dependensi native sama dengan paket audit V1.2.1. Jalankan run_local.py untuk compile Replay.dll, lalu run_pair.py A dan B dengan input di folder workspace inputs/. prepare.py dapat merekonstruksi work/ bila work/ audit sebelumnya beserta vendor dependencies sudah tersedia.

Seluruh delapan source strategi XAU/EUR, BtcCore dan BtcWeekendPolicy tetap identik byte. Source patch ada di CHANGE_FROM_V121.diff. METRICS, ledger, tahunan, bulanan, dua raw replay dan bukti tes disertakan.
