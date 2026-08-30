# Streamlit deployment

## Main file

Use this exact path in Streamlit Community Cloud:

```text
main.py
```

The file is located at the repository root and is the canonical deployment
entrypoint. It delegates to `streamlit_app.py`, which contains the dashboard UI.

## Recommended deployment

1. Create a new Streamlit Community Cloud app.
2. Select the `Forex-scanner` repository.
3. Select branch `main`.
4. Set **Main file path** to `main.py`.
5. Deploy.

The repository pins Streamlit `1.62.0` in `requirements.txt`.

## Supabase dashboard connection

The app can boot without credentials. In that state it shows validated config,
the 15-pair universe, cadence and acceptance gates.

To read durable scanner snapshots, add these values in Streamlit Cloud
**Secrets**:

```toml
SUPABASE_URL = "your-project-url"
SUPABASE_SECRET_KEY = "your-backend-secret"
```

Do not commit `.streamlit/secrets.toml`. It is git-ignored.

Do not put a Supabase backend secret in:

- GitHub source code
- README
- screenshots
- Android client code
- browser JavaScript
- chat messages

The Streamlit Secret is available only to the server-side Python process.

## What the dashboard reads

Read-only queries cover:

- `scanner_runs`
- `pair_rankings`
- `signals`
- `currency_macro_state`
- `runtime_heartbeats`
- `model_performance`
- `execution_control`

The dashboard does not update execution controls and has no order-submission
action.

## Safety state

The expected durable bootstrap remains:

```text
execution_mode       DISABLED
new_orders_enabled   false
emergency_stop       true
```

If the dashboard sees a different state it renders a safety alert.

## Architecture

Streamlit is intentionally not the continuous scanner host:

```text
broker feeds -> VPS/runtime scanner -> Supabase snapshots
                                      |
                                      v
                               Streamlit dashboard
```

This separation prevents page reruns, browser disconnects or Community Cloud
sleep/restart behavior from becoming part of the M5 trigger/order path.

## Provider checks

The **Macro & Data** tab has a manual official-provider check. It is user
initiated and cached for 60 seconds. It is not part of the quote/order hot path.

## Local smoke

```bash
pip install -r requirements.txt
pip install -e .
streamlit run main.py
```

`streamlit run streamlit_app.py` remains supported for direct local debugging,
but `main.py` is the deployment contract.

## CI

Every push and pull request compiles both `main.py` and
`streamlit_app.py` before unit tests. Static tests also verify:

- the canonical root `main.py` exists and delegates to `streamlit_app.py`
- the implementation contains the Streamlit page configuration
- Streamlit is pinned
- no backend secret literal is committed
- the dashboard implementation does not import the heavy validation package
