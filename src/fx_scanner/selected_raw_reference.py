"""Selected frozen RAW references for manual decisions; no broker operations."""
from hashlib import sha256
import json
import math
from pathlib import Path

SELECTED = {
    'XAUUSD': ('xauusd_raw_selected_v1.json', '7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf'),
    'EURUSD': ('eurusd_raw_selected_v3.json', '4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976'),
}
EXECUTION_SCOPE = 'MANUAL_REFERENCE_ONLY'


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
    c = frozen['contract']
    if symbol == 'XAUUSD':
        p = dict(zip(c['policy_vector_columns'], c['policy_vector']))
        lev = int(c['leverage_policy']['reference'])
        base = frozen['evidence']['raw_metrics_by_leverage']['raw_base'][str(lev)]
        stresses = {k: v[str(lev)] for k, v in frozen['evidence']['raw_metrics_by_leverage'].items()}
        child_lot = c['layering']['child_lot']
    else:
        p = c['policy']
        lev = c['reference_leverage']
        stresses = frozen['evidence']['base_and_stress_metrics']
        base = stresses['base']
        child_lot = c['sizing']['child_lot']
    return {'symbol': symbol, 'strategy_id': c['strategy_id'], 'hash': frozen['contract_sha256'],
            'scope': EXECUTION_SCOPE, 'account_type': 'RAW', 'leverage': lev,
            'layering': c['layering'], 'policy': p, 'child_lot': child_lot,
            'metrics': base, 'stress': stresses, 'frozen': frozen}


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
