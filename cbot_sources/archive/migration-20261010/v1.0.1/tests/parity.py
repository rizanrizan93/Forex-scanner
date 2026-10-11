"""Differential tests against the original Python signal kernels; no broker calls."""
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOTNET = os.environ.get('DOTNET', 'dotnet')
DLL = ROOT / 'Parity/bin/Release/net8.0/Parity.dll'
SOURCE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'reference'

def load(name):
    path = SOURCE / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def run(mode, data):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'input.json'
        path.write_text(json.dumps(data, allow_nan=False))
        return json.loads(subprocess.check_output([DOTNET, str(DLL), mode, str(path)], text=True))

def near(a, b, tolerance=1e-10):
    if b is None or pd.isna(b):
        assert a is None, (a, b)
    else:
        assert a is not None and math.isclose(a, float(b), rel_tol=tolerance, abs_tol=tolerance), (a, b)

# Startup regression: documented LocalStorage contract, no punctuation,
# account/symbol separation, stable keys and unfunded-account order rejection.
identities = ['RZEU3:2147903:EURUSD','RZXA1:1234480:XAUUSD','RZEU3:2147903:EURUSD.c',
              'RZEU3:2147903:EURUSD-c','RZEU3:2147903:EURUSD c', 'RZEU3:2147903:'+('X'*200)]
identities += [f'RZEU3:{account}:EURUSD' for account in range(1000, 1128)]
keys = run('storage', identities)
assert all(1 <= len(key) <= 50 and key.isascii() and key.isalnum() for key in keys)
assert len(set(keys)) == len(identities)
assert run('storage', identities) == keys

# Real archived OHLC fixture, with precomputed historical strict-bias columns.
fixture = ROOT / 'tests/xau_dd50_replay_2025.json.gz'
rows = json.load(gzip.open(fixture, 'rt'))
actual = run('xau', rows)
for original, got in zip(rows, actual, strict=True):
    assert got['Buy'] == original['expected_buy']
    assert got['Sell'] == original['expected_sell']
    if got['Buy']:
        near(got['BuyAnchor'], original['expected_buy_anchor'], 1e-8)
    if got['Sell']:
        near(got['SellAnchor'], original['expected_sell_anchor'], 1e-8)

# Real Python implementation, deterministic M1 stream, missing bars and sweeps.
eur = load('eurusd_frozen_dd37')
rng = np.random.default_rng(7903)
index = pd.date_range('2026-09-01T00:00Z', periods=24_000, freq='min')
cl = 1.10 + np.cumsum(rng.normal(0, .000045, len(index)))
op = np.r_[cl[0], cl[:-1]]
raw = pd.DataFrame({'open': op, 'high': np.maximum(op, cl) + rng.uniform(.000005, .0001, len(index)),
                    'low': np.minimum(op, cl) - rng.uniform(.000005, .0001, len(index)), 'close': cl}, index=index)
# Flat hourly closes make known H1 bias zero and produce actual sweep signals.
for stamp in index[index.minute == 59]:
    raw.loc[stamp, 'close'] = 1.10
    raw.loc[stamp, 'high'] = max(raw.loc[stamp, 'high'], 1.10)
    raw.loc[stamp, 'low'] = min(raw.loc[stamp, 'low'], 1.10)
raw = raw.drop(index[450:465]).drop(index[17000:17007])
state = {'cursor': (raw.index[0] - pd.Timedelta(minutes=1)).isoformat(), 'fast': 0., 'slow': 0.}
frame = eur.features(raw, state)
eur.advance_virtual(raw, frame, state)
bars = [{'OpenUtc': at.isoformat(), 'Open': float(row.open), 'High': float(row.high), 'Low': float(row.low),
         'Close': float(row.close), 'Count': 1} for at, row in raw.iterrows()]
got = run('eur', {'bars': bars})
assert len(frame) == len(got['Features'])
signals = 0
for (at, original), actual in zip(frame.iterrows(), got['Features'], strict=True):
    assert pd.Timestamp(actual['AtUtc']) == at, (actual['AtUtc'], str(at))
    assert actual['Count'] == original['count']
    for key, source in [('Atr', 'atr'), ('Body', 'body'), ('PriorHigh', 'prior_high'), ('PriorLow', 'prior_low')]:
        near(actual[key], original[source])
    assert actual['Bias'] == (99 if pd.isna(original['bias']) else original['bias'])
    signal = eur.signal(at, original)
    assert (actual['Signal'] is None) == (signal is None)
    if signal:
        signals += 1
        assert actual['Signal']['Side'] == signal['side']
        near(actual['Signal']['Distance'], signal['distance'])
assert signals > 0, 'Stream must exercise virtual trades'
near(got['State']['Fast'], state['fast'])
near(got['State']['Slow'], state['slow'])
assert pd.Timestamp(got['State']['CursorUtc']) == pd.Timestamp(state['cursor'])
assert pd.Timestamp(got['State']['LastExitUtc']) == pd.Timestamp(state['virtual_exit'])
near(got['Scale'], eur.multiplier(state['fast'], state['slow']))
# Split-state restart: virtual/H1/feedback must remain causal and unchanged.
first = run('eur', {'bars': bars[:12000]})
second = run('eur', {'bars': bars, 'state': first['State']})
for key in ['Fast', 'Slow']:
    near(second['State'][key], got['State'][key])
assert second['State']['LastExitUtc'] == got['State']['LastExitUtc']

# STOP_FIRST ambiguity, no-exit, gap, timeout and day boundary in both sides.
virtual_cases, virtual_expected = [], []
for side in [1, -1]:
    opened = pd.Timestamp('2026-10-09T07:00Z')
    for tag, at, high, low in [('BOTH', opened+pd.Timedelta(minutes=1), 1.106, 1.094),
                              ('NONE', opened+pd.Timedelta(minutes=1), 1.1002, 1.0998),
                              ('GAP', opened+pd.Timedelta(minutes=6), 1.1002, 1.0998),
                              ('TIME', opened+pd.Timedelta(minutes=240), 1.1002, 1.0998),
                              ('DAY', opened+pd.Timedelta(days=1), 1.1002, 1.0998)]:
        previous = at-pd.Timedelta(minutes=1) if tag in ('TIME', 'DAY') else opened
        pending = dict(side=side, entry=1.1, distance=.001, at=opened.isoformat(), last_at=previous.isoformat(), last_close=1.1001)
        row = pd.Series(dict(open=1.1, high=high, low=low, close=1.1001))
        output = eur.virtual_step(pending, at, row)
        virtual_expected.append(output)
        virtual_cases.append({'trade':{'Side':side,'Entry':1.1,'Distance':.001,'AtUtc':opened.isoformat(),
                                      'LastUtc':previous.isoformat(),'LastClose':1.1001},
                              'bar':{'OpenUtc':at.isoformat(),'Open':1.1,'High':high,'Low':low,'Close':1.1001}})
for actual, expected_exit in zip(run('virtual', virtual_cases), virtual_expected, strict=True):
    if expected_exit is None:
        assert actual['R'] is None
    else:
        near(actual['R'], expected_exit[0])
        assert pd.Timestamp(actual['AtUtc']) == pd.Timestamp(expected_exit[1])

# Actual archived confirmation functions, including incomplete-bucket exclusion.
confirmation = load('xau_confirmation_reference')
flags = confirmation.reversal_features(raw, 'XAUUSD')
selected = set(flags.index[flags.buy | flags.sell][:40])
selected.update(flags.index[::max(1,len(flags)//40)])
times = sorted(selected)
confirmed = run('confirmation', {'bars': bars, 'times': [t.isoformat() for t in times]})
for actual in confirmed:
    expected_flag = flags.loc[pd.Timestamp(actual['AtUtc'])]
    assert actual['Buy'] == bool(expected_flag.buy)
    assert actual['Sell'] == bool(expected_flag.sell)

# Independent scalar sizing oracle from archived policy formula.
cases, expected = [], []
for symbol in ['EURUSD', 'XAUUSD']:
    for balance in [5, 100, 200, 1000, 10000]:
        for side in [1, -1]:
            for dd in [0, .249999, .25, .5]:
                for scale in [1., .625, .1]:
                    entry, distance, atr, margin = (1.1, .0015, .0005, 5.5) if symbol == 'EURUSD' else (2700., 5.3, 2., 27.)
                    c = dict(symbol=symbol, side=side, distance=distance, atr=atr, anchor=entry-side*distance,
                             entry=entry, balance=balance, equity=balance, free=balance, used=0., margin=margin,
                             scale=scale, peak=balance/(1-dd))
                    cases.append(c)
                    risk_fraction, child_units, slip, share, power, stages, target = (.2725, 1000, .00001, .4, 1.5, 3, 4) if symbol == 'EURUSD' else (.125, 1, .05, 1, .5, 4, 6.6)
                    risk = child_units * (distance+slip) + .06
                    count = math.floor(min(balance*risk_fraction*scale/risk, balance*.5*scale/margin)+1e-9)
                    if symbol == 'XAUUSD':
                        count = min(count, max(1, math.floor(balance/100)))
                    degear = .7 if symbol == 'EURUSD' and (c['peak']-balance)/c['peak'] >= .25 else 1.
                    budget = balance*risk_fraction*scale*degear
                    initial = min(max(1, math.floor(count*share*degear)), math.floor(budget/risk+1e-9)) if count else 0
                    reserved = max(0., budget-initial*risk)
                    stop = entry-side*distance
                    quantities = []
                    for stage in range(1, stages):
                        depth = [0, .2, .4][stage] if symbol == 'EURUSD' else [0, .16111111111111112, .32222222222222224, .48333333333333334][stage]
                        fill = entry-side*depth*distance
                        r = child_units*(side*(fill-stop)+slip)+.06
                        allocation = reserved*(stage+1)**power/sum((k+1)**power for k in range(1, stages))
                        quantities.append(math.floor(min(allocation/r, max(0., budget-initial*risk)/r, balance*.5*scale/margin)+1e-9))
                    expected.append((initial, budget, stop, entry+side*distance*target, reserved, quantities))
result = run('sizing', cases)
for got, exp in zip(result, expected, strict=True):
    assert got['Initial'] == exp[0], (got, exp)
    if exp[0]:
        for key, value in zip(['RiskBudget', 'Stop', 'Target', 'RemainingStageBudget'], exp[1:5]):
            near(got[key], value)
        assert got['Stages'] == exp[5], (got, exp)
report = {'storage_key_cases': len(identities), 'zero_equity_checkpoint_and_no_order': 'PASS', 'xau_fixture_rows': len(rows), 'xau_buy': sum(r['expected_buy'] for r in rows),
          'xau_sell': sum(r['expected_sell'] for r in rows), 'eur_m1_rows': len(raw),
          'eur_features': len(frame), 'eur_signals': signals, 'eur_restart_parity': 'PASS',
          'virtual_boundary_cases': len(virtual_cases), 'confirmation_cases': len(times), 'sizing_cases': len(cases), 'status': 'PASS',
          'scope': 'Signal/virtual kernels and scalar sizing. Not a ten-year basket replay, Cloud execution or broker fill test.'}
(ROOT / 'validation-parity.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
