# V309 — Reachable Primary Reversal Zone

## Masalah

V307 berhasil memisahkan `PRIMARY REVERSAL ZONE` dari zona geografis terdekat,
tetapi ranking authority masih terlalu memberi bobot pada HTF nesting. Distance
penalty juga dibatasi maksimum 18 poin.

Akibatnya pada runtime 30 Sep 2026, saat XAU sekitar 4169:

- fresh structural supply 4257.52–4266.31 berada sekitar 5.0 ATR dari harga;
- fresh structural supply 4408.20–4431.29 berada sekitar 13.6 ATR dari harga;
- zona 4408 menang tipis karena nesting 3 vs 2 walaupun jauh lebih remote.

Itu membuat V240 menampilkan supply reversal utama yang tidak relevan untuk
jalur harga berikutnya.

## V309

Primary reversal authority sekarang harus memenuhi dua lapis seleksi:

1. **health gate** — zona deep/multi-tested tidak boleh mengalahkan zona sehat;
2. **forward relevance gate** — dari healthy pool, hanya zona dalam jarak
   `nearest healthy distance + 3 ATR` yang boleh bersaing untuk authority.

Di dalam forward pool, authority score tetap mempertimbangkan:

- freshness;
- structural BOS;
- HTF nesting;
- timeframe;
- research score;
- mitigation;
- distance.

Distance penalty tidak lagi di-cap, sehingga zona yang sangat jauh tidak bisa
menang hanya karena nesting tambahan.

## Implikasi runtime

Untuk snapshot yang memicu perbaikan:

- demand reversal utama tetap sekitar 4142.42–4149.01;
- supply 4408.20–4431.29 tidak lagi eligible sebagai primary supply karena
  berada jauh di luar forward relevance band;
- supply 4257.52–4266.31 menjadi kandidat reachable yang semestinya menang,
  selama struktur/lifecycle runtime berikutnya masih sama.

Tidak ada level yang di-hard-code. Nilai tersebut hanya contoh runtime yang
membuktikan bug ranking.

## Execution

V309 hanya memperbaiki structural/display authority. Tidak memberi execution
authority baru dan tidak mengubah V229/V280/admission/protection.
