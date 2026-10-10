"""
Execution models and risk validation adapted for automated live trading.
"""

class OrderIntent:
    def __init__(self, symbol, side, volume, sl, tp, risk_pct, is_demo=False):
        self.symbol = symbol
        self.side = side
        self.volume = volume
        self.sl = sl
        self.tp = tp
        self.risk_pct = risk_pct
        self.is_demo = is_demo
        self.validate()

    def validate(self):
        # Menghapus batasan kaku 1% untuk live order, menyesuaikan strategi growth/layering Anda
        if not self.is_demo:
            if self.risk_pct > 0.3:  # Batas maksimum toleransi risiko live
                raise ValueError(f"Risk percentage {self.risk_pct}% exceeds maximum permitted live risk.")
        if self.volume <= 0:
            raise ValueError("Invalid order volume.")
