# RIZAN Profit Exit V3 — research only

Read LAPORAN_PROFIT_EXIT_V3_20261021.md and STATUS.json first.

Entry and initial risk are unchanged from V2 H1 absorption_early. Eight exit policies, no risk/leverage increase. Train selection is locked before NEW outcomes; see PREVALIDATION_GIT_LOCK.json and LOCKED_TRAIN_SELECTION.json. Never replace that selection after seeing new dates.

Primary cohort requires a complete ungapped120minute quote window for all exits. This is an offline data-availability convention, not an executable prediction of future feed availability. Keep excluded signals in the ledger.

Reproduce:
python3 -m pip install -r requirements.txt
python3 -m unittest test_profit_engine -v
python3 profit_engine.py old
python3 profit_engine.py new
python3 audit_profit.py
MPLBACKEND=Agg python3 plot_results.py
python3 build_report.py

To reconstruct NEW raw sources, run new_inputs.py (~3.84GB of raw inputs plus derived cache). The delivered package includes derived inputs for all old/new dates. Raw historical URLs/SHA256 are in OLD_INPUT_MANIFEST.json and NEW_INPUT_MANIFEST.json. The original V2 package remains independently archived with its Library identifier and ZIP SHA256 in SOURCE_PROVENANCE.json.

No orders, no bridge or cBot changes, no merge main. Not native/full-parity, no portfolio leverage/compounding return claim, no XAU/EUR validation. Raw exchanges data and derived arrays are not published in the public research Git folder; results and source are archived there separately.
