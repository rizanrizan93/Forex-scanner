"""Read-only bridge diagnostics: identifiers only, no credentials or state bodies."""
import json
from pathlib import Path
import re
import shlex
import sqlite3
import time
from datetime import datetime, timezone
from deploy_bridge import ROOT, UNIT, MODEL_HASH, MODELS, command, prop, parse_env
# Read-only audit covers current LIVE cBot contracts and legacy rows.
STREAMS = {
    'RZXRC1': ('XAUUSD', '44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c', {'XAU_BATCH_SEND_REF_COOLDOWN_V1'}),
    'RZEF245': ('EURUSD', 'd39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a', {'EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1'}),
    'RZXA1': ('XAUUSD', MODEL_HASH, MODELS),
    'RZEU4B': ('EURUSD', '4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976',
               {'EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1'}),
}
CURRENT_PREFIXES = {'RZXRC1', 'RZEF245'}


def safe_identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Z0-9_]{1,100}', value) else 'ABSENT_OR_UNRECOGNIZED'


def time_fields(value, path=''):
    result = []
    if isinstance(value, dict):
        for name, item in value.items():
            child = path + '.' + name if path else name
            if name.lower().endswith('utc') or name == 'XauDay':
                if isinstance(item, str):
                    try:
                        aware = datetime.fromisoformat(item.replace('Z', '+00:00')).utcoffset() is not None
                    except ValueError:
                        aware = False
                    if not aware and re.fullmatch(r'[A-Za-z0-9_.\[\]]{1,150}', child):
                        result.append(child)
            else:
                result.extend(time_fields(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(time_fields(item, path + '[' + str(index) + ']'))
    return result


def run():
    environment = {}
    for setting in shlex.split(prop('Environment')):
        key, sep, value = setting.partition('=')
        if sep:
            environment[key] = value
    for path in re.findall(r'(\S+) \(ignore_errors=(?:yes|no)\)', prop('EnvironmentFiles')):
        environment.update(parse_env(Path(path).read_text()))
    active = command(['systemctl', 'is-active', '--quiet', UNIT], check=False).returncode == 0
    print('BRIDGE_AUDIT_SERVICE_ACTIVE=' + str(active), flush=True)
    database = Path(environment.get('RIZAN_STATE_DB', 'state/rizan-checkpoints.sqlite'))
    if not database.is_absolute():
        database = ROOT / database
    db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    for key, version, raw in db.execute('SELECT key,version,state FROM checkpoints'):
        prefix = key.split(':')[0]
        if prefix not in STREAMS:
            continue
        symbol, expected_hash, models = STREAMS[prefix]
        state = json.loads(raw)
        account = key.split(':')[1]
        model = state.get('ExecutionModel')
        result = {'symbol': symbol, 'contract_prefix': prefix, 'current_contract': prefix in CURRENT_PREFIXES, 'account_suffix': account[-4:], 'server_revision': version,
                  'state_revision': state.get('Revision'), 'schema': state.get('Schema'),
                  'hash_match': state.get('ContractHash') == expected_hash,
                  'model': safe_identifier(model), 'verified_repair_model': model in models,
                  'quarantined': state.get('Quarantined'),
                  'quarantine_reason': safe_identifier(state.get('QuarantineReason')),
                  'invalid_time_fields': time_fields(state)}
        print('BRIDGE_AUDIT_CHECKPOINT=' + json.dumps(result), flush=True)
        eur = state.get('Eur') or {}
        h1 = eur.get('H1') or []
        last_h1 = h1[-1] if h1 else {}
        basket = state.get('Basket') or {}
        reading = {'symbol':symbol, 'account_suffix':account[-4:],
                   **{name:state.get(name) for name in
                      ('LastBarUtc','LastSignalUtc','LastRealExitUtc','XauResumeUtc','PeakEquity','PendingChildren','PendingFirstFill')},
                   'pending_label_present':bool(state.get('PendingLabel')), 'basket_present':bool(basket),
                   'basket_side':basket.get('Side'), 'virtual_present':eur.get('Virtual') is not None,
                   'h1_records':len(h1), 'latest_h1':{name:last_h1.get(name) for name in ('AtUtc','Ema','Bias')}}
        print('BRIDGE_AUDIT_READING=' + json.dumps(reading), flush=True)
    for key, expires, touched in db.execute('SELECT key,expires_at,touched_at FROM bridge_leases'):
        prefix = key.split(':')[0]
        if prefix in STREAMS:
            print('BRIDGE_AUDIT_LEASE=' + json.dumps({'symbol': STREAMS[prefix][0], 'contract_prefix': prefix, 'current_contract': prefix in CURRENT_PREFIXES,
                                                     'account_suffix': key.split(':')[1][-4:],
                                                     'remaining_seconds': round(expires - time.time(), 1),
                                                     'last_touch_age_seconds': round(time.time() - touched, 1)}), flush=True)
    db.close()
    health = Path(environment.get('RIZAN_HEALTH_PATH', 'state/cbot_bridge_health.json'))
    if not health.is_absolute():
        health = ROOT / health
    if health.is_file():
        status = json.loads(health.read_text())
        for symbol in ('XAUUSD', 'EURUSD'):
            stream = status.get('streams', {}).get(symbol, {})
            observed = status.get('observed_at_unix')
            age_seconds = round(time.time() - observed, 1) if isinstance(observed, (int, float)) else None
            print('BRIDGE_AUDIT_HEALTH=' + json.dumps({'symbol': symbol,
                  'health_age_seconds': age_seconds,
                  **{name: stream.get(name) for name in
                  ('connected', 'checkpoint_count', 'checkpoint_version_max', 'macro_event_ready')}}), flush=True)
    snapshot = Path(environment.get('RIZAN_SNAPSHOT_PATH', 'state/xau_macro_event_snapshot.json'))
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    if snapshot.is_file():
        value = json.loads(snapshot.read_text())
        now = datetime.now(timezone.utc)
        upcoming = []
        for item in value.get('Events', []):
            try:
                at = datetime.fromisoformat(item['AtUtc'].replace('Z', '+00:00'))
                if at.utcoffset() is not None and at >= now:
                    upcoming.append({'AtUtc':item['AtUtc'], 'Category':safe_identifier(item.get('Category'))})
            except (ValueError, KeyError, TypeError):
                continue
        upcoming.sort(key=lambda item:item['AtUtc'])
        result = {name:value.get(name) for name in ('ProducedUtc','CoverageFromUtc','CoverageToUtc','ForexFactoryOk','BlsOk')}
        result['macro'] = {name:{field:(value.get(name) or {}).get(field) for field in ('Delta','AvailableUtc')}
                           for name in ('Dgs10','Dfii10')}
        result['event_count'] = len(value.get('Events', []))
        result['upcoming_events'] = upcoming[:6]
        result['source_error_count'] = len(value.get('Errors', []))
        print('BRIDGE_AUDIT_XAU_SNAPSHOT=' + json.dumps(result), flush=True)
    btc = command(['systemctl', 'is-active', 'rizan-btc7d130.service'], check=False)
    print('BRIDGE_AUDIT_BTC_SERVICE=' + json.dumps({
        'active': btc.returncode == 0 and btc.stdout.strip() == 'active',
        'service': 'rizan-btc7d130.service'}), flush=True)
    # Independent BTC10 and isolated-bridge diagnostics: read-only, no service mutation.
    for unit_name in ('rizan-btc10-bridge.service', 'rizan-btc7d130.service',
                      'rizan-disp1506-bridge.service'):
        response = command(['systemctl', 'is-active', unit_name], check=False)
        print('BRIDGE_AUDIT_SERVICE=' + json.dumps({
            'unit': unit_name, 'status': response.stdout.strip()[:40],
            'active': response.returncode == 0}), flush=True)
    btc_root = Path('/var/lib/rizan-btc10-bridge')
    health_file = btc_root / 'health.json'
    try:
        if health_file.is_file():
            value = json.loads(health_file.read_text())
            observed = value.get('observed_utc')
            try:
                at = datetime.fromisoformat(str(observed).replace('Z', '+00:00'))
                age = round((datetime.now(timezone.utc) - at).total_seconds(), 1) if at.utcoffset() is not None else None
            except (TypeError, ValueError):
                age = None
            print('BRIDGE_AUDIT_BTC10_HEALTH=' + json.dumps({
                'age_seconds': age, 'profile': safe_identifier(value.get('profile')),
                'btc': safe_identifier(value.get('btc')),
                'connected': value.get('connected') if isinstance(value.get('connected'), int) else None,
                'execution_authority': safe_identifier(value.get('execution_authority')),
                'macro_snapshot_present': value.get('macro_snapshot_present')
            }), flush=True)
        else:
            print('BRIDGE_AUDIT_BTC10_HEALTH=ABSENT', flush=True)
    except (OSError, ValueError, TypeError) as exc:
        print('BRIDGE_AUDIT_BTC10_HEALTH_READ_ERROR=' + type(exc).__name__, flush=True)
    btc_db = btc_root / 'checkpoints.sqlite'
    try:
        btc_con = sqlite3.connect(btc_db.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        btc_con.execute('PRAGMA query_only=ON')
        try:
            for key, version, raw in btc_con.execute('SELECT key,version,state FROM checkpoints'):
                state = json.loads(raw)
                account = str(state.get('AccountNumber', ''))
                symbol = state.get('Symbol')
                if not account.endswith('7903') or symbol not in ('XAUUSD', 'EURUSD', 'BTCUSD'):
                    continue
                summary = {'symbol': symbol, 'account_suffix': account[-4:],
                           'server_version': version, 'client_revision': state.get('Revision')}
                for field in ('LastBarUtc', 'LastSignalUtc', 'WeekendLockUntil',
                              'Quarantined', 'Fault', 'Sending', 'ExitPending'):
                    value = state.get(field)
                    if isinstance(value, (str, int, float, bool)) or value is None:
                        summary[field] = value[:48] if isinstance(value, str) else value
                summary['pending_intent'] = bool(state.get('NativePendingLabel') or state.get('PendingLabel'))
                print('BRIDGE_AUDIT_BTC10_STATUS=' + json.dumps(summary), flush=True)
            for key, expires, touched in btc_con.execute('SELECT key,expires_at,touched_at FROM bridge_leases'):
                if not re.search(r'7903:(?:XAUUSD|EURUSD|BTCUSD)
                symbol = key.split(':')[-1]
                if symbol not in ('XAUUSD', 'EURUSD', 'BTCUSD'):
                    continue
                print('BRIDGE_AUDIT_BTC10_LEASE=' + json.dumps({
                    'symbol': symbol, 'account_suffix': '7903',
                    'remaining_seconds': round(expires - time.time(), 1),
                    'last_touch_age_seconds': round(time.time() - touched, 1)
                }), flush=True)
        finally:
            btc_con.close()
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        print('BRIDGE_AUDIT_BTC10_DB_READ_ERROR=' + type(exc).__name__, flush=True)
, key):
                    continue
                symbol = key.split(':')[-1]
                if symbol not in ('XAUUSD', 'EURUSD', 'BTCUSD'):
                    continue
                print('BRIDGE_AUDIT_BTC10_LEASE=' + json.dumps({
                    'symbol': symbol, 'account_suffix': '7903',
                    'remaining_seconds': round(expires - time.time(), 1),
                    'last_touch_age_seconds': round(time.time() - touched, 1)
                }), flush=True)
        finally:
            btc_con.close()
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        print('BRIDGE_AUDIT_BTC10_DB_READ_ERROR=' + type(exc).__name__, flush=True)
    print('BRIDGE_AUDIT_READ_ONLY_COMPLETE', flush=True)


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('BRIDGE_AUDIT_FAILED:' + type(exc).__name__, flush=True)
        raise SystemExit(1)
