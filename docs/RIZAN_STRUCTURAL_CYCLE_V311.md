# V311 — Structural Reaction Cycle Validation

## Tujuan

V308 menunjukkan bahwa katalog plan lama terlalu sempit untuk menguji objective:

`entry -> reversal -> TP -> opposite entry -> reversal`

V310 kemudian membangun chronological supply/demand ledger dan menemukan bahwa
opposite zone coverage harus dibedakan antara:

- zona yang sudah aktif ketika reaction pertama diketahui;
- zona baru yang muncul dalam 30 menit;
- zona yang sebenarnya sudah pernah disentuh dan karena itu bukan clean next-entry candidate.

V311 menguji **structural analogue** dari objective tersebut sebelum menyentuh
parameter execution:

`reaction >=0.50 ATR -> clean opposite zone -> second reaction >=0.50 ATR`

## Causality correction

V183 reaction outcome memakai high/low/close sebuah M15 bar. Informasi outcome
tersebut baru causal setelah bar selesai.

Karena itu V311 juga mengeraskan V310:

- `reaction_bar_at` = timestamp open M15 outcome bar;
- `reaction_at` = `reaction_bar_at + 15m`;
- active opposite-zone lookup baru dilakukan pada `reaction_at`;
- 30-minute new-zone window juga dimulai dari timestamp tersebut.

Ini mencegah lookahead sampai 15 menit.

## Clean opposite candidate

Zona opposite hanya disebut clean next-entry candidate bila:

1. zona sudah aktif pada reaction pertama, atau muncul maksimal 30 menit setelahnya;
2. gap terhadap reaction close <= $5;
3. zona **belum pernah disentuh** sebelum handoff;
4. zona belum invalid/expired.

Zona yang sudah disentuh tetap dicatat sebagai coverage, tetapi tidak dihitung
sebagai clean opposite-entry candidate.

## Second reaction

Untuk setiap clean opposite candidate, V311 mencari episode reaction berikutnya
pada zona tersebut sesudah handoff eligibility.

Outcome:

- `SECOND_REACTION_HOLD` — zona menghasilkan >=0.50 ATR reaction sebelum break;
- `SECOND_REACTION_BREAK`;
- `SECOND_REACTION_STALL`;
- unresolved bila belum ada episode matang.

## Metric utama

V311 melaporkan:

- first reaction milestones;
- selected opposite-zone coverage;
- clean opposite candidate rate;
- resolved clean cycles;
- second HOLD/BREAK/STALL;
- second-HOLD rate pada seluruh clean candidates;
- second-HOLD rate pada resolved candidates;
- Wilson lower 95%;
- structural-cycle completion rate terhadap seluruh first reactions;
- median delay reaction -> second touch;
- median delay reaction -> second outcome;
- breakdown berdasarkan selection origin, zone class/timeframe, dan year.

## Batasan

V311 belum merupakan trade backtest.

`HOLD >=0.50 ATR` adalah structural reaction milestone, bukan actual TP.
`clean opposite candidate` adalah structural next-entry opportunity, bukan
broker fill.

Jadi V311 hanya menjawab apakah struktur pasar mendukung pola dua-leg reversal
secara causal. Bila evidence cukup, tahap berikutnya baru mengikat geometry
tersebut ke exact-entry / SL / TP replay seperti V284/V308.

## Execution

- policy effect: RESEARCH_ONLY
- execution influence: false
- execution authority: false
- promotion authority: false

Tidak ada perubahan pada V229/V280/admission/protection maupun V309 Primary
Reversal Zone.
