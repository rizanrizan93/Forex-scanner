# RIZAN — hasil pencarian zona reversal XAUUSD
Tanggal: 13 Oktober 2026 (WIB)

## Hasil utama
Replay keluarga daily/session sweep-reclaim sudah selesai untuk 2016–2025.
Sebanyak 10.000.000 tuple parameter dievaluasi. Tidak ada konfigurasi yang
lolos seluruh syarat. Ini tidak membuktikan semua tuple rugi, tetapi tidak
memberikan dasar untuk menyebut salah satunya zona reversal utama yang andal.

Run penelitian: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38384475679
Run audit: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38385049724
Source penelitian dikunci pada commit 78da8e355e88b7e5b271126699d107847ec1c52b.
Hasil ini dipulihkan dan diverifikasi dalam sesi ini; bukan rerun lokal sepuluh juta tuple.

## Keluarga dan metode
BUY/SELL di high/low hari sebelumnya, range dua hari sebelumnya, range Asia
00–06 UTC, range Eropa 06–12 UTC, serta range enam candle H4. M5 selesai
melakukan sweep dan reclaim; slope serta ATR H1 menjadi konteks. Ini bukan
pengujian tambahan konfirmasi M15 dari paket penelitian intraday terdahulu.

Variasi kedalaman sweep 0–0,2 ATR H1; wick minimal 0–65%; buffer SL di luar
ekstrem sweep 0,05–0,5 ATR H1. Target 25/35/50/75/100% ADR20 dari data yang
sudah diketahui. Horizon 2/4/6/8 jam, keluar paling lambat 20:55 UTC.
Empat jendela UTC 00–06, 06–12, 12–18, 18–24; setara WIB 07–13,
13–19, 19–01, 01–07. Batas waktu keluar membatasi sinyal sore UTC.

Entry memakai open M1 setelah M5 selesai. Satu trigger valid pertama per
konfigurasi/hari; stop-first bila TP dan SL tersentuh pada M1 yang sama;
stop gap mengisi harga yang lebih buruk. Sinyal kehilangan data tidak
diganti sinyal berikutnya berdasarkan hasil masa depan.

Biaya reference: spread 0,25 dan slippage 0,05 tiap fill;
cautious: 0,50 dan 0,10; stress: 1,00 dan 0,20 (USD/ounce).
RR minimum setelah biaya stress 1,5; grid RR 1,5/2/2,5/3/4.
Spread historis broker tidak tersedia. Sepuluh juta tuple bukan sepuluh juta
strategi independen; beberapa tuple dapat menghasilkan keputusan identik.
Macro/event belum masuk keluarga ini.

## Kelengkapan dan pemisahan periode
Manifest berisi seluruh sepuluh tahun termasuk 2017 (352.360 M1 tahun tersebut).
Total M1 di tahun target: 3,492,721.
Data memiliki hash per tahun; jumlah bar tidak menjamin seluruh menit sesi
tersedia. Sinyal yang melewati gap dicatat sebagai censored.
Train 2016–2021; validation 2022–2025. Periode lama sudah pernah dilihat:
hasil bersifat eksploratif dan bukan pristine holdout. Seleksi rolling
2020–2025 juga tidak memilih kandidat.
Data 2026 tersedia, tetapi daftar kandidat terkunci kosong. Ledger 2026
kosong; jangan menyebut hasil ini lulus atau gagal validasi trading 2026.

## Audit seleksi
| Syarat kumulatif | Tuple tersisa |
|---|---:|
| Train minimal 180 observasi | 313.051 |
| Validation minimal 60 observasi | 313.051 |
| Net R train positif | 4.623 |
| PF train minimal 1,15 | 317 |
| PF validation minimal 1,20 | 0 |

Syarat berikutnya adalah expectancy stress positif, batas bawah deskriptif
expectancy positif, kestabilan tahunan, dan censored maksimal 2%.

## Kandidat deskriptif tertinggi per sisi
Ranking audit memakai batas bawah deskriptif expectancy validation di antara
tuple dengan jumlah sampel cukup. Ini bukan ranking peluang reversal tertinggi,
bukan konfigurasi terpilih, dan bukan rekomendasi entry.

| Parameter/metrik | BUY | SELL |
|---|---|---|
| Level | Low range Asia 07–13 WIB | High range dua hari sebelumnya |
| Jendela trigger | 19:00–01:00 WIB | 19:00–01:00 WIB |
| Sweep minimal / ATR H1 | 0,05 | 0,10 |
| Wick minimal | 50% | 0% |
| Buffer SL / ATR H1 | 0,20 | 0,50 |
| TP / ADR20 | 100% | 75% |
| Horizon maksimal | 8 jam | 2 jam |
| RR minimum stress | 2 | 3 |
| Train n | 232 | 205 |
| Validation n | 131 | 143 |
| PF train | 0,743 | 0,438 |
| PF validation | 1,615 | 1,090 |
| Expectancy train | −0,199R | −0,397R |
| Expectancy validation | +0,409R | +0,049R |
| Expectancy validation stress | +0,211R | −0,146R |
| Censored validation | 8,39% | 6,54% |
| Status | DITOLAK | DITOLAK |

BUY gagal karena train negatif, hanya satu tahun train positif, batas bawah
expectancy validation negatif, dan censored terlalu tinggi. SELL juga gagal
pada PF validation serta biaya stress. Jendela ini belum dapat disebut jam
reversal terbaik. Tidak tersedia persentase reversal tervalidasi untuk
dijadikan probabilitas trading. Rasio target/SL di tabel adalah formula,
bukan level harga XAU hari ini atau hasil dolar akun.

## Scanner dan verifikasi
Engine penelitian daily_reversal.py, replay, dan tab dashboard sudah ada.
Hasil serta diagnostik dipublikasikan ke calibration; dashboard menampilkan
status akhir, kandidat ditolak, waktu WIB, TP, buffer SL, dan perbandingan
train/validation. Tidak ada geometri zona utama yang dipromosikan karena
tidak ada kandidat lolos. Runtime zona terkalibrasi masih membutuhkan kandidat
yang lolos dan data broker segar; pekerjaan tersebut belum terpenuhi oleh hasil ini.

44 pengujian unit terkait daily/major/reversal lulus lokal.
Kompilasi modul dashboard lulus. Pemeriksaan hash dan ruang lingkup source
cBot XAU serta EUR lulus; logic strategy/execution tidak berubah.
Pengujian tampilan Streamlit langsung belum dilakukan.
