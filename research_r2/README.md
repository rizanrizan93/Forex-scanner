# RIZAN XAU Asian Session R2

Offline research only. Read PROTOCOL_R2.md before interpreting results. No live order path, bridge writes or production changes are part of this package.

This continues R1 using exactly the same 87 XAU monthly files and adds 87 EUR files. Their hashes match the VPS archive manifest. Raw quote archives are not redistributed. R1's supply-chain and broker-parity limitations still apply. The source data end March 2026; no April–November 2026 tick claim is made.

## Reproduction

Install the pinned R1 runtime dependencies, acquire the raw tick files using the included SHA256 manifest, then run one research worker at a time. Two runs were killed when too many workers ran concurrently; sequential retries completed and both attempts are documented.

```bash
python -m pip install -r research_r1/requirements.txt
python research_r1/acquire.py
python research_r1/build_bars.py
python research_r2/acquire_eur.py
python research_r2/acquire_calendar.py
python research_r2/acquire_fomc.py
python research_r2/restore_vintages.py
python research_r2/acquire_vintages.py
python research_r2/test_r2.py
python research_r2/run_r2.py --name GRID
python research_r2/analyze_r2.py
python research_r2/followups.py
python research_r2/run_r2.py --configs r2_results/ablation_configs.json --name ABLATION
python research_r2/ml_prepare.py
python research_r2/run_r2.py --configs r2_results/ml_label_configs.json --mode ANNUAL --name ML_LABELS
python research_r2/ml_models.py
python research_r2/run_r2.py --configs r2_results/ml_configs.json --name ML
python research_r2/select_r2.py
python research_r2/run_r2.py --configs r2_results/review_configs.json --cost STRESS15 --name REVIEW_STRESS15
python research_r2/run_r2.py --configs r2_results/review_configs.json --cost STRESS20 --name REVIEW_STRESS20
python research_r2/run_r2.py --configs r2_results/review_configs.json --mode ANNUAL --name REVIEW_ANNUAL
python research_r2/run_r2.py --configs r2_results/review_configs.json --mode CONTINUOUS --name REVIEW_CONTINUOUS
python research_r2/run_r2.py --configs r2_results/review_configs.json --mode CONTINUOUS --compound --name REVIEW_COMPOUND
python research_r2/robustness_r2.py
python research_r2/plot_r2.py
python research_r2/report_r2.py
```

The retrospective tick archive must be reacquired only from its exact manifest version. Reject a changed upstream hash. All379 exact full ALFRED CSV responses are preserved in r2_raw/ALFRED_EXACT_RESPONSES.tar.xz; restore_vintages.py verifies each original uncompressed SHA256 before recreating its cache. Response URLs, the parsed PIT feature panel and the historical-vintage semantic sentinel are also included. Never replace the vintages with current FRED history.

Signals, parameters, fit cutoffs, period metrics, yearly resets, trade logs, drawdowns, model predictions, unavailable-data flags and failed/retried run logs remain separate. Do not add profits from independent account resets or interpret a no-trade account as a profitable strategy. There is no certified native FP Markets replay and no new cBot deployment from this research.
