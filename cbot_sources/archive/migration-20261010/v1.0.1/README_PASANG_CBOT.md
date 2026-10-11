# RIZAN — migrasi scanner ke dua cBot

Versi port: 1.0.1 (perbaikan startup), 2026-10-10, native C# / cTrader Automate 1.0.21.
Sumber GitHub: rizanrizan93/Forex-scanner, commit `1a5318f92048d6ef92764c7af8b3046c12aac05f`, ditambah konfigurasi frozen dan kode replay dari arsip Anda.

**Paket ini berisi dua file `.algo` yang sudah dikompilasi, source, bridge data/state, konfigurasi frozen, dan hasil pengujian. Belum dipasang di cTrader atau menjalankan order.**

## Perbaikan startup 1.0.1

Versi ini memperbaiki crash `OnStart` dengan `ArgumentException: The keys can only contain Latin letters, numbers and spaces`. Key LocalStorage sekarang berupa 45 karakter Latin/angka hasil hash identitas; identitas bridge tetap sama. Key tidak mengandung kolon atau karakter suffix simbol broker. Constraint API maksimum 50 karakter diperiksa dalam 134 kasus regression.

Akun bersaldo/equity 0 dapat menyimpan dan memuat checkpoint untuk monitoring. Budget tetap menolak order ketika dana tidak mencukupi. Jika belum ada equity, log startup menampilkan `NO_EQUITY_MONITORING`.

Untuk mengganti versi lama: Stop cBot Instance, buka `.algo` terbaru, terima pembaruan jika ditawarkan, lalu start dengan parameter akun yang sama dan `Kirim order=false`. Cari `RIZAN_STARTUP_OK version=1.0.1` di Logs. Build dan regression lulus; konfirmasi startup Cloud tetap membutuhkan log dari instance Anda.

## Hasil pemindahan

| Komponen | RizanEUR | RizanXAU |
|---|---|---|
| Akun LIVE | Nomor akun penuh dengan akhiran 7903 | Nomor akun penuh dengan akhiran 4480 |
| Sinyal | Sweep/reclaim M15, ATR14, H1 bias | Raw BUY/SELL M5, regression band/sweep, H1/M15 strict |
| Layer | 3: 0 / 0,2 / 0,4 R | 4: 0 / 0,161111 / 0,322222 / 0,483333 R |
| Tambahan | Tanpa konfirmasi, TTL 210 menit | Konfirmasi M5/M15/H1, TTL 45 menit |
| Maksimum budget risiko dasar | **27,25% × skala feedback** | **12,5%** |
| Budget margin dasar | 50% × skala feedback | 50% |
| Child | 0,01 lot = 1.000 unit EUR | 0,01 lot = 1 unit XAU |
| TP / batas waktu | 4 R / 240 menit, paling lambat 20:00 UTC | 6,6 R / 480 menit, paling lambat 19:59 UTC |
| Kontrol tambahan | Feedback virtual fast/slow; degear 0,7 saat DD ≥25% | Yield FRED + kalender berita; maksimum 6 basket/hari WIB |
| Kebutuhan data eksternal | Tidak perlu untuk sinyal | Bridge macro/news wajib |
| Pemulihan otomatis Cloud | Bridge checkpoint | Bridge checkpoint dan data |

Angka risiko tersebut mengikuti frozen EUR V3 / XAU V1 yang disertakan. Risiko EUR 27,25% adalah batas basket sebelum skala feedback/degear, bukan 27,25% untuk setiap child. Banyak child berbagi SL/TP dan satu budget basket. Risiko total diperiksa ulang sebelum dan setelah fill.

Native cBot mengirim order sungguhan melalui `ExecuteMarketOrder`, memasang bracket broker, lalu memverifikasi SL/TP absolut. Semua logika sizing memakai estimasi margin broker aktual. Leverage referensi EUR 200 dan XAU 100 dicatat; perbedaan leverage broker dapat mengubah jumlah child.

GitHub repository_dispatch, PAT, Turso, dan Open API access token tidak diperlukan pada jalur eksekusi baru. Otorisasi akun berasal dari instance cTrader tempat bot dipasang.

## Pasang `.algo` di cTrader

1. Ekstrak ZIP. Buka `compiled/RizanEUR.algo` dan `compiled/RizanXAU.algo` dengan cTrader. Aplikasi Windows, Mac, atau Mobile dapat memasang file `.algo`; sinkronisasi memakai cTrader ID yang sama.
2. Di Algo, buat satu instance untuk tiap bot. Pilih simbol broker EURUSD atau XAUUSD. Pilih M1 sebagai timeframe instance; bot mengambil M1 sendiri dan membentuk M5/M15/H1 dari bar yang sudah selesai.
3. Untuk pengujian, gunakan akun demo USD bertipe **hedged**. Isi `Nomor akun penuh` dengan **Account.Number** akun tersebut; pada demo tidak diwajibkan akhiran LIVE 7903/4480.
4. Biarkan `Kirim order = false` untuk pemeriksaan awal. Mode ini menghitung state tanpa entry baru, tetapi tetap mengelola posisi milik bot yang sudah ada. Setelah pemeriksaan, ubah menjadi `true` pada akun demo untuk memverifikasi order, child, SL/TP, dan expiry.
5. Untuk Cloud XAU, isi `Bridge WSS :25345` dan `Token bridge`. Untuk EUR, bridge disarankan agar state dan percobaan order bisa pulih otomatis setelah restart.
6. Periksa log setiap menit: `RIZAN_STATE`, `RIZAN_CHECKPOINT`, status feed, dan alasan quarantine. Simpan JSON setelah teks `RIZAN_CHECKPOINT` jika EUR dijalankan tanpa bridge.
7. Saat beralih ke LIVE, pilih akun yang benar, isi nomor penuh yang cocok, lalu atur `Kirim order` sesuai mode yang diinginkan. LIVE XAU wajib berakhiran 4480, LIVE EUR berakhiran 7903.

Akun harus USD, hedged, dan menerima child 0,01 lot dengan unit/step yang sesuai. Broker dengan ukuran kontrak berbeda ditolak. Gunakan satu instance aktif per bot/akun. Dengan bridge, lease menolak instance kedua pada key yang sama. Posisi/order asing pada akun memblokir entry baru; akun didedikasikan untuk strategi tersebut.

**Peralihan sistem:** hentikan jalur eksekusi scanner/GitHub Actions lama sebelum mengaktifkan order dari cBot. Pastikan jalur lama tidak mengirim ticket LIVE bersamaan. Posisi lama dengan label berbeda memerlukan pengelolaan melalui sistem asal; cBot ini hanya mengelola label `RZEU3|...` atau `RZXA1|...`.

## Bridge XAU dan checkpoint

Cloud cTrader tidak mengirim HTTP; koneksi `WebSocketClient` harus menggunakan port 25345. Karena itu yield dan kalender berita tidak dapat diambil langsung melalui HTTP oleh cBot Cloud. Folder `bridge/` menyediakan adapter read-only dan checkpoint SQLite. **Hosting bridge belum disediakan oleh paket ini.** Server harus tersedia selama bot membutuhkannya; paket ini tidak menjadikan kebutuhan server data XAU hilang.

Bridge membutuhkan Python 3.11/3.12, internet keluar, disk persisten, dan endpoint publik `wss://nama-domain:25345` dengan sertifikat TLS yang valid. Endpoint port 443 tidak dapat menggantikan port 25345 untuk Cloud. `ws://127.0.0.1:25345` hanya untuk uji lokal; pada Cloud localhost mengarah ke lingkungan Cloud, bukan PC Anda.

Persiapan server:

```bash
cd bridge
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Salin `rizan-bridge.env.example` menjadi `rizan-bridge.env`, isi secret acak minimal 32 karakter, path sertifikat, dan lokasi SQLite. Jangan memasukkan secret ke GitHub. Untuk menjalankan manual:

```bash
set -a
. ./rizan-bridge.env
set +a
python server.py
```

Untuk systemd, template `rizan-bridge.service` mengasumsikan user `rizan` dan folder `/opt/rizan-bridge` sudah dibuat. Atur hak baca sertifikat/key dan hak tulis SQLite untuk user tersebut. Jangan menghapus database saat bot berjalan. Port 25345 harus dapat dijangkau dari internet.

Isi parameter cBot dengan URL WSS dan secret yang sama. Bridge tidak memakai kredensial trading atau mengirim order.

### Data dan kegagalan feed

- FRED: SELL menggunakan DGS10; BUY menggunakan DFII10. Availability = tanggal observasi +2 hari kerja federal AS pada midnight New York. Delta terakhir yang tersedia harus berumur ≤7 hari.
- Berita: Forex Factory weekly JSON dan BLS official ICS. Kategori NFP, CPI, PPI, JOLTS, ECI, FOMC memblokir entry pada interval −30 hingga +495 menit dari signal.
- Sumber FRED dicache 1 jam, kalender 15 menit; snapshot dipublikasikan setiap 60 detik. Minggu kalender dan timezone diverifikasi. Snapshot berumur >180 detik memblokir entry baru XAU.
- Kesalahan fetch, calendar kosong/salah minggu, atau coverage BLS tidak lengkap membuat status feed gagal. Tidak ada fallback yang berpura-pura bahwa berita/macro valid.
- SL/TP broker dan pengelolaan expiry untuk basket yang sudah terbuka tetap berjalan ketika bridge/data terputus. Entry child baru membutuhkan checkpoint yang sudah di-ACK.

Probe saat pembuatan paket berhasil membaca dua seri FRED, FF, dan BLS; hasil ada di `validation/bridge-feed-probe.json`. Itu bukti konektivitas saat pengujian, bukan jaminan layanan sumber selalu tersedia.

## State, restart, dan order yang belum pasti

State menyimpan identity/hash kontrak, equity peak, feedback EUR, EMA H1, virtual trade, cursor, basket, budget per stage, sequence, dan label percobaan order. Bridge memakai SQLite synchronous FULL, compare-and-swap revision, dan lease 45 detik. Percobaan child harus dicatat sebelum request broker, dan ACK harus diterima sebelum request dikirim.

Saat restart, label yang tertunda direkonsiliasi dengan Positions/History. Jika tidak dapat dibuktikan hasilnya, bot quarantine dan tidak mengulang order tersebut. Menutup error dengan retry buta bisa membuat order ganda; pendekatan paket ini berhenti menambah exposure ketika hasil tidak pasti.

File lokal Cloud hilang ketika instance berhenti/restart. EUR tanpa bridge membutuhkan JSON `Checkpoint pemulihan JSON` dari log terakhir. Jika ada aktivitas bot sebelumnya tetapi checkpoint hilang, entry dikunci. Posisi yang dapat dikenali tetap dikelola untuk proteksi/expiry. Jangan menyunting field quarantine atau menghapus state untuk memaksa bot melanjutkan; selesaikan rekonsiliasi posisi/order terlebih dahulu.

State EUR baru dimulai dengan fast/slow = 0 dan equity peak akun saat deployment. Port tidak menganggap dirinya sudah membawa feedback/equity peak dari replay 2016. Checkpoint terikat nomor akun: state demo tidak digunakan sebagai state LIVE.

## Perbedaan implementasi LIVE terhadap replay

Perhitungan frozen yang diuji cocok pada cakupan di bawah, tetapi hasil trading/basket belum dibuktikan identik dengan seluruh replay 10 tahun.

- Fill memakai quote/spread/commission/swap broker aktual. Komisi 0,03 USD per child per sisi dan slippage model tetap dipakai untuk budget sesuai frozen; broker yang mengenakan lebih besar perlu validasi kontrak biaya.
- Setiap child merupakan order individual, dibatasi maksimum 3 child/detik secara default (parameter 1–5), dengan journaling dan ACK. Initial stage hanya diproses dalam satu menit pertama signal. Order yang tidak sempat masuk atau melampaui budget/geometry dibatalkan dari queue. Replay yang mengisi banyak child seketika dapat menghasilkan basket berbeda.
- Order awal memasang bracket relatif, lalu SL/TP disamakan ke geometry absolut dan diperiksa terhadap tick broker. Fill/protection/volume di luar kontrak memicu penutupan child dan quarantine; kegagalan penutupan dicatat.
- EUR equity peak disampling pada batas M1 menggunakan equity akun yang tersedia. Replay menggunakan ekstrem M1 sintetis; degear dekat batas 25% dapat berbeda.
- Sinyal XAU menggunakan histori M1 yang tersedia dari broker dan warmup awal sekitar 12 hari. Seed EMA/histori berbeda dari seluruh arsip dapat mengubah sinyal dekat batas. Setelah start, histori terus bertambah; tidak ada impor seluruh arsip 2016–2025.
- Session XAU memakai 12:00 ≤ UTC <20:00 dari archived frozen-input adapter. Runtime Python lama membatasi <17:00; keputusan port ini mengikuti arsip yang diuji. Penambahan layer memakai konfirmasi dari kode replay.
- Broker tetap memegang SL/TP saat cBot berhenti. Penutupan berdasarkan waktu memerlukan bot berjalan; berhenti tidak otomatis menutup seluruh posisi.

Tidak ada hasil broker atau profit yang direkayasa. Mode LIVE menggunakan API native, tetapi fill demo/Cloud belum dapat diuji tanpa akun pengguna.

## Bukti pengujian

`validation/parity.json` mencatat:

- 4.000 bar fixture XAU: 14 BUY dan 18 SELL cocok, termasuk anchor pada sinyal.
- 23.978 bar M1 EUR: 1.599 fitur dan 31 sinyal cocok dengan kernel Python asli; feedback virtual dan restart cocok.
- 10 kasus virtual: STOP_FIRST, tanpa exit, gap, timeout, dan batas hari, pada BUY/SELL.
- 41 kasus konfirmasi XAU dibanding fungsi konfirmasi arsip, termasuk bucket yang tidak lengkap.
- 240 kombinasi sizing: EUR/XAU, BUY/SELL, balance, feedback scale, dan batas drawdown.
- Empat unit test bridge: identity, CAS, lease, persistence, NaN, macro holiday/staleness, calendar timezone/week.
- Smoke test WebSocket nyata di localhost: hello/save/ACK/ping, penolakan lease ganda, dan journal pending tersimpan.
- Build dua project: 0 warning, 0 error; `.algo` dibuat dengan SDK .NET 8.0.425 dan cTrader.Automate 1.0.21, target net6.0.

Membangun ulang source memerlukan SDK .NET 8 atau versi yang kompatibel:

```bash
bash build.sh
dotnet build Parity/Parity.csproj -c Release
pip install -r bridge/requirements.txt
python tests/parity.py
python -m unittest discover -s tests -p test_bridge.py -v
python tests/protocol_smoke.py
```

Test parity membutuhkan numpy, yang merupakan dependensi pandas. Reference Python disertakan agar pengujian bisa diulang. Fixture menguji raw XAU dengan kolom bias historis yang sudah dihitung; bukan verifikasi end-to-end seluruh pembentukan stream g-0006/g-0274.

Dokumentasi resmi yang diperiksa:
- https://help.ctrader.com/ctrader-algo/documentation/cloud-features/
- https://help.ctrader.com/ctrader-algo/documentation/cbots/cloud-requirements/
- https://help.ctrader.com/ctrader-algo/guides/estimated-margin/
