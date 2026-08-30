# Runtime monitoring

Streamlit Community Cloud remains the monitor only. The broker terminal and
scanner runtime run outside Streamlit.

## Windows HFM MT5 host

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-mt5-windows.txt
pip install -e .
```

Host-only environment variables:

```text
MT5_TERMINAL_PATH
MT5_LOGIN
MT5_SERVER
MT5_PASSWORD
SUPABASE_URL
SUPABASE_SECRET_KEY
```

Never put MT5 credentials in Streamlit or GitHub.

## First broker telemetry check

With HFM MT5 open and logged in:

```powershell
python -m fx_scanner.cli mt5-monitor --once
```

Expected output begins with `MT5_MONITOR_OK`. Then compare the Streamlit
**Account & Positions** tab with the MT5 account.

## Continuous monitor

```powershell
python -m fx_scanner.cli mt5-monitor --interval 15
```

The worker reads account information and open positions, writes one coherent
snapshot to Supabase, and updates the `mt5_account_monitor` heartbeat.

It does not call `order_check` or `order_send`. Trading control remains
fail-closed: `DISABLED`, new orders off, emergency stop on.
