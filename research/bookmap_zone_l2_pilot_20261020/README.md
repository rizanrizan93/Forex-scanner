# RIZAN L2 + Zone Reversal — read-only research

See LAPORAN_BOOKMAP_ZONE_PILOT_20261020.md for actual results and limitations.

Research only: execution_influence=false. No live connection, broker changes, orders, bridge imports or Bookmap account connection. This is an independent depth-heatmap prototype, not official Bookmap software. No consistent net-positive improvement was established.

- `book_adapter.py`: reconstruct snapshot/delta and causal depth evidence.
- `zone_overlay.py`: annotate existing zones, reject venue/future-zone mismatches; keep original boundaries.
- `evaluate.py`: uses original repo H1/M5 source unchanged and runs two other explicit research cohorts. No grid search.
- `visualize.py`: historical depth heatmap; `--interactive --day 2024-01-06` offers a local replay slider.
- `EVENT_LEDGER.csv`, `ZONE_ANNOTATIONS.json`, `COMPARISON.csv`: actual paired events and outputs.
- `STATUS.json`, input audit, protocols, source provenance and tests: evidence.

Install requirements; run `python3 -m unittest test_research -v`.
Full raw reconstruction: `python3 download.py` then `python3 prepare_books.py` (~2.1 GB raw ZIPs).
Evaluate: `python3 evaluate.py`. Generate charts: `MPLBACKEND=Agg python3 visualize.py`.

The downloadable research bundle includes derived NPZ inputs. Repository text archive excludes large raw and derived market data. Source URLs and raw SHA256 are retained. Jan6-8 2024 is a very short diagnostic holdout, not live qualification. BTCUSDT/Bybit results do not validate XAU/EUR or BTCUSD broker.
