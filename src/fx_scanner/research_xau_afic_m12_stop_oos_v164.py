from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_afic_m12_vs_m15_v162 import resample_bars
from . import research_xau_afic_m12_stop_geometry_v163 as v163

RESEARCH_VERSION="XAU_AFIC_M12_STOP_OOS_V164"
ARTIFACT_CONTRACT="XAU_AFIC_M12_STOP_OOS_V164_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
LIVE_EXECUTION_ENABLED=False

# Frozen before inspecting this sample. 2025-2026YTD was used by V163 and is excluded.
HOLDOUT_START=datetime(2023,1,1,tzinfo=timezone.utc)
HOLDOUT_END=datetime(2025,1,1,tzinfo=timezone.utc)
STOP_VARIANTS=v163.STOP_VARIANTS
LOCAL_BUFFER_ATR=v163.LOCAL_BUFFER_ATR


def evaluate_v164(m1_rows:Sequence[Bar])->dict[str,Any]:
    rows=tuple(sorted(m1_rows,key=lambda x:ensure_utc(x.timestamp)))
    m15=resample_bars(rows,minutes=15,timeframe="M15")
    m12=resample_bars(rows,minutes=12,timeframe="M12")

    # Expand only the evaluation start; map selector, zone construction, M12 confirmation,
    # target geometry, four stop definitions and 0.05 ATR buffer remain byte-for-byte V163 logic.
    old_start=v163.EVAL_START
    try:
        v163.EVAL_START=HOLDOUT_START
        confirmations=v163._collect_confirmations(m15,m12,evaluation_end=HOLDOUT_END)
    finally:
        v163.EVAL_START=old_start

    confirmations=tuple(c for c in confirmations if HOLDOUT_START<=ensure_utc(c["scenario"].map_at)<HOLDOUT_END)
    details={variant:[v163._evaluate(c,variant) for c in confirmations] for variant in STOP_VARIANTS}
    summary={variant:v163._summarize(vals) for variant,vals in details.items()}

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":LIVE_EXECUTION_ENABLED,
        "holdout":{"start":HOLDOUT_START.isoformat(),"end":HOLDOUT_END.isoformat(),"overlaps_v163_sample":False},
        "confirmation_count":len(confirmations),
        "stop_variants":list(STOP_VARIANTS),
        "local_buffer_atr":LOCAL_BUFFER_ATR,
        "summary":summary,
        "details":details,
        "interpretation_contract":{
            "sample_predeclared_before_result":True,
            "v163_sample_excluded":True,
            "map_zone_m12_confirmation_frozen":True,
            "stop_definitions_frozen":True,
            "target_geometry_frozen":True,
            "public_afic_exact_sl_formula_known":False,
            "no_same_sample_stop_promotion":True,
            "observer_change_allowed":False,
            "purpose":"independent historical falsification/validation of V163 stop geometry only",
        },
    }
