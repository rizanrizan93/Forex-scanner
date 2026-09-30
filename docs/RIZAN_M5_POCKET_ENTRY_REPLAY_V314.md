# V314 — Exact M5 Pocket Entry Replay

## Latar belakang

V313 membuktikan bahwa pre-registered `ALL_H1_MICRO_REQUIRED` cohort lolos
holdout gate setelah V189 reclaim + MSS + displacement:

- holdout confirmations: 84;
- post-confirm HOLD: 64/84 = 76.19%;
- Wilson lower 95%: 66.06%;
- uplift vs first-touch baseline: +21.67 pp;
- median touch -> confirmation: 55 menit.

Primary V313 cohort `STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED` tidak lolos
karena holdout confirmation hanya 21 (<30), meskipun reaction quality tinggi.

V314 tidak mengubah primary V313 conclusion. Ia memakai secondary pre-registered
cohort yang memang lolos gate untuk menguji **exact entry geometry**.

## Candidate universe

Hanya V313 `ALL_H1_MICRO_REQUIRED` candidates yang:

- sudah melalui H1 lifecycle gate;
- V189 confirmed reclaim + MSS + displacement;
- memiliki refined M5 origin pocket.

## Entry grid

Grid dibekukan sebelum holdout replay:

1. `MARKET_CONFIRM`
2. `POCKET_PROXIMAL_LIMIT`
3. `POCKET_MID_LIMIT`
4. `POCKET_DEEP_LIMIT`

Untuk LONG, proximal = pocket high dan deep = pocket low.
Untuk SHORT, proximal = pocket low dan deep = pocket high.

Limit order hanya boleh fill maksimal 120 menit setelah confirmation.

## Stop grid

- `POCKET_DISTAL_0P10_ATR`
- `H1_DISTAL_0P10_ATR`

Buffer = 0.10 H1 ATR.

## Target grid

- 0.50 H1 ATR;
- 0.75 H1 ATR;
- 1.00 H1 ATR.

Geometry dengan terminal RR <1.50 ditolak sebelum trade replay.

## Conservative execution contract

Historical proxy costs sama dengan V242/V284:

- spread: $0.37;
- slippage: $0.002;
- round-trip commission proxy: $0.002.

Rules:

- STOP_FIRST untuk intrabar ambiguity;
- target tidak diberi credit pada fill candle;
- worse opening gap digunakan untuk stop;
- max hold 480 menit;
- limit queue position tidak dianggap pasti.

## Precision metric

Selain TP rate dan profit factor, V314 mengukur:

`precision_5_and_tp = TP AND max adverse excursion <= $5`

Ini langsung menguji objective entry yang reversal-nya dekat dengan level entry.

## Development / holdout

Confirmed V313 opportunities dibagi chronological:

- development 60%;
- purge 24 jam;
- holdout 40%.

Semua 24 kombinasi geometry hanya dinilai/ranking pada development.

Development combo dipilih dengan:

1. minimum 30 fills;
2. profit factor tertinggi;
3. average net R;
4. precision <=$5 + TP;
5. fill rate.

**Holdout tidak dipakai untuk memilih geometry.**

## Holdout gate

Gate dibekukan sebelum hasil:

- >=30 fills;
- fill rate >=25%;
- TP rate >=55%;
- TP Wilson lower 95% >=45%;
- profit factor >=1.30;
- average net R >=0.15;
- precision_5_and_tp >=50%.

Pass hanya berarti layak maju ke forward DEMO shadow/prospective validation.
Tidak memberi execution authority.

## Batasan

- recent-era cTrader sample yang sama dengan V313, bukan independent external OOS;
- fixed historical spread proxy, bukan historical tick spread;
- M5 OHLC tidak dapat menentukan urutan intrabar sehingga STOP_FIRST digunakan;
- queue position/latency broker tidak dimodelkan;
- no execution/promotion authority.
