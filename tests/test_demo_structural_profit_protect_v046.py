from fx_scanner.demo_structural_profit_protector import (
    _signal_id_from_comment,
    evaluate_profit_protect,
)
from fx_scanner.technical import DisplacementSignal, StructureSnapshot


def _snapshot(*, trend="RANGE", bos=None, mss=None, disp_direction=None, disp_valid=False):
    displacement = None
    if disp_direction is not None:
        displacement = DisplacementSignal(
            direction=disp_direction,
            body_ratio=2.0,
            range_atr_ratio=1.5,
            close_location=0.9,
            tick_activity_ratio=1.2,
            valid=disp_valid,
        )
    return StructureSnapshot(
        trend=trend,
        last_swing_high=1.2,
        last_swing_low=1.1,
        bos=bos,
        mss=mss,
        displacement=displacement,
        fvg=None,
        sweep=None,
    )


def test_profitable_long_closes_only_on_confirmed_bearish_m5_and_m15():
    decision = evaluate_profit_protect(
        side="BUY",
        net_floating_pnl=1.25,
        m5=_snapshot(mss="BEARISH"),
        m15=_snapshot(trend="BEARISH", disp_direction="BEARISH", disp_valid=True),
    )
    assert decision.close is True
    assert decision.opposite_direction == "BEARISH"
    assert decision.m5_transition is True
    assert decision.m15_confirmation is True


def test_profitable_short_closes_only_on_confirmed_bullish_m5_and_m15():
    decision = evaluate_profit_protect(
        side="SELL",
        net_floating_pnl=0.75,
        m5=_snapshot(bos="BULLISH", disp_direction="BULLISH", disp_valid=True),
        m15=_snapshot(mss="BULLISH"),
    )
    assert decision.close is True
    assert decision.opposite_direction == "BULLISH"


def test_no_close_when_trade_not_in_net_profit():
    decision = evaluate_profit_protect(
        side="BUY",
        net_floating_pnl=0.0,
        m5=_snapshot(mss="BEARISH"),
        m15=_snapshot(mss="BEARISH"),
    )
    assert decision.close is False
    assert decision.reason == "NOT_IN_NET_PROFIT"


def test_no_close_on_m5_only_reversal_without_m15_confirmation():
    decision = evaluate_profit_protect(
        side="BUY",
        net_floating_pnl=2.0,
        m5=_snapshot(mss="BEARISH"),
        m15=_snapshot(trend="BULLISH", disp_direction="BULLISH", disp_valid=True),
    )
    assert decision.close is False
    assert decision.reason == "M15_REVERSAL_NOT_CONFIRMED"


def test_bos_without_displacement_is_not_a_confirmed_m5_transition():
    decision = evaluate_profit_protect(
        side="SELL",
        net_floating_pnl=1.0,
        m5=_snapshot(bos="BULLISH", disp_direction="BULLISH", disp_valid=False),
        m15=_snapshot(mss="BULLISH"),
    )
    assert decision.close is False
    assert decision.reason == "NO_CONFIRMED_M5_REVERSAL"


def test_only_exact_scanner_comment_yields_signal_id():
    signal_id = "12345678-1234-5678-1234-567812345678"
    assert _signal_id_from_comment(f"FXIS:{signal_id}", "FXIS") == signal_id
    assert _signal_id_from_comment(signal_id, "FXIS") is None
    assert _signal_id_from_comment(f"OTHER:{signal_id}", "FXIS") is None
    assert _signal_id_from_comment("FXIS:not-a-uuid", "FXIS") is None
