"""Pre-maintenance remote backup and redacted audit; never modifies live state."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROFILE = 'e4ebbc111db1c40a261483181f5d6aad1c71c49dfd8e53fbc77d043a5504e22f'
FOLDER = Path('/var/lib/rizan-btc10-bridge')


def audit(folder, backup_root):
    now = datetime.now(timezone.utc)
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = backup_root / now.strftime('btc-weekend-preflight-%Y%m%dT%H%M%S%fZ')
    target.mkdir(mode=0o700)
    source = sqlite3.connect((folder / 'checkpoints.sqlite').resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    source.execute('PRAGMA query_only=ON')
    backup = target / 'checkpoints.sqlite'
    old_umask = os.umask(0o077)
    try:
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
        os.umask(old_umask)
    backup.chmod(0o600)
    result = {'observed_utc': now.isoformat(), 'checkpoint_writes': 0, 'service_restarts': 0,
              'broker_requests': 0, 'deployment_verified': False, 'state_correction_ready': False,
              'backup_created': True, 'backup_name': target.name,
              'backup_sha256': hashlib.sha256(backup.read_bytes()).hexdigest(), 'states': [], 'leases': []}
    db = sqlite3.connect(backup.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    db.execute('PRAGMA query_only=ON')
    accounts = set()
    try:
        for key, version, raw in db.execute('SELECT key,version,state FROM checkpoints'):
            state = json.loads(raw)
            account = str(state.get('AccountNumber', ''))
            if not account.endswith('7903'):
                continue
            accounts.add(account)
            symbol = state.get('Symbol')
            if symbol not in ('XAUUSD', 'EURUSD', 'BTCUSD'):
                continue
            item = {'symbol': symbol, 'account_suffix': account[-4:], 'server_revision': version,
                    'client_revision': state.get('Revision'),
                    'state_sha256': hashlib.sha256(raw.encode()).hexdigest()}
            for name in ('WeekendLockUntil', 'LastSignal', 'LastSignalUtc', 'LastBarUtc', 'Sending',
                         'Fault', 'ExitPending', 'BatchActive', 'BatchRemaining', 'NativePendingSequence'):
                if name in state:
                    value = state[name]
                    # Only bounded scalar fields; never output complete checkpoint bodies.
                    item[name] = value if isinstance(value, (bool, int, float, type(None))) else str(value)[:64]
            item['pending_intent'] = bool(state.get('NativePendingLabel') or state.get('PendingLabel'))
            item['basket_present'] = bool(state.get('Basket'))
            if symbol == 'BTCUSD':
                item['identity_valid'] = (key == f'TPBTC:{PROFILE}:{account}:BTCUSD'
                                          and state.get('Schema') == 1
                                          and state.get('NativeProfileHash') == PROFILE
                                          and state.get('ContractHash') == 'RZ-7D130-BTC8500283-LFOLLOW-WEEKEND')
            if symbol == 'BTCUSD':
                receipt = db.execute(
                    'SELECT base,digest,version FROM checkpoint_receipts WHERE key=? AND client_revision=?',
                    (key, state.get('Revision')),
                ).fetchone()
                item['durable_receipt_matches_checkpoint'] = bool(
                    receipt and receipt[1] == item['state_sha256']
                    and receipt[2] == version and receipt[0] + 1 == version
                )
                item['known_lock_correction_persisted'] = bool(
                    item.get('identity_valid') and item['durable_receipt_matches_checkpoint']
                    and state.get('WeekendLockUntil') in ('2026-11-02T00:00:00Z', '2026-11-02T00:00:00.0000000Z')
                    and state.get('Revision', 0) >= 170
                )
            result['states'].append(item)
        if len(accounts) != 1 or len([x for x in result['states'] if x['symbol'] == 'BTCUSD']) != 1:
            raise ValueError('IDENTITY_AMBIGUOUS')
        account = next(iter(accounts))
        for key, expires, touched in db.execute('SELECT key,expires_at,touched_at FROM bridge_leases'):
            if f':{account}:' in key:
                symbol = key.split(':')[-1]
                if symbol in ('XAUUSD', 'EURUSD', 'BTCUSD'):
                    result['leases'].append({'symbol': symbol,
                                             'remaining_seconds_at_snapshot': round(expires - now.timestamp(), 2),
                                             'last_touch_age_seconds': round(now.timestamp() - touched, 2)})
    finally:
        db.close()
    health = folder / 'health.json'
    if health.is_file():
        data = json.loads(health.read_text())
        result['health'] = {k: data.get(k) for k in ('profile', 'observed_utc', 'btc', 'connected', 'execution_authority')}
    result['limitations'] = ['Pre-maintenance remote snapshot only; writer remains active',
                            'Local cTrader checkpoint, active binary, parameters and journal unavailable',
                            'No broker position or pending order verification in this script',
                            'Do not use this snapshot as a compare-and-swap value for a later correction']
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(audit(FOLDER, Path('/home/Rizanrizan/.local/state/rizan-maintenance')), allow_nan=False))
    except Exception as exc:
        print(json.dumps({'preflight_failed': type(exc).__name__, 'checkpoint_writes': 0}))
        raise SystemExit(1)
