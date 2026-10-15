"""Bounded continuous publisher. Market data only; no broker execution imports."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from fx_scanner.pre_news_transport import BRANCH, MAX_BYTES, validate_snapshot
from datetime import UTC, datetime


def github_api(method, path, payload=None):
    repository = os.environ['GITHUB_REPOSITORY']
    if repository != 'rizanrizan93/Forex-scanner':
        raise ValueError('Pre-News repository mismatch')
    request = Request('https://api.github.com/repos/'+repository+'/'+path,
        data=None if payload is None else json.dumps(payload).encode(), method=method,
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
                 'Accept':'application/vnd.github+json','Content-Type':'application/json',
                 'User-Agent':'RIZAN-Pre-News-Publisher/2'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def publish(data, api=github_api):
    validate_snapshot(data, now=datetime.now(UTC))
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False)
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError('Pre-News publication too large')
    try:
        parent = api('GET','git/ref/heads/'+BRANCH)['object']['sha']
        exists = True
    except HTTPError as exc:
        if exc.code != 404: raise
        parent, exists = os.environ['GITHUB_SHA'], False
    tree_base = api('GET','git/commits/'+parent)['tree']['sha']
    tree = api('POST','git/trees',{'base_tree':tree_base,'tree':[
        {'path':'runtime/pre_news_snapshot.json','mode':'100644','type':'blob','content':raw}]})
    commit = api('POST','git/commits',{'message':'pre-news: refresh calendar and macro context',
                                     'tree':tree['sha'],'parents':[parent]})
    if exists:
        api('PATCH','git/refs/heads/'+BRANCH,{'sha':commit['sha'],'force':False})
    else:
        api('POST','git/refs',{'ref':'refs/heads/'+BRANCH,'sha':commit['sha']})
    return commit['sha']


def run_step(name, args, limit):
    try:
        result = subprocess.run([sys.executable,*args],cwd=ROOT,timeout=limit,check=False)
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = 124
    print('PRE_NEWS_STEP '+name+' exit='+str(code),flush=True)
    return code


def cycle(index):
    folder = ROOT/'artifacts';folder.mkdir(exist_ok=True)
    broker, snapshot = folder/'dxy_broker.json', folder/'pre_news_snapshot.json'
    broker.unlink(missing_ok=True);snapshot.unlink(missing_ok=True)
    statuses = {
        'calendar':run_step('calendar',['-m','fx_scanner.demo_xau_event_risk_v192'],60),
        'macro':run_step('macro',['-m','fx_scanner.demo_xau_macro_attribution_v399'],60),
        'broker_dxy':run_step('broker_dxy',['scripts/collect_broker_dxy.py',str(broker)],55),
    }
    code = run_step('snapshot',['scripts/publish_pre_news_snapshot.py',str(snapshot),str(broker)],25)
    if code or not snapshot.is_file():
        raise RuntimeError('Pre-News snapshot generation failed')
    data = json.loads(snapshot.read_text())
    data['publisher'] = {'cycle':index,'refresh_seconds':240,'steps':statuses,
                         'build':os.environ.get('GITHUB_SHA','')}
    sha = publish(data)
    print('PRE_NEWS_PUBLISHED cycle='+str(index)+' at='+str(data['published_at'])+' commit='+sha,flush=True)


def run_loop(*, seconds=19800, interval=240, cycle_fn=cycle, clock=time.monotonic, sleeper=time.sleep):
    started = clock();index=0;failures=0
    while clock()-started < seconds:
        tick = clock();index+=1
        try:
            cycle_fn(index);failures=0
        except Exception as exc:
            failures+=1
            print('PRE_NEWS_CYCLE_FAILED cycle='+str(index)+' type='+type(exc).__name__,flush=True)
            if failures >= 3: raise RuntimeError('Three consecutive Pre-News publication failures') from None
        remaining = min(interval-(clock()-tick),seconds-(clock()-started))
        if remaining > 0:sleeper(remaining)
    return index


if __name__=='__main__':run_loop()
