# Audit terbatas RIZAN LIVE 7903 — 4 November 2026

## Hasil dan batas verifikasi

**Bug source Weekend Lock BTC: TERBUKTI melalui reproduksi engine lengkap. Penyebab transisi aktual LIVE: DUGAAN kuat, timestamp journal BELUM TERVERIFIKASI.** Patch dan build resmi sudah diverifikasi offline. Instance LIVE, parameter, bridge, lease, posisi, dan checkpoint tidak diubah. Tidak ada test order nyata. Draft PR: https://github.com/rizanrizan93/Forex-scanner/pull/815 . Branch `fix/btc-weekend-cache-20261104`; commit build terverifikasi `49f69ee53989cbca7eb57cc5d10fc6784969bafb`.

| Lapisan | Status |
|---|---|
| Code fixed | YA, cache jadwal BTC melewati batas minggu UTC |
| Build verified | YA, cTrader.Automate 1.0.21, net6.0, 0 error/0 warning |
| Simulated runtime verified | YA, engine produksi dengan API/broker simulasi |
| cTrader pengguna berhasil mengimpor/menjalankan binary | BELUM DIVERIFIKASI |
| Runtime LIVE memakai patch | TIDAK; belum dideploy |
| LIVE deployment verified | TIDAK |
| Checkpoint lock LIVE telah dikoreksi | TIDAK |

Snapshot terakhir yang berhasil diperoleh untuk audit ini adalah **4 November 07.03 WIB**, bukan pemeriksaan runtime baru pada jam penyelesaian laporan. Connected=3 dan lease aktif membuktikan konektivitas/state service saat snapshot; keduanya tidak membuktikan semua guard executable terpenuhi.

## P0: source, aliran state, dan root cause

Source frozen diambil dari `RIZAN_F005_BTC10_FROZEN_20261102.zip`, lalu diverifikasi terhadap GitHub `work/btc-eff20-frozen-20261102:isolated_btc10_20261102/overlay.tar.gz`: seluruh **21/21 file source identik**. Salinan terisolasi untuk PR berada pada `repairs/btc_weekend_20261104/source/`.

File/fungsi terkait:

- `BtcEngine.cs`: `RefreshSchedule`, `Manage`, `Enter`, `ExecuteSignal`, `ProcessResearchBatch`, `Save`, `OnStart`, dan `Recover`.
- `BtcWeekendPolicy.cs`: `Monday`, `Weekend`, `LastClose`, `MustFlatten`, dan `CanEnter`.
- `BtcStateLink.cs`: `Receive` (`ready` memulihkan checkpoint; `ack` mengonfirmasi revision) dan `Changed`/`Flush`.
- `BtcNativeLifecycle.cs`: validasi/reconcile intent dan sequence setelah recovery.

`Manage` memanggil `RefreshSchedule` terlebih dahulu. Namun source lama hanya memperbarui weekly close jika `now >= nextSchedule`, dengan cache lima menit. Jika cached close Jumat masih ada pada Senin 00.00 UTC dan refresh berikutnya 00.03 UTC, `MustFlatten(now, oldClose)` bernilai true. Saat prior lock tepat kedaluwarsa, `WeekendLockUntil <= now` juga true. `Manage` menulis `Monday(now).AddDays(7)` sebagai lock baru: 9 November, bukan mempertahankan 2 November. `SaveExitIntent` meneruskan ke `Save`, yang menyimpan LocalStorage dan mengirim revision state ke bridge.

**Lock merupakan guard eksekusi nyata, bukan label telemetry.** `CanEnter` mensyaratkan `now >= lockUntil`. Guard ini dipakai pada admission `Enter`, pemeriksaan ulang sebelum order `ExecuteSignal`, serta setiap child order `ProcessResearchBatch`. `Recover` dapat mengadopsi state remote dengan client revision lebih tinggi daripada local. Snapshot remote menunjukkan revision client 168/server 167 dan lock 9 November. Namun local memory/LocalStorage instance dan journal transisi tidak diambil secara langsung, sehingga pemakaian *nilai persis tersebut* di memori LIVE saat ini belum dibuktikan independen.

### Rekonstruksi 30 Oktober–2 November

| Waktu UTC | Rekonstruksi mekanisme source |
|---|---|
| Jumat 30 Oktober close 20.59 | Timetable minggu lama memiliki weekly close ini; cutoff no-entry 60 menit dan flatten 30 menit tetap berlaku |
| Weekend 31 Oktober–1 November | Sabtu/Minggu UTC tidak boleh entry; lock semestinya sampai Senin 2 November 00.00 UTC |
| Minggu menjelang tengah malam | Refresh lima menit dapat menempatkan `nextSchedule` sesudah 00.00 Senin; cached close masih milik minggu lama |
| Senin 2 November 00.00 | Prior lock 2 November habis; close cache Jumat memicu flatten dan source lama memperpanjang lock ke 9 November |
| Senin sesudah refresh | Jadwal sudah segar, tetapi future lock yang salah telah tersimpan dan tetap menghalangi entry |
| Snapshot 3–4 November | Evidence memang berisi lock 9 November, Fault=false, Sending=false; tidak membuktikan menit terjadinya transisi |

Tanggal/Jam pada rekonstruksi yang tidak berasal dari snapshot adalah skenario reproduksi, bukan journal kejadian LIVE. Perubahan DST New York 1 November menjelaskan pergeseran weekly close dari 20.59 menjadi 21.59 UTC. Aritmetika lock source menggunakan `Server.TimeInUtc`, bukan broker wall time; tidak ditemukan alasan mengganti timezone atau cutoff frozen.

### Patch produksi

Hanya kondisi invalidasi cache pada `RefreshSchedule` diubah:

```csharp
// lama
if(now>=nextSchedule) { /* refresh weekly close */ }
// baru
if(now>=nextSchedule ||
   (weekClose.HasValue && weekClose.Value<=BtcWeekendPolicy.Monday(now)))
{ /* refresh weekly close */ }
```

Refresh tetap terjadi sebelum keputusan flatten/lock/entry. Close dari minggu lama tidak dipakai untuk keputusan minggu baru. Error jadwal tetap membuat `marketOpen=false` dan `weekClose=null`: fail closed. Tidak ada auto-unlock, reset state, perubahan `MustFlatten`/`CanEnter`, penambahan order, atau pemutaran ulang sinyal terlewat.

### Hasil regresi sebelum/sesudah

Offline workflow berhasil: https://github.com/rizanrizan93/Forex-scanner/actions/runs/41751129544 . Log lengkap disertakan dalam paket audit.

| Kasus | Frozen lama | Patch |
|---|---|---|
| Exact cached close 30 Okt 20.59; next refresh 2 Nov 00.03; evaluasi 00.00; prior lock 2 Nov | Lock menjadi 9 Nov, eligibility false | Lock tetap 2 Nov, eligibility true jika broker open |
| Berjalan normal Jumat → weekend → Senin dengan cache melewati boundary | Lock salah diperpanjang | Kembali eligible pada batas frozen |
| Jumat sebelum no-entry / 60 menit sebelum close / 30 menit sebelum close | Cutoff asli berlaku | Sama |
| Restart Sabtu/Minggu | Entry diblokir | Sama |
| Restart/reconnect Senin dengan jadwal segar dan expired lock | Eligible jika broker open | Sama |
| Broker belum buka Senin, kemudian buka | Tunggu broker open | Sama; tidak membuka lebih awal |
| Cache segar | Eligibility sesuai guard | Sama |
| Restart Rabu dengan expired lock normal | Eligible | Sama |
| Restart Rabu dengan poisoned future lock 9 Nov | Masih diblokir | Masih diblokir; perlu koreksi state terpisah |
| Error timetable | Fail closed | Sama |
| Batas tahun/ISO year, cache lama pada Senin 28 Des, 1 Jan, 4 Jan | Bug berulang pada skenario boundary | Lock tidak diperpanjang karena cache minggu lalu |
| Manage dipanggil berulang, ACK/reconnect, intent crash | Proteksi sequence berlaku | Proteksi tetap berlaku; tidak ada order nyata |

Suite weekend memeriksa **58 checks pada source lama dan 58 pada patch**. Mode lama sengaja mengharapkan hasil bug untuk membuktikan reproduksi; lulusnya suite lama bukan pernyataan bahwa perilaku lama benar. Selain itu: **449 checks native BTC**, **54 checks native XAU/EUR**, dan **295 gate checks dengan 141 sinyal historis BTC**. Tes BTC mencakup BUY/SELL, ACK wajib sebelum order, duplikasi label/sequence, recovery, rejection, persistence failure, margin/risk, expiry, dan batas batch. Pembandingan hash membuktikan 20 source lain identik, dan pembalikan patch satu kondisi menghasilkan SHA256 engine frozen asli. Ini bukan replay profit/DD baru dan bukan pembuktian runtime LIVE.

## Eligibility BTC LIVE dan koreksi state yang diperlukan

Evidence 07.03 WIB: profile sesuai; connected=3; lease BTC aktif dengan sisa sekitar 36,9 detik; Fault=false; Sending=false; lock `2026-11-09T00:00:00Z`; history broker tiga hari lengkap dengan **0 order/0 deal**; tidak ada raw BTC baru pada snapshot. Karena itu tidak dapat disimpulkan bahwa bug telah menyebabkan missed trade BTC pada interval tersebut. Jika state tersebut dipakai runtime, BTC tetap ditahan lock sampai 9 November **07.00 WIB**. Patch pencegahan saja tidak mengubah future lock yang sudah telanjur salah.

Pemulihan lebih cepat memerlukan **persetujuan deployment dan koreksi state BTC yang terarah**, bukan clear checkpoint. Proposal nilai pada konteks snapshot Rabu ini adalah `WeekendLockUntil: 2026-11-09T00:00:00Z → 2026-11-02T00:00:00Z`. Semua field strategi, LastSignal/watermark, expiry, intent, sequence, fault, dan state XAU/EUR harus dipertahankan. Nilai proposal harus dihitung/ditinjau kembali dari waktu dan timetable aktual saat pelaksanaan; jangan menerapkan proposal ini setelah masuk window proteksi Jumat atau weekend.

Koreksi belum dilakukan dan laporan ini tidak menyediakan perintah tulis LIVE. Sebelum koreksi: baca ulang local+remote state, account binding penuh (hanya tampilkan suffix), revision, lease owner, posisi/pending order broker, intent in-flight, dan schedule. Tolak jika Sending/pending intent/posisi/queue berubah, identity berbeda, waktu masuk guard weekend, atau revision bergerak. Gunakan maintenance terkendali dengan satu writer, backup konsisten, compare-and-swap server revision, dan client revision monotonik; jangan membuat konflik equal-revision local/remote. Rekonsiliasi local dan remote harus tervalidasi sebelum trading diaktifkan kembali. Jangan force lease atau menghapus state.

Opsi menunggu natural expiry juga memerlukan patch sebelum boundary berikutnya; pada source lama, bug yang sama dapat berulang pada Senin berikutnya. Kelulusan guard lock tidak menjamin ada sinyal baru atau order: seluruh guard frozen tetap berlaku, dan sinyal yang sudah dikonsumsi tidak boleh dikejar ulang.

## P1: kandidat XAUUSD SELL 3 November 19.05 WIB

**Klasifikasi final: POTENSI ORDER TERLEWAT — BELUM TERVERIFIKASI.** Kedua raw seed menghasilkan waktu, sisi, ATR, anchor, dan family yang sama: `2026-11-03T12:05:00Z`, SELL, ATR `2.8935714285713794`, anchor BID `3907.6493571428573`, `F005_COMPRESSION`. Seed awal 13/14 Oktober serta 19 Oktober memberikan kandidat sama. M1 broker terbaru memiliki 20.612 bar berurutan, unik, OHLC valid; kelima candle 12.00–12.04 UTC tersedia. Runtime history depth dan candle yang benar-benar dilihat instance saat itu tidak tersimpan.

| Pemeriksaan | Temuan / batas bukti |
|---|---|
| Session, warmup, trend, compression | Raw frozen evaluator menerima kandidat pada window 12–17 UTC, M5 lengkap, warmup H1 cukup di kedua seed. Ini belum membuktikan history/warmup runtime identik |
| NEWS/MACRO source | `xau/RizanRobot.cs: ExternalOk` mewajibkan snapshot fresh ≤180 detik, coverage -30/+495 menit, source FF/BLS OK, macro tidak stale/future, dan direction sesuai |
| US10Y SELL | SELL memakai Dgs10. Guard `s.Side * macro.Delta > 0` memblokir SELL bila delta yield negatif |
| Snapshot yang tersedia | Snapshot 4 Nov 07.05 WIB memuat Dgs10 delta -0.04 (AvailableUtc 3 Nov 05.00 UTC) dan JOLTS 3 Nov 15.00 UTC/22.00 WIB. Keduanya berpotensi memblokir SELL menurut source, tetapi **ProducedUtc sesudah kandidat**, sehingga bukan bukti input runtime 19.05 |
| NEWS HOLD | Window kandidat adalah 3 Nov 18.35 sampai 4 Nov 03.20 WIB. JOLTS 22.00 WIB berada di dalamnya **jika event itu sudah ada dalam snapshot runtime saat kandidat**; kondisi itu belum dibuktikan |
| Spread/min volume/risk/margin/exposure | Tidak ada spread historis/quote, equity, margin, atau exposure tepat saat kandidat. Snapshot kemudian tidak dapat dipakai menggantikannya |
| Cooldown/quarantine | Snapshot kemudian menunjukkan XauResumeUtc default, Quarantined=false, Basket=null; bukan journal guard 19.05 |
| EnableTrading/PortfolioReady/account binding | Broker reader memakai akun suffix 7903 dan checkpoint terikat 7903. Nilai runtime EnableTrading/BindingOk/PortfolioReady pada 19.05 tidak tersedia |
| Handshake/lease/ACK/sequence/journal | Lease dan connected pada snapshot kemudian aktif. Tidak tersedia journal historis per-decision/ACK untuk menit kandidat; current receipts/state bukan historical decision log |
| Order intent/request/rejection/history | 0 order/0 deal pada history broker lengkap tiga hari; LastSignalUtc default pada checkpoint kemudian. Tidak ditemukan intent/request ID/rejection yang cocok. Tidak ada bukti request pernah dikirim |

LastSignalUtc yang tetap default konsisten dengan kandidat berhenti sebelum basket dikomit, tetapi tidak mengidentifikasi guard penyebab. Jangan menamai macro/JOLTS sebagai penyebab TERBUKTI tanpa snapshot historis dan journal. Tidak ada aturan entry XAU yang diubah untuk mengejar sinyal ini.

## P2: jeda XAU 4 November 05.57 WIB

**Sesuai jeda pasar terjadwal; tidak ada bug checkpoint yang terbukti, tidak ada patch P2.** Kontrak broker XAUUSD memiliki timezone `America/New_York`. Sesi terkait berakhir 3 November 16.59 EST = **4 November 04.59 WIB**, dan sesi selanjutnya mulai 3 November 18.00 EST = **4 November 06.00 WIB**. Candle M1 terakhir dibuka 04.58 WIB lalu ditutup 04.59 WIB.

Pada snapshot 05.57 WIB, **broker bars dan checkpoint XAU sama-sama terakhir 04.58 WIB**, sedangkan EUR/BTC mencapai 05.56. Pada snapshot 07.03 WIB broker bars/checkpoint XAU mencapai 07.02 WIB; CSV memuat bar kembali setelah pembukaan. Tidak ada evidence collector ketinggalan dibanding feed broker pada dua snapshot tersebut. Jadwal+data menjelaskan jeda; konektivitas aktif tidak perlu diklasifikasikan disconnect. Jangan memaksa candle sintetis atau memajukan watermark saat pasar tutup.

## Dampak frozen dan kompatibilitas

- Seluruh `BtcWeekendPolicy.cs` tetap identik: Sabtu/Minggu **UTC** dilarang; entry berhenti 60 menit sebelum close; flatten 30 menit sebelum close; reopening memerlukan marketOpen serta lock habis. Walau broker dapat buka Minggu malam UTC, guard kalender tetap menahan sampai Senin 00.00 UTC / **07.00 WIB**, sesuai aturan lama.
- XAU/EUR, indikator, threshold, risk, sizing, lot, SL/TP, compression, batch, ACK, lease, fault recovery, LastSignal dan deduplikasi tidak diubah.
- Target/metadata binary: `cAlgo.Robots.RizanPortfolioBTC10Frozen`, assembly versi `3.3.0.0`, timezone UTC, API `1.0.21`, target `net6.0`. Metadata robot dan seluruh parameter **identik dengan metadata frozen**; default EnableTrading tetap false.
- File hasil build resmi: `RizanPortfolioBTC10Frozen_WeekendFix_20261104.algo`. Kompatibilitas compile/package terverifikasi. Import/run pada versi cTrader pengguna belum dilakukan; ini tetap merupakan deployment gate terpisah.

## Hash, backup, deployment, rollback

| Artefak | SHA256 |
|---|---|
| Paket frozen asal | `67ed4ccfab3c98613a533b174e7d5db2e2bfc839652bf682f786b6b99df4635b` |
| Binary frozen asal | `0abf9c0dad2ad0fc911a96b7bd6e78524862a29dee8c7a283c4489c250cc803b` |
| BtcEngine.cs frozen | `106ac56455f9cc4cfa00562246aa3223541162c7a3d86b64d17a0daf1b3224a0` |
| BtcEngine.cs patch | `526442e4924d3c861eb59bff24911dc1ab01c2ed8c69098852f03f3fcba4c79d` |
| Binary patch hasil run sukses | `6ed8912e8aaad9a985c98327043363101b91b36ae6a44b754c2c1d5e40943edd` |

Daftar hash seluruh source/binary dan log build tersedia dalam paket. Binary frozen yang diarsipkan adalah backup **distribusi asal**, bukan klaim bahwa binary yang aktif di mesin cTrader sudah dibackup/dihash ulang. Snapshot evidence tetap bersifat historis; backup fresh konsisten sebelum perubahan LIVE masih wajib.

### Rencana tindakan setelah persetujuan eksplisit

1. Review/approve PR dan binary hash; ambil snapshot baru read-only; cocokkan instance/account 7903, versi cTrader, source/build identity, parameter, posisi, pending order, queue, intent, client/server revision, serta pemilik lease. Jangan lanjut jika hasil berbeda dari prasyarat atau timbul posisi baru.
2. Uji import/start di lingkungan terisolasi tanpa akses broker LIVE, EnableTrading=false, tanpa mengambil lease produksi. Validasi parameter/metadata/recovery sebelum menyentuh instance produksi.
3. Ambil backup binary aktif sebenarnya, parameter tanpa token dalam laporan, local checkpoint dan remote checkpoint/receipts beserta revision, serta journal. Simpan material sensitif secara privat; jangan unggah token/credential.
4. Karena satu cBot menaungi tiga instrumen, replacement/start-stop dapat menjeda XAU/EUR sebentar walau kode strateginya identik. Pilih maintenance window dan hanya lakukan stop/start **instance gabungan yang diperlukan** setelah disetujui; tidak perlu restart cTrader aplikasi atau bridge, dan tidak perlu provisioning workflow lama.
5. Lakukan koreksi field lock BTC hanya dengan persetujuan spesifik dan prosedur revision/local-remote konsisten yang ditinjau. Jangan reset watermark, LastSignal, sequence, atau checkpoint XAU/EUR. Tolak snapshot stale dan state konflik.
6. Deploy binary patch dengan parameter frozen sama. Biarkan recovery/reconcile dan ACK berjalan normal; jangan force lease. Verifikasi Fault=false, Sending=false, lease tunggal, readiness/handshake/account binding, checkpoint konsisten, future close segar, serta lock sesuai minggu berjalan.
7. Verifikasi bahwa status weekday tidak lagi ditahan WEEKEND LOCK, sementara spread/risk/macro/news/signal/session tetap dapat memblokir. Tunggu sinyal baru alami; jangan mengirim test order dan jangan replay/catch-up kandidat lama. Verifikasi request ID → broker result hanya bila entry frozen baru sungguh terjadi.
8. Pantau transisi Jumat cutoff 60/30 menit, Sabtu/Minggu UTC, dan Senin 00.00 UTC berikutnya. Ini baru dapat menaikkan status menjadi LIVE deployment/runtime verified setelah evidence nyata tersedia.

### Rollback

Jika import/recovery/ACK/identity gagal, hentikan aktivasi pengiriman order dan simpan journal/state terbaru; jangan mencoba ulang order yang statusnya tidak pasti. Setelah otorisasi maintenance, kembali ke binary aktif yang telah dibackup dan parameter identik. Pertahankan checkpoint terbaru yang valid dan revision monotonik. **Jangan mengembalikan checkpoint lama secara buta setelah ada sinyal/order baru**, karena dapat memutar ulang watermark/sequence atau membuat konflik state. Rollback state, bila diperlukan, harus menjadi tindakan terpisah yang direkonsiliasi dengan history broker dan persetujuan khusus. Binary lama tetap mengandung bug boundary; rollback bukan perbaikan permanen weekend.

## Persetujuan yang masih diperlukan

- Merge/release serta deploy binary ke instance LIVE gabungan 7903, termasuk maintenance stop/start instance bila diperlukan.
- Koreksi terarah `WeekendLockUntil` BTC yang sudah telanjur salah, sesudah snapshot baru dan validasi writer/revision; tidak ada izin untuk reset/clear checkpoint.
- Tindakan rollback LIVE atau perubahan state lain apabila kelak diperlukan.

Sampai persetujuan diberikan, audit berhenti pada source/PR/build terverifikasi. Tidak ada perubahan atau redeploy LIVE yang telah dilakukan.
