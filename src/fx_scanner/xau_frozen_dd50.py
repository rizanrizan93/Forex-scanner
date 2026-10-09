"""Frozen retrospective BUY/SELL candidate; completed-bar, DEMO-only core.

The replay's DD is evidence, never a forward loss guarantee. Runtime differences
(broker bars, actual margin, revised daily macro) remain visible and fail closed.
"""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import StringIO
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from .providers.transport import UrllibHttpTransport

SYMBOL = 'XAUUSD'
STRATEGY_ID = 'XAUUSD_BUYSELL_DD50_FROZEN_V1'
POLICY_HASH = 'cfda521b790a10322b9059bfca99065a05ebf69e6b4d77227e0a74eb7a5aa2de'
MANIFEST_PATH = Path(__file__).resolve().parents[2] / 'config/frozen/xauusd_buysell_dd50_v1.json'
EVENT_CATEGORIES = {'NFP', 'CPI', 'PPI', 'JOLTS', 'ECI', 'FOMC'}


def manifest(path=MANIFEST_PATH):
    result = json.loads(Path(path).read_text())
    digest = sha256(json.dumps(result['contract'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != POLICY_HASH or result['policy_hash'] != POLICY_HASH:
        raise RuntimeError('XAU_FROZEN_POLICY_HASH_MISMATCH')
    return result


def frame_from_bars(rows, minutes, now):
    # cTrader timestamps denote bar OPEN. Research features use completed END.
    data = [{'at': pd.Timestamp(b.timestamp) + pd.Timedelta(minutes=minutes),
             'open': float(b.open), 'high': float(b.high),
             'low': float(b.low), 'close': float(b.close)} for b in rows]
    if not data:
        raise RuntimeError('XAU_COMPLETED_BARS_MISSING')
    frame = pd.DataFrame(data).set_index('at').sort_index()
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame[~frame.index.duplicated(keep='last')].loc[lambda f: f.index <= pd.Timestamp(now)]


def strict(frame):
    c = frame.close
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    return pd.Series(np.where((c > e200) & (e50 >= e50.shift(2)), 1,
        np.where((c < e200) & (e50 <= e50.shift(2)), -1, 0)), index=frame.index)


def features(m5, h1, m15):
    if min(len(h1), len(m15)) < 200 or len(m5) < 100:
        raise RuntimeError('XAU_FEATURE_WARMUP_INCOMPLETE')
    d = m5.copy()
    prev = d.close.shift(1)
    d['atr'] = pd.concat([d.high-d.low, (d.high-prev).abs(), (d.low-prev).abs()], axis=1).max(axis=1).rolling(14).mean()
    d['local_low'] = d.low.rolling(3).min()-.1*d.atr
    d['local_high'] = d.high.rolling(3).max()+.1*d.atr
    for name, frame in [('h1strict', h1), ('m15strict', m15)]:
        d[name] = strict(frame).reindex(d.index, method='ffill').fillna(0)
    return d


def raw_signals(d):
    c, o, n = d.close, d.open, 48
    mean = c.rolling(n).mean()
    weighted = np.r_[np.full(n-1, np.nan), np.convolve(c.to_numpy(), np.arange(n)[::-1], mode='valid')]
    slope = (weighted - n*(n-1)/2*mean)/(n*(n*n-1)/12)
    fit = mean+slope*(n-1)/2
    std = c.rolling(n).std(ddof=0)
    upper, lower = (fit+1.5*std).shift(1), (fit-1.5*std).shift(1)
    buy = ((c>lower)&(c.shift(1)<=lower.shift(1))&(c>o)).to_numpy()
    buy_other = ((c<upper)&(c.shift(1)>=upper.shift(1))&(c<o)).to_numpy()
    lg, sh = np.zeros(len(d), bool), np.zeros(len(d), bool)
    anchor = np.full(len(d), np.nan)
    pl = d.low.shift(1).rolling(24).min().to_numpy()
    ph = d.high.shift(1).rolling(24).max().to_numpy()
    lc = sc = -100
    lh = sl = la = sa = 0.
    for i, (op, hi, lo, cl, atr) in enumerate(d[['open','high','low','close','atr']].to_numpy()):
        if not np.isfinite(atr):
            continue
        if 0 < i-lc <= 3 and cl > lh+.05*atr and cl > op:
            lg[i], anchor[i], lc = True, la-.1*atr, -100
        if 0 < i-sc <= 3 and cl < sl-.05*atr and cl < op:
            sh[i], anchor[i], sc = True, sa+.1*atr, -100
        if lo < pl[i] and cl > pl[i]:
            lc, lh, la = i, hi, lo
        if hi > ph[i] and cl < ph[i]:
            sc, sl, sa = i, lo, hi
    up = ((d.h1strict == 1)&(d.m15strict == 1)).to_numpy()
    down = ((d.h1strict == -1)&(d.m15strict == -1)).to_numpy()
    buy, buy_other = buy & up, buy_other & down
    lg, sh = lg & up, sh & down
    return pd.DataFrame({'buy': buy & ~buy_other, 'sell': sh & ~lg,
        'buy_anchor': d.local_low, 'sell_anchor': anchor}, index=d.index)


def macro_observation(frame, series, at):
    values = pd.to_numeric(frame[series], errors='coerce').dropna()
    dates = pd.to_datetime(frame.loc[values.index, 'DATE']).dt.normalize()
    days = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    available = pd.DatetimeIndex([x+2*days for x in dates]).tz_localize('America/New_York').tz_convert('UTC')
    observations = pd.DataFrame({'delta': values.diff().to_numpy(), 'available': available})
    known = observations[observations.available <= pd.Timestamp(at)]
    if known.empty:
        raise RuntimeError('XAU_MACRO_NOT_YET_AVAILABLE')
    row = known.iloc[-1]
    if not np.isfinite(row.delta) or pd.Timestamp(at)-row.available > pd.Timedelta(days=7):
        raise RuntimeError('XAU_MACRO_STALE_OR_MISSING')
    return {'delta': float(row.delta), 'available_at': row.available.isoformat(), 'series': series}


def fetch_macro(now, cache_path=Path('/tmp/rizan_xau_dd50_macro.json')):
    cache = {}
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        pass
    fresh = cache.get('fetched_at') and timedelta(0) <= now-datetime.fromisoformat(cache['fetched_at']) <= timedelta(hours=1)
    if not fresh:
        transport = UrllibHttpTransport(timeout_seconds=8)
        tables = {}
        for series in ('DGS10','DFII10'):
            response = transport.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id='+series+'&cosd='+(now-timedelta(days=60)).date().isoformat(), allowed_host='fred.stlouisfed.org')
            text = response.body.decode()
            tables[series] = text
        cache = {'fetched_at': now.isoformat(), 'tables': tables}
        cache_path.write_text(json.dumps(cache))
    result = {}
    for series, text in cache['tables'].items():
        frame = pd.read_csv(StringIO(text)).rename(columns={'observation_date':'DATE'})
        result[series] = macro_observation(frame, series, now)
    return result


def blocked_event(events, at):
    lo, hi = pd.Timestamp(at)-pd.Timedelta(minutes=30), pd.Timestamp(at)+pd.Timedelta(minutes=495)
    return next((e for e in events if e.category in EVENT_CATEGORIES and lo <= pd.Timestamp(e.scheduled_at) <= hi), None)


def evaluate_core(*, bars_m5, bars_h1, bars_m15, now, events, source_status, macro=None):
    manifest()
    result = {'strategy_id':STRATEGY_ID, 'policy_hash':POLICY_HASH, 'state':'WAIT',
        'reason':'NO_FRESH_SIGNAL', 'execution_scope':'DEMO_ONLY', 'live_execution_enabled':False,
        'candidate':None, 'bar_source':'CTRADER_COMPLETED_NATIVE_BARS'}
    try:
        m5 = frame_from_bars(bars_m5,5,now)
        d = features(m5,frame_from_bars(bars_h1,60,now),frame_from_bars(bars_m15,15,now))
        at = d.index[-1]
        result['last_completed_m5'] = at.isoformat()
        age = (pd.Timestamp(now)-at).total_seconds()
        if not 0 <= age <= 60:
            result['reason'] = 'WAIT_NEXT_M5_COMPLETION_WINDOW'
            return result
        if not 12 <= at.hour < 17 or at.tz_convert('Asia/Jakarta').weekday() >= 5:
            result['reason'] = 'OUTSIDE_FROZEN_ENTRY_SESSION'
            return result
        raw = raw_signals(d).iloc[-1]
        side = -1 if raw.sell else 1 if raw.buy else 0
        if not side:
            return result
        if any(not str(source_status.get(key,'')).startswith('OK:') for key in ('FOREX_FACTORY_WEEKLY','BLS_OFFICIAL_ICS')):
            result['reason'] = 'NEWS_COVERAGE_UNAVAILABLE'
            return result
        event = blocked_event(events,at)
        if event:
            result.update(reason='PLANNED_HOLD_NEWS_EXPOSURE', blocked_event=event.as_dict())
            return result
        macro = macro if macro is not None else fetch_macro(now)
        series = 'DFII10' if side == 1 else 'DGS10'
        observation = macro[series]
        available = pd.Timestamp(observation['available_at'])
        if not available <= at <= available+pd.Timedelta(days=7) or not math.isfinite(observation['delta']):
            raise RuntimeError('XAU_MACRO_STALE_OR_FUTURE')
        result['macro'] = observation
        if side*observation['delta'] > 0:
            result['reason'] = 'FROZEN_MACRO_DIRECTION_BLOCK'
            return result
        anchor = float(raw.buy_anchor if side == 1 else raw.sell_anchor)
        result.update(state='READY', reason='FROZEN_BUYSELL_SIGNAL', candidate={
            'at':at.isoformat(), 'side':side, 'direction':'BUY' if side==1 else 'SELL',
            'anchor':anchor, 'atr':float(d.atr.iloc[-1]), 'reference_bid':float(d.close.iloc[-1]),
            'expires_at':min(at+pd.Timedelta(minutes=480),at.normalize()+pd.Timedelta(hours=20)-pd.Timedelta(minutes=1)).isoformat()})
        return result
    except Exception as exc:
        result.update(state='BLOCKED', reason=f'{type(exc).__name__}:{exc}')
        return result


def geometry(candidate, bid, ask):
    if not all(math.isfinite(x) for x in (bid,ask,candidate['atr'],candidate['anchor'])) or ask < bid or ask-bid > 1.5:
        raise RuntimeError('XAU_SPREAD_OR_PRICE_INVALID')
    side = candidate['side']
    entry = ask if side == 1 else bid
    structural = entry-candidate['anchor'] if side==1 else candidate['anchor']-entry+(ask-bid)
    distance = max(2.65*candidate['atr'],structural,.5)
    return entry, entry-side*distance, entry+side*distance*6.6, distance


def layers(balance, equity, distance, margin_child, free_margin, used_margin=0):
    if not all(math.isfinite(x) for x in (balance,equity,distance,margin_child,free_margin,used_margin)) or min(equity,distance,margin_child) <= 0:
        return 0
    desired = max(1,math.floor(balance/100))
    risk = math.floor(equity*.125/(distance+.05)+1e-9)
    margin = math.floor(max(0,min(free_margin,equity*.5-used_margin))/margin_child+1e-9)
    return max(0,min(desired,risk,margin))
