"""Selected frozen RAW references plus the supervised scanner deployment overlay.

This module has no broker transport. It exposes the frozen research contracts and
applies the current scanner basket-risk ceiling without rewriting historical
replay evidence.
"""
from hashlib import sha256
import json
import math
from pathlib import Path

SELECTED = {
    'XAUUSD': ('xauusd_raw_selected_v1.json', '7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf'),
    'EURUSD': ('eurusd_raw_selected_v3.json', '4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976'),
}
EXECUTION_SCOPE = 'MANUAL_REFERENCE_ONLY'
DEPLOYMENT_PROFILE_ID = 'XAU_EUR_SUPERVISED_RISK_12_5_V1'
DEPLOYMENT_PATH = Path(__file__).resolve().parents[2] / 'config/frozen/xau_eur_supervised_12_5_v1.json'


def deployment_profile(path=DEPLOYMENT_PATH):
    value = json.loads(Path(path).read_text())
    if value.get('profile_id') != DEPLOYMENT_PROFILE_ID:
        raise RuntimeError('SELECTED_RAW_DEPLOYMENT_PROFILE_MISMATCH')
    if value.get('status') != 'ACTIVE_SCANNER_SUPERVISED':
        raise RuntimeError('SELECTED_RAW_DEPLOYMENT_NOT_ACTIVE')
    if value.get('execution_mode') != 'LIVE_MANUAL_APPROVAL_ONLY' or value.get('unattended_live_execution') is not False:
        raise RuntimeError('SELECTED_RAW_DEPLOYMENT_SCOPE_INVALID')
    if not math.isclose(float(value.get('basket_risk_ceiling', 0)), .125):
        raise RuntimeError('SELECTED_RAW_DEPLOYMENT_RISK_INVALID')
    if not math.isclose(float(value.get('per_ticket_live_risk_ceiling', 0)), .01):
        raise RuntimeError('SELECTED_RAW_PER_TICKET_RISK_INVALID')
    for symbol, (_, expected_hash) in SELECTED.items():
        row = value.get('symbols', {}).get(symbol, {})
        if row.get('source_contract_sha256') != expected_hash:
            raise RuntimeError('SELECTED_RAW_DEPLOYMENT_SOURCE_HASH_MISMATCH')
        if not math.isclose(float(row.get('risk_ceiling', 0)), .125):
            raise RuntimeError('SELECTED_RAW_SYMBOL_RISK_INVALID')
        if float(row.get('margin_ceiling', 1)) > .5:
            raise RuntimeError('SELECTED_RAW_SYMBOL_MARGIN_INVALID')
    return value


def manifest(symbol, path=None):
    name, expected = SELECTED[symbol]
    path = path or Path(__file__).resolve().parents[2] / 'config/frozen' / name
    value = json.loads(Path(path).read_text())
    contract = value['contract']
    digest = sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != expected or value['contract_sha256'] != digest or contract['symbol'] != symbol:
        raise RuntimeError('SELECTED_RAW_CONTRACT_HASH_MISMATCH')
    return value


def reference(symbol):
    frozen = manifest(symbol)
    deployment = deployment_profile()
    deployed = deployment['symbols'][symbol]
    c = frozen['contract']
    if symbol == 'XAUUSD':
        p = dict(zip(c['policy_vector_columns'], c['policy_vector']))
        lev = int(c['leverage_policy']['reference'])
        base = frozen['evidence']['raw_metrics_by_leverage']['raw_base'][str(lev)]
        stresses = {k: v[str(lev)] for k, v in frozen['evidence']['raw_metrics_by_leverage'].items()}
        child_lot = c['layering']['child_lot']
    else:
        p = dict(c['policy'])
        lev = c['reference_leverage']
        stresses = frozen['evidence']['base_and_stress_metrics']
        base = stresses['base']
        child_lot = c['sizing']['child_lot']
    source_risk_ceiling = float(p['risk_ceiling'])
    p['risk_ceiling'] = float(deployed['risk_ceiling'])
    p['margin_ceiling'] = min(float(p['margin_ceiling']), float(deployed['margin_ceiling']))
    return {'symbol': symbol, 'strategy_id': c['strategy_id'], 'hash': frozen['contract_sha256'],
            'scope': EXECUTION_SCOPE, 'deployment_scope': deployment['execution_mode'],
            'account_type': 'RAW', 'leverage': lev, 'layering': c['layering'],
            'policy': p, 'source_policy_risk_ceiling': source_risk_ceiling,
            'child_lot': child_lot, 'metrics': base, 'stress': stresses,
            'deployment': deployment, 'deployment_symbol': deployed,
            'per_ticket_live_risk_ceiling': float(deployment['per_ticket_live_risk_ceiling']),
            'frozen': frozen}


def geometry(symbol, entry, stop, target):
    """Depth trigger levels from user-entered geometry, never a submitted order."""
    values = (entry, stop, target)
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Entry, SL dan TP harus berupa harga positif.')
    side = 1 if stop < entry < target else -1 if target < entry < stop else 0
    if not side:
        raise ValueError('BUY: SL < entry < TP. SELL: TP < entry < SL.')
    cfg = reference(symbol)['layering']
    return [{'stage': i, 'depth_r': depth, 'trigger': entry - side * depth * abs(entry-stop),
             'sl': stop, 'tp': target, 'requires_confirmation': bool(i and cfg['confirmed'])}
            for i, depth in enumerate(cfg['depths_r'])]
