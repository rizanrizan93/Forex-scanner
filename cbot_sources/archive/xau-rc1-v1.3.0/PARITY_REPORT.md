# XAU RC1 v1.3.0 parity report

Strategy: `XAUUSD_RC1_102_5_PRIMARY_FROZEN_V1`.

Build asserts the embedded cBot contract matches RC1 $102.5: 2.4 ATR/structural stop, 5.5R target, 3 stages at 0/0.20/0.40R, 90 minute confirmed-add TTL, 12.1% basket risk cap, 50% margin cap, $102.50 balance step, 480 minute hold, 3-day loss cooldown, and 0.20R send-reference tolerance.

Execution fixtures are inherited from XAU stable v1.2.1 and rerun against the patched RC1 source. The `.algo` is compiled from this isolated source and defaults to trading disabled.

Historical replay reference through 2026-10-09 is research evidence, not a native cTrader tick backtest and not a guarantee of live results. RC1 $102.5 exceeded the former <50% DD criterion in the 2026 extension (about 51.3% observed in the synthetic replay).
