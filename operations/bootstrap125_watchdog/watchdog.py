"""Independent read-only observer. Cannot send orders or restart services."""
import json
from datetime import datetime, timezone
from pathlib import Path
from cbot_v1_reliability import observe

PROFILE='RIZAN_BOOTSTRAP125_V1_FROZEN_20261114'
HASH='b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128'
ROLES={'BOOTSTRAP','XAUUSD','EURUSD','BTCUSD'}

def check(payload,now):
    if (payload.get('contract')!='RIZAN_BOOTSTRAP125_READONLY_V1' or payload.get('profile')!=PROFILE
        or payload.get('profile_hash')!=HASH or payload.get('account_suffix')!='7903'
        or payload.get('read_only') is not True or payload.get('execution_authority') is not False):
        raise ValueError('INVALID_MONITOR_CONTRACT')
    rows=payload.get('roles')
    if not isinstance(rows,list) or len(rows)!=4 or {r.get('role') for r in rows}!=ROLES:
        raise ValueError('INVALID_ROLES')
    result=observe(payload,now)
    result.update(event='V1_HEARTBEAT_ALERT' if result['attention_required'] else 'V1_HEARTBEAT_OBSERVED',
                  observed_at=now.isoformat(),read_only=True,execution_authority=False)
    return result

def main():
    try:
        p=json.loads(Path('/var/lib/rizan-bootstrap125-monitor/status.json').read_text())
        result=check(p,datetime.now(timezone.utc))
    except Exception as exc:
        result=dict(event='V1_HEARTBEAT_ALERT',status='UNKNOWN',reason=type(exc).__name__,
                    execution_ready=None,automatic_recovery=False,read_only=True,execution_authority=False)
    print(json.dumps(result,allow_nan=False),flush=True)

if __name__=='__main__':main()
