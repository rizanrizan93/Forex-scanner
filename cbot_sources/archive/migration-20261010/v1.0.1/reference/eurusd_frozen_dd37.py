"""Frozen EURUSD liquidity-sweep research contract; no parameter optimization."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import floor, isfinite
import pandas as pd

SYMBOL = "EURUSD"
STRATEGY_ID = "EURUSD_SWEEP_COMPOUND_DD37_FROZEN_V1"

@dataclass(frozen=True)
class FrozenPolicy:
    risk: float = .2725
    margin: float = .60
    cap_at_100: int = 195
    cap_exponent: float = .0625
    fast_span: int = 2
    fast_threshold: float = -.5
    fast_weak: float = .1
    slow_span: int = 8
    slow_threshold: float = -.05
    slow_weak: float = .625
    lookback: int = 8
    atr_period: int = 14
    atr_multiplier: float = 3
    stop_min: float = .0005
    stop_max: float = .006
    target_r: float = 4
    hold_minutes: int = 240
    virtual_spread: float = .00012
    virtual_slip: float = .00001
    child_lot: float = .01
    child_units: int = 1000
    reference_leverage: int = 100

POLICY = FrozenPolicy()
POLICY_HASH = sha256(json.dumps(asdict(POLICY), sort_keys=True).encode()).hexdigest()

def multiplier(fast, slow):
    return min(POLICY.fast_weak if fast < POLICY.fast_threshold else 1.,
               POLICY.slow_weak if slow < POLICY.slow_threshold else 1.)

def layers(equity, entry, distance, fast, slow, *, margin_per_child=None, free_margin=None):
    if not all(isfinite(v) and v > 0 for v in (equity, entry, distance)):
        return 0
    scale = multiplier(fast, slow)
    margin_cost = entry * 10 if margin_per_child is None else margin_per_child
    if not isfinite(margin_cost) or margin_cost <= 0:
        return 0
    margin_budget = equity * POLICY.margin * scale
    if free_margin is not None:
        margin_budget = min(margin_budget, max(0, free_margin))
    return max(0, floor(min(POLICY.cap_at_100 * (equity / 100)**POLICY.cap_exponent,
        equity * POLICY.risk * scale / (1000 * (distance + POLICY.virtual_slip)),
        margin_budget / margin_cost) + 1e-9))

def frame_from_bars(bars, now):
    rows = [dict(timestamp=b.timestamp, open=b.open, high=b.high, low=b.low, close=b.close)
            for b in bars if b.timestamp + pd.Timedelta(minutes=1) <= now]
    if not rows:
        raise ValueError("NO_COMPLETED_M1")
    return pd.DataFrame(rows).drop_duplicates('timestamp').set_index('timestamp').sort_index()

def features(raw, state):
    """Closed M15/H1 only. H1 EMA state survives restarts and rolling fetch windows."""
    d = raw.resample('15min', closed='left', label='right').agg(
        {'open':'first','high':'max','low':'min','close':'last'}).dropna()
    d['count'] = raw.close.resample('15min', closed='left', label='right').count()
    prev = d.close.shift(1)
    tr = pd.concat([d.high-d.low, (d.high-prev).abs(), (d.low-prev).abs()], axis=1).max(axis=1)
    d['atr'] = tr.rolling(14).mean()
    d['body'] = (d.close-d.open)/(d.high-d.low).replace(0, float('nan'))
    d['prior_high'] = d.high.shift(1).rolling(8).max()
    d['prior_low'] = d.low.shift(1).rolling(8).min()
    h = raw.close.resample('1h', closed='left', label='right').last().dropna()
    # Partial final H1/M15 buckets cannot be used as closed features.
    available = raw.index[-1] + pd.Timedelta(minutes=1)
    h = h[h.index <= available]
    d = d[d.index <= available]
    records = list(state.get('h1_records', []))
    last = pd.Timestamp(records[-1]['at']) if records else None
    for at, close in h.items():
        if last is not None and at <= last:
            continue
        ema = float(close) if not records else (2/51)*float(close)+(49/51)*records[-1]['ema']
        slope = ema-records[-3]['ema'] if len(records)>=3 else 0.
        bias = 1 if close > ema and slope > 0 else (-1 if close < ema and slope < 0 else 0)
        records.append({'at':at.isoformat(), 'ema':ema, 'bias':bias})
    state['h1_records'] = records[-512:]
    hb = pd.Series({pd.Timestamp(x['at']):x['bias'] for x in records}).sort_index()
    d['bias'] = hb.reindex(d.index, method='ffill') if len(hb) else float('nan')
    return d

def signal(at, row):
    if not (7 <= at.hour < 12) or row['count'] < 12 or row['bias'] != 0:
        return None
    if not isfinite(row['atr']) or row['atr'] <= 0:
        return None
    side = 1 if row.low < row.prior_low and row.close > row.prior_low and row.body > .2 else (
        -1 if row.high > row.prior_high and row.close < row.prior_high and row.body < -.2 else 0)
    if not side:
        return None
    return {'at':at.isoformat(), 'side':side,
            'distance':max(.0005,min(.006,3*float(row.atr)))}

def virtual_step(pending, at, bar):
    """Return netR, exit timestamp, or None; conservative STOP_FIRST + gap handling."""
    s, entry, r = pending['side'], pending['entry'], pending['distance']
    previous = pd.Timestamp(pending['last_at'])
    opened = pd.Timestamp(pending['at'])
    offset = POLICY.virtual_spread if s == -1 else 0
    exit_px = None
    exit_at = at
    if at > previous and (at-previous).total_seconds() > 300:
        exit_px = bar.open + offset - s*POLICY.virtual_slip
    elif at >= opened+pd.Timedelta(minutes=240) or at.hour>=20 or at.date()!=opened.date():
        exit_px = pending['last_close'] + offset - s*POLICY.virtual_slip
        exit_at = previous
    else:
        op, hi, lo = bar.open+offset, bar.high+offset, bar.low+offset
        stop, target = entry-s*r, entry+s*r*4
        hit_stop = lo<=stop if s==1 else hi>=stop
        hit_target = hi>=target if s==1 else lo<=target
        if hit_stop:
            exit_px = (min(stop,op) if s==1 else max(stop,op))-s*POLICY.virtual_slip
        elif hit_target:
            exit_px = target-s*POLICY.virtual_slip
    pending['last_at'], pending['last_close'] = at.isoformat(), float(bar.close)
    if exit_px is None:
        return None
    return s*(exit_px-entry)/r, exit_at.isoformat()

def advance_virtual(raw, feature_frame, state):
    cursor = pd.Timestamp(state['cursor'])
    pending = state.get('virtual')
    last_exit = pd.Timestamp(state['virtual_exit']) if state.get('virtual_exit') else None
    for at, bar in raw[raw.index>cursor].iterrows():
        # An exit on this M1 bar cannot inform a signal at this same minute's open.
        candidate = signal(at, feature_frame.loc[at]) if at in feature_frame.index else None
        if pending is None and candidate and (last_exit is None or at>last_exit):
            pending = {**candidate, 'entry':float(bar.open)+(POLICY.virtual_spread if candidate['side']==1 else 0)
                +candidate['side']*POLICY.virtual_slip, 'last_at':at.isoformat(), 'last_close':float(bar.open)}
        if pending:
            result = virtual_step(pending, at, bar)
            if result:
                net_r, exited = result
                state['fast'] = (2/3)*net_r+(1/3)*state.get('fast',0.)
                state['slow'] = (2/9)*net_r+(7/9)*state.get('slow',0.)
                state['virtual_exit'] = exited
                last_exit, pending = pd.Timestamp(exited), None
        state['cursor'] = at.isoformat()
    state['virtual'] = pending
