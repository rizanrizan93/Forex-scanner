from datetime import UTC, datetime, timedelta
import unittest
from unittest.mock import patch
import pandas as pd
from fx_scanner.research_xau_v229_historical_v242 import price_arrays
from fx_scanner.research_xau_entry_cycle import (candidate_grid, replay, next_cycle, setup_state_at, next_cycle_with_active_ledger, EXECUTION_AUTHORITY)

AT = datetime(2024, 1, 2, tzinfo=UTC)

def plan(direction="LONG", minutes=0, identity="A"):
    return dict(plan_id=identity, direction=direction, plan_at=(AT+timedelta(minutes=minutes)).isoformat(),
                signal_expires_at=(AT+timedelta(minutes=minutes+10)).isoformat(),
                entry_low=98., entry_high=102., stop=90. if direction == "LONG" else 130.,
                children=[dict(slot=1, reference_price=100. if direction == "LONG" else 122.,
                               planned_target=120. if direction == "LONG" else 100.)])

def px(rows):
    return price_arrays(pd.DataFrame([dict(timestamp=AT+timedelta(minutes=i), open=o, high=h, low=l, close=c)
                                      for i,(o,h,l,c) in enumerate(rows)]))

def candidate(mode="LIMIT"):
    return dict(entry=100., target=120., mode=mode)

class CycleTests(unittest.TestCase):
    def run_replay(self, rows, mode="LIMIT", **kw):
        return replay(px=px(rows), plan=plan(), candidate=candidate(mode),
                      spread_usd=0, slippage_usd=0, **kw)

    def test_fill_then_fast_reaction_and_tp(self):
        r=self.run_replay([(101,102,99,101),(101,121,100,120)])
        self.assertEqual(r["state"],"TP")
        self.assertTrue(r["fast_precision_tp"])
        self.assertEqual(r["reaction_minutes"],2)
        self.assertFalse(EXECUTION_AUTHORITY)

    def test_fill_candle_target_not_credited(self):
        r=self.run_replay([(101,121,99,101),(101,102,100,101)],hold_minutes=1)
        self.assertEqual(r["state"],"TIME_EXIT")

    def test_ambiguous_stop_never_precise(self):
        r=self.run_replay([(101,102,99,101),(101,121,89,100)])
        self.assertEqual(r["state"],"STOP")
        self.assertFalse(r["precision_5_and_tp"])

    def test_reclaim_executes_next_open(self):
        r=self.run_replay([(101,102,99,100),(100.5,103,100,102),(102,121,101,120)],"RECLAIM")
        self.assertEqual(r["fill_price"],100.5)
        self.assertEqual(r["fill_at"],(AT+timedelta(minutes=1)).isoformat())

    def test_reclaim_no_chase(self):
        r=self.run_replay([(101,102,99,100),(102,104,100,103)],"RECLAIM")
        self.assertEqual(r["reason"],"NO_CHASE")

    def test_reclaim_invalidates_before_confirmation(self):
        r=self.run_replay([(101,102,89,101),(100,121,99,120)],"RECLAIM")
        self.assertEqual(r["reason"],"INVALIDATED_BEFORE_CONFIRMATION")

    def test_incomplete_history_censored(self):
        self.assertEqual(self.run_replay([(101,102,100.5,101)])["state"],"CENSORED")
        self.assertEqual(self.run_replay([(101,102,99,101)])["state"],"CENSORED")

    def test_time_exit_uses_next_available_quote_not_past_close(self):
        data=px([(101,102,99,101),(80,82,79,81)])
        from dataclasses import replace
        data=replace(data,timestamps=(data.timestamps[0],pd.Timestamp(AT)+pd.Timedelta(days=3)))
        r=replay(px=data,plan=plan(),candidate=candidate(),spread_usd=0,slippage_usd=0,hold_minutes=4)
        self.assertEqual(r["state"],"STOP")
        self.assertEqual(r["exit_price"],80)
        self.assertEqual(r["holding_minutes"],4320)

    def test_stop_gap_and_cost(self):
        r=replay(px=px([(101,102,99,101),(85,88,84,86)]),plan=plan(),candidate=candidate(),spread_usd=.4,slippage_usd=.1)
        self.assertAlmostEqual(r["exit_price"],84.7)

    def test_depth_and_tp_buffer(self):
        grid=candidate_grid(plan())
        self.assertEqual(grid["D75_T1_B0.5_LIMIT"]["entry"],99)
        self.assertEqual(grid["D75_T1_B0.5_LIMIT"]["target"],119.5)

    def test_no_automatic_reverse(self):
        first=dict(state="TP",exit_at=AT.isoformat(),exit_price=120,fast_precision_tp=True)
        r=next_cycle(first=first,first_plan=plan(),plans=[],px=px([(120,121,119,120)]),key="E1_T1")
        self.assertEqual(r["state"],"NO_NEW_ELIGIBLE_OPPOSITE_PLAN")

    def test_first_eligible_opposite_is_not_replaced_by_later_winner(self):
        first=dict(state="TP",exit_at=AT.isoformat(),exit_price=120,fast_precision_tp=True)
        bad=plan("SHORT",0,"first")
        good=plan("SHORT",1,"later")
        good["children"][0]["reference_price"]=120
        rows=[(120,121,119,120)]*31
        r=next_cycle(first=first,first_plan=plan(),plans=[good,bad],px=px(rows),key="E1_T1",spread_usd=0,slippage_usd=0)
        self.assertEqual(r["next_plan_id"],"first")
        self.assertEqual(r["next_result"]["state"],"MISSED")

    def test_short_quote_side(self):
        r=replay(px=px([(121,122.3,120,121),(121,122,99,100)]),plan=plan("SHORT"),
                 candidate=dict(entry=122,target=100,mode="LIMIT"),spread_usd=.4,slippage_usd=.1)
        self.assertEqual(r["state"],"TP")
        self.assertTrue(r["precision_5_and_tp"])


    def test_ledger_keeps_unfilled_opposite_setup_active_at_tp(self):
        opposite=plan("SHORT",0,"old-opposite")
        opposite["signal_expires_at"]=(AT+timedelta(minutes=40)).isoformat()
        opposite["entry_low"]=118.
        opposite["entry_high"]=122.
        opposite["children"][0]["reference_price"]=122.
        opposite["children"][0]["planned_target"]=100.
        data=px([
            (110,111,109,110),
            (111,112,110,111),
            (120,121,119,120),
            (120,123,119,122),
            (121,122,99,100),
        ] + [(100,101,99,100)]*40)
        state=setup_state_at(
            px=data,
            plan=opposite,
            candidate=dict(entry=122.,target=100.,mode="LIMIT"),
            as_of=AT+timedelta(minutes=3),
            spread_usd=0,
            slippage_usd=0,
        )
        self.assertTrue(state["active"])
        self.assertEqual(state["state"],"ACTIVE_UNFILLED")

    def test_active_at_tp_opposite_setup_precedes_later_publication(self):
        first=dict(
            state="TP",
            exit_at=(AT+timedelta(minutes=3)).isoformat(),
            exit_price=120.,
            fast_precision_tp=True,
        )
        old=plan("SHORT",0,"old")
        old["signal_expires_at"]=(AT+timedelta(minutes=30)).isoformat()
        old["entry_low"]=118.
        old["entry_high"]=122.
        old["children"][0]["reference_price"]=120.
        old["children"][0]["planned_target"]=100.
        later=plan("SHORT",4,"later")
        later["signal_expires_at"]=(AT+timedelta(minutes=20)).isoformat()
        later["entry_low"]=118.
        later["entry_high"]=122.
        later["children"][0]["reference_price"]=120.
        later["children"][0]["planned_target"]=100.
        data=px([
            (110,111,109,110),
            (111,112,110,111),
            (119,119.5,118.5,119),
            (120,120.5,119.5,120),
            (120,120.5,119.5,120),
            (120,121,119,120),
            (120,121,99,100),
        ] + [(100,101,99,100)]*30)
        result=next_cycle_with_active_ledger(
            first=first,
            first_plan=plan("LONG",0,"first"),
            plans=[later,old],
            px=data,
            key="E1_T1",
            spread_usd=0,
            slippage_usd=0,
            hold_minutes=30,
        )
        self.assertEqual(result["state"],"SELECTED")
        self.assertEqual(result["next_plan_id"],"old")
        self.assertEqual(result["selection_origin"],"ACTIVE_AT_TP")

    def test_already_filled_opposite_is_not_reused_at_tp(self):
        first=dict(
            state="TP",
            exit_at=(AT+timedelta(minutes=4)).isoformat(),
            exit_price=120.,
            fast_precision_tp=True,
        )
        old=plan("SHORT",0,"old-filled")
        old["signal_expires_at"]=(AT+timedelta(minutes=30)).isoformat()
        old["entry_low"]=118.
        old["entry_high"]=122.
        old["children"][0]["reference_price"]=120.
        old["children"][0]["planned_target"]=100.
        data=px([
            (120,121,119,120),
            (120,121,119,120),
            (120,121,119,120),
            (120,121,119,120),
            (120,121,119,120),
        ] + [(120,121,119,120)]*30)
        result=next_cycle_with_active_ledger(
            first=first,
            first_plan=plan("LONG",0,"first"),
            plans=[old],
            px=data,
            key="E1_T1",
            spread_usd=0,
            slippage_usd=0,
            hold_minutes=30,
        )
        self.assertEqual(result["state"],"NO_ELIGIBLE_OPPOSITE_SETUP")

class RuntimeTests(unittest.TestCase):
    def test_complete_paired_grid_and_report(self):
        from fx_scanner.research_xau_entry_cycle_runtime import year_replay, aggregate, KEYS
        ts=pd.date_range(AT,periods=1500,freq="min")
        frame=pd.DataFrame(dict(timestamp=ts,open=101.,high=102.,low=99.,close=101.))
        frame.loc[2,["high","close"]]=[121.,120.]
        with patch("fx_scanner.research_xau_entry_cycle_runtime.simulate_year",return_value={"plans":[plan()]}):
            shard=year_replay(2024,frame,{"failed_periods":[]})
        self.assertEqual(set(shard["rows"][0]["pairs"]),set(KEYS))
        report=aggregate([shard])
        self.assertEqual(report["mature_plans"],1)
        self.assertFalse(report["folds"][0]["eligible"])
        self.assertEqual(report["descriptive_only"]["E1_T1"]["tp"],1)

    def test_failed_download_rejected(self):
        from fx_scanner.research_xau_entry_cycle_runtime import year_replay
        frame=pd.DataFrame([dict(timestamp=AT,open=100.,high=101.,low=99.,close=100.)])
        with self.assertRaisesRegex(ValueError,"incomplete provider"):
            year_replay(2024,frame,{"failed_periods":["missing month"]})

    def test_unmature_training_rows_excluded(self):
        from fx_scanner.research_xau_entry_cycle_runtime import aggregate, RESEARCH_VERSION
        shard=dict(research_version=RESEARCH_VERSION,year=2023,price_end="2024-01-31",price_provenance={},
                   rows=[dict(year=2023,mature_at="2024-01-02T00:00:00Z",censored=False,pairs={})]*30)
        # No need to score malformed test rows: verify cutoff selection through a stub scorer.
        with patch("fx_scanner.research_xau_entry_cycle_runtime.score",return_value={}):
            result=aggregate([shard,dict(research_version=RESEARCH_VERSION,year=2024,price_end="2024-12-31",price_provenance={},rows=[])])
        self.assertEqual(result["folds"][1]["train_plans"],0)

if __name__ == "__main__": unittest.main()
