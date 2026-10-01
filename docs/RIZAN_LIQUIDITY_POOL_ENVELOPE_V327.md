# V327 — Liquidity Pool & Sweep Envelope

## Masalah yang diperbaiki

Supply/demand zone yang sempit tidak selalu menjadi titik reversal aktual.

Kasus yang memicu V327:

- supply sempit sekitar 4194–4200;
- harga tetap menyapu liquidity sampai sekitar 4215;
- reversal baru terjadi setelah sweep tersebut.

V317 sudah memperluas narrow decision zone memakai parent-zone dan liquidity
metadata V182. Tetapi bila atlas tidak memiliki explicit nearby-liquidity row,
sweep band dapat tetap sama persis dengan decision zone.

V327 menambahkan causal price-derived liquidity map dari chart M15 yang sudah
tersedia di V182.

## Sumber liquidity

V327 menggunakan hanya data yang sudah tersedia saat runtime:

- M15 swing highs/lows;
- clustered/equal highs/lows;
- recent 12h/24h M15 extreme;
- round-number $5/$10;
- V317 parent-zone extension;
- V317 explicit zone-liquidity metadata.

Tidak ada harga contoh yang di-hard-code.

## Pool detection

Pivot M15 memakai 2 bar kiri + 2 bar kanan.

Swing yang berdekatan dikelompokkan dengan tolerance dinamis:

`max($0.50, min($2.50, 0.07 * ATR))`

Cluster dua atau lebih swing menjadi:

- `M15_EQUAL_HIGHS`, atau
- `M15_EQUAL_LOWS`.

Pool menyimpan:

- representative price;
- low/high envelope;
- source list;
- touch count;
- confluence score;
- latest timestamp.

## Sweep danger band

Untuk supply/SHORT:

`decision high -> liquidity pools above supply`

Untuk demand/LONG:

`liquidity pools below demand -> decision low`

Band maksimal dibatasi 1.25 ATR dari boundary decision zone supaya level jauh
yang tidak relevan tidak memperbesar risk envelope.

Risk grade:

- LOW
- MEDIUM
- HIGH

Repeated/equal highs-lows dapat menaikkan warning walaupun tidak ada explicit
parent zone.

## Dashboard

Pusat Keputusan XAU sekarang memprioritaskan:

`liquidity_sweep_map_v327`

dengan fallback ke V317.

Dashboard menampilkan:

- decision zone;
- sweep danger band;
- primary liquidity pool;
- pool sources/confluence;
- reversal validation rule.

Jika V296 meta heartbeat sementara stale/hilang tetapi V182 masih tersedia,
dashboard membangun structural/liquidity fallback lokal dan menampilkan:

`WAIT • STRUCTURAL MAP ONLY`

Fallback tidak membuat confidence, entry, SL/TP, atau broker authority palsu.

## Execution

V327 hanya context:

- execution influence: false
- execution authority: false
- promotion authority: false

Scanner tidak boleh fade zone edge hanya karena harga sudah menyentuh
supply/demand. Reversal tetap membutuhkan sweep exhaustion dan M5/M15
reclaim/MSS/displacement sesuai execution gate yang sudah ada.
