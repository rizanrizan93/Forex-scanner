"""Persist R29 research evidence; never promote models automatically."""
import json
from pathlib import Path
import sys


def percent(value):
    return '—' if value is None else f'{100*value:.2f}%'


def run(root):
    root=Path(root)
    paths=sorted(root.glob('r29-*.json'))
    if len(paths)!=4:
        raise ValueError('All four timeframe reports required')
    docs=[json.loads(p.read_text()) for p in paths]
    if {d['tf'] for d in docs}!={'H1','H4','D1','W1'}:
        raise ValueError('Duplicate or missing timeframe')
    out=Path('research/r29');out.mkdir(parents=True,exist_ok=True)
    lines=['# R29 Direction Accuracy Research','',
           'Research only. No production promotion. Chronological tests reuse previously inspected archives; independent prospective accuracy is unproven.','',
           '| TF | Year | R28 accuracy | R29 accuracy | Delta pp | R29 BUY (n) | R29 SELL (n) | R28 coverage | R29 coverage |',
           '|---|---:|---:|---:|---:|---|---|---:|---:|']
    for d in docs:
        (out/f"r29-{d['tf']}.json").write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
        for f in d['folds']:
            if f['status']!='EVALUATED':
                lines.append(f"| {d['tf']} | {f['year']} | No admissible validation policy | | | | | | |")
                continue
            a,b=f['r281_same_sample'],f['r29']
            delta=f['accuracy_delta_pp']
            lines.append(f"| {d['tf']} | {f['year']} | {percent(a['accuracy'])} | {percent(b['accuracy'])} | {delta:+.2f} | {percent(b['BUY']['accuracy'])} ({b['BUY']['n']}) | {percent(b['SELL']['accuracy'])} ({b['SELL']['n']}) | {percent(a['coverage'])} | {percent(b['coverage'])} |" if delta is not None else f"| {d['tf']} | {f['year']} | No predictions | | | | | | |")
    lines+=['','See JSON reports for per-side Wilson bounds, exact validation policies, source hashes and source cutoff.','',
            'The coverage floor applies to validation, and may fail on test data. Any such failure is a research failure, not grounds to retune using the test year.','',
            'No candidate is claimed to reach 80% without sufficient test samples and independent forward evidence.']
    (out/'R29_RESULTS.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines),flush=True)


if __name__=='__main__':
    run(sys.argv[1])
