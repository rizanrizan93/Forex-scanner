from __future__ import annotations
from typing import Any, Mapping, Sequence

from .models import Bar, ensure_utc
from .research_xau_100usd_bootstrap_v89 import _assemble
from .research_xau_100usd_leverage_v22 import _cash_path
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec, _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_pullback_bootstrap_v91 import transform_v87_satellite

RESEARCH_VERSION="XAU_UNBOUNDED_RISK_V94"
ARTIFACT_CONTRACT="XAU_UNBOUNDED_RISK_V94_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
ACCOUNT_LEVERAGE=100.0
LOT_MODES=("FIXED_001","BALANCE_STEP_100")
VARIANTS=("V87_NEXT_OPEN","V91_DISPLACEMENT_50_RETEST_4")

def evaluate_v94(
    bars:Sequence[Bar],*,evaluation_start,evaluation_end,pip_size:float,
    costs:M15ResearchCosts,broker_spec:BrokerLotSpec,
    leverage_tiers:Sequence[LeverageTier],
)->dict[str,Any]:
    rows=tuple(sorted(bars,key=lambda x:ensure_utc(x.timestamp)))
    start=ensure_utc(evaluation_start); end=ensure_utc(evaluation_end)
    _,satellite,_,change_points,gates=_assemble(rows,costs=costs,pip_size=pip_size,end=end)
    baseline=tuple(t for t in satellite if start<=ensure_utc(t.entry_at)<end)
    displacement=transform_v87_satellite(
        rows,baseline,variant_id="DISPLACEMENT_50_RETEST_4",costs=costs
    )
    dates=_trading_dates(rows,start=start,end=end)
    streams={"V87_NEXT_OPEN":baseline,"V91_DISPLACEMENT_50_RETEST_4":displacement}
    results={}
    for vid,trades in streams.items():
        results[vid]={}
        for lot_mode in LOT_MODES:
            results[vid][lot_mode]=_cash_path(
                trades,spec=broker_spec,tiers=leverage_tiers,
                account_leverage=ACCOUNT_LEVERAGE,lot_mode=lot_mode,
                trading_dates=dates,
            )
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "starting_balance_usd":100.0,
            "account_leverage":ACCOUNT_LEVERAGE,
            "risk_pct_filter":None,
            "planned_stop_guard":False,
            "broker_stopout_model":False,
            "margin_to_open_only":True,
            "lot_modes":list(LOT_MODES),
            "warning":"THEORETICAL_MARGIN_ONLY_PATH_NOT_BROKER_SURVIVABILITY_REALISTIC",
        },
        "change_points":list(change_points),
        "gates":gates,
        "variants":results,
    }
