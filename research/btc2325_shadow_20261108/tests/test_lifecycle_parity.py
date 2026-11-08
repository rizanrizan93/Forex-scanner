"""BTC2325 research-only lifecycle regression. No broker orders or LIVE access."""
import datetime as dt
import pathlib
import unittest

SOURCE=(pathlib.Path(__file__).resolve().parents[1]/'source'/'Btc2325Shadow.cs').read_text()
UTC=dt.timezone.utc

def reference_cooldown(decision_close_utc,exit_utc):
    # Python frozen i < prev_exit_hour + 6 compares the last CLOSED H1 index.
    previous_hour=exit_utc.replace(minute=0,second=0,microsecond=0)
    return decision_close_utc-dt.timedelta(hours=1) < previous_hour+dt.timedelta(hours=6)

class LifecycleParity(unittest.TestCase):
    def test_native_retries_new_H1_bar_before_marking_decision_consumed(self):
        i=SOURCE.index('int currentH1 = _h1.Count-1;')
        j=SOURCE.index('var signal = ClosedSignal(hourUtc);')
        segment=SOURCE[i:j]
        self.assertLess(segment.index('if(currentH1<0'),segment.index('_lastDecisionHourUtc=hourUtc'))
        self.assertIn('if(nowUtc-hourUtc<=TimeSpan.FromMinutes(2))return;',segment)
        self.assertIn('NEW_H1_BAR_UNAVAILABLE',segment)
    def test_hour_based_cooldown_semantics(self):
        exit_=dt.datetime(2024,4,12,13,59,tzinfo=UTC)
        self.assertTrue(reference_cooldown(dt.datetime(2024,4,12,19,0,tzinfo=UTC),exit_))
        self.assertFalse(reference_cooldown(dt.datetime(2024,4,12,20,0,tzinfo=UTC),exit_))
        self.assertIn('hourUtc.AddHours(-1)',SOURCE)
        self.assertIn('DateTimeKind.Utc).AddHours(6)',SOURCE)
    def test_paper_guard_is_causal_not_real_account_drift(self):
        a=SOURCE.index('private bool CausalObservedGuardOk()')
        b=SOURCE.index('private void Decide(',a)
        block=SOURCE[a:b]
        self.assertIn('Math.Max(_closedPeak, _cash)',block)
        self.assertIn('1-_cash/_closedPeak',block)
        self.assertNotIn('Account.Balance)',block)
    def test_frozen_families_still_shadow_no_orders(self):
        for token in ['"H4_SWEEP20"','"H1_EMA20"','1.5*atr4','2*atr1','Target=assumedEntry+s.Side*s.Distance*10',
                      'RiskFraction = 0.025','MarginFraction = 0.10','MaxModelBtcQuantity = 3200']:
            self.assertIn(token,SOURCE)
        lines='\n'.join(l for l in SOURCE.splitlines() if not l.lstrip().startswith('//'))
        for api in ('ExecuteMarketOrder(', 'ModifyPosition(', 'ClosePosition(', 'PlaceLimitOrder('):
            self.assertNotIn(api,lines)

if __name__=='__main__':unittest.main()
