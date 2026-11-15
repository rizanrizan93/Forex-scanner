"""Sanitized V1 bridge observation. No broker API, secrets or state mutation.

Reads health.json and SQLite using mode=ro / query_only. Published fields are
explicitly constructed; never include raw state, labels, account IDs or prices.
"""
from __future__ import annotations
import json
import math
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/var/lib/rizan-bootstrap125-bridge')
PROFILE = 'b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128'
PROFILE_ID = 'RIZAN_BOOTSTRAP125_V1_FROZEN_20261114'
ROLES = ('BOOTSTRAP', 'XAUUSD', 'EURUSD', 'BTCUSD')
CONTRACTS = {
    'BOOTSTRAP': (PROFILE, 1, None),
    'XAUUSD': ('44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c', 1, 'XAU_BATCH_SEND_REF_COOLDOWN_V1'),
    'EURUSD': ('d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a', 3, 'EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1'),
    'BTCUSD': ('RZ-7D130-BTC8500283-LFOLLOW-WEEKEND', 1, None),
}


def utc_text(value):
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return t.astimezone(timezone.utc).isoformat() if t.tzinfo and t.year >= 2020 else None
    except (ValueError, TypeError, OverflowError):
        return None


def checkpoint_role(key):
    parts = str(key).split(':')
    if len(parts) == 4 and parts[0] in ('TPBOOT', 'TPBTC') and parts[1] == PROFILE:
        account, role = parts[2:]
        expected = 'BOOTSTRAP' if parts[0] == 'TPBOOT' else 'BTCUSD'
    elif len(parts) == 3 and parts[0] in ('TPX_b6014ae7', 'TPE_b6014ae7'):
        account, role = parts[1:]
        expected = 'XAUUSD' if parts[0] == 'TPX_b6014ae7' else 'EURUSD'
    else:
        return None
    if (role != expected or not re.fullmatch(r'[1-9][0-9]{0,18}', account)
            or int(account) > 9223372036854775807 or not account.endswith('7903')):
        return None
    return role, account


def identity_ok(role, account, state):
    contract, schema, execution = CONTRACTS[role]
    revision = state.get('Revision')
    ok = (type(state.get('AccountNumber')) is int and str(state['AccountNumber']) == account
          and state.get('Symbol') == role and type(state.get('Schema')) is int
          and state['Schema'] == schema and state.get('ContractHash') == contract
          and type(revision) is int and revision >= 0)
    if execution:
        ok = ok and state.get('ExecutionModel') == execution
    if role == 'XAUUSD':
        ok = ok and state.get('ProfileHash') == PROFILE
    if role == 'BTCUSD':
        ok = ok and state.get('NativeProfileHash') == PROFILE
    if role == 'BOOTSTRAP':
        ok = ok and state.get('Phase') in ('SEED', 'GROWTH')
        if state.get('Phase') == 'GROWTH':
            balance = state.get('GraduationBalance')
            ok = (ok and type(balance) in (int, float) and math.isfinite(balance) and balance >= 125
                  and utc_text(state.get('GraduatedUtc')) is not None
                  and state.get('Intent') is None and not state.get('OpenLabel'))
    return bool(ok)


def flag(state, name):
    value = state.get(name)
    return value if type(value) is bool else None


def sanitize(states, leases, *, now):
    selected, accounts = {}, set()
    for key, version, raw in states:
        match = checkpoint_role(key)
        if not match:
            continue
        role, account = match
        if role in selected:
            raise ValueError('DUPLICATE_V1_ROLE')
        accounts.add(account)
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError('INVALID_V1_STATE')
        selected[role] = (key, version, account, state)
    if len(accounts) > 1:
        raise ValueError('MULTIPLE_V1_ACCOUNTS')
    lease_by_key = {k: (expires, touched) for k, expires, touched in leases}
    output = []
    for role in ROLES:
        row = dict(role=role, checkpoint_present=False, identity_ok=False,
                   checkpoint_version=None, client_revision=None, phase=None,
                   lease_active=False, lease_touched_at=None, lease_expires_at=None,
                   last_signal_at=None, weekend_lock_until=None,
                   checkpoint_basket=None, pending_intent=None,
                   fault=None, quarantined=None, halted=None, exit_pending=None)
        if role in selected:
            key, version, account, state = selected[role]
            row.update(checkpoint_present=True, identity_ok=identity_ok(role, account, state),
                       checkpoint_version=version if type(version) is int and version >= 0 else None,
                       client_revision=state.get('Revision') if type(state.get('Revision')) is int else None,
                       phase=state.get('Phase') if role == 'BOOTSTRAP' and state.get('Phase') in ('SEED', 'GROWTH') else None,
                       last_signal_at=utc_text(state.get('LastSignalUtc', state.get('LastSignal'))),
                       weekend_lock_until=utc_text(state.get('WeekendLockUntil')) if role == 'BTCUSD' else None,
                       checkpoint_basket=bool(state.get('Basket') or state.get('BatchActive') or state.get('OpenLabel')),
                       pending_intent=bool(state.get('Intent') or state.get('PendingLabel') or state.get('NativePendingLabel')
                                           or state.get('PendingFirstFill') or state.get('XauPendingSignal')
                                           or state.get('Sending') or state.get('BatchRemaining') or state.get('HandoffSignal')),
                       fault=flag(state, 'Fault'), quarantined=flag(state, 'Quarantined'),
                       halted=flag(state, 'Halted'), exit_pending=flag(state, 'ExitPending'))
            lease = lease_by_key.get(key)
            if lease and all(type(v) in (int, float) and math.isfinite(v) for v in lease):
                expires, touched = lease
                try:
                    row['lease_expires_at'] = datetime.fromtimestamp(expires, timezone.utc).isoformat()
                    row['lease_touched_at'] = datetime.fromtimestamp(touched, timezone.utc).isoformat()
                    row['lease_active'] = expires > now.timestamp() and -5 <= now.timestamp() - touched <= 90
                except (ValueError, OverflowError, OSError):
                    pass
        output.append(row)
    return output


def snapshot(root=ROOT):
    now = datetime.now(timezone.utc)
    output = dict(contract='RIZAN_BOOTSTRAP125_READONLY_V1', profile=PROFILE_ID,
                  profile_hash=PROFILE, account_suffix='7903', observed_at=now.isoformat(),
                  read_only=True, execution_authority=False, service_active=False,
                  bridge=dict(observed_at=None, profile_ok=False, btc_feed_status='UNKNOWN', macro_snapshot_present=None))
    try:
        service = subprocess.run(['systemctl', 'is-active', 'rizan-bootstrap125-bridge.service'],
                                 capture_output=True, text=True, timeout=8, check=False)
        output['service_active'] = service.returncode == 0 and service.stdout.strip() == 'active'
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        health = json.loads((root / 'health.json').read_text())
        status = health.get('btc')
        output['bridge'] = dict(observed_at=utc_text(health.get('observed_utc')),
                                profile_ok=health.get('profile') == PROFILE_ID,
                                btc_feed_status='READY' if status == 'ready' else 'UNAVAILABLE' if isinstance(status, str) and status.startswith('unavailable:') else 'UNKNOWN',
                                macro_snapshot_present=flag(health, 'macro_snapshot_present'))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    db = sqlite3.connect((root / 'checkpoints.sqlite').resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        states = db.execute('SELECT key,version,state FROM checkpoints').fetchall()
        leases = db.execute('SELECT key,expires_at,touched_at FROM bridge_leases').fetchall()
    finally:
        db.close()
    output['roles'] = sanitize(states, leases, now=now)
    return output


if __name__ == '__main__':
    print(json.dumps(snapshot(), allow_nan=False, separators=(',', ':')))
