# Phone-only research runtime v0.11

FP Markets cTrader Open API remains the research/live-market feed.

```text
FP Markets cTrader (RESEARCH_ONLY)
          |
          v
Linux research runtime
  live Bid/Ask + D1/H4/H1/M15/M5 trendbars
          |
          v
Supabase -> Streamlit on Android

HFM MT5 stays separate for execution/telemetry when a Windows host exists.
```

The Linux process has no MT5 or order-submission dependency.
It sends a client heartbeat every 8 seconds and paces historical requests at
4 requests/second.

Required cloud secrets:

```text
CTRADER_CLIENT_ID
CTRADER_CLIENT_SECRET
CTRADER_ACCESS_TOKEN
CTRADER_REFRESH_TOKEN
CTRADER_TRADER_LOGIN
SUPABASE_URL
SUPABASE_SECRET_KEY
```

Use persistent storage for:

```text
CTRADER_TOKEN_STATE_PATH=/app/state/ctrader_tokens.json
```

The runtime resolves the actual `ctidTraderAccountId` from the access-token
account list by matching `CTRADER_TRADER_LOGIN`. It fails closed unless the
match is unique and is a demo account. `CTRADER_ACCOUNT_ID` is optional; when
provided it acts only as a second pin and must match the resolved API ID.

One-shot validation:

```bash
python -m fx_scanner.cli research-cloud --once
```

Continuous runtime:

```bash
python -m fx_scanner.cli research-cloud --heartbeat 8 --mtf-refresh 900
```

The Supabase heartbeat worker name is ctrader_research_cloud.
Full ranking remains fail-closed when required macro evidence is incomplete.
