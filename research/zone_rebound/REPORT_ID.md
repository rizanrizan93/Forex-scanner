# Riset zona pantul R1 — 17 November 2026

Manual R3 telah dikembalikan sebagai tab tersendiri, dengan zona BUY dan SELL.
R2 tetap merupakan model SELL tersendiri. Penggabungan panel sebelumnya terlalu
jauh karena juga mengalihkan Manual R3. Aturan entry R3 dan cBot LIVE tidak
diubah oleh eksperimen ini.

## Pertanyaan dan ukuran keberhasilan

Apakah zona yang digambar sebelum disentuh mampu menghasilkan pantulan
0,25 ATR H1 sebelum harga bergerak 0,25 ATR H1 berlawanan, dalam 60 menit?
BUY dan SELL diuji secara terpisah. Target 80% belum tercapai.

- Input: 2.557.244 candle BID M1 XAU, 1 Januari 2019–31 Maret 2026.
- 11 metode zona, 2 arah, 4 pilihan sesi, 15 filter: 1.320 konfigurasi.
- 95.331 publikasi zona yang berada di sisi pendekatan yang benar;
  47.643 catatan sentuhan. Ini bukan jumlah transaksi atau kejadian independen:
  beberapa metode zona dapat tersentuh pada gerakan yang sama.
- Metode: Keltner M15 1,5/2/2,5 ATR; Bollinger M15 2/2,5/3 deviasi;
  high/low hari sebelumnya; range Asia; swing H1/H4; garis tren H1.
- Swing baru tersedia sesudah dua candle di kanannya selesai. Garis tren hanya
  memakai dua swing yang sudah terkonfirmasi. Zona/koefisien garis dan konteks
  dibekukan saat publikasi 07.00, 14.00, atau 19.00 WIB.
- Filter meliputi ADX, arah H1/H4, slope EMA, pertemuan metode zona berbeda,
  serta discount/premium terhadap midpoint range hari sebelumnya.

Puncak candle sentuh tidak dihitung sebagai pantulan karena mungkin terjadi
sebelum sentuhan. Candle yang menyentuh kedua batas dihitung gagal terlebih
dahulu. Gap data tidak dihitung sebagai sukses. Zona yang sudah berada di
belakang harga saat publikasi ditolak. Pengujian menggunakan sentuhan pertama
per publikasi zona; riwayat sentuhan level yang sama pada sesi sebelumnya
belum menjadi filter freshness global.

## Pemilihan tanpa memilih ulang dari hasil periode berikutnya

Setiap arah memilih satu konfigurasi berdasarkan batas bawah Wilson 95%
tertinggi pada 2019–2022, minimal 100 sentuhan. Sesudah pemilihan, aturan yang
sama dinilai pada 2023–2024, 2025, dan Q1 2026. Data tahun-tahun tersebut sudah
pernah dipakai dalam proyek riset sebelumnya, sehingga bukan test yang sama
sekali belum pernah dilihat. Sebanyak 704 konfigurasi awal diperluas dengan
filter confluence/premium-discount menjadi 1.320; hasil tahap awal disimpan.

| Kandidat terpilih | 2019–2022 | 2023–2024 | 2025 | Q1 2026 |
| --- | --- | --- | --- | --- |
| BUY · Keltner 2 ATR · Asia · pertemuan ≥2 metode + H1/H4 searah | 78/125 (62,4%) | 24/67 (35,8%) | 17/42 (40,5%) | 6/8 (75,0%) |
| SELL · Keltner 2,5 ATR · London · ADX H1 <20 | 92/165 (55,8%) | 48/103 (46,6%) | 15/32 (46,9%) | 3/4 (75,0%) |

Angka Q1 2026 berasal dari sampel sangat kecil. Penambahan confluence menaikkan
hasil BUY pada data pemilihan, tetapi memburuk pada periode berikutnya.
Tidak ada dasar untuk menaikkan label zona aktif menjadi probabilitas 80%.
Hasil ini juga bukan evaluasi ulang seluruh aturan R3: zona dibekukan per sesi
untuk menguji sentuhan langsung, sedangkan R3 asli memakai kondisi dan reclaim.

## Batas penggunaan dan keputusan

Pantulan 0,10 ATR dan 0,50 ATR dihitung sebagai sensitivitas dengan batas
berlawanan tetap 0,25 ATR. Mengurangi target pantulan tidak menghasilkan
jaminan peluang yang sama untuk pantulan lebih besar. Ini statistik gerak BID,
bukan win rate trading setelah spread, slippage, atau biaya. Belum ada replay
native FP Markets untuk eksperimen zona ini; kalender gap sumber belum
sepenuhnya tersertifikasi.

Makro belum dimasukkan ke replay: belum tersedia arsip input makro historis
berdasarkan waktu publikasinya dalam bahan eksperimen ini. Data makro hari ini
tidak boleh dipakai untuk menjelaskan entry bertahun-tahun lalu. Tahap berikutnya
memerlukan arsip point-in-time yield/USD/news serta pembanding tanpa makro,
kemudian pengujian pada data tambahan yang belum dipakai untuk memilih aturan.

Keputusan: pertahankan zona BUY/SELL dan aturan Manual R3 yang ada. Simpan
kandidat baru sebagai riset saja. Jangan mengadopsinya ke cBot atau mengklaim
pantulan minimal 80% dari hasil yang tersedia.

## Reproduksi dan bukti

`audit.py` menghasilkan seluruh ledger, ranking dan ringkasan dari CSV M1.
`verify.py` memakai loop skalar independen untuk memeriksa 300 label sentuhan
terhadap sumber M1. `evidence/` memuat ringkasan, ranking lengkap terkompresi,
seluruh sentuhan kandidat terpilih, hash sumber dan hash ledger lengkap.
Pengujian otomatis memeriksa simetri BUY/SELL, candle ambigu, gap data,
konfirmasi swing, jumlah metode confluence, dan pemilihan yang tidak berubah
ketika hasil periode validasi dibalik.
