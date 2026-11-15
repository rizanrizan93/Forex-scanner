# Deliverable5 — Final Recommendation

**Keputusan operasional sementara:A. Pertahankan Frozen V1 existing dan jangan memasang strategi Asia R1.** Riset ini belum membandingkan Frozen secara tick-native pada risk budget yang sama, sehingga rekomendasiA adalah keputusan mempertahankan sistem yang ada sambil menolak tambahan yang belum terbukti; bukan pengesahan historis profit/DD Frozen. Tidak ada dasar bukti untukB,C,D saat ini.

| Pertanyaan | Jawaban berdasarkan hasil R1 |
| --- | --- |
| 1 Yield resmi bisa diperkirakan dengan error kecil sebelum publikasi? |Secara metodologi dapat diestimasi dari quotes yang cocok, tetapi MAE kecil belum dibuktikan di R1.|
| 2 Nowcast memiliki informasi tambahan bagiXAU? |Belum diketahui; targetA berpotensi hanya mengemas ulang harga pasar yang sudah bereaksi. TargetB/C harus diuji terpisah.|
| 3 Seberapa akurat memprediksiDXY? |N/A; tidak ada run model pada histori terverifikasi.|
| 4 Yield+DXY konsisten memperbaiki prediksiXAU? |Belum diuji; korelasi harian bukan hasil ablation.|
| 5 ExpectancyAsia08–13positif setelah biaya? |Tidak pada5hipotesis awal dengan parameter training-selected dalam sample tersedia; hasil ini terbatas pada definisi/data/biaya R1.|
| 6 Jam paling menguntungkan? |Belum ada jamAsia yang lolos bukti profit robust.08WIB punya range rata-rata terbesar pada08–12, tidak otomatis expectancy tertinggi.|
| 7 Asia memperbaiki profit/DD portfolioFrozen? |Belum dapat dinilai; portfolio replay belum dilakukan.|
| 8 Paling robust untuk pasar masa depan? |Tidak ada kandidat baru yang dapat disahkan. Hasil historis yang sudah dilihat, sampel pendek/sparse dan kekurangan data menghalangi klaim robustness masa depan.|

Jika sensitivitas eksploratif menampilkan varian yang lebih baik, varian tersebut tetap research-only sampai parameter dibekukan dari training, bertahan pada biaya tinggi, memiliki sampel cukup dan lulus data/forward holdout baru. Tidak ada filealgo baru, deployment, atau perubahanLIVE dari R1 ini.

Sumber biaya:[FP Markets cTrader fees](https://www.fpmarkets.com/en-id/ctrader-fees-and-charges/). Kontrak emas contoh100oz/lot:[FP Markets metals](https://www.fpmarkets.com/metals/). Sumber tick original:[Dukascopy export](https://www.dukascopy.com/api/data/get/historical-data-export). Supply-chain archive:[dataset card](https://huggingface.co/datasets/Henrik404/dukascopy-ticks). Definisi/event/fee saat ini tidak dianggap identik untuk seluruh histori2019–2026.
