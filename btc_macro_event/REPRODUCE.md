# Fixed BTC macro/event comparison

Frozen baseline source commit: `1d6ad83f285f293b103342073b637fa16e597fb9`.
Preregistered filters/data/replay adapter commit: `5c9e5f9fb0525d10e966f9001d5dcaf9eb1fbfed`.
Research only. No native strategy/source or live system changes.

Use .NET 8 SDK with Roslyn/reference assemblies, Python 3 and matplotlib. `prepare_filters.py` additionally uses pandas for US federal holidays; generated exact filter CSVs are already included. Reuse these files rather than silently downloading a newer FRED vintage. Do not modify filter thresholds after viewing outcomes.

Input provenance is the same frozen release: official Bitstamp BTC M1 sha256 c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504; XAU sha256 3fda8011082e2691b6ebe1a8a4da5fff8e4bf0fc07baf57506b7894d95fc1808; recovered complete EUR sha256 3c74ac5ccaeeac64f44693bc6bd4406e9225a9ef61dbb5f80756530f050506ec. Do not use the truncated EUR archive CSV. Inputs are not redownloaded, imputed, or included in this small delivery ZIP.

Run from repository root after placing original verified data paths:

```sh
python btc_macro_event/bootstrap.py
python btc_macro_event/build_gate_tests.py /absolute/path/to/dotnet-root
python btc_macro_event/run_local.py /absolute/path/to/dotnet-root replay
BTC_INPUT=/absolute/path/BTCUSD_M1.csv BTC_GATE_DATA="$PWD/btc_macro_event/data" BTC_FRIDAY_CLOSE_UTC_HOUR=22 /absolute/path/to/dotnet-root/dotnet btc_macro_event/replay/Replay.dll /absolute/path/xau.csv /absolute/path/complete_eur.csv btc_macro_event/replay/matrix.json matrix 2019 2026
```

The optional last index 0–7 selects one case. Do not rebuild/overwrite a replay DLL while it is running. Preserve its full output and gate audit; compare BASE A/B fill ledgers exactly to the frozen package's corresponding raw reports. `verify_zip.py` independently checks published package hashes, cash accounting, PF, balance DD, BTC direction counts, and weekend exposure.

This is a current-vintage macro experiment, not a certified point-in-time historical macro test. Event scope is FOMC rate decisions only; CPI, NFP, sentiment/surprise, DXY, ETF flows, or liquidity balances are not included. No leverage retuning (BTC10x/XAU-EUR200x), no stress cost/delay tests in this initial experiment. Model sessions and OHLC path limitations remain inherited.
