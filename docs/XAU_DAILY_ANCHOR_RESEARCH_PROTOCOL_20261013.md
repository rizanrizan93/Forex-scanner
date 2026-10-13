# Protokol sebelum hasil: reversal harian XAU, 13 Oktober 2026

Contract: RIZAN_XAU_DAILY_ANCHOR_REVERSAL_NET_V1.
Berlaku untuk scanner saja. Tidak mengubah atau memanggil execution/cBot/bridge.

Hipotesis baru: sweep dan reclaim level dari D1 sebelumnya, ekstrem dua D1 terakhir, sesi UTC00–06, sesi UTC06–12, atau enam H4 yang sudah selesai. Anchor harus sudah diketahui sebelum M5 trigger membuka; anchor sesi hanya berlaku pada hari UTC yang sama setelah sesi selesai. Trigger harus menyapu level, close kembali di dalam minimal 0,025 H1 ATR, dan body mengarah ke reversal.

ATR adalah rata-rata true range 20 H1 tertutup. Trend adalah slope EMA50 H1 tiga bar dibagi ATR, dengan threshold ±0,05; bukan filter M15 dari cBot. ADR20 dari hari UTC lengkap dengan >=900 bar M1. Istilah Asia/Europe hanya nama rentang UTC tetap, tidak mengklaim jam resmi pasar/DST.

10.000.000 tuple parameter:
- Side BUY/SELL.
- Lima sumber anchor di atas.
- Minimum sweep depth 0/0,025/0,05/0,1/0,2 H1 ATR.
- SL di luar ekstrem M5 sweep plus 0,05/0,1/0,2/0,35/0,5 H1 ATR.
- TP dari fill entry sebesar 25/35/50/75/100% ADR20.
- Horizon 120/240/360/480 menit.
- Minimum wick fraction 0/0,2/0,35/0,5/0,65.
- Trend ANY/ALIGNED/OPPOSED/FLAT.
- Minimum approach 0/0,25/0,5/1/1,5 H1 ATR.
- Minimum RR net normal fills 1,5/2/2,5/3/4.
- Sesi entry UTC00–06/06–12/12–18/18–24 (WIB07–13/13–19/19–01/01–07). Karena cutoff20:55UTC dan waktu tersisa minimal120menit, bagian akhir sesi terakhir tidak eligible.

Model fills sama dengan riset V6: entry next-M1 open; bid/ask synthetic spread; adverse slippage; stop first bila TP/SL tersentuh dalam bar sama; stop gap di harga lebih buruk; timeout actual deadline open; gap data >300detik/cutoffbar hilang dicensor. Tidak overnight; deadline paling lambat20:55UTC.

Biaya reference/cautious/stress:
spread0,25/0,50/1,00 XAUUSD; slip tiap sisi0,05/0,10/0,20.
Komisi0 sebagai proxy Standard, bukan data biaya historis akun. Tidak mengukur lot/margin/equity/compounding. Broker minimum distance bukan dimodelkan sebagai contract eksekusi: keluaran hanya penelitian scanner.

Satu trigger pertama eligible per konfigurasi, per hari UTC, setelah seluruh known-at-entry filter. Trigger censored tidak dapat diganti memakai pengetahuan masa depan. BUY/SELL adalah hasil terpisah, bukan portfolio gabungan. Tidak menjamin ada pantulan setiap hari.

Kriteria tetap:
- Training2016–2021 n>=180, mean/net R positif, PF>=1,15, minimal5/6tahun positif dengan>=15trade/tahun, censor<=2%.
- Validation2022–2025 n>=60, PF>=1,20, stressmean>0, descriptive lower bound mean R>0, minimal3/4tahun positif dengan>=15trade/tahun, censor<=2%.
- Ranking berdasarkan descriptive lower bound validation; bukan confidence yang mengoreksi multiple testing.
- Rolling walkforward2020–2025 memilih hanya dari tahun sebelumnya, tetap eksploratif karena desain keluarga pola melihat riwayat riset lama.
- Parameter dikunci sebelum menghitung outcome kandidat Jan–Sep2026. Data tahun2026 sudah pernah ada dalam cache; tidak mengklaim data pertama kali didownload setelah lock.
- Qualification2026 n>=30, meanNetR>0, PF>=1,20, stressmean>0, lower95% CI monthly block bootstrap meanR>0, censor<=2%.
- Tidak mempromosikan kandidat bila kosong atau ditolak, tidak mengubah threshold setelah hasil untuk membuatnya tampak lolos.
- Pelaporan harus membedakan net-positive win rate, TP-before-SL hit rate, timeout, dan censored. R adalah nominalrisk penelitian, bukan persentase equity.
- Tidak ada event/macro tanpa verified initial-publication availability.

Implementasi dan44regression tests sebelum hasil dipush pada78da8e355e88b7e5b271126699d107847ec1c52b.

