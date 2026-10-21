# cBots manual monitor

The main dashboard's **cBots** tab displays strategy preparation levels, conditions,
short-lived manual entry references, planned SL/TP/layers, and broker-observed owned
positions. The separate XAU zone tab stays free of research archives.

Signal calculations use byte-identical pure C# files from frozen portfolio V1.3.0,
commit e357272fec03411a6e7c4d2397faf742d1a11047. SOURCE_MANIFEST.json verifies all five
files before collection. No native cTrader robot, trading API, order dispatcher,
checkpoint write, lease acquisition or service restart is included in this monitor.

The read-only workflow collects native FP Markets M1 candles and recent BID/ASK
quotes, reads copies of FX checkpoints and macro data over pinned SSH, and validates
the original seven-day Bitstamp BTC seed through the unchanged BtcSevenDayFeed.
The BTC adapter runs a separate in-memory Feed with the existing service interpreter;
it does not connect a second cBot or touch its live checkpoint/lease.

Public snapshots contain only display fields; account IDs, hashed account binding,
checkpoint bodies, EUR feedback state, credentials and raw BTC seed are not published.
The reader refuses ambiguous account matching, every trade mutation and token refresh.

Cadence is approximately 30 seconds plus collection/publication time; the dashboard
checks every 10 seconds. A signal's original expiry is rechecked at display time:
FX <60 seconds, BTC <=5 seconds. The monitor cannot guarantee capturing BTC's five
second entry window. Delayed signals cannot become fresh merely by republishing.
Stale publications hide prices/positions; source-specific stale candles hide levels.

WATCH levels describe source triggers, not executable pending orders. Some strategies
use a single breakout/channel threshold rather than a supply/demand zone. ENTRY manual
is an independent calculation, not proof the native cBot accepted the same signal:
XAU warmup history, terminal flags, ACKs, broker schedule, volume normalization and
portfolio margin checks are not fully observable here. Native EUR H1 state is resumed
from a copy. Manual sizing/margin must be checked in cTrader. The original cBot's
broker execution, risk, sizing, state and recovery logic remain authoritative.

Validation: Python tests cover frozen hashes, protocol rejection of order messages,
geometry, macro/news gates, same-account matching, stale/expired signals, active
positions and lazy tab routing. CI compiles the unchanged C# cores and adapter.
