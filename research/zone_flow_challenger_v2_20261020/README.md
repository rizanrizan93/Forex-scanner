# RIZAN Zone Flow Challenger V2 — research only

Read LAPORAN_ZONE_FLOW_CHALLENGER_V2_20261020.md first. Actual public Bybit BTCUSDT L2 and tape, four sample dates with3day warmup; not XAU/EUR CFD or native execution. No robust qualification or live changes.

Reconstruct: install requirements, run download_inputs.py, prepare_inputs.py, unittest test_challenger, challenger.py, audit_ledgers.py, flow_chart.py.

Primary evidence: EVENT_LEDGER.csv; ONE_POSITION_LEDGER.csv; MATCHED_ZONE_ABLATION.csv; ORDERFLOW_EVIDENCE.csv; COMPARISON.csv; DATA_QUALITY.json; INPUT_MANIFEST.json. See protocols and post-initial-results M15_M5_EXTENSION.json. No freeze modification, bridge action, orders or merge main.
