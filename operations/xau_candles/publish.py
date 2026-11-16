"""Refresh the independent VPS candle file atomically; never redate old bars."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import UTC, datetime

APP = Path('/opt/rizan-xau-candles')
OUT = Path('/var/lib/rizan-xau-candles')
CREDENTIALS = Path('/etc/rizan-bootstrap125-monitor-broker.json')


def publish_collected(payload, *, folder=OUT, now=None):
    from fx_scanner.xau_decision_candle_feed_v1 import validate_candle_snapshot
    validate_candle_snapshot(payload, now=now or datetime.now(UTC))
    target = folder/'candles.json'
    temporary = folder/'candles.tmp'
    with temporary.open('w') as stream:
        json.dump(payload, stream, allow_nan=False, separators=(',', ':'))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, target)


def main():
    values = json.loads(CREDENTIALS.read_text())
    fields = ('CTRADER_CLIENT_ID', 'CTRADER_CLIENT_SECRET', 'CTRADER_ACCESS_TOKEN')
    if not all(values.get(k) for k in fields):
        raise RuntimeError('CANDLE_READONLY_CREDENTIALS_MISSING')
    env = dict(os.environ, **{k: values[k] for k in fields})
    artifact = OUT/'collected.json'
    artifact.unlink(missing_ok=True)
    # A fresh process isolates Twisted's lifecycle and makes timeout recovery
    # independent of the trading bridge and other read-only collectors.
    subprocess.run([sys.executable, str(APP/'scripts/collect_xau_decision_readonly.py'),
                    str(artifact)], env=env, cwd=APP, check=True, timeout=80,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    payload = json.loads(artifact.read_text())
    publish_collected(payload)
    print('XAU_DIRECT_PUBLISHED as_of='+payload['as_of']+
          ' M5='+payload['bars']['M5'][-1]['closed_at'], flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('XAU_DIRECT_COLLECTION_FAILED:'+type(exc).__name__, flush=True)
        raise SystemExit(1)
