# V307 — Primary Reversal Zone Authority

## Tujuan

V307 menghapus ambiguitas antara **zona terdekat** dan **zona reversal utama**.

Mulai V307, scanner operasional hanya memakai satu demand utama dan satu supply utama sebagai authority struktural:

- `primary_reversal_demand`
- `primary_reversal_supply`

Zona lain tetap disimpan sebagai diagnostic/research evidence, tetapi tidak lagi boleh mengalahkan zona reversal utama hanya karena lebih dekat ke harga.

## Masalah yang diperbaiki

Sebelumnya V182 mengutamakan zona yang sedang ditempati harga atau paling dekat. Akibatnya demand yang sudah sangat ter-mitigasi dapat menjadi source aktif dan membalik path LONG terlalu cepat.

Contoh runtime sebelum V307:

- strategic bias: SHORT;
- demand 4181.37–4190.52;
- mitigation depth sekitar 94.5%;
- zone berada di dalam harga sehingga dipilih sebagai source LONG.

Secara semantik zona seperti itu lebih tepat dianggap local reaction/roadblock, bukan reversal authority.

## Seleksi primary reversal zone

Candidate harus:

1. aktif;
2. berada di sisi harga yang benar;
3. direction sesuai demand/supply yang sedang dinilai.

Jika ada kandidat yang lebih sehat, zona dengan mitigation >=75% atau freshness `DEEPLY_MITIGATED/MULTI_TESTED` tidak boleh mengalahkannya.

Ranking authority menggabungkan:

- freshness;
- structural BOS;
- HTF nesting;
- timeframe precision;
- existing research score;
- distance penalty;
- mitigation penalty.

Skor ini adalah **ranking authority**, bukan win probability.

## Path authority

Jika strategic bias adalah SHORT:

- active path tetap SHORT menuju `primary_reversal_demand`;
- masuk ke demand tidak otomatis membalik scanner LONG;
- reversal LONG hanya boleh dipromosikan melalui causal opposing-leg handoff V257 setelah M5 refinement confirmation.

Mirror rule berlaku untuk strategic bias LONG menuju `primary_reversal_supply`.

Dengan demikian:

`trend/path -> primary reversal zone -> wait confirmation -> confirmed handoff`

bukan:

`nearest zone touched -> auto flip direction`.

## Dashboard

Dashboard operasional menampilkan:

- **Demand reversal utama**
- **Supply reversal utama**

Label “Demand/Supply terdekat” dihapus dari area operasional.

Operational chart dibatasi pada primary reversal zones dan current/next structural path. Raw nearby/roadblock zones tetap diagnostic/research-only.

## Compatibility

Field legacy `nearest_demand` dan `nearest_supply` tetap tersedia untuk downstream compatibility, tetapi sejak V307 nilainya menunjuk ke primary reversal authority.

Raw geographic nearest disimpan terpisah sebagai:

- `raw_nearest_demand`
- `raw_nearest_supply`

## Execution

V307 tidak memberi execution authority baru.

V229/V280/admission/protection tetap fail-closed. Primary reversal zone menentukan structural destination/authority; entry tetap memerlukan confirmation yang berlaku.
