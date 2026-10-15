"""Bounded market-data publisher; each collection uses a fresh Twisted process."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fx_scanner.manual_reversal_map import validate

BRANCH = 'scanner-reversal-snapshots'
PATHS = ('runtime/reversal_snapshot.json', 'runtime/manual_reversal_snapshot.json')


def github_api(method, path, payload=None):
    repository = os.environ['GITHUB_REPOSITORY']
    if repository != 'rizanrizan93/Forex-scanner':
        raise ValueError('Reversal repository mismatch')
    request = Request('https://api.github.com/repos/' + repository + '/' + path,
        data=None if payload is None else json.dumps(payload).encode(), method=method,
        headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                 'User-Agent': 'RIZAN-Reversal-Publisher/1'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def publish(data, manual, api=github_api, *, now=None):
    for item in (data, manual):
        if (item.get('execution_authority') is not False or
            item.get('execution_influence') is not False or item.get('symbol') != 'XAUUSD'):
            raise ValueError('Reversal read-only guard')
    # A new commit must not make an old market price look fresh.
    if not validate(manual, now=now or datetime.now(UTC))['fresh']:
        raise ValueError('Reversal collection stale or unavailable')
    contents = [json.dumps(item, allow_nan=False) for item in (data, manual)]
    if any(len(raw.encode()) > 1_000_000 for raw in contents):
        raise ValueError('Reversal publication too large')
    try:
        parent = api('GET', 'git/ref/heads/' + BRANCH)['object']['sha']
        exists = True
    except HTTPError as exc:
        if exc.code != 404:
            raise
        parent, exists = os.environ['GITHUB_SHA'], False
    base = api('GET', 'git/commits/' + parent)['tree']['sha']
    tree = api('POST', 'git/trees', {'base_tree': base, 'tree': [
        {'path': path, 'mode': '100644', 'type': 'blob', 'content': raw}
        for path, raw in zip(PATHS, contents)]})
    commit = api('POST', 'git/commits', {'message': 'scanner: refresh read-only XAU reversal map',
        'tree': tree['sha'], 'parents': [parent]})
    if exists:
        api('PATCH', 'git/refs/heads/' + BRANCH, {'sha': commit['sha'], 'force': False})
    else:
        api('POST', 'git/refs', {'ref': 'refs/heads/' + BRANCH, 'sha': commit['sha']})
    return commit['sha']


def cycle(index):
    folder = ROOT / 'artifacts'
    folder.mkdir(exist_ok=True)
    snapshot = folder / 'reversal_snapshot.json'
    manual = folder / 'manual_reversal_snapshot.json'
    for path in (snapshot, manual):
        path.unlink(missing_ok=True)
    subprocess.run([sys.executable, 'scripts/publish_reversal_snapshot.py', str(snapshot)],
                   cwd=ROOT, timeout=210, check=True)
    data = json.loads(snapshot.read_text())
    mapping = json.loads(manual.read_text())
    mapping['publisher'] = {'cycle': index, 'refresh_seconds': 300,
                            'build': os.environ.get('GITHUB_SHA', '')}
    sha = publish(data, mapping)
    print('REVERSAL_PUBLISHED cycle=' + str(index) + ' at=' + mapping['as_of'] +
          ' candle=' + str(mapping.get('price_observed_at')) + ' commit=' + sha, flush=True)


def run_loop(*, seconds=19800, interval=300, cycle_fn=cycle,
             clock=time.monotonic, sleeper=time.sleep):
    started = clock()
    index = failures = 0
    while clock() - started < seconds:
        tick = clock()
        index += 1
        try:
            cycle_fn(index)
            failures = 0
        except Exception as exc:
            failures += 1
            print('REVERSAL_CYCLE_FAILED cycle=' + str(index) + ' type=' + type(exc).__name__, flush=True)
            if failures >= 3:
                raise RuntimeError('Three consecutive reversal publication failures') from None
        remaining = min(interval - (clock() - tick), seconds - (clock() - started))
        if remaining > 0:
            sleeper(remaining)
    return index


if __name__ == '__main__':
    run_loop()
