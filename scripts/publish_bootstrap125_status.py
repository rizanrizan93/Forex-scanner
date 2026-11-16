"""Publish only the allowlisted bridge status; never modify bridge state."""
import json
import os
from pathlib import Path
from read_bootstrap125_dashboard import snapshot

OUTPUT = Path('/var/lib/rizan-bootstrap125-monitor/status.json')

def publish(path=OUTPUT):
    data = snapshot()
    payload = json.dumps(data, allow_nan=False, separators=(',', ':'))
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, path)

if __name__ == '__main__':
    publish()
