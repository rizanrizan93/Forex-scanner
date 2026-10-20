# Pemeriksaan lanjutan bridge — 21 Oktober 2026

Screenshot menunjukkan LEASE_BUSY saat startup20 Oktober22:45:48UTC, lalu handshake dan heartbeat bridge utama22:46:03–08UTC. Snapshot server sesudahnya mengonfirmasi koneksi sudah pulih.

## Bukti aktual
Actions39510945722 completed/success.
Dua snapshot read-only pada20 Oktober22:50:37UTC dan22:50:56UTC (21 Oktober05:50WIB):
- Lease EUR RZEF245 aktif; umur heartbeat10,32detik lalu8,21detik.
- Lease XAU RZXRC1 aktif; umur heartbeat6,32detik lalu5,19detik.
- Lease BTC RZBTC7D130 aktif; umur heartbeat11,29detik lalu7,19detik.
- Server/client BTC checkpoint revisi2, Fault=false, Sending=false, ExitPending=false.
- Token layanan utama danBTC cocok, akunBTC sesuai.
Audit ini tidak membuka koneksi WebSocket, tidak memperoleh lease uji, dan tidak menyimpan checkpoint. Lease diperbarui oleh klien yang sudah berjalan, bukan oleh audit.

## Keputusan
Tidak ada perubahan runtime tambahan yang diperlukan untuk screenshot tersebut setelah bukti koneksi pulih. Pertahankan layanan dan instans aktif. Jangan menghapus checkpoint/lease aktif atau mengubah token untuk mengatasi log startup lama.

LEASE_BUSY menolak writer/session kedua untuk identitas yang sama. Sesudah klien lama berhenti, lease tersisa dapat menghalangi instans baru sampai45detik sejak heartbeat terakhir. Jika klien lama terus berjalan, lease tetap diperbarui. Ini mekanisme mencegah dua penulis/eksekutor; bukan alasan melemahkan validasi identitas.

Kode persis penolakan BTC pada screenshot tidak terekam oleh binary, sehingga tidak boleh diklaim pasti AUTH_FAILED/IDENTITY_INVALID/LEASE_BUSY. Keberadaan koneksi aktif sesudahnya terverifikasi langsung. Setidaknya satu klien untuk masing-masing instrumen aktif, tetapi audit server tidak mengidentifikasi instans mana yang sedang dibuka di layar pengguna.

Koneksi dan checkpoint aktif tidak membuktikan semua syarat entry: FeedReady/RecoveryReady, jadwal broker, sinyal, margin dan risk gate native tetap berlaku. Audit tidak mengirim order atau mengubah EnableTrading.

## Perubahan
Hanya workflow audit read-only dan dokumentasi pada branchfix/btc7d-bridge-connectivity-20261021. Tidak ada restart VPS/bridge, perubahan source strategi, DB, environment, token, risk, atau merge ke main. Router alternatif tidak dipasang atau dikomit karena audit menunjukkan koneksi yang ada sudah berjalan.

- Actions: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39510945722
- Artefak: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39510945722/artifacts/12306610018
- SHA256 ZIP luar: b932469917427a0e7e47d19175d657f08536541698464ab702cd52fd4eb0e93e
