"""Display-only inputs with independent source freshness; no trading authority."""
from datetime import UTC, datetime
from copy import deepcopy
import math

from .manual_reversal_map import validate
from .pre_news_expectation import MACRO_WORKER, fresh
from .pre_news_transport import CONTRACT as MACRO_CONTRACT


def hierarchy_input(payload, *, now=None):
    p = validate(payload, now=now)
    if not p['fresh']:
        raise ValueError('Candle peta zona sudah kedaluwarsa')
    rows = []
    for z in p.get('zones', []):
        if not p.get('timeframe_fresh', {}).get(z['timeframe']) or not z.get('eligible'):
            continue
        rows.append({**z, 'direction': 'LONG' if z['direction'] == 'BUY' else 'SHORT',
                     'condition': 'ACTIVE', 'lifecycle_state': z.get('lifecycle', 'ACTIVE'),
                     'lifecycle': {'touch_count': z.get('touch_count', 0)}})
    structural = [z for z in rows if z['timeframe'] in {'H1', 'H4'}]
    micro = [z for z in rows if z['timeframe'] in {'M15', 'M5'}]
    micro.sort(key=lambda z: (z.get('distance', float('inf')), z['timeframe'] != 'M15'))
    out = {'price_now': p['price'], 'active_zones': structural,
           'decision_zone': micro[0] if micro else {},
           'execution_authority': False, 'execution_influence': False,
           'source': p.get('source'), 'price_observed_at': p['price_observed_at']}
    # Never substitute the latest M1 price for a completed M15 close.
    bar = p.get('latest_closed_m15') or {}
    at = bar.get('closed_at')
    value = bar.get('close')
    if (p.get('timeframe_fresh', {}).get('M15') and fresh(at, now or datetime.now(UTC), 25*60)
            and value is not None and math.isfinite(float(value)) and float(value) > 0):
        out['latest_m15_close'] = float(value)
    return out


def macro_input(payload, *, now=None):
    now = now or datetime.now(UTC)
    if (payload.get('contract') != MACRO_CONTRACT or
            payload.get('execution_authority') is not False or
            payload.get('execution_influence') is not False):
        raise ValueError('Kontrak feed makro tidak valid')
    if not fresh(payload.get('published_at'), now, 900):
        raise ValueError('Publikasi makro sudah kedaluwarsa')
    rows = [x for x in payload.get('heartbeats', []) if x.get('worker_name') == MACRO_WORKER]
    rows.sort(key=lambda x: str(x.get('observed_at') or ''), reverse=True)
    if not rows or rows[0].get('healthy') is not True or not fresh(rows[0].get('observed_at'), now, 900):
        raise ValueError('Pembaruan sumber makro belum sehat atau kedaluwarsa')
    evaluation = deepcopy((rows[0].get('details') or {}).get('evaluation') or {})
    if not evaluation:
        raise ValueError('Data makro belum tersedia')
    intraday = evaluation.get('intraday_yield_context') or {}
    # Publisher and upstream cached age_seconds are not the quote timestamp.
    if intraday and not fresh(intraday.get('current_at'), now, 900):
        evaluation['last_cash_yield'] = deepcopy(intraday)
        evaluation['intraday_yield_context'] = {
            'available': False, 'state': 'STALE_CASH_QUOTE',
            'gold_implication': 'UNAVAILABLE', 'source': intraday.get('source'),
            'current_at': intraday.get('current_at'),
        }
    return {'evaluation': evaluation, 'observed_at': rows[0]['observed_at'],
            'published_at': payload['published_at']}
