"""Package completed raw native evidence and a human-readable result report."""
from pathlib import Path
import argparse, gzip, hashlib, json, zipfile
def run(root):
    root=Path(root).resolve();repo=root/'Forex-scanner/research/r16_no_pause';cases=root/'native_runs/cases'
    r=json.loads((repo/'results.json').read_text());b=r['baseline']
    lines=['# RIZAN R16: selective XAU entries without the additional 24h pause',
        '', 'Completed native continuous B1 pilot, 2019–2026-11-13 03:00 UTC. Initial cash $100.',
        '', '| Profile | Ending cash USD | Change vs baseline | Floating DD | Add-on baskets | Missing core keys |',
        '|---|---:|---:|---:|---:|---:|',
        f"| R15 no-pause reference | {b['EndingBalance']:,.2f} | — | {b['MaxEquityDDPct']:.4f}% | 0 | 0 |"]
    evidence={}
    for name,s in r['cases'].items():
        lines.append(f"| {name} | {s['EndingBalance']:,.2f} | {s['terminal_change_pct']:+.4f}% | {s['MaxEquityDDPct']:.4f}% | {s['addon_filled_baskets']} | {s['original_core_keys_missing']} |")
        raw=cases/f'{name}_B_cost1.json.gz'
        z=root/f'RIZAN_R16_{name.upper()}_20261123.zip'
        with zipfile.ZipFile(z,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as arc:
            arc.write(raw,'native/'+raw.name,compress_type=zipfile.ZIP_STORED)
            for f in repo.iterdir():
                if f.is_file():arc.write(f,'research/'+f.name)
            for f in ['r16.stdout.log','r16.stderr.log']:
                arc.write(root/'native_runs'/f,'logs/'+f)
        blob=z.read_bytes();evidence[z.name]={'bytes':len(blob),'sha256':hashlib.sha256(blob).hexdigest(),
            'git_blob_sha1':hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()}
    lines += ['', '## Interpretation', '',
        'Both tests disabled R15_GROWTH_GUARD. Original strategy cooldowns and risk/flat-account checks remained.',
        'The EUR seed ledger is checked against the reference; missing core keys are measured, not erased.',
        'A lower terminal balance rejects a candidate for the stated objective, even if it has extra profitable trades.',
        'All history was reused: no pristine OOS evidence or statistical significance claim.', '',
        '## Continuous annual cash (not annual $100 resets)', '',
        '| Profile | Year | Opening cash USD | Closing cash USD | Annual floating DD |',
        '|---|---:|---:|---:|---:|']
    for name in ['r15_indexed_baseline',*r['cases']]:
        a=json.loads(gzip.decompress((cases/f'{name}_B_cost1.json.gz').read_bytes()))
        for y in a['Annual']:
            lines.append(f"| {name} | {y['Year']} | {y['Start']:,.2f} | {y['End']:,.2f} | {y['AnnualEquityDDPct']:.4f}% |")
    lines += ['', '## Limits', '', *['* '+x for x in r['limitations']], '',
        'No LIVE, main branch or frozen strategy changes. The $10 billion objective remains unproven.', '',
        'Machine-readable native comparison: `r16_no_pause/results.json`.',
        'Raw native ledger evidence is archived per profile under `r16_no_pause/evidence/`.']
    report=root/'Forex-scanner/research/RIZAN_R16_NO_PAUSE_NATIVE_RESULTS_20261123.md'
    report.write_text('\n'.join(lines)+'\n')
    (repo/'evidence_manifest.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);run(p.parse_args().root)
