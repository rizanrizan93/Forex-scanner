# V310 — Chronological Supply/Demand Transition Ledger

## Tujuan

V310 melanjutkan pekerjaan Work/agentic setelah V308 menunjukkan bahwa evaluasi
`TP -> opposite setup` masih dibatasi oleh katalog plan lama.

V310 tidak membuat setup trading baru. Ia membangun ledger kronologis seluruh
zona supply/demand V183 agar kita dapat menguji transition market structure
secara causal:

`publication -> active -> first touch -> reaction hold/break -> invalidation/expiry`

Kemudian, pada setiap milestone reaction >= 0.50 ATR, V310 mengukur apakah zona
berlawanan:

1. sudah aktif ketika reaction tercapai; atau
2. baru tersedia dalam 30 menit berikutnya.

## Event ledger

Setiap event menyimpan:

- timestamp;
- zone id;
- timeframe;
- zone class / pattern;
- direction;
- low / high;
- event type;
- reaction metadata jika relevan.

Event types:

- `PUBLISHED`
- `FIRST_TOUCH`
- `REACTION_HOLD`
- `REACTION_BREAK`
- `REACTION_STALL`
- `INVALIDATED`
- `EXPIRED`

Tidak ada event yang diberi timestamp sebelum informasi tersebut secara causal
tersedia.

## Opposite-zone coverage

Pada setiap V183 `REACTION_HOLD`, V310 mengambil close M15 outcome sebagai
milestone price dan mencari zona opposite yang masih aktif.

Metric awal:

- active opposite zones;
- active opposite within $5;
- new opposite zone within 30 minutes and $5;
- selection origin: `ACTIVE_AT_REACTION` atau `NEW_WITHIN_WINDOW`;
- selected zone geometry;
- selected gap.

Ini menjawab coverage question dari V308 tanpa menganggap reaction milestone
sebagai actual TP.

## Penting

V310 **bukan** win-rate, profit-factor, atau execution backtest.

V183 HOLD >=0.50 ATR hanya dipakai sebagai structural reaction milestone.
Actual TP/SL cycle masih harus diuji terpisah setelah chronological coverage
cukup.

Historical ledger memakai M15 OHLC dan tidak membuktikan actual broker fills,
latency atau queue position.

## Execution

- policy effect: RESEARCH_ONLY
- execution influence: false
- execution authority: false
- promotion authority: false

V229/V280/admission/protection dan V309 Primary Reversal Zone tetap tidak berubah.
