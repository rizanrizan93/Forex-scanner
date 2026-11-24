"""Audit completed local research replay artifacts; no broker or network access."""
from pathlib import Path
from collections import Counter
import csv
import gzip
import hashlib
import json
import math

root = Path(__file__).resolve().parent
audits = []
for metrics in sorted((root / 'results').glob('*/summary.json.metrics.json')):
    for case in json.loads(metrics.read_text()):
        profile = case['Profile']
        if (profile.get('EndYear') or profile['Year']) <= profile['Year']:
            continue
        raw = metrics.parent / Path(case['File']).name
        result = json.load(gzip.open(raw, 'rt'))
        summary = result['Summary']
        btc = result.get('BtcResearchStatus', {})
        residual = summary['EndingBalance'] - 100 - math.fsum(t['Pnl'] for t in result['Ledger'])
        passed = (
            abs(residual) < .01 and not result['Errors'] and not result['Open']
            and not summary['AccountingBlock'] and not summary['Quarantined']
            and summary['TotalContributions'] == 100
            and summary['ActualCutoff'] == '2026-11-13T03:00:00Z'
            and not any(btc.values())
        )
        audits.append(dict(
            series=metrics.parent.name, path=case['Path'], cost=case['Cost'],
            ending_balance=summary['EndingBalance'], max_floating_dd_pct=summary['MaxEquityDDPct'],
            ledger_pnl_residual_usd=residual, raw_errors=len(result['Errors']),
            open_positions=len(result['Open']), btc_status=btc, passed=passed,
            raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        ))
        if metrics.parent.name == 'btc_addon_continuous':
            control_file = next((root / 'results/filterF7').glob('*.json.gz'))
            control = json.load(gzip.open(control_file, 'rt'))
            def key(t):
                return (t['Symbol'], t['Entry'])
            old = {key(t): t for t in control['Ledger']}
            new = {key(t): t for t in result['Ledger']}
            added = [t for t in result['Ledger'] if t['Origin'] == 'BTC_H1_BULL_COMPRESS16']
            data = dict(
                control='R1_ALL_ASSETS_BTC18H72_RSI80',
                candidate=profile['Id'],
                control_balance=control['Summary']['EndingBalance'],
                candidate_balance=summary['EndingBalance'],
                delta_usd=summary['EndingBalance'] - control['Summary']['EndingBalance'],
                change_pct=100*(summary['EndingBalance']/control['Summary']['EndingBalance']-1),
                control_floating_dd_pct=control['Summary']['MaxEquityDDPct'],
                candidate_floating_dd_pct=summary['MaxEquityDDPct'],
                control_baskets=control['Summary']['Baskets'],
                candidate_baskets=summary['Baskets'],
                added_family_executed_baskets=len(added),
                added_family_net_pnl=math.fsum(t['Pnl'] for t in added),
                added_family_winners=sum(t['Pnl'] > 0 for t in added),
                common_entry_keys=len(old.keys() & new.keys()),
                missing_control_entry_keys=len(old.keys() - new.keys()),
                extra_entry_keys=len(new.keys() - old.keys()),
                note='Paired source-model replay. Added-family dollar PnL is descriptive; shared wallet changes sizes and admission of later trades.',
            )
            (root / 'BTC_ADDON_CONTINUOUS_AUDIT.json').write_text(json.dumps(data, indent=2))

(root / 'CONTINUOUS_ACCOUNTING_AUDIT.json').write_text(json.dumps(audits, indent=2))
selection = json.loads((root / 'RESULTS_R1.json').read_text())['best_cost1_B']
metrics = json.loads((root / 'results' / selection['series'] / 'summary.json.metrics.json').read_text())
case = next(c for c in metrics if c['Profile']['Id'] == selection['id'] and c['Path'] == selection['path'] and c['Cost'] == selection['cost'])
raw = root / 'results' / selection['series'] / Path(case['File']).name
result = json.load(gzip.open(raw, 'rt'))
rows = result['Ledger']
with (root / 'BEST_MODEL_BASKETS.csv').open('w') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
by_symbol = {s: dict(baskets=sum(t['Symbol'] == s for t in rows), net_pnl=math.fsum(t['Pnl'] for t in rows if t['Symbol'] == s)) for s in sorted({t['Symbol'] for t in rows})}
(root / 'BEST_MODEL_SYMBOL_ATTRIBUTION.json').write_text(json.dumps(dict(profile=selection['id'], scope='Observed shared-wallet basket PnL, not independent causal alpha.', by_symbol=by_symbol), indent=2))
print(json.dumps(dict(completed_cases=len(audits), all_passed=all(a['passed'] for a in audits))))
if not all(a['passed'] for a in audits):
    raise SystemExit('Accounting or terminal-state audit failed')
