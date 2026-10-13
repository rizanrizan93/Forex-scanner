# Protokol varian stop struktural M5 — sebelum outcome 2026

Contract RIZAN_XAU_STRUCTURAL_M5_REVERSAL_NET_V1. Scanner-only, tanpa order/cBot/bridge.
Dua keluarga sebelumnya belum lolos training+validation; tidak mengubah threshold seleksi untuk meloloskannya.

Sumber: re-entry channel M5 24/32/48/64 bar dan sweep24 dengan konfirmasi1–3bar; fitur yang sama dengan riset V6. Untuk channel, anchor stop adalah low/high candle trigger yang sudah selesai. Untuk sweep, anchor stop ekstrem seed yang sudah diketahui sebelum konfirmasi. Konteks H1/M15 strict EMA200 dan slope EMA50, dengan opsi ANY/ALIGNED/OPPOSED/FLAT.

SL umum ditentukan di saat entry dari fill cautious:
distance=max(0,5XAUUSD, ATR14 M5 × [1/1,65/2,15/2,65/3,25], jarak fill ke anchor).
SL berada minimal pada ekstrem yang menginvalidasi pola. TP distance=[1,5/2/3/4/6,6]×distance. Harga TP tiap skenario dihitung dari entry skenario tersebut, tetapi distance dan SL umum sama agar observation set konsisten. Target masih wajib >=25% ADR20. Minimum RR net normal fills [1,5/2/2,5/3/4] mempertimbangkan biaya masuk/keluar. Gap bisa loss>1R.

Dimensi lainnya sama V6: side2×source5×halfwidth5×stop5×target5×horizon4×wick5×trend4×approach5×minRR5×session4=10.000.000tuple. Tuples bukan strategi independen. Horizon120/240/360/480menit, cutoff20:55UTC, firsteligible perUTCday/sesi/perarah, gap data>300sec/deadline missing dicensor dan tidak boleh memilih trade pengganti memakai masa depan. BUY/SELL tidak digabung sebagai portfolio.

Biaya spread0,25/0,50/1,00; slippage0,05/0,10/0,20 tiap sisi. Komisi0 proxy Standard; bukan actualbidask/biaya broker historis. R bukan equityreturn; lot/margin/layering tidak dimodelkan.

Syarat tidak berubah:
- Train2016–2021 n>=180; netR>0,PF>=1,15; >=5tahunpositif dengan>=15trade/tahun; censor<=2%.
- Validation2022–2025 n>=60; PF>=1,20; stressR>0; descriptive meanLCB>0; >=3tahunpositif dengan>=15trade/tahun; censor<=2%.
- Pilih berdasarkan meanLCB validation; bukan multiple-test correctedconfidence.
- Rolling walkforward2020–2025 hanya boleh memilih dengandata tahunsebelumnya, tetapexploratory.
- Lock sebelum outcome Jan–Sep2026. Data2026 sudah ada dicache; tidak mengklaim pertama didownload sesudahlock.
- Qualification2026 n>=30; netMeanR>0; PF>=1,20; stressMeanR>0; lowermonthlyblockbootstrap95%CI meanR>0; censor<=2%.
- Tanpa kandidat lolos, tidak menampilkan entry/TP/SL sebagai rekomendasiutama.
- Tidak menjamin reversal setiap hari; laporkan frequencydanconditional target-hit/net-win terpisah.

56regression tests lokal PASS sebelum replay ini dimulai, termasuk causality, fill/cost, RR, stop/target ambiguity, deadlineopen, firsteligible/day dancensoring.

