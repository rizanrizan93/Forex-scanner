# Riset R2: harga terlalu jauh, gagal melanjutkan, lalu memantul

Putaran ini menguji gagasan overextension secara terpisah untuk area yang
tersedia **sebelum sentuhan** dan setup **sesudah konfirmasi** M1/M5.
Tidak ada perubahan pada Manual R3, indikator, bridge, atau cBot LIVE.

## Susunan ide yang diuji

1. **Jarak dari rata-rata:** jarak harga terhadap EMA20 H1 dibagi ATR14 H1,
   dengan ambang 0; 0,5; 1; 1,5; dan 2 ATR. Untuk area, fitur diketahui
   sebelum candle sentuh; untuk konfirmasi, ekstrem candle yang sudah selesai
   diketahui sebelum entry berikutnya.
2. **Gagal melanjutkan:** sweep high/low 1 jam atau 4 jam lalu close kembali,
   kembali masuk Bollinger/Keltner, wick penolakan setelah dorongan 30 menit,
   atau divergensi RSI pada swing yang baru tersedia setelah konfirmasi.
3. **Kondisi H1:** semua kondisi, ADX <25/<35, slope EMA relatif datar, atau
   kombinasi keduanya. RSI ekstrem dan sesi WIB dinilai sebagai filter.
4. **Timing:** bandingkan M1 dengan M5; setelah konfirmasi, entry acuan adalah
   open M1 berikutnya. Uji keterlambatan satu menit dan proxy satu spread.

Enam keluarga konfirmasi: BB re-entry, KC re-entry, sweep 1 jam, sweep 4 jam,
impulse-wick, dan pivot divergence. Sebelas keluarga zona awal memakai hasil
publikasi zona R1. Range sesi tetap: Asia 07.00–14.00, London 14.00–19.00,
New York 19.00–23.55 WIB; bukan penyesuaian jam bursa berdasarkan DST.

## Data, jumlah konfigurasi, dan pemilihan

- 2.557.244 candle BID M1, 1 Januari 2019–31 Maret 2026.
- 256.933 catatan kandidat, yang bisa saling tumpang tindih antar-metode.
- Grid 13.800 susunan aturan; 2.857 memenuhi minimal sampel pengembangan.
- Tiga skenario pemilihan: 8.571 pasangan aturan–skenario yang memenuhi sampel.
  Skenario keempat hanya untuk sensitivitas.
- Minimal 150 kejadian pada 2019–2022 dan 100 pada 2023–2024. Ranking memakai
  nilai terendah dari batas bawah Wilson 95% kedua periode tersebut.
- **2025 tidak masuk ranking.** Q1 2026 juga tidak memilih aturan. Namun seluruh
  tahun ini sudah pernah muncul dalam proyek riset lain; jangan menganggapnya
  test yang sama sekali belum pernah dilihat.
- Pemilihan kejadian bersifat kausal: maksimum dua per hari dan jeda 60 menit,
  tanpa melihat hasil pantulan. Kelayakan window data berikutnya tidak dipakai
  untuk memilih entry; gap data tetap dihitung bukan sukses.

| Skenario | Pantulan sesuai arah | Gerak melawan yang membatalkan | Waktu |
| --- | --- | --- | --- |
| STRICT | 0,25 ATR H1 | 0,25 ATR H1 | 60 menit |
| MODERATE · sensitivitas | 0,25 ATR H1 | 0,50 ATR H1 | 60 menit |
| SMALL | 0,10 ATR H1 | 0,50 ATR H1 | 60 menit |
| WIDE | 0,25 ATR H1 | 1,00 ATR H1 | 60 menit |

Untuk area intra-candle, ekstrem menguntungkan candle sentuh tidak dihitung
karena dapat terjadi sebelum sentuhan. Untuk entry open sesudah konfirmasi,
bar entry boleh dihitung karena entry mendahului pergerakan bar. Jika kedua
batas tersentuh dalam satu bar, batas melawan dihitung lebih dahulu.

## Kandidat di atas 80%: hanya reaksi kecil sesudah konfirmasi

| Setup tetap hasil pemilihan 2019–2024 | 2025 | Q1 2026 |
| --- | --- | --- |
| BUY · sweep low 1 jam M1 + H1 relatif datar | 275/333 = **82,58%** | 63/74 = 85,14% |
| SELL · sweep high 4 jam M1 + extension ≥1 ATR H1 + ADX H1 <35 | 218/267 = **81,65%** | 52/63 = 82,54% |

Keduanya memakai skenario SMALL: pantulan 0,10 ATR sebelum gerak melawan
0,50 ATR. Batas bawah Wilson 95% 2025 masing-masing **78,14%** dan **76,57%**;
belum mendukung klaim peluang minimal 80% dengan keyakinan tersebut.

Susunan BUY yang tepat: low M1 menembus low 60 candle M1 sebelumnya,
close kembali di atas low sebelumnya, close > open, lower wick ≥35% range,
dan |EMA20 H1 − EMA20 H1 tiga candle sebelumnya| / ATR H1 <0,25.
Kandidat BUY terbaik untuk ukuran kecil tidak mensyaratkan extension tambahan.

Susunan SELL yang tepat: high M1 menembus high 240 candle M1 sebelumnya,
close kembali di bawah high sebelumnya, close < open, upper wick ≥35% range,
(high M1 − EMA20 H1)/ATR H1 ≥1, dan ADX14 H1 <35.
Kedua susunan memakai entry acuan pada open M1 berikutnya, bukan limit order
pada ekstrem yang baru diketahui setelah candle selesai.

## Apakah 80% itu keunggulan?

| Pemeriksaan 2025 · skenario SMALL | BUY | SELL |
| --- | --- | --- |
| Reaksi harga bruto | 82,58% | 81,65% |
| Setelah entry terlambat satu menit | 79,88% | 79,78% |
| Setelah proxy satu spread | 72,67% | 70,04% |
| Ekspektasi arah acak 50/50 pada waktu dan harga acuan yang sama | 82,43% | 82,40% |

Pembanding acak dihitung secara seimbang dengan mencoba kedua arah pada setiap
entry yang sama, bukan memilih satu seed yang kebetulan buruk. Setup BUY hanya
berbeda sekitar +0,15 poin persentase; SELL sekitar −0,75 poin terhadap pembanding
itu. Angka >80% belum menunjukkan keunggulan arah yang berarti.

Median patokan SMALL pada 2025 sekitar **US$0,96/ons vs US$4,82/ons** untuk BUY,
dan **US$0,88/ons vs US$4,38/ons** untuk SELL. Artinya toleransi gerakan melawan
lima kali besar pantulan yang dinilai sukses. Dalam ilustrasi TP/SL tetap 1:5,
breakeven tanpa biaya memerlukan 83,33%; angka ini bukan hasil profit backtest.

Proxy biaya memakai spread menit entry, bukan replay bid/ask native FP Markets.
Timeout, gap dan perubahan spread intrabar belum menjadi strategi exit trading
lengkap. Semua persentase di sini adalah statistik gerak harga, bukan probabilitas
terkalibrasi untuk sinyal sekarang atau win rate net trading.

## Hasil area yang sudah diketahui sebelum disentuh

| Kandidat area terpilih · SMALL | 2025 | Q1 2026 | Catatan |
| --- | --- | --- | --- |
| BUY · Keltner M15 2 ATR · ADX H1 <25 · sesi 14.00–19.00 WIB | 45/50 = 90,00% | 8/10 = 80,00% | Sampel test kecil; batas bawah 95% 2025 78,64% |
| SELL · Keltner M15 1,5 ATR · extension ≥0,5 ATR H1 · Asia | 74/94 = 78,72% | 14/16 = 87,50% | Belum 80% pada 2025 dan n<100 |

Zona Keltner pada eksperimen area dibekukan saat publikasi sesi, dengan lebar
setengah zona 0,05 ATR H1. Ini tidak sama dengan keseluruhan mesin Manual R3.
Pada ukuran STRICT, kandidat area BUY hanya 13/34 = 38,24% dan SELL 30/52 =
57,69% pada 2025. Kandidat STRICT dipilih tersendiri; bukan penggantian ukuran
hasil SMALL pada setup yang sama.

## Keputusan dan ide lanjutan

**Belum ada area BUY dan SELL sebelum sentuhan yang terbukti minimal 80% dengan
ukuran pantulan yang lebih besar dan toleransi gerak melawan yang seimbang.**
Kandidat konfirmasi berangka >80% juga belum layak dipromosikan: target kecil,
kontrol acak hampir sama, dan biaya/delay mengurangi hasil.

Struktur yang tetap berguna untuk penelitian adalah extension → sweep/gagal
break → reclaim cepat → evaluasi pantulan. Prioritas berikutnya adalah membedakan
impulse yang masih kuat dari impulse yang kehabisan dorongan, menguji kegagalan
break berulang dan kestabilan spread, kemudian memasukkan arsip macro/news
point-in-time dengan pembanding tanpa makro. Ketiga tambahan terakhir belum
tervalidasi dalam putaran ini. Tidak ada data makro hari ini yang dimasukkan
secara retrospektif ke entry tahun-tahun sebelumnya.

Manual R3 dipertahankan. Tidak ada kandidat baru yang diterapkan ke sinyal LIVE.

## Reproduksi

- `exhaustion_r2.py`: generator kausal, grid, frozen selection, label dan stress.
- `exhaustion_verify.py`: 300 sampel / 900 pemeriksaan skalar independen,
  mencakup hasil bruto, delay dan spread.
- `exhaustion_control.py`: pembanding kedua arah pada entry yang sama.
- `exhaustion_evidence/`: ringkasan, audit, ranking, seluruh event terpilih dan
  manifest hash. Ledger mentah berisi overlap antar-kandidat, bukan portofolio.
- Pengujian memeriksa candle ambigu, simetri BUY/SELL, gap, cooldown,
  ketidakberubahan fitur terhadap data masa depan, dan pemilihan yang tidak
  bergantung pada hasil 2025.
