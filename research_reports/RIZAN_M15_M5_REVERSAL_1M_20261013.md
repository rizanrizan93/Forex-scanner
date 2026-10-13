# RIZAN — hasil 1.000.000 konfigurasi zona reversal XAUUSD
13 Oktober 2026 WIB

**Selesai. Belum ada konfigurasi lolos seluruh syarat.**
Run penelitian sukses: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38394413950
Source/protokol sebelum replay: commit 7a6d439719001dad0e221e4ca11fee6cafb58969.

## Perubahan hipotesis
Berbeda dari batch sebelumnya: candle M15 lengkap menyapu lalu reclaim anchor
yang sudah diketahui sebelum M15 membuka. M5 setelah M15 selesai harus close
melewati high M15 (BUY) atau low M15 (SELL) dengan displacement minimal
0,025 ATR H1 dan body searah, dalam 30 menit. Seed baru mengganti seed sebelumnya.
SL berada di luar ekstrem seed M15 ditambah buffer ATR H1. H1 memberi konteks
slope yang sudah diketahui saat M15 seed membuka. Entry memakai open M1 setelah
M5 selesai. Pola ini adalah definisi penelitian sweep/reclaim; bukan bukti
transaksi institusi atau top/bottom absolut.

## Ruang konfigurasi dan data
Tepat 1.000.000 tuple: 2 arah ×5 anchor ×5 kedalaman sweep ×5 buffer SL ×5
target ×4 horizon ×5 wick ×2 konteks H1 ×1 approach ×5 RR ×4 sesi.
Sebagian tuple menghasilkan keputusan sama; bukan satu juta strategi independen.

Anchor:high/low D1 sebelumnya, dua hari sebelumnya, range Asia00–06UTC,
range Eropa06–12UTC, range enam candle H4. Target25/35/50/75/100% ADR20;
horizon2/4/6/8jam; wick M15 minimal0/20/35/50/65%; H1 ANY/ALIGNED.
Sweep0/0,025/0,05/0,1/0,2 ATR H1; bufferSL0,05/0,1/0,2/0,35/0,5 ATR H1;
netRR floor1,5/2/2,5/3/4. Empat sesi WIB07–13/13–19/19–01/01–07.
Holding dibatasi20:55UTC. Asia/Eropa adalah rentang UTC tetap, bukan jam DST resmi.

HistData bid M1, 3,492,721 bar dalam tahun target2016–2025,
ditambah warm-up/buffer. Hash per tahun ada dalam JSON hasil. Jumlah bar tidak
menjamin semua menit sesi lengkap. Train2016–2021; validation2022–2025.
Histori ini pernah dilihat, sehingga studi eksploratif dan bukan holdout baru.

## Ranking dan kelulusan
Ranking memilih batas bawah Wilson deskriptif peluang TP-before-SL di antara
tuple yang memenuhi seluruh gates. Confidence belum dikoreksi banyak percobaan.
Diagnostik yang ditampilkan hanya kandidat dengan ntrain≥180/nvalidation≥60,
dipilih sesudah melihat validation; bukan kandidat tervalidasi.

Gates dipertahankan: train netR positif, PF≥1,15, n≥180, setidaknya5/6tahun
positif dengan n≥15/tahun. Validation PF≥1,20, n≥60, expectancy stress positif,
batas bawah deskriptif expectancy positif,3/4tahun positif, censored≤2%
di masing-masing periode. Seleksi rolling2020–2025 juga tidak memilih kandidat.

Daftar kandidat dikunci kosong. Pipeline ledger/verify2026 selesai, tetapi
tidak ada trade kandidat2026 yang dievaluasi. Jangan menyebut ini gagal/lolos
validasi trading2026. Data2026 sudah cached; bukan pristine holdout.

## Kandidat diagnostik tertinggi tiap sisi
Keduanya memakai sweep range Asia, waktu trigger13:00–19:00WIB, target35%ADR20,
horizon maksimal8jam, H1 ANY, tanpa minimum wick, netRR minimal1,5.
BUY sweep≥0,10ATR H1/bufferSL0,05ATR H1; SELL sweep>0/bufferSL0,50ATR H1.

| Metrik | BUY train | BUY validation | SELL train | SELL validation |
|---|---:|---:|---:|---:|
| Observasi terukur |189|157|233|177|
| TP sebelum SL |15,87%|24,84%|22,75%|23,16%|
| Trade net positif |21,16%|29,94%|29,18%|31,07%|
| Profit factor |0,543|0,936|0,743|0,740|
| Expectancy net R |−0,370|−0,045|−0,182|−0,183|
| Expectancy stress R |−0,574|−0,163|−0,404|−0,377|
| Rata-rata jarak SL |2,91|4,92|3,47|6,07|
| Rata-rata jarak TP |7,34|11,96|7,11|12,09|
| Sinyal censored |1|11|1|13|

Jarak dalam USD/ounce (poin harga XAU), **bukan dolar laba/rugi akun**.
Angka adalah rata-rata historis dari observasi terukur, bukan harga entry
atau SL/TP emas hari ini. Win rate net positif termasuk timeout profit;
target-hit rate mengukur TP penuh sebelum SL dalam horizon dan tidak sama
dengan probabilitas semua ukuran pantulan. Biaya masuk dalam semua metrik.

Censoring BUY validation11/(157+11)=6,55%; SELL13/(177+13)=6,84%, melewati2%.
Tahun train positif yang memenuhi n≥15:BUY0 dan SELL2; validation:BUY2/SELL0.
Keduanya gagal profit dan kestabilan. Jam13–19WIB belum dapat disebut waktu
reversal terbaik. Batas bawah Wilson deskriptif TP-hit BUY18,74%/SELL17,56%;
angka ini tidak memberikan jaminan atau confidence trading setelah pencarian
satu juta tuple.

Frekuensi validation sekitar3,27 observasi BUY/bulan dan3,69 SELL/bulan
(157/48 dan177/48), belum termasuk censored; bukan setup harian.
Statistik BUY/SELL terpisah dan tidak boleh dijumlah sebagai return portfolio.

## Eksekusi penelitian dan biaya
Reference spread/slippage tiap sisi0,25/0,05; cautious0,50/0,10;
stress1,00/0,20. Synthetic bid/ask/spread, bukan histori tick FP Markets.
Tidak ada lot, leverage, compounding atau layering cBot.

TP minimal25%ADR20 dan netRRstress≥1,5 pada entry. Stop-first bila TP/SL
bersamaan pada M1; adverse gap mengisi harga lebih buruk; exit deadline
memerlukan open tepat waktunya. Gap>300detik/deadline hilang dicensor.
First eligible per hari setelah filter; censored first tidak diganti dengan
trade kemudian menggunakan hasil masa depan. Macro/event belum dipakai karena
historical initial-publication availability belum diverifikasi.

## Scanner dan validasi
Modul m15_m5_reversal.py dan replay baru berada di repository. Panel penelitian
baru tersedia pada source tab Zona reversal, dengan status, contoh deskriptif,
peluang TP/SL dan waktu WIB. JSON final disimpan pada calibration.
Tidak ada geometri zona reversal utama baru yang dipromosikan karena nol
kandidat lolos. Tidak ada pengiriman order atau perubahan konfigurasi cBot.

20 tes penelitian lulus lokal dan pada job unit. Seluruh10shard tahunan,
lock,11ledger, danverify lulus. Smoke end-to-end memakai data sintetis
memverifikasi bentuk1.000.000tuple/14field tanpa NaN; datanya tidak dihitung
sebagai hasil historis. SELL seed/confirmation dan struktur high juga dicek.
Scope/hash cBot XAU/EUR lulus. Syntax main/panel lulus.
CI umum repository sebelumnya gagal import OrderSide; kelulusan penelitian
tidak berarti semua CI repository hijau. UI Streamlit langsung belum diperiksa.

Ada perbaikan metadata saat publikasi: deskripsi SL salinan M5 dikoreksi
menjadi ekstrem seed M15, tanpa mengubah angka/outcome. Raw output pipeline
disertakan untuk audit. Tidak ada penggantian hasil buruk atau penurunan gates.
