"""Read-only bridge diagnostics: identifiers only, no credentials or state bodies."""
import json
from pathlib import Path
import re
import shlex
import sqlite3
import time
from datetime import datetime, timezone
from deploy_bridge import ROOT, UNIT, MODEL_HASH, MODELS, command, prop, parse_env
STREAMS = {'RZXA1': ('XAUUSD', MODEL_HASH, MODELS),
           'RZEU4B': ('EURUSD', '4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976',
                      {'EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1'})}


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
        result = {'symbol': symbol, 'account_suffix': account[-4:], 'server_revision': version,
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
    for key, expires in db.execute('SELECT key,expires_at FROM bridge_leases'):
        prefix = key.split(':')[0]
        if prefix in STREAMS:
            print('BRIDGE_AUDIT_LEASE=' + json.dumps({'symbol': STREAMS[prefix][0], 'account_suffix': key.split(':')[1][-4:],
                                                     'remaining_seconds': round(expires - time.time(), 1)}), flush=True)
    db.close()
    health = Path(environment.get('RIZAN_HEALTH_PATH', 'state/cbot_bridge_health.json'))
    if not health.is_absolute():
        health = ROOT / health
    if health.is_file():
        status = json.loads(health.read_text())
        for symbol in ('XAUUSD', 'EURUSD'):
            stream = status.get('streams', {}).get(symbol, {})
            print('BRIDGE_AUDIT_HEALTH=' + json.dumps({'symbol':symbol, **{name: stream.get(name) for name in
                  ('connected', 'macro_event_ready', 'checkpoint_revision', 'last_checkpoint_at_unix')}}), flush=True)
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
    print('BRIDGE_AUDIT_READ_ONLY_COMPLETE', flush=True)


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('BRIDGE_AUDIT_FAILED:' + type(exc).__name__, flush=True)
        raise SystemExit(1)
