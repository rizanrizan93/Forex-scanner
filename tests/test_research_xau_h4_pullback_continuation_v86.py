from pathlib import Path

from fx_scanner.research_xau_h4_pullback_continuation_v86 import (
    COST_R_CAP,
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    H4_EMA_FAST,
    H4_EMA_MID,
    H4_EMA_SLOW,
    MAX_HOLD_H4_BARS,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    TARGET_R,
    _signal_side,
)

ROOT=Path(__file__).resolve().parents[1]


def test_v86_is_shadow_only_and_single_frozen_variant():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True
    assert (H4_EMA_FAST,H4_EMA_MID,H4_EMA_SLOW)==(20,50,200)
    assert TARGET_R==2.0
    assert MAX_HOLD_H4_BARS==6
    assert COST_R_CAP==0.10


def test_v86_long_pullback_reclaim_shape():
    previous={"close":99.0,"ema20":100.0}
    current={
        "close":102.0,
        "low":98.0,
        "high":103.0,
        "ema20":101.0,
        "ema50":95.0,
        "ema200":90.0,
    }
    d1={"secular_side":1,"regime_side":1}
    assert _signal_side(previous=previous,current=current,d1=d1)==1


def test_v86_rejects_wrong_d1_direction():
    previous={"close":99.0,"ema20":100.0}
    current={
        "close":102.0,
        "low":98.0,
        "high":103.0,
        "ema20":101.0,
        "ema50":95.0,
        "ema200":90.0,
    }
    d1={"secular_side":-1,"regime_side":-1}
    assert _signal_side(previous=previous,current=current,d1=d1)==0


def test_v86_has_no_grid_search_or_execution_path():
    src=(ROOT/"src/fx_scanner/research_xau_h4_pullback_continuation_v86.py").read_text()
    runtime=(ROOT/"src/fx_scanner/research_xau_h4_pullback_continuation_v86_runtime.py").read_text()
    combined=src+"\n"+runtime
    assert '"parameter_grid_search": False' in src
    assert '"alternate_target_variants": False' in src
    assert '"alternate_stop_variants": False' in src
    assert '"selection_uses_future_outcomes": False' in src
    assert "send_new_order" not in combined
    assert "claim_signal_for_execution" not in combined
