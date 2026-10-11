import pandas as pd
import numpy as np
from types import SimpleNamespace
def strict(frame):
    c = frame.close
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    return pd.Series(np.where((c > e200) & (e50 >= e50.shift(2)), 1, np.where((c < e200) & (e50 <= e50.shift(2)), -1, 0)), index=frame.index)
xau=SimpleNamespace(strict=strict)
def completed(raw, minutes):
    f = raw.resample(f'{minutes}min', closed='left', label='right').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    count = raw.close.resample(f'{minutes}min', closed='left', label='right').count()
    return f[count == minutes].dropna()

def reversal_features(raw, symbol):
    """M15 and M5 break prior completed candle; H1 frozen bias must allow side.

    Fresh complete buckets only. No centered swings or future pivot confirmation.
    Confirmation boolean is recomputed each M5 closure; expires after one M5.
    """
    m5, m15, h1 = (completed(raw, m) for m in (5, 15, 60))
    bias = xau.strict(h1) if symbol == 'XAUUSD' else _eur_h1_bias(h1)
    a = pd.DataFrame(index=m5.index)
    a['m5_buy'] = (m5.close > m5.high.shift(1)) & (m5.close > m5.open)
    a['m5_sell'] = (m5.close < m5.low.shift(1)) & (m5.close < m5.open)
    b = pd.DataFrame(index=m15.index)
    b['m15_buy'] = (m15.close > m15.high.shift(1)) & (m15.close > m15.open)
    b['m15_sell'] = (m15.close < m15.low.shift(1)) & (m15.close < m15.open)
    b['m15_bias'] = xau.strict(m15)
    a = a.join(b.reindex(a.index, method='ffill', tolerance=pd.Timedelta(minutes=15)))
    a['h1_bias'] = bias.reindex(a.index, method='ffill', tolerance=pd.Timedelta(minutes=60))
    if symbol == 'XAUUSD':
        buy_htf = (a.h1_bias == 1) & (a.m15_bias == 1)
        sell_htf = (a.h1_bias == -1) & (a.m15_bias == -1)
    else:
        buy_htf = a.h1_bias.isin([0, 1])
        sell_htf = a.h1_bias.isin([0, -1])
    result = pd.DataFrame({'buy': a.m5_buy & a.m15_buy & buy_htf, 'sell': a.m5_sell & a.m15_sell & sell_htf})
    return result.fillna(False)
