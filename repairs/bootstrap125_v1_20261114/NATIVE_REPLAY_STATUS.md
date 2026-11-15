# Status replay native — 15 November 2026 WIB

**Belum dijalankan penuh / belum tersertifikasi. Tidak ada angka saldo, DD atau trade bulanan baru dari replay tick broker tiga pair.**

Inventaris file VPS pada audit terbaru:

| Pair | File tick 2026 yang terlihat |
|---|---|
| XAUUSD | Januari–Maret |
| EURUSD | Januari–April |
| BTCUSD | Folder tick tidak tersedia |

Jumlah file bukan bukti data bebas gap/duplikasi. Arsip penelitian XAU/EUR selama ini menggunakan Dukascopy; audit ini tidak mengesahkan kesetaraannya dengan tick FP Markets. BTC live bridge memakai Bitstamp M1/H1, bukan tick CFD broker.

File live memakai bridge, ACK dan clock live. Feed BTC produksi mempunyai seed/hash tetap sampai16Oktober2026, sehingga validator produksi tidak menerima prefix awal2019 sebagai feed live valid. Jangan menghubungkan backtest historis ke route/checkpoint akun live. Diperlukan adapter replay point-in-time dengan state terisolasi dan bukti bahwa tidak ada harga atau macro masa depan masuk ke keputusan.

Untuk replay penuh diperlukan bid/ask tiga pair pada rentang yang sama, warmup sebelum2019, spec kontrak/margin/leverage/biaya/swap yang sesuai, dan akun simulasi/backtester terautentikasi. Equity floating serta DD harus dihitung menurut urutan tick gabungan. Laporan harus memisahkan continuous compounding dari reset100per tahun, serta mencatat trade bulanan, margin/stop-out, seed graduation, order ditolak dan minimum lot yang dilewati.

Hasil arsip sintetis M1 sampai13November2026 10:00WIB tetap hasil arsip, bukan hasil tick native baru. Akhir November belum terjadi pada tanggal audit. Keberadaan image CLI pada VPS atau keberhasilan membaca metadata bukan bukti replay selesai.
