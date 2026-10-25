# RIZAN XAU cBot · WebView plugin

Halaman plugin berada pada host dashboard yang sudah ada:

`https://forexrizan.streamlit.app/cbot-plugin?embed=true`

Halaman ini adalah web app untuk plugin builder, **bukan file indikator .algo**.
Pemasangan ke cTrader ID tetap melalui plugin builder resmi cTrader Web/Windows/Mac.
Selesai dibuat dan diterbitkan ke cloud cTrader, plugin bisa dibuka pada penempatan
Mobile yang diaktifkan. Pengujian web app tidak membuktikan bahwa plugin sudah
terpasang pada cTrader Android pengguna.

## Aturan yang digunakan

Plugin mengambil frame dan panah dari monitor C# XAU V1.3.0 yang sudah dipin pada
commit `e357272fec03411a6e7c4d2397faf742d1a11047`; ia tidak menghitung ulang
strategi dengan JavaScript. Entry BUY/SELL, bias H1/M15, konfirmasi M5, TP 5,5R
dan referensi hold 480 menit mengikuti indikator 1.0.1. Tidak ada trailing tambahan.

Panah chart merupakan konfirmasi **teknis historis**, bukan bukti order diterima.
Aba-aba adalah persiapan, bukan entry limit sebelum sentuhan. Level entry/SL/TP
baru hanya diekspor jika status monitor ENTRY_MANUAL, gate masih lengkap, quote
baru, sumber/checkpoint fresh, arah cocok dengan frame dan geometrinya cocok
dengan 5,5R. Masa berlaku paling pendek dari sumber, quote, checkpoint dan jendela
60 detik tetap berlaku di browser. Menyalin snapshot atau memublikasikannya ulang
tidak memperpanjang sinyal. Belum ada jaminan menangkap semua jendela entry.

Readiness berasal dari monitor, bukan verifikasi akun yang sedang aktif di
cTrader. Plugin tidak meminta saldo, posisi, akun, token atau akses order.
DTO yang masuk ke webview menghapus semua field selain chart dan sinyal yang
diizinkan. Tidak ada SDK request, transaksi atau perubahan broker.

## Mode uji

Tombol **Contoh uji** menampilkan 96 frame M5 historis 14 Februari 2022 yang
diekspor dari core C# yang sama, dengan empat penanda BUY teknis. Semua harga
tersebut adalah contoh historis, bukan harga sekarang. Mode uji selalu menahan
acuan entry live. Tombol **Live monitor** kembali ke publikasi sebenarnya.
Mode yang terakhir dipilih dapat tersimpan di perangkat; label MODE UJI tetap
ditampilkan jika contoh sedang dibuka.

## Membuat plugin pada cTrader ID

1. Buka cTrader Web/Windows/Mac → Algo → Plugins → Create.
2. Nama: **RIZAN XAU cBot**. Ikon: `icon-300.png` (300 × 300).
3. URL: `https://forexrizan.streamlit.app/cbot-plugin?embed=true`.
4. Android/iOS: aktifkan **Trade tabs bottom sheet** dan **Symbol overview bottom
   sheet**, tinggi **100%**. Embedded block tidak diperlukan untuk chart penuh.
5. Untuk pengujian Web, aktifkan **Active Symbol Panel tab**, judul **RIZAN XAU**.
6. Tidak ada izin akun/order atau SDK request yang dibutuhkan oleh halaman ini.
7. Tinjau sendiri pernyataan kepatuhan/ketentuan builder sebelum menekan Publish.
8. Buka plugin di cTrader Android melalui plugin bar/overview XAUUSD pada cTrader ID
   yang sama. Plugin muncul dalam panel tersendiri, bukan overlay chart utama.

`builder_settings.json` adalah catatan pengisian manual, bukan format impor atau
file plugin yang bisa dipasang. Login dan persetujuan ketentuan cTrader harus
diselesaikan pemilik akun jika sesi browser belum tersedia. Jangan mengirim kata
sandi atau OTP melalui chat.

## Parameter resmi

Query `theme=light|dark` dan `symbol=XAUUSD` didukung. `lang`, `platform`,
`placement`, `id` boleh ditambahkan host dan tidak dipakai untuk membaca akun.
Jika simbol aktif bukan XAUUSD, data live tidak ditampilkan sebagai sinyal simbol
tersebut. Default tanpa simbol tetap XAUUSD. Host menggunakan URL `embed=true`
agar halaman Streamlit sesuai untuk penempatan web/iframe.

## Uji dan batasnya

- Tes Python: kontrak/clock/expiry, input palsu/basi, arah BUY/SELL, geometri asli,
  penghapusan data akun/posisi, mode uji, serta escaping JSON.
- Tes Node: expiry tepat batas tanpa network refresh, stale/future clock, mode uji,
  arah SELL dan batas chart datar.
- Browser: 320, 390, 720 piksel, mode live basi, chart historis, kontrol jumlah
  candle dan tanpa overflow horizontal. Ini simulasi ukuran viewport, bukan uji
  pada perangkat Android fisik.
- Source C# dan protokol reader/bridge tidak diubah. Tidak ada replay profit baru
  atau klaim win rate/PF baru.

Perintah dari root repository:

```bash
PYTHONPATH=src:. python3 -m pytest -q tests/test_cbot_webview.py tests/test_cbot_indicator.py tests/test_cbot_manual.py tests/test_runtime_telemetry_labels.py
node --test webview_app/contract.test.mjs
```

Dokumentasi resmi:

- https://help.ctrader.com/plugins/developers/all-apps/build-a-plugin/
- https://help.ctrader.com/plugins/developers/all-apps/query-string-parameters/
- https://help.ctrader.com/plugins/developers/placements/
- https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app/embed-your-app
