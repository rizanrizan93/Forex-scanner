from fx_scanner.research_xau_fvg_ote_bootstrap_v93 import VARIANTS,PENDING_WINDOW_BARS,STARTING_BALANCE_USD,POLICY_EFFECT,EXECUTION_INFLUENCE,PROMOTION_ELIGIBLE,_zone_mid
def test_v93_contract():
    assert VARIANTS==("FVG_CE_4","OTE_MID_4","FVG_OTE_OVERLAP_MID_4")
    assert PENDING_WINDOW_BARS==4
    assert STARTING_BALANCE_USD==100.0
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
def test_zone_mid():
    assert _zone_mid(10.0,12.0)==11.0
    assert _zone_mid(None,12.0) is None

from datetime import datetime, timedelta, timezone

from fx_scanner.demo_donchian_adaptive_tournament import TournamentTrade
from fx_scanner.models import Bar
from fx_scanner.research_xau_fvg_ote_bootstrap_v93 import _simulate_limit_trade
from fx_scanner.research_xau_m15_dual_strategy import M15ResearchCosts


def test_v93_runtime_path_initializes_entry_index_before_context_slice():
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    bars=tuple(
        Bar(
            symbol="XAUUSD",timeframe="M15",timestamp=base+timedelta(minutes=15*i),
            open=2000.0,high=2001.0,low=1999.0,close=2000.0,
            tick_count=1,spread_avg=0.1,spread_max=0.1,
        )
        for i in range(40)
    )
    trade=TournamentTrade(
        "V18_L12_ADX12_D1_R150","XAUUSD","LONG",
        bars[20].timestamp,bars[21].timestamp,bars[22].timestamp,
        20,22,2000.0,2000.0,2.0,1990.0,2020.0,
        0.0,0.0,0.0,1,"TEST",
    )
    costs=M15ResearchCosts(
        spread_pips=1.0,slippage_pips=1.0,
        commission_pips_round_trip=0.0,swap_pips_per_day=0.0,
    )
    assert _simulate_limit_trade(
        bars,trade,variant_id="FVG_CE_4",costs=costs
    ) is None
