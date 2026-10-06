from datetime import UTC,datetime,timedelta
from dataclasses import replace
import unittest
import numpy as np
import pandas as pd
from fx_scanner.demo_xau_supply_demand_atlas_v182 import SDZone
from fx_scanner.research_xau_v229_historical_v242 import price_arrays
from fx_scanner.research_xau_zone_destination import (
    causal_build_zones,validate_frame,zone_catalog,feature_snapshot,destination_label,build_dataset,
    fit_destination,predict_destination,evaluate_destination,reaction_after_destination,entry_summary,aggregate,VERSION,
)
AT=datetime(2024,1,2,tzinfo=UTC)

def frame(n=700):
    return pd.DataFrame(dict(timestamp=pd.date_range(AT,periods=n,freq="min"),open=100.,high=100.5,low=99.5,close=100.))

def zone(side="LONG",identifier="D",available=AT):
    return SDZone(zone_id=identifier,timeframe="H1",zone_class="IMBALANCE",pattern="DBR",
                  direction=side,low=94. if side=="LONG" else 105.,high=95. if side=="LONG" else 106.,
                  proximal=95. if side=="LONG" else 105.,distal=94. if side=="LONG" else 106.,
                  available_at=available,origin_at=available-timedelta(hours=1),departure_at=available,
                  atr_points=2.,base_bars=1,base_range_atr=.5,departure_range_atr=1.5,
                  departure_body_fraction=.8,structural_bos=False)

def features(data=None):
    data=frame() if data is None else data
    px=price_arrays(data); cat=zone_catalog([zone(),zone("SHORT","S")],px)
    return px,cat,feature_snapshot(px,AT+timedelta(hours=1),list(cat.values()))

class DestinationTests(unittest.TestCase):
    def test_never_touched_zones_kept(self):
        d=build_dataset(frame(),target_year=2024,zones=[zone(),zone("SHORT","S")])
        self.assertEqual(len(d["zone_outcome_catalog"]),2)
        self.assertTrue(all(z["touch_episode_count"]==0 for z in d["zone_outcome_catalog"]))
        self.assertEqual(d["rows"][1]["labels"]["destinations"]["30"]["state"],"NEITHER")

    def test_future_zone_not_available(self):
        data=price_arrays(frame())
        c=zone_catalog([zone(available=AT+timedelta(hours=2))],data)
        self.assertEqual(feature_snapshot(data,AT+timedelta(hours=1),list(c.values()))["active_zones"],[])

    def test_close_invalidation_known_only_at_next_minute(self):
        data=frame();data.loc[60,["open","high","low","close"]]=[100,100,92,93]
        px=price_arrays(data);cat=zone_catalog([zone()],px)
        self.assertEqual(len(feature_snapshot(px,AT+timedelta(minutes=60),list(cat.values()))["active_zones"]),1)
        self.assertEqual(len(feature_snapshot(px,AT+timedelta(minutes=61),list(cat.values()))["active_zones"]),0)

    def test_touch_counts_use_completed_bars(self):
        data=frame();data.loc[60,"low"]=94.5
        px=price_arrays(data);cat=zone_catalog([zone()],px)
        self.assertEqual(feature_snapshot(px,AT+timedelta(minutes=60),list(cat.values()))["active_zones"][0]["past_touch_episodes"],0)
        self.assertEqual(feature_snapshot(px,AT+timedelta(minutes=61),list(cat.values()))["active_zones"][0]["past_touch_episodes"],1)

    def test_same_bar_destination_ambiguous(self):
        data=frame();data.loc[61,["high","low"]]=[106,94]
        px,_,f=features(data)
        self.assertEqual(destination_label(px,f,30)["state"],"AMBIGUOUS")

    def test_first_supply_touch(self):
        data=frame();data.loc[65,"high"]=105.5
        px,_,f=features(data)
        label=destination_label(px,f,30)
        self.assertEqual(label["state"],"SUPPLY_FIRST")
        self.assertEqual(label["known_at"],(AT+timedelta(minutes=66)).isoformat())

    def test_gap_censors_destination(self):
        data=frame().drop(index=65)
        px,_,f=features(data)
        self.assertEqual(destination_label(px,f,30)["state"],"CENSORED")

    def test_features_invariant_to_future_prices(self):
        data=frame();_,_,before=features(data)
        data.loc[60:,["open","high","low","close"]]=[120,130,110,120]
        _,_,after=features(data)
        self.assertEqual(before,after)

    def test_future_replacement_does_not_erase_old_zone(self):
        px=price_arrays(frame())
        z=zone();new=replace(z,zone_id="D2",available_at=AT+timedelta(minutes=65))
        cat=zone_catalog([z,new],px)
        old=feature_snapshot(px,AT+timedelta(minutes=60),list(cat.values()))
        self.assertEqual([z["zone_id"] for z in old["active_zones"]],["D"])
        now=feature_snapshot(px,AT+timedelta(minutes=65),list(cat.values()))
        self.assertEqual([z["zone_id"] for z in now["active_zones"]],["D2"])

    def test_break_wins_reaction_ambiguity(self):
        data=frame();data.loc[61,["open","high","low","close"]]=[104,105.5,103,104]
        data.loc[62,["open","high","low","close"]]=[104,108,102,107]
        px,_,f=features(data)
        result=reaction_after_destination(px,f,destination_label(px,f,30))
        self.assertEqual(result["state"],"BREAK_FIRST")
        self.assertTrue(result["ambiguous"])

    def test_entry_denominators_keep_misses(self):
        d=build_dataset(frame(),target_year=2024,zones=[zone(),zone("SHORT","S")])
        a=entry_summary(d["rows"],"LONG_D25")
        b=entry_summary(d["rows"],"LONG_D75")
        self.assertGreater(a["opportunities"],0)
        self.assertEqual(a["opportunities"],b["opportunities"])
        self.assertEqual(a["filled"],0)

    def test_forecast_reads_features_only_and_backoffs(self):
        px,_,f=features()
        r=dict(features=f,labels=dict(destinations={"30":dict(state="SUPPLY_FIRST")}))
        model=fit_destination([r]*10,30)
        p=predict_destination(model,f)
        self.assertTrue(p["backoff"])
        self.assertAlmostEqual(sum(p["probabilities"].values()),1)
        self.assertGreater(p["probabilities"]["SUPPLY_FIRST"],.5)

    def test_calibration_evaluation_uses_training_only(self):
        _,_,f=features()
        train=[dict(features=f,labels=dict(destinations={"30":dict(state="SUPPLY_FIRST")})) for _ in range(120)]
        test=[dict(features=f,labels=dict(destinations={"30":dict(state="DEMAND_FIRST")})) for _ in range(10)]
        r=evaluate_destination(train,test,30)
        self.assertEqual(r["accuracy"],0)
        self.assertEqual(r["training_n"],120)
        self.assertEqual(len(r["daily_block_brier_improvement_ci95"]),2)
        self.assertGreater(r["multiclass_brier"],1)

    def test_insufficient_labels_not_reported_as_trained_model(self):
        _,_,f=features()
        row=dict(features=f,labels=dict(destinations={"30":dict(state="NEITHER")}))
        self.assertEqual(evaluate_destination([row],[row],30)["state"],"INSUFFICIENT_PAIRED_HISTORY")

    def test_bad_ohlc_rejected(self):
        data=frame();data.loc[2,"high"]=90
        with self.assertRaisesRegex(ValueError,"invalid OHLC"):validate_frame(data)

    def test_zone_detector_prefix_consistency(self):
        rng=np.random.default_rng(17)
        n=60*24*4; prices=100+np.cumsum(rng.normal(0,.3,n))
        data=pd.DataFrame(dict(timestamp=pd.date_range(AT,periods=n,freq="min"),open=prices,high=prices+.2,low=prices-.2,close=prices))
        cutoff=pd.Timestamp(AT)+pd.Timedelta(days=3)
        full={z.zone_id:z for z in causal_build_zones(data) if pd.Timestamp(z.available_at)<=cutoff}
        prefix={z.zone_id:z for z in causal_build_zones(data[data.timestamp<cutoff]) if pd.Timestamp(z.available_at)<=cutoff}
        self.assertTrue(full)
        self.assertEqual(full,prefix)

    def test_training_excludes_unmature_outcomes(self):
        d=build_dataset(frame(),target_year=2024,zones=[zone(),zone("SHORT","S")])
        for r in d["rows"]:r["mature_at"]="2025-01-02T00:00:00Z"
        empty=dict(research_version=VERSION,year=2025,rows=[],zone_outcome_catalog=[],price_end="2025-12-31")
        result=aggregate([d,empty])
        self.assertEqual(result["folds"][1]["train_snapshots"],0)

if __name__=="__main__":unittest.main()
