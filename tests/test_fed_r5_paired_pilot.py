"""R5 retrospective macro-to-V4 paired pilot integrity (synthetic unit data)."""
import pandas as pd
import pytest
from scripts.replay_fed_r5_paired_pilot import replay

def sample():
    idx=pd.date_range(end="2023-09-20T22:00:00Z",periods=6800,
                      freq="min",tz="UTC")
    raw=pd.DataFrame({"open":100.0,"high":101.0,"low":99.0,"close":100.0},
                     index=idx)
    at="2023-09-20T19:30:00Z"
    event={
        "event_id":"FOMC-2023-09-20-1","window":"FULL_MONETARY",
        "window_end_utc":at,
        "release_at_utc":"2023-09-20T18:00:00Z",
        "r4_source_join":"VERIFIED_DATE_WINDOW_AND_EVENT_CLOCK",
        "r4_features":{"MP2":3.0,"TIPS10Y":2.0,"DXY":.2,
                       "OIS1Y":2.0,"SP500":-.3}
    }
    manifest={"source":"HISTDATA_XAUUSD_M1",
              "failed_periods":[],"sha256_csv":"SYNTHETIC_UNIT_PRICE_NOT_REAL"}
    return raw,manifest,event

def test_pilot_never_promotes_expost_macro_to_realtime_trade():
    d,manifest,event=sample()
    out=replay(d,manifest=manifest,event=event,expost_source_sha="OFFICIAL_UNIT_SHA")
    assert out["macro_oracle_directions"]["MP2_TIPS10_DXY"]=="SELL"
    assert out["macro_oracle_directions"]["POLICY_OIS1Y_TIPS10_SP500_VETO"]=="SELL"
    assert out["true_macro_pit_buy_n"]==0 and out["true_macro_pit_sell_n"]==0
    assert out["production_eligible"] is False
    assert out["authority_to_execute"] is False
    assert out["counters"].get("screened_m1_closes",0)>0

def test_official_window_must_match_exact():
    d,m,e=sample()
    e["r4_source_join"]="UNRESOLVED_AMBIGUOUS_OR_MISSING"
    with pytest.raises(ValueError,match="UNTRUSTED_OFFICIAL"):
        replay(d,manifest=m,event=e,expost_source_sha="sha")

def test_no_fake_price_source():
    d,m,e=sample()
    m["failed_periods"]=[{"period":"September 2023","reason":"not downloaded"}]
    with pytest.raises(ValueError,match="SOURCE_MANIFEST_REJECTED"):
        replay(d,manifest=m,event=e,expost_source_sha="sha")

def test_missing_m1_offset_never_inferred():
    d,m,e=sample()
    d.index=d.index.tz_localize(None)
    with pytest.raises(ValueError,match="UNTRUSTED_HISTORICAL"):
        replay(d,manifest=m,event=e,expost_source_sha="sha")

def test_window_never_exceeds_validity_of_original_fomc_macro():
    d,m,e=sample()
    out=replay(d,manifest=m,event=e,expost_source_sha="sha")
    assert out["actual_scan_end_exclusive_utc"]=="2023-09-20T20:30:00+00:00"
    assert out["research_macro_expiry_utc"]=="2023-09-20T20:30:00+00:00"
    assert out["counters"].get("screened_m1_closes",0)<=60

def test_extra_long_emergency_fomc_ends_after_macro_expiry_no_entry():
    d,m,e=sample()
    e["release_at_utc"]="2023-09-20T16:00:00Z"
    out=replay(d,manifest=m,event=e,expost_source_sha="sha")
    assert out["completed_window_macro_context_still_valid"] is False
    assert out["counters"]["macro_expired_before_completed_communication_window"]==1
    assert out["counters"].get("screened_m1_closes",0)==0
    assert out["production_eligible"] is False

def test_r6_causal_pivot_and_continuation_risk_audit_observational_only():
    d,m,e=sample()
    out=replay(d,manifest=m,event=e,expost_source_sha="sha")
    assert out["r6_pivot_and_h1_risk_are_AB_OBSERVATIONS_ONLY"] is True
    assert out["production_eligible"] is False
    assert out["true_macro_pit_buy_n"]==0
    assert out["true_macro_pit_sell_n"]==0
    assert out["counters"].get("r6_pivot_BUY_old_room_only_recovered_n",0)>=0
    assert out["counters"].get("r6_pivot_SELL_old_room_only_recovered_n",0)>=0
