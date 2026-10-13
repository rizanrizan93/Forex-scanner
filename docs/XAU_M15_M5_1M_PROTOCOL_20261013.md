# RIZAN XAU M15→M5 reversal — 1.000.000 kombinasi
Protokol sebelum replay, 13 Oktober 2026 WIB. Scanner display-only; tanpa order/cBot.

Hipotesis baru: M15 lengkap menyapu dan reclaim anchor yang sudah ada sebelum
M15 membuka, dengan body searah. M5 setelah seed selesai harus close melewati
high (BUY)/low (SELL) M15 +0,025 ATR H1, dengan body searah, dalam 30 menit.
Seed baru mengganti seed sebelumnya. Ekstrem M15 menjadi dasar SL. Konteks H1
memakai slope tertutup saat seed membuka. Wick memakai candle M15 seed.

Grid: side2 × source5 × sweep5 × stop5 × target5 × horizon4 × wick5 ×
trend2 × approach1 × RR5 × session4 = tepat 1.000.000 tuple. Bukan satu juta
strategi independen. Sources D1/2D sebelumnya, Asia00–06 UTC, Europe06–12 UTC,
range6H4. Depth0/0,025/0,05/0,1/0,2 ATR H1; stop buffer0,05/0,1/0,2/0,35/0,5
ATR H1; target25/35/50/75/100% ADR20; horizon120/240/360/480menit;
wick0/20/35/50/65%; trend ANY/ALIGNED; approach tidak difilter;
net RR1,5/2/2,5/3/4. Sessions WIB07–13/13–19/19–01/01–07.

Replay2016–2025, train2016–2021 dan validation2022–2025. Histori sudah pernah
dilihat; studi eksploratif. Kandidat dikunci sebelum outcomes Jan–Sep2026;
prices2026 sudah cached. Tidak menyebut 2026 pristine holdout. Seleksi rolling
menggunakan tahun sebelum test. Ranking utama adalah batas bawah Wilson
deskriptif target-before-stop di antara kandidat yang memenuhi semua gates
profit/biaya/stabilitas sebelumnya. Ranking banyak konfigurasi tidak memberi
confidence yang terkoreksi multiple testing. Net-positive WR berbeda dari TP-hit.

Gates dipertahankan:train n180/PF1,15/netR positif/5tahun positif;
validation n60/PF1,20/stressmean positif/mean lower bound positif/3tahun positif;
censored≤2%. Test2026 n30/PF1,20/mean dan stress positif/month-block CI bawah>0.

Biaya sintetis spread/slip per fill0,25/0,05;0,50/0,10;1/0,20. M1 bid;
next-M1 open; stop-first ambiguity, adverse gap fill, tepat deadline market exit.
TP≥25%ADR20, RRstress≥1,5; stop struktur, tidak compounding/account return.
First eligible per hari setelah filter; censored first tidak diganti lewat future outcome.
Tidak ada macro/event karena histori publication-time belum terverifikasi.
No guaranteed daily reversal. Konfigurasi gagal tetap RESEARCH_ONLY.
