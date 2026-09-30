# V312 — Reusable Primary Reversal Cycle

## Tujuan

V311 membuktikan bahwa pola struktural dua-leg:

`reaction >=0.50 ATR -> opposite zone -> reaction kedua >=0.50 ATR`

memang ada, tetapi fresh/untouched opposite-zone coverage hanya sekitar 5% dari
first reactions.

V312 menguji hipotesis yang sesuai dengan kebijakan scanner saat ini:

> H1/H4 tidak harus fresh/first-touch. Parent zone boleh tetap dipakai selama
> belum retired/consumed, tetapi reuse tidak boleh blind.

V312 menggabungkan prinsip:

- V309 forward-reachable Primary Reversal authority;
- V200 zone-reuse lifecycle;
- V310 chronological supply/demand ledger;
- V311 causal two-leg structural cycle.

## Historical V200 proxy

Live V200 memakai lifecycle V182, termasuk mitigation depth dan M5
reconfirmation. Field tersebut tidak tersimpan lengkap untuk seluruh sejarah V183.

Karena itu V312 **tidak mengklaim production parity**.

Historical proxy V312 menggunakan:

- causal V183 touch ordinal;
- touch hanya diketahui setelah M15 bar selesai;
- M15 episode-window penetration sebagai mitigation-depth proxy;
- prior HTF nesting dari episode terakhir.

State penelitian:

- `FRESH_PARENT_ZONE`: belum ada prior touch yang causal-known;
- `FIRST_TEST_PARENT_ACTIVE`: satu prior touch, mitigation proxy <35%;
- `PARTIALLY_MITIGATED_REQUIRE_RECONFIRMATION`: mitigation >=35%;
- `DEEPLY_MITIGATED_REQUIRE_NEW_MICRO`: mitigation >=75%;
- `SECOND_TEST_CONDITIONAL`: touch count proxy = 2;
- `MULTI_TESTED_REQUIRE_NEW_MICRO`: touch count proxy >2.

V312 strict reusable policy hanya menambahkan
`FIRST_TEST_PARENT_ACTIVE` ke baseline fresh-only.

Zona yang memerlukan fresh micro confirmation tetap dicatat sebagai diagnostic
coverage, tetapi **tidak** dipromosikan menjadi historical reusable candidate
karena historical M5 confirmation belum dibuktikan.

## Primary Reversal authority

Untuk kandidat yang berada <=$5 dari reaction close, ranking memakai historical
proxy dari V309:

- freshness/reuse state;
- STRUCTURAL vs IMBALANCE;
- timeframe;
- HTF nesting yang causal-known;
- distance in ATR;
- mitigation penalty.

Ini disebut:

`V309_COMPATIBLE_FORWARD_REACHABLE_HISTORICAL_PROXY`

dan bukan replika 1:1 live V309 karena historical V183 tidak menyimpan seluruh
live research score.

## Dua policy yang dibandingkan

### Fresh-only baseline

Hanya zona dengan 0 prior causal-known touches.

### Fresh + V200 reusable

Fresh zones + first-tested parent zones dengan mitigation proxy <35%.

Kedua policy memakai dataset, reaction timestamp, gap <=$5 dan 30-minute window
yang sama.

## Outcome

Untuk selected opposite zone, V312 mencari reaction episode berikutnya setelah
handoff eligibility.

Metric:

- coverage;
- resolved second reaction;
- second HOLD/BREAK/STALL;
- second-HOLD rate all selected;
- second-HOLD rate resolved;
- Wilson lower 95%;
- full-cycle completion rate;
- fresh vs reused selection count;
- lifecycle breakdown;
- yearly breakdown;
- median delay ke second touch/outcome.

## Pre-registered research gate

Agar reuse tidak dipromosikan hanya karena menaikkan coverage, V312 membekukan
gate sebelum hasil 100K dilihat:

- >=100 selected reusable-policy candidates;
- coverage uplift >=2 percentage points vs fresh-only;
- second-HOLD rate all selected >=55%;
- resolved second-HOLD Wilson lower 95% >=50%.

Pass hanya berarti layak lanjut ke **exact-entry replay**. Tidak memberi
execution authority.

## Batasan

- V200 live mitigation depth tidak tersedia penuh secara historis;
- M15 penetration hanya causal proxy;
- fresh M5 micro reconfirmation belum diuji historis di V312;
- structural HOLD >=0.50 ATR bukan broker TP;
- selected zone bukan broker fill;
- no execution/promotion authority.

Tahap berikut bila gate lolos adalah exact-entry / SL / TP replay pada subset
reusable yang sudah terbukti secara structural.
