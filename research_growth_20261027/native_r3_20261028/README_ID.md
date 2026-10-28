# RIZAN R3 Frozen — cTrader cBot 3.0.0

Profil yang dibekukan: **R3_I100_W060**. R4 dihentikan atas permintaan pengguna. BUFFER V1, R2, sistem LIVE, bridge produksi dan branch main tidak diubah.

Satu cBot mengelola XAUUSD, EURUSD dan BTCUSD bersama dalam satu akun. Jangan memasang tiga instance terpisah: batas risiko, margin, prioritas EUR→XAU→BTC dan pemulihan adalah milik satu portofolio. Parameter strategi R3 tertanam pada FrozenR3.cs; hanya pengaturan akun/koneksi/izin transaksi yang tampil sebagai parameter.

## Berkas

- `RizanPortfolioR3Frozen.algo`: hasil build SDK resmi cTrader.Automate, bukan replay DLL yang diganti ekstensi.
- `source/`: proyek C# lengkap untuk dibaca dan dibangun ulang.
- `FROZEN_R3_LOCK.json`: identitas sumber, konfigurasi dan enam hasil historis R3.
- `PROFILE.json`: konfigurasi beku termasuk nilai default yang digunakan.
- `VALIDATION.json` dan `validation/`: bukti build, tes dan pemeriksaan yang selesai. Baca status demo/bridge secara terpisah dari status tes lokal.
- `BTC_SEED_PACKET.json`: seed historis yang dipatok hash. Ini **bukan feed terkini**; bridge harus memperpanjangnya dengan data asli.
- `SHA256SUMS.txt`: integritas berkas paket.

## Memasang di cTrader

1. Gunakan akun **demo USD hedged**, dengan simbol persis `XAUUSD`, `EURUSD`, `BTCUSD`. Sufiks simbol tidak otomatis dipetakan. Broker harus mendukung 0,01 lot XAU=1 oz dan 0,01 lot EUR=1.000 unit; cBot memeriksa kontrak tersebut dan berhenti jika tidak cocok. Ukuran BTC dikonversi melalui PipValue/PipSize dan langkah volume broker.
2. Impor/buka `RizanPortfolioR3Frozen.algo` melalui cTrader Algo. Buat **satu** instance saja; chart XAUUSD M1 boleh digunakan. cBot mengambil data simbol/timeframe strateginya sendiri.
3. Isi nomor akun penuh dan dua koneksi bridge pada tabel berikut. Pertahankan tiga strategi aktif. Mulai dengan `Kirim order=false` untuk memeriksa startup, kontrak, feed dan heartbeat.
4. Pastikan log menunjukkan profil `R3_I100_W060`, handshake bridge, feed BTC valid dan `RIZAN_PORTFOLIO ready=True`. Log `ready=False` berarti ada prasyarat yang belum terpenuhi; jangan memalsukan feed/ACK untuk mengatasinya.
5. Hentikan instance yang masih tanpa posisi, lalu mulai pada **akun demo yang sama** dengan `Kirim order=true`. Verifikasi order, SL/TP aktual, sizing, pembatalan antrean, expiry, disconnect dan restart memakai bridge/broker nyata sebelum penggunaan akun real.

| Parameter cTrader | Isi |
|---|---|
| Kirim order | Awalnya false; true hanya saat uji eksekusi demo siap |
| Nomor akun penuh | Nomor akun instance, bukan nomor yang disingkat |
| XAU aktif / EUR aktif / BTC aktif | Ketiganya true |
| Batas risiko terbuka gabungan % | 20,75; terkunci |
| Bridge WSS :25345 | Endpoint makro + checkpoint XAU/EUR yang kompatibel |
| Token bridge | Token pribadi minimal 32 karakter |
| BTC 7D WSS :25345 | Endpoint leased checkpoint + feed BTC yang kompatibel |
| Token BTC 7D | Token pribadi minimal 32 karakter |

Token tidak disertakan dan tidak ditulis pada laporan. Endpoint publik harus WSS port25345; WS hanya diterima untuk loopback pada pengujian lokal. cTrader Cloud memerlukan bridge eksternal yang dapat diakses; `localhost` di Cloud bukan komputer pengguna. Tidak ada pengujian Cloud atau koneksi ke akun/bridge nyata pada proses pembuatan ini.

`Kirim order=false` juga memblokir penutupan yang dilakukan cBot, mengikuti kode beku. Broker tetap memegang SL/TP yang telah terpasang. Jangan menggunakan false sebagai mekanisme penutupan posisi. Menghentikan cBot menghentikan pengelolaan antrean/expiry; SL/TP broker tetap berlaku. Jangan menghapus checkpoint untuk memaksa bot menjadi siap saat masih ada posisi.

## Dependensi strategi yang wajib tersedia

R3 asli menggunakan bridge makro/news dan feed BTC Bitstamp tujuh hari; paket ini mempertahankannya. Menjalankan file `.algo` saja dengan URL kosong tidak akan menghasilkan perdagangan R3 yang benar. Bridge produksi tidak dimodifikasi atau dihubungi. Gunakan instance bridge riset/demo dengan namespace baru di bawah ini; hanya server yang benar-benar menyimpan state secara durable dan menerapkan lease eksklusif yang boleh mengirim ACK.

**XAU/EUR:** client mengirim hello `{type,token,key,contract,lease}`. Key baru masing-masing `R3X_fe015394:<account>:XAUUSD` dan `R3E_fe015394:<account>:EURUSD`; hash contract tetap milik masing-masing frozen core. Server mengembalikan ready `{type:"ready",revision,state}`, menerima save dengan base_revision/client_revision dan checkpoint utuh, membalas ack dengan revision/client_revision, serta ping→pong. Snapshot makro dikirim sebagai `{type:"snapshot",data:...}` sesuai tipe ExternalSnapshot pada source: ProducedUtc, CoverageFromUtc/ToUtc, ForexFactoryOk, BlsOk, Dgs10/ Dfii10 (Delta, AvailableUtc), Events (AtUtc, Category). Data harus benar, segar dan memiliki cakupan waktu yang diminta; jangan mengubah flag sumber menjadi true tanpa data.

**BTC:** key `R3BTC:fe015394258bf1407ddb90c7d28f3a4e3a2c821a0f019c3c70d487d161c57cbf:<account>:BTCUSD`; kontrak `RZ-7D130-BTC8500283-LFOLLOW-WEEKEND`. Protokol di BtcStateLink.cs: hello→ready(revision,state), save(base_revision,client_revision,state)→ack(revision=base_revision+1,client_revision), ping→pong, feed / feed_unavailable, error. State adalah objek JSON utuh; pertahankan seluruh field NativeProfileHash dan NativePending*, jangan menyaringnya. Revision server dan revision client adalah dua penghitung yang berbeda. Satu lease aktif per key; pergantian lease harus meniadakan writer sebelumnya.

**Feed BTC:** `BTC_SEED_PACKET.json` memuat seed Bitstamp sampai 16 Oktober 2026 00:00 UTC. Untuk berjalan setelah tanggal tersebut, kirim paket dengan kontrak/sumber yang sama dan seluruh rangkaian hourly yang diperpanjang hingga awal jam berjalan, tiap hourly berasal dari 60 M1 asli tanpa celah. Format dan pemeriksaan hash terdapat di BtcSevenDayFeed.cs. Mengubah timestamp seed lama menjadi hari ini atau mencampur bars broker ditolak. Feed basi/tidak tersedia memblokir entry baru; pengelolaan exit posisi yang sudah dikenal tetap diupayakan ketika eksekusi diizinkan dan pasar terbuka.

## Kesetaraan dan adaptasi native

Entry, SL/TP, target, EUR BE, XAU step, safety fraction, risiko gabungan 20,75%, margin gabungan 50%, prioritas dan matematika batch BTC berasal dari R3 yang dibekukan. Source privat XAU/EUR tetap identik byte demi byte. BTC maksimum32 order total, risiko batch2,5%, margin batch10%, jendela180 detik, batas100 BTC per order sebelum safety/normalisasi dan batas broker. Angka ini bukan jaminan DD: perubahan equity/harga/biaya dapat membuat rasio risiko/margin yang teramati naik setelah order.

Port native menambahkan namespace R3, penyimpanan dengan key valid cTrader dan intent per order yang harus menerima durable ACK sebelum broker dipanggil. Konfirmasi jaringan/latensi nyata dapat membuat fill berbeda atau sinyal terlewat. Bila crash terjadi ketika hasil request belum pasti, cBot tidak mengulang request secara buta. Ia mencocokkan posisi/history dengan label dan batas volume, atau memblokir entry. Hasil yang terkonfirmasi dipelihara; sisa batch yang belum committed dibatalkan saat rekonsiliasi in-flight. Ini adaptasi pemulihan, bukan klaim jalur broker nyata identik dengan simulasi heartbeat sempurna.

Label baru mencegah bot ini mengambil alih posisi milik rilis LIVE/R2. Exposure asing memblokir entry; cBot tidak sengaja mengambil alih/menghapus posisi tersebut. Gunakan akun demo terpisah, satu instance, dan state bridge terpisah untuk pengujian.

## Hasil historis yang dibekukan

Modal simulasi USD100, tanpa top-up, periode2019 sampai9 Oktober2026; data M1 sintetis jalur A/B. Normal A saldo1.025.730.663,27; normal B972.851.373,67. Saldo biaya2x terendah861.912.752,79; DD equity terburuk enam skenario **71,6217%**. Angka ini bukan hasil trading native/real dan bukan proyeksi. Target DD<60% tidak dicapai R3. Replay bukan real ticks/OOS dan tidak mensertifikasi sesi historis broker atau vintage makro.

## Build ulang

Buka `source/RizanPortfolioR3Frozen.csproj` dengan cTrader Algo/IDE yang mendukung .NET dan NuGet, atau jalankan `dotnet build source/RizanPortfolioR3Frozen.csproj -c Release`. Target net6.0; cTrader.Automate dipatok1.0.21. SDK8.0.427 dipakai pada validasi paket ini. `AlgoPublish=false` mencegah pemasangan otomatis pada mesin build; `.algo` terdapat di bin/Release/net6.0. Jangan mendefinisikan REPLAY untuk build native, dan jangan menambahkan ApiStubs.cs/Replay.cs ke proyek produksi. Proyek native tidak memerlukan CSV historis atau runtime replay.
