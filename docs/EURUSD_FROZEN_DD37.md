# EURUSD frozen compounding DEMO setup

User-authorized activation: 9 October 2026. Strategy identity:
`EURUSD_SWEEP_COMPOUND_DD37_FROZEN_V1`. Only EURUSD uses this setup.
XAUUSD keeps its current V351/V375 execution lane. All other pair execution
remains paused; no LIVE authority is granted.

Research candidate: 2016–2025, initial $100, ending $11,820.23,
floating equity DD 37.08%, dollar profit factor 2.211.
Reset 2021–2025: $1,625.44, DD39.27%, PF1.890.
These are selected historical results, not a drawdown ceiling or forecast.

Frozen signal: completed M15 liquidity sweep of the previous 8 candles,
signed body ratio >0.2 for BUY / <-0.2 for SELL; completed H1 EMA50 and
three-hour EMA slope must yield neutral bias. Signal closes 07:00–11:59 UTC.
ATR is the simple mean of 14 true ranges, not Wilder ATR. Stop distance
3×ATR, bounded 5–60 pips; target 4R; maximum hold 240 minutes, no holding
past 20:00 UTC. One actual EURUSD basket at a time; no averaging down.

Frozen sizing: risk 27.25% of current equity for the whole basket, initial
margin 60%; .01-lot /1000EUR children; cap floor(195×(equity/100)^0.0625).
Virtual outcome EMA fast span2, threshold -0.5R, weak multiplier0.1;
slow span8, threshold -0.05R, weak multiplier0.625. Take the smaller
multiplier, applied to both risk and margin. No DD throttle. Virtual outcomes
use fixed synthetic base spread1.2pip/slip0.1pip and STOP_FIRST, even when
the real order is skipped. Only completed outcomes update the EMAs.

FrozenPolicy is immutable and SHA256-identified. State is scoped to broker
account, persisted in runtime_heartbeats with optimistic CAS and a short lease.
EMAs start at zero at activation; price features bootstrap from broker history.
Policy hash mismatch or uncertain submission blocks new EURUSD entries.
Every child is durably reserved before broker submit; a restart cannot resend
an indeterminate child. Broker SL+TP are mandatory for every child.

Forward adapter constraints: USD account and 100000EUR standard contract,
quote freshness, new entry within 60 seconds of signal boundary, spread at
most2.2pip, batch price drift at most0.03R. The real broker margin per child
can reduce the number of layers below the 1:100 reference. Actual free
margin and shared XAUUSD equity constrain sizing; exposure differs from a
standalone research account. All children share planned absolute SL/TP;
real fills differ slightly. Timeout is closed on the next runtime observation,
not the exact prior M1 close used in replay. GitHub scheduled starts can be
late or have gaps; missing entry windows are skipped, never chased.

DEMO supervision: an independent serialized EURUSD workflow runs ~five
minutes per scheduled cycle. Live broker account gates, emergency stop,
kill switch, preflight and post-fill protection remain enforced. Existing
XAUUSD limits do not inherit the EURUSD layer override.
