"""Paired L2 event study; quote-based at one second, not a tick fill backtest."""
from pathlib import Path
import json, math, hashlib
import importlib.util
import numpy as np
import pandas as pd
from book_adapter import decision_features
from zone_overlay import Zone, annotate

ROOT = Path(__file__).resolve().parent

def load():
    xs = [np.load(ROOT / 'derived' / f'2024-01-{i:02}.npz') for i in range(1, 9)]
    ts = np.concatenate([x['ts'] for x in xs])
    q = np.concatenate([x['quotes'] for x in xs])
    assert np.all(np.diff(ts) == 1000)
    mid = (q[:, 0] + q[:, 1]) / 2
    denom = q[:, 2] + q[:, 3]
    imb = np.divide(q[:, 2] - q[:, 3], denom, out=np.full(len(q), np.nan), where=denom > 0)
    df = pd.DataFrame({'mid': mid}, index=pd.to_datetime(ts, unit='ms', utc=True))
    m = df.resample('15min', closed='left', label='left').mid.agg(['first', 'max', 'min', 'last', 'count'])
    m.columns = ['open', 'high', 'low', 'close', 'count']
    prev = m.close.shift(1)
    tr = pd.concat([m.high - m.low, (m.high - prev).abs(), (m.low - prev).abs()], axis=1).max(axis=1)
    m['atr'] = tr.rolling(56, min_periods=56).mean().shift(1)
    # Broken bars cannot silently become indicator inputs.
    clean = m['count'] >= 895
    m['usable'] = clean.rolling(57, min_periods=57).min().eq(1)
    m['history_usable'] = clean.shift(1).rolling(56, min_periods=56).min().eq(1)
    m['hi16'] = m.high.shift(1).rolling(16).max()
    m['lo16'] = m.low.shift(1).rolling(16).min()
    return ts, q, mid, imb, m

def generate_events(ts, mid, m):
    events = []
    for at, bar in m.iterrows():
        if at < pd.Timestamp('2024-01-02', tz='UTC') or not bar.history_usable:
            continue
        start = at.value // 1_000_000
        a = np.searchsorted(ts, start)
        b = np.searchsorted(ts, start + 900_000)
        atr = bar.atr
        rng = bar.high - bar.low
        if not np.isfinite(atr) or atr <= 0:
            continue
        # Fixed existing liquidity-sweep formula: w16/depth0/wick0.3.
        buy = bar.usable and rng > 0 and bar.low < bar.lo16 and bar.close > bar.lo16 and (min(bar.open, bar.close) - bar.low) / rng >= .3
        sell = bar.usable and rng > 0 and bar.high > bar.hi16 and bar.close < bar.hi16 and (bar.high - max(bar.open, bar.close)) / rng >= .3
        if bool(buy) != bool(sell):
            side = 1 if buy else -1
            events.append({'cohort': 'sweep_reclaim', 'decision_ms': start + 901_000, 'mapped_ms': start,
                           'side': side, 'level': bar.lo16 if buy else bar.hi16, 'atr': atr,
                           'stop': bar.low - .1 * atr if buy else bar.high + .1 * atr})
        # A separate map known at bar open. First touch has no reclaim prerequisite.
        hit = np.flatnonzero((mid[a:b] <= bar.lo16) | (mid[a:b] >= bar.hi16))
        if len(hit):
            ix = a + hit[0]
            side = 1 if mid[ix] <= bar.lo16 else -1
            level = bar.lo16 if side == 1 else bar.hi16
            events.append({'cohort': 'exante_touch', 'decision_ms': int(ts[ix]) + 1000,
                           'mapped_ms': start, 'side': side, 'level': level, 'atr': atr,
                           'stop': level - side * .75 * atr})
    return sorted(events, key=lambda x: (x['decision_ms'], x['cohort']))

def repo_events(ts, mid):
    """Use the actual repository's causal H1/M5 implementation unchanged."""
    p = ROOT / 'origin' / 'repo' / 'reversal_zones.py'
    spec = importlib.util.spec_from_file_location('original_reversal_zones', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    df = pd.DataFrame({'mid': mid}, index=pd.to_datetime(ts, unit='ms', utc=True))
    m1 = df.mid.resample('1min').ohlc()
    count = df.mid.resample('1min').count()
    m1 = m1.loc[count >= 58].copy()
    m1.index.name = 'timestamp'
    f = mod.closed_features(m1)
    events = []
    for side in (1, -1):
        base = mod.base_events(f, side, 6, .1)
        base = mod.thin_events(base.loc[base.wick_bin >= 3])
        for at, row in base.iterrows():
            if at < pd.Timestamp('2024-01-02', tz='UTC'):
                continue
            events.append({'cohort': 'repo_h1_m5', 'decision_ms': at.value // 1_000_000 + 1000,
                           'mapped_ms': at.value // 1_000_000 - 300_000, 'side': side,
                           'level': row.level, 'atr': row.atr, 'stop': row.level - side * .75 * row.atr})
    return events

def simulate(e, ts, q):
    j = np.searchsorted(ts, e['decision_ms'])
    limit = np.searchsorted(ts, e['decision_ms'] + 5000, side='right')
    while j < min(limit, len(ts)) and not np.isfinite(q[j, 0]):
        j += 1
    if j >= min(limit, len(ts)):
        return {'status': 'no_entry_quote'}
    side = e['side']
    entry = q[j, 1] if side == 1 else q[j, 0]
    risk = side * (entry - e['stop'])
    if not .15 * e['atr'] <= risk <= 4 * e['atr']:
        return {'status': 'invalid_risk'}
    target = entry + side * risk
    end = np.searchsorted(ts, ts[j] + 1_800_000)
    if end >= len(ts):
        return {'status': 'right_censored'}
    # Exit at sampled executable side, including sampled gaps beyond stop/target.
    px = q[j:end + 1, 0 if side == 1 else 1]
    stop = side * (px - e['stop']) <= 0
    take = side * (px - target) >= 0
    missing = ~np.isfinite(px)
    hit = np.flatnonzero(stop | take | missing)
    k = int(hit[0]) if len(hit) else len(px) - 1
    if missing[k]:
        return {'status': 'quote_gap_censored'}
    exit_px = px[k]
    duration = (ts[j + k] - ts[j]) / 1000
    gross = side * (exit_px - entry)
    # Spread already embedded in entry ask/bid and opposite-side exit.
    cost = (entry + exit_px) * (5.5 + 1) / 1e4 + entry * .0003 * duration / 86400
    result = {'status': 'complete', 'reason': 'stop' if stop[k] else 'target' if take[k] else 'timeout',
              'entry_ms': int(ts[j]), 'exit_ms': int(ts[j + k]), 'entry_px': entry, 'exit_px': exit_px,
              'risk_usd_per_btc': risk, 'target': target, 'gross_R': gross / risk,
              'cost_R_1x': cost / risk, 'duration_s': duration}
    for multiple in (1., 1.5, 2.):
        result[f'net_R_{multiple:g}x'] = (gross - multiple * cost) / risk
    return result

def wilson(w, n):
    if not n:
        return None, None
    z = 1.96
    p = w / n
    c = (p + z*z/(2*n)) / (1 + z*z/n)
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return 100*(c-h), 100*(c+h)

def summary(df):
    rows = []
    for (cohort, split), g in df.groupby(['cohort', 'split']):
        valid = g[g.status.eq('complete') & g.feature_valid]
        filters = {'baseline': np.ones(len(valid), bool), 'imbalance': valid.imbalance_filter,
                   'persistent': valid.persistent_filter,
                   'both': valid.imbalance_filter & valid.persistent_filter}
        for name, mask in filters.items():
            selected = valid.loc[mask]
            rejected = valid.loc[~np.asarray(mask)]
            for multiple in (1., 1.5, 2.):
                key = f'net_R_{multiple:g}x'
                p = selected[key].to_numpy()
                n = len(p)
                lo, hi = wilson(int((p > 0).sum()), n)
                loss = -p[p < 0].sum()
                rejected_p = rejected[key]
                rows.append({'cohort': cohort, 'split': split, 'filter': name, 'cost_multiplier': multiple,
                             'candidate_events': len(g), 'eligible_paired_events': len(valid), 'n': n,
                             'coverage_pct': 100*n/len(valid) if len(valid) else None,
                             'wins': int((p > 0).sum()), 'losses': int((p < 0).sum()),
                             'target_first_n': int(selected.reason.eq('target').sum()),
                             'stop_first_n': int(selected.reason.eq('stop').sum()),
                             'timeout_n': int(selected.reason.eq('timeout').sum()),
                             'target_first_pct': 100*selected.reason.eq('target').mean() if n else None,
                             'gross_positive_pct': 100*(selected.gross_R>0).mean() if n else None,
                             'win_pct': 100*(p > 0).mean() if n else None,
                             'win_wilson_lo': lo, 'win_wilson_hi': hi,
                             'mean_net_R': p.mean() if n else None, 'sum_net_R': p.sum() if n else 0,
                             'PF_R': p[p > 0].sum()/loss if loss > 0 else None,
                             'rejected_n': len(rejected),
                             'rejected_mean_R': rejected_p.mean() if len(rejected) else None,
                             'mean_R_per_baseline_opportunity': p.sum()/len(valid) if len(valid) else None})
    return pd.DataFrame(rows)

def main():
    ts, q, mid, imb, m = load()
    events = generate_events(ts, mid, m) + repo_events(ts, mid)
    events.sort(key=lambda x: (x['decision_ms'], x['cohort']))
    rows = []
    annotations = []
    for e in events:
        d = dict(e)
        width = .1*e['atr'] if e['cohort']=='repo_h1_m5' else 0
        zone = Zone(f"{e['cohort']}|{e['mapped_ms']}|{e['side']}", 'BTCUSDT', 'Bybit',
                    e['mapped_ms'], e['side'], e['level']-width, e['level']+width)
        annotation = annotate(zone, e['decision_ms'], 'BTCUSDT', 'Bybit', ts, imb)
        annotations.append({**annotation, 'decision_ms':e['decision_ms'], 'available_ms':e['mapped_ms']})
        d.update({k:annotation[k] for k in ['feature_valid','aligned_imbalance','persistence_60s',
                                         'feature_last_ms','imbalance_filter','persistent_filter']})
        d.update(simulate(e, ts, q))
        d['split'] = 'development' if e['decision_ms'] < pd.Timestamp('2024-01-06', tz='UTC').value // 1_000_000 else 'holdout'
        rows.append(d)
    df = pd.DataFrame(rows)
    for col in ['decision_ms', 'entry_ms', 'exit_ms', 'mapped_ms', 'feature_last_ms']:
        df[col.replace('_ms', '_utc')] = pd.to_datetime(df[col], unit='ms', utc=True)
    assert (df.feature_last_ms < df.decision_ms).all()
    assert (df.mapped_ms < df.decision_ms).all()
    df.to_csv(ROOT / 'EVENT_LEDGER.csv', index=False)
    (ROOT / 'ZONE_ANNOTATIONS.json').write_text(json.dumps(annotations, indent=2, allow_nan=False) + '\n')
    s = summary(df)
    s.to_csv(ROOT / 'COMPARISON.csv', index=False)
    m.to_csv(ROOT / 'M15_ZONE_INPUT.csv')
    complete = df[df.status.eq('complete')]
    overlaps = {}
    for (cohort, split), g in complete.groupby(['cohort', 'split']):
        running_end = -1
        count = 0
        for r in g.sort_values('entry_ms').itertuples():
            count += int(r.entry_ms <= running_end)
            running_end = max(running_end, r.exit_ms)
        overlaps[cohort + ':' + split] = count
    audit = {'events': len(df), 'status_counts': df.status.value_counts().to_dict(),
             'feature_valid': int(df.feature_valid.sum()), 'overlap_counts': overlaps,
             'causal_feature_and_zone_assertions': 'PASS',
             'original_source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for folder in ('zone_engine', 'repo') for p in (ROOT/'origin'/folder).glob('*.py')},
             'model': 'paired event study, risk normalized, no compounded portfolio claim',
             'holdout_definition': 'Jan6-8; very small chronological diagnostic, not certification'}
    (ROOT / 'EVENT_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(s.query('cost_multiplier==1').to_string(index=False))
    print(json.dumps(audit, indent=2))

if __name__ == '__main__':
    main()
