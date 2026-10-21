# Audit pengiriman order dan replay sejak bridge aktif — 21 Oktober 2026

**Hasil:** fungsi pengiriman order source beku V1.3.0 bekerja dalam simulasi terisolasi. Belum terbukti bahwa seluruh syarat entry live XAU pada 20 Oktober lolos. Tidak ada pengiriman order live dalam audit ini.

## Batas waktu dan versi

- Journal bridge utama paling awal yang masih tersimpan: 11 Oktober 2026 14:37:13 WIB. Ini bukti paling awal yang tersedia, bukan sertifikasi waktu instalasi pertama pada 10 Oktober.
- Proses bridge utama yang sekarang berjalan dimulai 16 Oktober 17:07:07 WIB.
- Epoch checkpoint EUR F0245: 15 Oktober 12:19:17 WIB; XAU RC1: 16 Oktober 17:28:50 WIB. Epoch adalah awal checkpoint, bukan bukti waktu handshake terminal.
- Backend BTC: mulai 21 Oktober 05:19:45 WIB. Tidak boleh menganggap bridge BTC ini sudah aktif sejak 10 Oktober.
- Semua replay dibatasi candle closed sebelum 21 Oktober 09:49 WIB (02:49 UTC). Pemanasan indikator memakai data sebelum awal eksekusi.
- FX_SINCE_FIRST_RETAINED_BRIDGE menerapkan source SEKARANG pada periode journal bridge paling awal; bukan replay perubahan versi cBot lama. FX_CHECKPOINT_EPOCHS mulai dari epoch masing-masing engine versi sekarang. COMBINED_BTC_BACKEND mulai ketika backend BTC pertama tercatat berjalan.

## Replay yang benar-benar selesai

Sumber candle: cTrader Open API akun FP Markets yang cocok dengan akun pengguna. Input replay pertama: 49.622 bar XAU, 51.514 bar EUR, 51.982 bar BTC sejak 1 September; seluruh hash tercantum dalam REPLAY_BROKER_INPUT_MANIFEST.json. Seed indikator BTC tetap Bitstamp H1 tujuh hari sejak 2019, diperbarui dalam objek feed riset terpisah. OHLC broker untuk harga eksekusi BTC tidak menggantikan seed indikator tujuh hari.

Saldo simulasi baru $115,17, tanpa top-up; bukan rekonstruksi saldo/peak/checkpoint historis akun. Risk entry 20,75%, margin cap 50%, prioritas dan aturan entry/SL/TP/cooldown tetap beku. Path A/B adalah dua lintasan intramenit sintetis dari M1. ACK bridge 2 detik dan fill broker 2 detik dimodelkan; koneksi terminal historis tidak diputar ulang.

XAU memakai spread konstan 0,26, EUR 0,00001, biaya normal model beku. Spread historis ask dan kondisi broker di tiap sinyal tidak tersedia. Leverage simulasi 200; ini tidak membuktikan leverage efektif BTC broker. TECH_ALLOWED menyediakan izin macro sintetis; STRICT_NO_MACRO memakai macro tidak tersedia. Keduanya bukan arsip macro point-in-time.

| Case | Kandidat XAU/EUR/BTC | Basket XAU/EUR/BTC | Request | Saldo akhir | Error / cash residual |
|---|---:|---:|---:|---:|---:|
| FX_SINCE_FIRST_RETAINED_BRIDGE_TECH_ALLOWED_A | 4/1/0 | 1/1/0 | 3 | $97.435500 | 0 / 0.00000000 |
| FX_SINCE_FIRST_RETAINED_BRIDGE_TECH_ALLOWED_B | 4/1/0 | 1/1/0 | 3 | $103.663000 | 0 / 0.00000000 |
| FX_SINCE_FIRST_RETAINED_BRIDGE_STRICT_NO_MACRO_A | 4/1/0 | 0/1/0 | 2 | $104.134000 | 0 / 0.00000000 |
| FX_SINCE_FIRST_RETAINED_BRIDGE_STRICT_NO_MACRO_B | 4/1/0 | 0/1/0 | 2 | $104.083000 | 0 / 0.00000000 |
| FX_CHECKPOINT_EPOCHS_TECH_ALLOWED_A | 3/0/0 | 1/0/0 | 1 | $108.471500 | 0 / 0.00000000 |
| FX_CHECKPOINT_EPOCHS_TECH_ALLOWED_B | 3/0/0 | 1/0/0 | 1 | $114.750000 | 0 / 0.00000000 |
| FX_CHECKPOINT_EPOCHS_STRICT_NO_MACRO_A | 3/0/0 | 0/0/0 | 0 | $115.170000 | 0 / 0.00000000 |
| FX_CHECKPOINT_EPOCHS_STRICT_NO_MACRO_B | 3/0/0 | 0/0/0 | 0 | $115.170000 | 0 / 0.00000000 |
| COMBINED_BTC_BACKEND_TECH_ALLOWED_A | 0/0/0 | 0/0/0 | 0 | $115.170000 | 0 / 0.00000000 |
| COMBINED_BTC_BACKEND_TECH_ALLOWED_B | 0/0/0 | 0/0/0 | 0 | $115.170000 | 0 / 0.00000000 |
| COMBINED_BTC_BACKEND_STRICT_NO_MACRO_A | 0/0/0 | 0/0/0 | 0 | $115.170000 | 0 / 0.00000000 |
| COMBINED_BTC_BACKEND_STRICT_NO_MACRO_B | 0/0/0 | 0/0/0 | 0 | $115.170000 | 0 / 0.00000000 |

Semua case berakhir tanpa posisi tersisa, tanpa terminal forced close, tanpa quarantine atau accounting block. Rekonsiliasi cash absolut < $0,000001. Tidak ada stress biaya/delay baru atau optimasi strategi dalam audit ini.

Pada jendela epoch versi sekarang, XAU menghasilkan kandidat SELL 20 Oktober pukul 19:05, 19:40, dan 20:55 WIB. Kontrol macro mengizinkan menghasilkan satu basket pada kedua path, dengan request simulasi 19:05:04 WIB. Kandidat berikutnya tertahan basket aktif atau cooldown setelah kerugian; tiga kandidat bukan tiga order. Path A/B adalah alternatif lintasan yang sama, bukan dua transaksi independen. Pada kontrol tanpa macro, ketiganya berstatus XAU_MACRO_NEWS_FEED_REQUIRED dan tidak ada request.

EUR tidak memiliki kandidat setelah epoch F0245 yang diperiksa. Sejak backend BTC mulai 21 Oktober 05:19 sampai batas data 09:49 WIB, tidak ada kandidat XAU, EUR, maupun BTC. Karena itu tidak ada order dalam keempat kontrol gabungan pada jendela tersebut.

Jendela bridge paling awal yang tersimpan (11 Oktober 14:37 WIB) menghasilkan 4 kandidat XAU dan 1 kandidat EUR pada source sekarang. EUR SELL 13 Oktober 18:00 WIB membentuk satu basket dengan dua batch/request. XAU SELL 14 Oktober 19:35 WIB tertahan NO_INTEGER_CHILD_WITHIN_BUDGET setelah saldo simulasi turun ke sekitar $104,13. XAU SELL 20 Oktober 19:05 membentuk satu basket jika macro diizinkan. Total kontrol ini dua basket, tiga request pada masing-masing path; bukan rekonstruksi versi EUR lama RZEU4B. Pada kontrol tanpa macro hanya basket EUR yang terjadi. Timestamp sinyal EUR 13 Oktober juga cocok dengan LastSignal checkpoint EUR lama, tetapi parameter/versi dan histori keputusan lama belum direkonstruksi penuh.

## Uji fungsi pengiriman terisolasi

24 fixture XAU/EUR BUY/SELL lulus: sinyal eksekusi valid + ACK menghasilkan tepat satu request dan posisi simulasi ber-SL/TP. ACK intent yang belum diterima menghasilkan nol request; EnableTrading=false, spread berlebih, posisi asing, atau bridge stale juga menahan request. Fixture memasukkan sinyal eksekusi terkontrol, bukan pola pasar historis tambahan.

1.087 pemeriksaan regresi lulus: Portfolio 827 (termasuk 200 siklus reconnect), Weekend 25, Leverage 31 (termasuk BTC BUY/SELL), SevenDay 204 (termasuk 158 signal parity). Fake broker digunakan; native order acceptance belum terbukti. Semua 16 file source manifest tetap cocok byte dengan versi beku.

## Bukti dari akun dan bridge

Akun terbaca $115,17, posisi 0 dan pending order 0. Riwayat order yang dikembalikan API tidak memuat label cBot yang ditargetkan sejak 10 Oktober; has_more=false. Ini bukan bukti bahwa tidak pernah ada permintaan yang ditolak sebelum menjadi order historis. Seluruh pesan API keluar dibatasi allowlist baca saja; tidak ada NewOrder/Amend/Cancel atau refresh token.

Margin minimum saat pemeriksaan: XAU 1 unit $20,59; EUR 1.000 unit $5,61; BTC 0,01 BTC $16,55. Leverage akun terlapor 20.000 cent = 1:200. Dengan harga BTC M1 sekitar $82.721, rasio notional/margin untuk 0,01 BTC sekitar 50×; ini estimasi indikatif memakai candle terakhir dan margin saat permintaan, bukan sertifikasi tier leverage. Native harus mengikuti GetEstimatedMargin broker. Margin BTC simulasi 200× tidak boleh dianggap sama dengan kondisi broker; pada jendela BTC yang diperiksa tidak ada kandidat, sehingga perbedaan ini tidak menyebabkan angka entry nol tersebut.

Checkpoint saat audit tidak berisi basket/pending intent, XauPendingSignal=null, LastSignal XAU/EUR versi sekarang masih default, dan tidak quarantined. Ini tidak cukup untuk menentukan alasan blok saat setiap sinyal masa lalu. Source menahan entry sebelum pembentukan basket jika trading/account/recovery/portfolio gate belum lolos atau macro tidak lolos.

Snapshot macro yang dibaca sekarang berstatus sumber tersedia dan menyimpan DGS10 Delta=-0,01, AvailableUtc 20 Oktober 04:00 UTC. Menurut aturan source, nilai itu tidak selaras untuk SELL. Akan tetapi snapshot tersebut diproduksi 21 Oktober, sehingga TIDAK membuktikan snapshot/point tersebut benar-benar diterima terminal pada 20 Oktober. Tidak dibuat klaim bahwa macro pasti merupakan penyebab tunggal nihil entry.

Catatan batas: terminal cTrader bisa memiliki parameter, warmup history, waktu restart, atau status readiness yang tidak tercatat di VPS. Journal keputusan terminal pada waktu sinyal dan arsip macro yang dikirim saat itu diperlukan untuk menyertifikasi alasan setiap keputusan live. Heartbeat bridge saja tidak membuktikan seluruh syarat entry lolos. Tidak ada perubahan cBot live, risk, production env, restart bridge, merge main, atau pengiriman order.

## Sumber dan artefak

- Source beku acuan: e357272fec03411a6e7c4d2397faf742d1a11047, portfolio_7day_frozen. Source manifest cocok 16/16.
- Wrapper replay awal: 89ca1f2cd64601bb8af89a3186369ec3a7af54ed. Perluasan jendela journal paling awal: 0612939a23b35e0275d1b7e50956e0f330abf3dc. Seluruh perubahan wrapper dicatat dalam ACTIVATION_HARNESS.diff.
- Regresi/orderability: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39535910719 (success).
- Replay lengkap 12 case: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39536869038 (success). ZIP luar 2.983.349 byte; SHA256 5897e08bebe02306d75509ea15127379555c74e7c6e994f5747c48552b4b5b4e; artifact 12318001900. Perbandingan delapan case sebelumnya tetap sama.
- Pembacaan marker native/current macro: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39536538363 (success).
- Pengambilan broker dan margin berhasil pada job 119012023463. Run 39535798577 keseluruhan gagal pada dependency fixture yang kemudian diperbaiki dan lulus di run regresi terpisah; artefak broker diverifikasi byte, tidak menganggap run awal tersebut sukses keseluruhan.
- Ledger fill, kandidat, konfigurasi, checksum artefak luar, rekonsiliasi, marker native dan hasil pemeriksaan disimpan bersama laporan ini.
