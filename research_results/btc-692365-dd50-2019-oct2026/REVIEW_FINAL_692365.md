# BTC 692365 — hasil pencarian DD di bawah 50%

Dari 112.420 konfigurasi unik, saldo akhir tertinggi yang ditemukan dengan floating drawdown model di bawah 50% adalah **$53.784,54 dengan DD 49,43%**. Pencarian ini belum mempertahankan saldo $1 juta pada batas DD tersebut.

Semua hasil menggunakan modal awal $100 tanpa top-up, akun BTC standalone, periode 1 Januari 2019–15 Oktober 2026. Sinyal kandidat 692365 dipertahankan: displacement BUY H4, threshold 0,2, konfirmasi trend H4 dari candle closed, sesi UTC 00:00–07:59 (WIB 07:00–14:59). Parameter konfigurasi dioptimasi sebagai eksperimen baru; strategi XAU–EUR dan trading live tidak diubah.

| Pilihan | ID riset | Saldo akhir | Floating DD |
|---|---:|---:|---:|
| Baseline lama 692365 | 2000001 | $1.005.025,52 | 67,92% |
| Tertinggi yang lolos DD <50% | 2065842 | $53.784,54 | 49,43% |
| Pembanding DD <48% | 2065840 | $43.656,69 | 47,77% |
| Pembanding DD <45% | 2065577 | $29.152,36 | 44,32% |
| Cadangan DD 50–55%; tidak lolos target utama | 2020348 | $98.286,58 | 54,83% |

Angka tertinggi di atas berlaku untuk ruang parameter yang diuji. Ini bukan bukti bahwa tidak ada konfigurasi lain yang lebih baik. Pembanding dari keluarga berbeda pada penelitian sebelumnya, D1 structure_break, menghasilkan $56.582,38/DD 46,75%; jangan menyebutnya hasil modifikasi kandidat 692365.

## Konfigurasi pilihan

| Parameter | Baseline 692365 | Tertinggi DD <50% | Pembanding DD <45% |
|---|---:|---:|---:|
| Risk budget model | 40% | 40% | 36% |
| Margin budget model | 95% | 43% | 37% |
| Stop | 2 ATR | 2 ATR | 2 ATR |
| Target | 16 R | 16 R | 16 R |
| Maksimum holding | 32 candle H4 | 32 candle H4 | 32 candle H4 |
| Maksimum tahap add | 2 | 2 | 2 |
| Break-even | Trigger 2 R | Nonaktif | Nonaktif |

Risk budget bukan kerugian pasti per trade. Jika layering aktif, model membuka 40% dari risk budget pada entry awal; penambahan dibatasi sisa risk, margin, dan pembulatan volume. Tahap add mengambil keputusan dari penutupan M1 dan dieksekusi pada open berikutnya.

Kandidat 2065842 mencatat PF 1,5424, 63 basket, 35 basket menang (55,56%), dan 8 add yang terisi. Balance DD 46,20%; tidak ada initial margin skip atau model liquidation. Jumlah pengisian posisi adalah 71 (63 awal +8 add), bukan jumlah child order broker native.

## Sensitivitas parameter terkunci

| Skenario | Saldo 2065842 | DD 2065842 | Saldo 2065577 | DD 2065577 |
|---|---:|---:|---:|---:|
| Biaya normal | $53.784,54 | 49,43% | $29.152,36 | 44,32% |
| Biaya 1,5× | $39.752,38 | 50,59% | $20.562,31 | 45,35% |
| Biaya 2× | $30.112,29 | 52,12% | $16.754,32 | 46,62% |
| Delay ke M1 berikutnya | $25.169,07 | 49,47% | $14.454,70 | 44,21% |

Pilihan dengan saldo tertinggi hanya lolos batas pada biaya normal. Pembanding 2065577 mempunyai ruang lebih besar dan tetap berada di bawah 50% pada skenario biaya 2× yang diuji. Kandidat DD <48% melewati 50% pada biaya 2× (50,39%). Pembanding DD <45% bukan hasil pencarian menyeluruh atas semua konfigurasi dengan kendala biaya 2×; ia dipilih berdasarkan DD normal lalu diuji stres.

Efek compounding dan minimum volume penting. Kandidat 2065842 yang dimulai ulang dari $100 pada 2025 tidak membuka posisi: 19 sinyal dilewati karena minimum volume/margin. Saldo $100 dan DD 0% pada segmen tersebut tidak menunjukkan ketahanan strategi. Segmen 2019–22 dan 2023–24 masing-masing restart $100; hasil segmen tidak dijumlahkan dan bukan OOS yang belum pernah dilihat.

## Pemeriksaan dan batas validitas

- Baseline lama direproduksi sebelum pencarian: saldo $1.005.025,5238208736, floating DD 67,9209240083%, 63 basket. Sinyal dan fungsi eksekusi tetap; source diff memperluas array numerik sizing.
- Sembilan fixture engine asli lulus. Semua kandidat terpilih direplay ulang. Sebanyak 120 ledger skenario direkonsiliasi independen untuk gross PnL, komisi, financing, net PnL, dan saldo. Error kas maksimum sekitar $0,00000000559.
- Data adalah OHLC M1 resmi Bitstamp, bukan tick bid/ask broker. Leverage 10 adalah hipotesis; minimum/step 0,01 BTC, maksimum 100 BTC. Margin linear dan stop-out model belum membuktikan perilaku broker.
- Asumsi: spread 5 bp, slippage 1 bp per sisi, komisi 5 bp per sisi, financing debit 3 bp notional per hari. Stres biaya mengalikan komisi/slippage/financing; spread tidak digandakan. Delay minimum satu menit, bukan dua detik.
- Sinyal memakai candle closed dan entry open berikutnya. Urutan intrabar memakai stop-first dan gap stop pada harga open yang lebih buruk. DD dihitung pada semua M1; grafik memakai snapshot per jam.
- Source mempertahankan prioritas SL/TP sebelum fallback stop-out dan aturan penghentian akun saat capital-floor tercapai. ACK, reconnect, partial fill, depth pasar, dan spesifikasi broker native belum divalidasi.
- Seluruh periode dipakai untuk pencarian. Ini optimasi historis setelah banyak percobaan, bukan bukti profit masa depan atau jaminan DD <50%. BTC belum diuji bersama equity/margin XAU–EUR.

## Artefak dan reproduksi

Run awal: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39245458518

Run final sukses: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39246381754

Commit eksekusi: bff6add740dd7e48c0428bc53786501f4fc91dbd

Branch: research/btc-692365-dd50-2019-2026

Lokasi VPS: /home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/btc-692365-dd50-2019-oct2026/run-39246381754/

Paket RIZAN_BTC_692365_DD50_AUDIT.zip mencakup seluruh 112.420 konfigurasi, source asli dan engine penelitian, diff, protokol tahap awal dan refinement berurutan, ledger seluruh skenario kandidat terpilih, rekonsiliasi, hasil bulanan/tahunan, grafik, provenance, dan manifest. Laporan ini merupakan ringkasan yang dirapikan; laporan keluaran runner tetap tersimpan utuh dalam ZIP.

SHA-256 ZIP: dd5e0ad6b9eaccac08894e79a90ff6151b21ac86f148856b4d45cd5746721ae6

SHA-256 CSV input: c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504

Arsip Actions, paket ZIP internal, dan seluruh isi manifest telah diverifikasi ulang setelah diunduh. Verifikasi checksum paket di VPS juga lulus.
