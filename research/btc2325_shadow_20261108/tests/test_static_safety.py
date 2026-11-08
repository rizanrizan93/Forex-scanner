import pathlib
import unittest
P=pathlib.Path(__file__).resolve().parents[1]/'source'/'Btc2325Shadow.cs'
s=P.read_text()
class TestShadow(unittest.TestCase):
    def test_no_broker_mutation(self):
        code='\n'.join(l for l in s.splitlines() if not l.lstrip().startswith('//'))
        for api in ('ExecuteMarketOrder(', 'PlaceLimitOrder(', 'PlaceStopOrder(', 'ModifyPosition(', 'ClosePosition(', 'CancelPendingOrder('):
            self.assertNotIn(api,code)
    def test_strategies(self):
        for v in ('"H4_SWEEP20"','"H1_EMA20"','1.5*atr4','2*atr1','RiskFraction = 0.025','MarginFraction = 0.10','BTC2325_SHADOW_HEALTH'):
            self.assertIn(v,s)
    def test_completed_bars_no_lookahead(self):
        self.assertIn('LastClosed(_h1, decisionUtc, 1)',s)
        self.assertIn('LastClosed(_h4, decisionUtc, 4)',s)
        self.assertIn('CAUSAL_BALANCE_GUARD_10PCT',s)
if __name__=='__main__':unittest.main()
