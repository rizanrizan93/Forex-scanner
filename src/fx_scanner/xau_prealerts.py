"""Research pre-touch plans. No account, broker, order or bridge operations."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import pandas as pd
from .manual_reversal_map import frame, timestamp

CONTRACT = 'RIZAN_XAU_PREALERT_1'
QUOTE_MAX_AGE = 90
BUY_MODEL = dict(model='FVG_M15_BUY_SL20_TP25', side='BUY', sl_distance=20.,
                 tp_distance=25., ttl_hours=4, hold_hours=240,
                 validation='EXPLORATORY_SMALL_SAMPLE', review_n=57,
                 review_tp_pct=59.649123, review_pf=1.803640, review_cost2_pf=1.671827,
                 session_utc='ALL', q1_n=19, q1_pf=1.690202)


def view(plan, *, now, feed_fresh=True):
    """Recompute expiry on every render; cached snapshots cannot revive a setup."""
    p = deepcopy(plan)
    try:
        t = timestamp(now)
        formed, published, expires = (timestamp(p[k]) for k in
                                      ('formed_at', 'first_published_at', 'expires_at'))
        if not formed <= published <= t or expires <= formed:
            raise ValueError('Invalid publication chronology')
        presented = timestamp(p.get('first_presented_at') or published)
        if not published <= presented <= t:
            raise ValueError('Invalid presentation chronology')
        buy = p['side'] == 'BUY'
        if p['side'] not in ('BUY', 'SELL'):
            raise ValueError('Invalid side')
        e, sl, tp = (float(p[k]) for k in ('entry', 'sl', 'tp'))
        if not all(math.isfinite(x) and x > 0 for x in (e, sl, tp)):
            raise ValueError('Invalid geometry')
        d = 1 if buy else -1
        if d * (e-sl) <= 0 or d * (tp-e) < 25:
            raise ValueError('Invalid stop or minimum target')
        if p.get('execution_authority') is not False or p.get('execution_influence') is not False:
            raise ValueError('Read-only guard')
        touch = timestamp(p['first_observed_touch_at']) if p.get('first_observed_touch_at') else None
        if touch is not None and (touch < formed or touch > t):
            raise ValueError('Invalid touch chronology')
        if touch is not None:
            p['state'] = 'TERLEWAT' if touch <= presented else 'TERSENTUH'
            p['entry_available'] = False
            return p
        if t >= expires:
            p.update(state='KEDALUWARSA', entry_available=False)
            return p
        observed = timestamp(p['price_observed_at'])
        if (not feed_fresh or not 0 <= (t-observed).total_seconds() <= QUOTE_MAX_AGE
                or not p.get('touch_history_complete')):
            p.update(state='DATA_BELUM_CUKUP', entry_available=False)
            return p
        p.update(state='ABA_ABA' if p.get('session_utc') == 'ALL' or 7 <= t.hour < 17 else 'MENUNGGU_SESI',
                 entry_available=False)  # a research plan is never a broker entry confirmation
        return p
    except (ValueError, TypeError, KeyError, OverflowError):
        p.update(state='DATA_TIDAK_VALID', entry_available=False)
        return p


def _indicators(b):
    b = b.copy()
    tr = pd.concat([b.high-b.low, (b.high-b.close.shift()).abs(),
                    (b.low-b.close.shift()).abs()], axis=1).max(axis=1)
    b['atr'] = tr.rolling(14).mean()
    b['ema'] = b.close.ewm(span=20, adjust=False).mean()
    b['vol'] = b.atr / b.atr.rolling(30).median()
    return b


def build(native, *, now, previous=None, data_as_of=None):
    """Publish the tested BUY research geometry before touch when feed permits.

    H4 is reconstructed from four contiguous H1 candles at UTC boundaries,
    matching the research clock rather than assuming broker H4 alignment.
    Native-feed/replay parity remains unverified and is explicitly labelled.
    """
    now = timestamp(now)
    data_as_of = timestamp(data_as_of) if data_as_of is not None else now
    result = dict(contract=CONTRACT, as_of=now.isoformat(), plans=[],
                  execution_authority=False, execution_influence=False,
                  sell_status='SELL_BELUM_LOLOS_RISET', producer_interval_seconds=60,
                  validation='NATIVE_OPERATIONAL_ADAPTATION_PARITY_NOT_VERIFIED')
    try:
        m = frame(native.get('M1', []), 'M1', data_as_of)
        h = frame(native.get('H1', []), 'H1', data_as_of)
        q = frame(native.get('M15', []), 'M15', data_as_of)
        if len(m) < 2 or len(h) < 200 or len(q) < 61:
            return result
        h = _indicators(h.set_index('timestamp'))
        four = h.resample('4h', label='left', closed='left').agg(
            open=('open','first'), high=('high','max'), low=('low','min'),
            close=('close','last'), n=('close','size'))
        present = set(h.index)
        four = four.loc[(four.n == 4) & (four.index + pd.Timedelta(hours=4) <= now)]
        four = four.loc[[all(t + pd.Timedelta(hours=i) in present for i in range(4)) for t in four.index]]
        four = _indicators(four)
        h.index = h.index + pd.Timedelta(hours=1)
        four.index = four.index + pd.Timedelta(hours=4)
        q = _indicators(q.set_index('timestamp'))
        q.index = q.index + pd.Timedelta(minutes=15)
        prior = {p['id']: p for p in (previous or {}).get('plans', [])
                 if (previous or {}).get('contract') == CONTRACT and p.get('id')}
        last_center = None
        last_stamp = None
        plans = []
        for i in range(60, len(q)):
            at = q.index[i]
            r = q.iloc[i]
            if at-q.index[i-2] != pd.Timedelta(minutes=30):
                continue
            if not math.isfinite(r.atr) or r.atr <= 0:
                continue
            if not r.low > q.high.iloc[i-2] or not q.close.iloc[i-1] > q.open.iloc[i-1]:
                continue
            lo = q.high.iloc[i-2]
            hi = r.low
            if not .015*r.atr < hi-lo <= 3*r.atr:
                continue
            center = (lo+hi)/2
            if last_stamp is not None and at-last_stamp < pd.Timedelta(hours=4) and abs(center-last_center) < .25*r.atr:
                continue
            last_center, last_stamp = center, at
            if not now-pd.Timedelta(hours=4) <= at <= now:
                continue
            hh, ff = h.loc[:at], four.loc[:at]
            if hh.empty or ff.empty:
                continue
            c1, c4 = hh.iloc[-1], ff.iloc[-1]
            if not c1.close > c1.ema or not c4.close > c4.ema or not c4.vol >= 1.2:
                continue
            # Fraction 1 is the distal FVG edge; the planned SL is fixed.
            entry = lo
            if 20 < .25*r.atr:
                continue
            key = hashlib.sha256(f"{BUY_MODEL['model']}:{at.isoformat()}".encode()).hexdigest()[:20]
            p = prior.get(key)
            if p is None:
                p = dict(BUY_MODEL, id=key, formed_at=at.isoformat(),
                         first_published_at=now.isoformat(),
                         expires_at=(at+pd.Timedelta(hours=4)).isoformat(),
                         low=float(lo), high=float(hi), entry=float(entry),
                         sl=float(entry-20), tp=float(entry+25),
                         execution_authority=False, execution_influence=False)
            else:
                p = deepcopy(p)  # published geometry and publication clock stay fixed
            window = m[m.timestamp >= at]
            touch = window[window.low <= p['entry']]
            complete = len(window) > 0 and window.timestamp.iloc[0] == at
            if len(window) > 1:
                complete = complete and window.timestamp.diff().iloc[1:].eq(pd.Timedelta(minutes=1)).all()
            p.update(first_observed_touch_at=(touch.timestamp.iloc[0].isoformat() if len(touch) else p.get('first_observed_touch_at')),
                     price_observed_at=(m.timestamp.iloc[-1]+pd.Timedelta(minutes=1)).isoformat(),
                     price_reference=float(m.close.iloc[-1]), touch_history_complete=bool(complete),
                     cost_validation='BROKER_SPREAD_REQUIRES_MANUAL_CHECK')
            plans.append(view(p, now=now))
        # Keep an already-published pending plan ahead of new replacements.
        plans.sort(key=lambda p: (p['state'] not in ('ABA_ABA','MENUNGGU_SESI'),
                                  p['id'] not in prior, abs(p['entry']-p['price_reference'])))
        result['plans'] = plans[:2]
        return result
    except (ValueError, KeyError, TypeError, IndexError, OverflowError):
        return result
