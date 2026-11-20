"""Synthetic regression fixtures: not historical hit-rate evidence."""
import math
import pandas as pd
from fx_scanner.fed_r63_liquidity_stress import assess_liquidity_stress, CONTRACT
from fx_scanner.fed_r63_macro_price_divergence import evaluate_divergence

NOW=pd.Timestamp("2026-11-20T10:00:10Z")


def bars():
    idx=pd.date_range(end="2026-11-20T10:00:00Z", periods=36, freq="5min")
    rows=[]
    for i in range(len(idx)):
        c=100.0 + .08 * math.sin(i)
        rows.append({"open":c-.05,"high":c+.50,"low":c-.50,"close":c})
    return pd.DataFrame(rows,index=idx)


def case_down():
    d=bars()
    for i,c in zip((-3,-2,-1),(98.7,97.1,95.4)):
        opening=float(d.close.iloc[i-1])
        d.iloc[i]=[opening,max(opening,c)+.25,min(opening,c)-.25,c]
    return d


def case_up():
    d=bars()
    for i,c in zip((-3,-2,-1),(101.5,103.0,104.6)):
        opening=float(d.close.iloc[i-1])
        d.iloc[i]=[opening,max(opening,c)+.25,min(opening,c)-.25,c]
    return d


def test_downside_displacement_is_not_asserted_forced_liquidation():
    x=assess_liquidity_stress(case_down(),now=NOW)
    assert x["contract"]==CONTRACT
    assert x["state"]=="DOWNSIDE_DISPLACEMENT"
    assert x["risk_veto"] is True
    assert x["liquidation_confirmed"] is False
    assert x["volume_confirmation"] is False
    assert x["open_interest_confirmation"] is False
    assert x["entry_permission"] is False


def test_upside_displacement_also_vetoes_fomo_entries():
    x=assess_liquidity_stress(case_up(),now=NOW)
    assert x["state"]=="UPSIDE_DISPLACEMENT"
    assert x["risk_veto"] is True


def test_sweep_below_old_low_reclaims_is_not_same_as_breakdown():
    d=bars()
    d.iloc[-1]=[100.,100.8,98.,100.3]
    x=assess_liquidity_stress(d,now=NOW)
    assert x["state"]=="SWEEP_LOW_RECLAIM"
    assert x["risk_veto"] is True


def test_sweep_above_old_high_rejects_is_not_same_as_rally():
    d=bars()
    d.iloc[-1]=[100.,103.,99.5,99.8]
    x=assess_liquidity_stress(d,now=NOW)
    assert x["state"]=="SWEEP_HIGH_REJECT"
    assert x["risk_veto"] is True


def test_normal_market_does_not_invent_liquidation_pressure():
    x=assess_liquidity_stress(bars(),now=NOW)
    assert x["state"]=="NORMAL"
    assert x["risk_veto"] is False


def test_wide_spread_overrides_pattern_and_vetoes_chasing():
    x=assess_liquidity_stress(bars(),now=NOW,spread=1.0)
    assert x["state"]=="WIDE_SPREAD"
    assert x["risk_veto"] is True


def test_missing_gapped_stale_and_future_m5_fail_closed():
    b=bars()
    assert assess_liquidity_stress(b.iloc[:10],now=NOW)["state"]=="UNKNOWN"
    assert assess_liquidity_stress(b.drop(b.index[-10]),now=NOW)["state"]=="UNKNOWN"
    assert assess_liquidity_stress(b,now=NOW-pd.Timedelta(minutes=15))["state"]=="UNKNOWN"
    assert assess_liquidity_stress(b,now=NOW+pd.Timedelta(hours=1))["state"]=="UNKNOWN"


def macro(side="SELL"):
    return {"contract":"RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1",
            "direction":side,"daily_direction":side,"entry_permission":False}


def price(side="SELL",liq=None):
    return {
        "contract":"RIZAN_XAU_FED_R6_MANUAL_AREA_V1",
        "status":"WATCH",
        "as_of":"2026-11-20T10:00:10Z",
        "price":95.4,
        "quote_at":"2026-11-20T10:00:05Z",
        "last_closed_m1":"2026-11-20T10:00:00Z",
        "bias_m15":side,"bias_h1":side,"bias_h4":"UNKNOWN",
        "entry_allowed":False,"authority_to_send_orders":False,
        "liquidity_context":liq,
    }


def test_r63_aligned_macro_price_blocked_if_displacement():
    x=evaluate_divergence(macro(),price(liq=assess_liquidity_stress(case_down(),now=NOW)))
    assert x["liquidity_state"]=="DOWNSIDE_DISPLACEMENT"
    assert x["liquidity_risk_veto"] is True
    assert x["display_direction"]=="WAIT"
    assert x["watch_side"]=="SELL"
    assert x["state"]=="WAIT_LIQUIDITY_STRESS"
    assert x["entry_permission"] is False


def test_r63_macro_price_conflict_still_waits_and_marks_liquidity():
    x=evaluate_divergence(macro("BUY"),price(liq=assess_liquidity_stress(case_down(),now=NOW)))
    assert x["state"]=="MACRO_PRICE_DIVERGENCE"
    assert x["display_direction"]=="WAIT"
    assert x["liquidity_risk_veto"] is True


def test_r63_normal_bars_preserve_readonly_direction():
    x=evaluate_divergence(macro(),price(liq=assess_liquidity_stress(bars(),now=NOW)))
    assert x["state"]=="MACRO_AND_PRICE_ALIGNED_WATCH"
    assert x["display_direction"]=="SELL"
    assert x["entry_permission"] is False


def test_r63_unknown_m5_does_not_upgrade_to_direction():
    x=evaluate_divergence(macro(),price(liq=assess_liquidity_stress(bars().iloc[:5],now=NOW)))
    assert x["state"]=="WAIT_LIQUIDITY_DATA_INCOMPLETE"
    assert x["display_direction"]=="WAIT"


def test_r63_rejects_untrusted_liquidity_contract():
    x=evaluate_divergence(macro(),price(liq={"contract":"BAD","risk_veto":False}))
    assert x["state"]=="WAIT_UNTRUSTED_LIQUIDITY_CLASSIFIER"
    assert x["display_direction"]=="WAIT"


def test_post_stress_cooldown_survives_one_normal_m5_bar():
    d=bars()
    d.iloc[-2]=[100.,105.,95.,100.]
    x=assess_liquidity_stress(d,now=NOW)
    assert x["state"]=="POST_STRESS_COOLDOWN"
    assert x["risk_veto"] is True
    assert x["stress_age_bars"]==1
    assert x["prior_stress_state"] in ("SWEEP_LOW_RECLAIM","VOLATILITY_SPIKE")


def test_post_stress_cooldown_expires_after_three_completed_m5_bars():
    d=bars()
    d.iloc[-5]=[100.,105.,95.,100.]
    x=assess_liquidity_stress(d,now=NOW)
    assert x["state"]=="NORMAL"
    assert x["risk_veto"] is False
