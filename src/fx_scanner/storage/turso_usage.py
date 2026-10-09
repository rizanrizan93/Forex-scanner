"""Aggregate server-reported usage without retaining SQL, values or credentials."""
import atexit
import os
from datetime import datetime, timezone
from threading import Lock

_LOCK = Lock()
_BUCKETS = {}
_CLIENTS = {}
FIELDS = ('requests', 'statements', 'rows_read', 'rows_written', 'unmetered_statements')

def record(client, items):
    if os.getenv('TURSO_USAGE_TRACKING', '0') != '1':
        return
    day = datetime.now(timezone.utc).date().isoformat()
    worker = os.getenv('GITHUB_WORKFLOW', 'local') + '/' + os.getenv('GITHUB_JOB', 'runtime')
    key = (client.endpoint, day, worker)
    delta = dict.fromkeys(FIELDS, 0)
    delta['requests'] = 1
    for item in items:
        delta['statements'] += 1
        if not item or not all(isinstance(item.get(f), int) for f in ('rows_read', 'rows_written')):
            delta['unmetered_statements'] += 1
            continue
        delta['rows_read'] += max(0, item['rows_read'])
        delta['rows_written'] += max(0, item['rows_written'])
    with _LOCK:
        bucket = _BUCKETS.setdefault(key, dict.fromkeys(FIELDS, 0))
        for f in FIELDS:
            bucket[f] += delta[f]
        _CLIENTS[client.endpoint] = client

def flush():
    with _LOCK:
        buckets = dict(_BUCKETS)
        _BUCKETS.clear()
    by_endpoint = {}
    for (endpoint, day, worker), data in buckets.items():
        columns = ','.join(FIELDS)
        update = ','.join(f'{f}={f}+excluded.{f}' for f in FIELDS)
        sql = f'INSERT INTO turso_usage_daily(day,worker,{columns}) VALUES (?,?,?,?,?,?,?) ON CONFLICT(day,worker) DO UPDATE SET {update}'
        by_endpoint.setdefault(endpoint, []).append((sql, [day, worker] + [data[f] for f in FIELDS]))
    for endpoint, statements in by_endpoint.items():
        try:
            _CLIENTS[endpoint].batch(statements, transaction=True, track_usage=False)
        except Exception:
            # Never retry uncertain writes or interfere with trading shutdown.
            print('TURSO_USAGE_REPORT_UNAVAILABLE; provider dashboard remains authoritative', flush=True)

atexit.register(flush)
