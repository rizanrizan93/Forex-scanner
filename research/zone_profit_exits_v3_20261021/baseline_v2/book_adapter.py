"""Read-only Bybit L2 reconstruction. No credentials or order endpoints.

Archive timestamps are exchange publication time, NOT local arrival time.
Integer-tenth-dollar prices avoid float key drift for the 2024 BTCUSDT feed.
"""
import math
from sortedcontainers import SortedDict


class Book:
    def __init__(self):
        self.bids = SortedDict()
        self.asks = SortedDict()
        self.ts = -1
        self.seq = -1
        self.ready = False
        self.resets = 0

    def apply(self, msg):
        d = msg['data']
        ts = int(msg['ts'])
        seq = int(d.get('seq', -1))
        reset = msg['type'] == 'snapshot' or d.get('u') == 1
        if reset:
            self.bids.clear()
            self.asks.clear()
            self.ready = msg['type'] == 'snapshot'
            self.seq = -1
            self.resets += 1
        if not self.ready:
            return False
        if ts < self.ts or (seq >= 0 and self.seq >= 0 and seq < self.seq):
            self.ready = False
            return False  # fail closed until a complete new snapshot
        for side, target in [('b', self.bids), ('a', self.asks)]:
            for p, q in d[side]:
                price = round(float(p) * 10)
                size = float(q)
                if size == 0:
                    target.pop(price, None)
                else:
                    target[price] = size
        self.ts, self.seq = ts, seq
        return True

    def sample(self, grid_ms):
        if not self.ready or not self.bids or not self.asks:
            return None
        bid, ask = self.bids.peekitem(-1)[0] / 10, self.asks.peekitem(0)[0] / 10
        if bid >= ask or not 0 <= grid_ms - self.ts <= 2000:
            return None
        mid = (bid + ask) / 2
        lo, hi = math.ceil(mid * .9995 * 10), math.floor(mid * 1.0005 * 10)
        bn = sum(p / 10 * self.bids[p] for p in self.bids.irange(lo, None))
        an = sum(p / 10 * self.asks[p] for p in self.asks.irange(None, hi))
        return bid, ask, bn, an, grid_ms - self.ts


def decision_features(ts_ms, imbalance, decision_ms, side):
    """Strictly pre-decision evidence; no forward-filled missing samples."""
    import numpy as np
    j = np.searchsorted(ts_ms, decision_ms, side='left')
    start = np.searchsorted(ts_ms, decision_ms - 60_000)
    x = imbalance[start:j]
    x = x[np.isfinite(x)]
    valid = len(x) >= 55 and j > 0 and decision_ms - ts_ms[j - 1] <= 2000 and np.isfinite(imbalance[j - 1])
    instant = float(side * imbalance[j - 1]) if valid else float('nan')
    persistence = float(np.mean(side * x >= .2)) if valid else float('nan')
    return {'feature_valid': bool(valid), 'aligned_imbalance': instant,
            'persistence_60s': persistence, 'feature_last_ms': int(ts_ms[j - 1]) if j else -1,
            'imbalance_filter': bool(valid and instant >= .2),
            'persistent_filter': bool(valid and persistence >= .6)}
