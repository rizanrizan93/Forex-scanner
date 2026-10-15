"""DXY proxy from broker candles; synthetic fallback uses the complete ICE basket.

Formula: https://www.ice.com/publicdocs/futures_us/ICE_Dollar_Index_FAQ.pdf
Broker close prices differ from ICE's multi-contributor mid quotes. Neither the
CFD nor reconstructed index is presented as a licensed official ICE index feed.
"""
from __future__ import annotations

from datetime import timedelta
from math import isfinite, prod
from .pre_news_expectation import fresh, number, timestamp
from .xau_intraday_macro_v398 import evaluate_dxy_pressure

WEIGHTS = {'EURUSD': -.576, 'USDJPY': .136, 'GBPUSD': -.119,
           'USDCAD': .091, 'USDSEK': .042, 'USDCHF': .036}
DIRECT_NAMES = frozenset({'DXY', 'USDX', 'USDINDEX', 'DOLLARINDEX'})


def normalize_symbol(value):
    return ''.join(c for c in str(value).upper() if c.isalnum())


def _points(rows, *, now):
    points = {}
    for row in rows:
        at = timestamp(row.get('observed_at'))
        value = number(row.get('value'))
        if at is not None and at <= now and value is not None and value > 0:
            points[at] = value
    return points


def synthetic_points(basket, *, now):
    if set(basket) != set(WEIGHTS):
        return []
    series = {key: _points(basket[key], now=now) for key in WEIGHTS}
    common = set.intersection(*(set(rows) for rows in series.values()))
    result = []
    for at in sorted(common):
        value = 50.14348112 * prod(series[key][at] ** weight for key, weight in WEIGHTS.items())
        if isfinite(value) and value > 0:
            result.append({'observed_at': at, 'value': value})
    return result


def evaluate_broker_dxy(*, now, direct=None, basket=None, symbol=None):
    points = []
    source = 'CTRADER_DXY_CFD_PROXY'
    basis = 'BROKER_CFD_M5_CLOSE_NOT_OFFICIAL_ICE'
    if symbol and normalize_symbol(symbol) in DIRECT_NAMES:
        points = [{'observed_at': at, 'value': value} for at, value in sorted(_points(direct or [], now=now).items())]
    if len(points) < 2 or not fresh(points[-1]['observed_at'], now, 900):
        points = synthetic_points(basket or {}, now=now)
        source = 'CTRADER_SYNTHETIC_USDX_6FX'
        basis = 'COMPLETE_6_CURRENCY_BASKET_SYNCHRONIZED_BROKER_M5_CLOSES_NOT_OFFICIAL_ICE'
    # Two distinct synchronized observations, covering a meaningful pressure window.
    window = [p for p in points if p['observed_at'] >= now-timedelta(minutes=125)]
    if len(window) < 2 or (window[-1]['observed_at']-window[0]['observed_at']).total_seconds() < 1800:
        return {'available': False, 'freshness': 'MISSING', 'state': 'DXY_BROKER_INSUFFICIENT_COVERAGE',
                'source': source, 'basis': basis, 'execution_authority': False, 'execution_influence': False}
    result = evaluate_dxy_pressure(window, now=now, max_age_seconds=900, window_minutes=120)
    result.update(source=source, basis=basis, source_status='OK' if result['available'] else 'STALE_OR_MISSING',
                  symbol=symbol if source == 'CTRADER_DXY_CFD_PROXY' else 'SYNTHETIC_USDX_6FX',
                  frequency='M5_CLOSED_BARS', component_count=6 if '6FX' in source else 1)
    result['current_at'] = str(result['current_at'])
    return result


def select_dxy(primary, broker, *, now):
    """Keep a usable primary; otherwise accept only recent allowlisted broker evidence."""
    if primary.get('available') and primary.get('freshness') == 'FRESH' and fresh(primary.get('current_at'), now, 1200):
        return dict(primary)
    allowed = {'CTRADER_DXY_CFD_PROXY', 'CTRADER_SYNTHETIC_USDX_6FX'}
    if (broker.get('source') in allowed and broker.get('available') is True
        and broker.get('freshness') == 'FRESH' and fresh(broker.get('current_at'), now, 900)
        and number(broker.get('net_pct')) is not None
        and broker.get('execution_authority') is False and broker.get('execution_influence') is False):
        return dict(broker)
    return dict(primary)
