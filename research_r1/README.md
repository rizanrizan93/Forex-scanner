# RIZAN XAU Yield/Asia R1

Offline research only. Read PROTOCOL.md before using any result.

Execution order (from package root):

```bash
python -m pip install -r research_r1/requirements.txt
python research_r1/acquire.py
python research_r1/acquire_macro.py
python research_r1/acquire_fred_reference.py
python research_r1/build_bars.py
python research_r1/test_research.py
python research_r1/profiles.py
python research_r1/replay.py
python research_r1/replay.py --mode PERIODS
python research_r1/replay.py --mode ANNUAL
python research_r1/analyze.py
python research_r1/replay.py --selected --cost STRESS15 --mode PERIODS
python research_r1/replay.py --selected --cost STRESS20 --mode PERIODS
python research_r1/replay.py --selected --compound --mode PERIODS
python research_r1/replay.py --selected --compound --initial 100 --mode PERIODS
python research_r1/replay.py --selected --cost ZERO_DIAGNOSTIC --mode PERIODS
python research_r1/sensitivity.py
python research_r1/exploratory_candidate.py
python research_r1/curves.py
python research_r1/report.py
```

Data hashes in audit/acquisition.json must match before reproducing the results. Raw third-party ticks are not redistributed in this package. The included archive paths and source URLs allow authorized reacquisition. Official daily Treasury XML files are included for audit, not treated as intraday point-in-time features. A changed upstream file must be rejected rather than silently replacing the version tested here.

CONTINUOUS, PERIODS, and ANNUAL are independent account experiments. Never sum their ending balances. The zero-cost diagnostic has no spread/commission/slippage and is not an executable trading result. Macro model APIs are unfitted scaffolding; no trained macro artefact is supplied. Files in baseline contain identity evidence only, no live runtime or credentials.

The SSH inventory workflow is optional and only lists historical storage. All numeric research ran offline in the isolated workspace, not on the live VPS. It never restarts services, writes checkpoints, changes production, or accesses the order API.
