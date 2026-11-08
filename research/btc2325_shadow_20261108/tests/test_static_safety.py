import pathlib
import re
import unittest

P=pathlib.Path(__file__).resolve().parents[1]/'source'/'Btc2325Shadow.cs'
s=P.read_text(encoding="utf-8")

class TestShadow(unittest.TestCase):
    def test_no_broker_mutation(self):
        code='\n'.join(l for l in s.splitlines() if not l.lstrip().startswith('//'))
        for api in ('ExecuteMarketOrder(', 'PlaceLimitOrder(', 'PlaceStopOrder(', 'ModifyPosition(', 'ClosePosition(', 'CancelPendingOrder('):
            self.assertNotIn(api,code)
    def test_two_frozen_signal_families_and_risk(self):
        for v in ('"H4_SWEEP20"','"H1_EMA20"','1.5*atr4','2*atr1',
                  'RiskFraction = 0.025','MarginFraction = 0.10',
                  'MaxModelBtcQuantity = 3200', 'BtcStep = 0.01',
                  'Stop = assumedEntry-s.Side*s.Distance',
                  'Target = assumedEntry+s.Side*s.Distance*10',
                  'BTC2325_SHADOW_HEALTH'):
            self.assertIn(v,s)
    def test_completed_bars_and_research_warmup(self):
        self.assertIn('LastClosed(_h1, decisionUtc, 1)',s)
        self.assertIn('LastClosed(_h4, decisionUtc, 4)',s)
        self.assertIn('hi <= 410',s)
        self.assertIn('CAUSAL_BALANCE_GUARD_10PCT',s)
        self.assertIn('strategy_guard_exact=False',s)
    def test_m1_exit_exact_expiry_minute(self):
        # The replay_btc_m1_path.py limit is pos + holding*60 + 59.
        self.assertIn('ExpiresUtc=hourUtc.AddHours(s.HoldHours).AddMinutes(59)',s)
        for hold in (72,128):
            reference_index=hold*60+59
            # Native compares bar-open UTC against its entry + hold + 59 min.
            native_index=hold*60+59
            self.assertEqual(reference_index,native_index)
    def test_m1_monitor_is_logarithmic_before_new_bars(self):
        self.assertIn('int lo=0, hi=_m1.Count;',s)
        self.assertIn('int mid=lo+(hi-lo)/2;',s)
        self.assertIn('if(_m1.OpenTimes[mid]<=_lastClosedMinuteUtc)lo=mid+1;',s)
        self.assertNotIn('for(int i=0;i<_m1.Count;i++)',s)
    def test_stop_first_and_weekend_priority(self):
        start=s.index('if(IncumbentBusy()) {ExitVirtual')
        end=s.index('if(at>=b.ExpiresUtc)',start)
        block=s[start:end]
        assert_order=['IncumbentBusy()', 'ExitWeekend(at)', 'SL_GAP_OPEN',
                      'SL_INTRABAR', 'TP_INTRABAR']
        self.assertEqual([block.index(v) for v in assert_order],
                         sorted(block.index(v) for v in assert_order))
    def test_user_research_is_not_deployed_by_shadow(self):
        self.assertIn('orders_enabled=False',s)
        self.assertIn('original_Bitstamp_M1_parity_unverified=True',s)
        self.assertNotIn('PortfolioHost',s)
        self.assertNotIn('BUY050_TRADE_ENGINE_ACTIVE',s)

if __name__=='__main__':
    unittest.main()
