"""BUY050 Cloud resource-pressure regression; no brokerage/trading operations."""
import pathlib
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/"source"
BRIDGE=ROOT/"bridge"

class ResourcePressure(unittest.TestCase):
    def test_btc_full_history_is_not_recomputed_inside_one_hour(self):
        source=(SOURCE/"BtcSevenDayFeed.cs").read_text()
        self.assertIn('if(Through==Hour(now))return;',source)
        self.assertIn('var fourHourly=BtcCore.Aggregate(bars,240);',source)
        self.assertIn('BtcCore.Signals(bars,fourHourly)',source)
        self.assertIn('EntryFamilies.MergeBtc(candidate,fourHourly)',source)
        self.assertNotIn('EnumerateArray().ToArray()',source)
        self.assertNotIn('new[]{o,h,l,c}.Any(',source)
        self.assertIn('SeedHash=',source)
        self.assertIn('FEED_SEED_HASH',source)
        self.assertIn('FEED_EXTENSION_GAP',source)
        self.assertIn('FEED_COVERAGE',source)
    def test_bridge_retains_single_hour_delivery_semantics(self):
        source=(BRIDGE/"server.py").read_text()
        self.assertIn('self.btc_delivery = {}',source)
        self.assertIn('if self.btc_delivery.get(ws) == marker:',source)
        self.assertIn('self.btc_delivery.pop(ws, None)',source)
        self.assertIn('if bridge.feed is None or bridge.feed.get("through") != completed_hour:',source)
        self.assertIn('await self.send_data(ws, symbol)',source)
    def test_trade_protection_and_frozen_strategy_unchanged(self):
        host=(SOURCE/"PortfolioHost.cs").read_text()
        self.assertIn('20.75',host)
        self.assertIn('PortfolioReady',host)
        self.assertIn('OpenRisk()',host)
        self.assertIn('STORAGE_GUARD_NEW_ENTRIES_BLOCKED',host)
        self.assertIn('return ModifyPosition(p,sl,tp,type);',host)
        self.assertIn('return ClosePosition(p);',host)
        self.assertIn('workingSetMb=-1;',host)
        self.assertIn('catch { /* Cloud process metrics can be sandbox-restricted. */ }',host)
if __name__=="__main__": unittest.main()
