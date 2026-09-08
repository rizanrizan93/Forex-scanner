from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from .execution.models import OrderIntent, OrderSide

UTC = timezone.utc


def _float(value: Any, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"DEMO_STACK_{name}_INVALID") from exc
    if not isfinite(parsed):
        raise ValueError(f"DEMO_STACK_{name}_NONFINITE")
    return parsed


def _position_side_code(position: Any) -> int:
    trade_data = getattr(position, "tradeData", None)
    return int(getattr(trade_data, "tradeSide", 0) or 0)


def _position_opened_at(position: Any) -> datetime | None:
    trade_data = getattr(position, "tradeData", None)
    raw = int(getattr(trade_data, "openTimestamp", 0) or 0)
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw / 1000.0, tz=UTC)


def _position_lots(position: Any, symbol_info: Any) -> float:
    trade_data = getattr(position, "tradeData", None)
    raw_volume = int(getattr(trade_data, "volume", 0) or 0)
    lot_size = int(getattr(symbol_info, "lotSize", 0) or 0)
    if raw_volume <= 0 or lot_size <= 0:
        raise ValueError("DEMO_STACK_BROKER_VOLUME_INVALID")
    return float(raw_volume) / float(lot_size)


def evaluate_same_symbol_stack(
    *,
    row: dict[str, Any],
    intent: OrderIntent,
    same_symbol_positions: tuple[Any, ...],
    symbol_info: Any,
    demo_safety: dict[str, Any],
) -> str | None:
    """Return a fail-closed reason when a same-symbol stack is not permitted.

    A second/third position is permitted only for a fresh, independently claimed
    EXECUTION_READY signal whose live execution intent already passed the base
    quote/geometry/RR checks. Stacks must remain same-direction, high-conviction,
    protected, spaced apart, and inside a bounded per-symbol position/lot cap.
    """
    if not same_symbol_positions:
        return None
    if not bool(demo_safety.get("allow_same_symbol_stacking", False)):
        return f"BROKER_SYMBOL_ALREADY_OPEN:{intent.symbol}"

    score = _float(row.get("final_score"), name="SCORE")
    coverage = _float(row.get("data_coverage"), name="COVERAGE")
    rr2 = _float(row.get("rr2"), name="RR2")
    min_score = _float(demo_safety.get("stack_min_score", 85.0), name="MIN_SCORE")
    min_coverage = _float(
        demo_safety.get("stack_min_coverage", 0.90), name="MIN_COVERAGE"
    )
    min_rr2 = _float(demo_safety.get("stack_min_rr2", 2.0), name="MIN_RR2")
    if score < min_score:
        return f"BROKER_STACK_SCORE_BELOW_MIN:{score:.2f}/{min_score:.2f}"
    if coverage < min_coverage:
        return f"BROKER_STACK_COVERAGE_BELOW_MIN:{coverage:.3f}/{min_coverage:.3f}"
    if rr2 < min_rr2:
        return f"BROKER_STACK_RR_BELOW_MIN:{rr2:.3f}/{min_rr2:.3f}"

    max_positions = int(demo_safety.get("max_same_symbol_positions", 3))
    if len(same_symbol_positions) >= max_positions:
        return f"BROKER_SYMBOL_STACK_CAP:{len(same_symbol_positions)}/{max_positions}"

    expected_side = 1 if intent.side == OrderSide.BUY else 2
    for position in same_symbol_positions:
        side_code = _position_side_code(position)
        if side_code not in {1, 2}:
            return "BROKER_STACK_EXISTING_SIDE_UNKNOWN"
        if side_code != expected_side:
            return f"BROKER_SYMBOL_OPPOSITE_EXPOSURE:{intent.symbol}"

    min_spacing = _float(
        demo_safety.get("min_stack_spacing_seconds", 300.0), name="MIN_SPACING"
    )
    if min_spacing > 0:
        opened = tuple(
            timestamp
            for timestamp in (_position_opened_at(position) for position in same_symbol_positions)
            if timestamp is not None
        )
        if len(opened) != len(same_symbol_positions):
            return "BROKER_STACK_OPEN_TIME_UNKNOWN"
        newest = max(opened)
        spacing = (intent.created_at.astimezone(UTC) - newest).total_seconds()
        if spacing < min_spacing:
            return f"BROKER_STACK_SPACING_TOO_SHORT:{max(0.0, spacing):.1f}/{min_spacing:.1f}"

    max_symbol_lots = _float(
        demo_safety.get(
            "max_same_symbol_lots",
            float(demo_safety.get("max_order_lots", 0.10)) * max_positions,
        ),
        name="MAX_SYMBOL_LOTS",
    )
    existing_lots = sum(
        _position_lots(position, symbol_info) for position in same_symbol_positions
    )
    if existing_lots + float(intent.volume) > max_symbol_lots + 1e-9:
        return (
            "BROKER_SYMBOL_LOT_CAP:"
            f"{existing_lots + float(intent.volume):.3f}/{max_symbol_lots:.3f}"
        )
    return None


def install_demo_conditional_stacking() -> None:
    """Install DEMO-only high-conviction stacking without weakening base safety."""
    from .execution.demo_autotrade import CTraderDemoAutoExecutor

    if getattr(CTraderDemoAutoExecutor, "_demo_conditional_stacking_installed", False):
        return

    original_intent_diagnostic = CTraderDemoAutoExecutor._intent_diagnostic
    original_exposure_block = CTraderDemoAutoExecutor._broker_exposure_block

    def _intent_diagnostic_with_stack_context(self, row, *, now):
        intent, reason = original_intent_diagnostic(self, row, now=now)
        if intent is None:
            self._demo_stack_context = None
        else:
            self._demo_stack_context = (dict(row), intent)
        return intent, reason

    def _broker_exposure_block_with_conditional_stack(self, symbol: str):
        if not bool(self.demo.get("allow_same_symbol_stacking", False)):
            return original_exposure_block(self, symbol)

        try:
            open_positions = int(self.gateway.position_count())
        except Exception as exc:
            return f"BROKER_POSITION_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"

        max_positions = int(self.demo.get("max_concurrent_positions", 1))
        if open_positions >= max_positions:
            return f"BROKER_CAPACITY_FULL:{open_positions}/{max_positions}"

        context = getattr(self, "_demo_stack_context", None)
        if not context or len(context) != 2:
            return "BROKER_STACK_CONTEXT_MISSING"
        row, intent = context
        if str(intent.symbol).upper() != str(symbol).upper():
            return "BROKER_STACK_CONTEXT_SYMBOL_MISMATCH"

        session = getattr(self.gateway, "session", None)
        if session is None:
            return "BROKER_STACK_SESSION_UNAVAILABLE"
        try:
            session.ensure_connected()
            symbol_info = session.symbol_info(symbol)
            target_symbol_id = int(symbol_info.symbolId)
            reconcile = session.reconcile()
            same_symbol_positions: list[Any] = []
            for position in tuple(getattr(reconcile, "position", ())):
                position_id = int(getattr(position, "positionId", 0) or 0)
                stop_loss = float(getattr(position, "stopLoss", 0.0) or 0.0)
                take_profit = float(getattr(position, "takeProfit", 0.0) or 0.0)
                if stop_loss <= 0.0 or take_profit <= 0.0:
                    return f"BROKER_POSITION_UNPROTECTED:{position_id or 'UNKNOWN'}"
                trade_data = getattr(position, "tradeData", None)
                position_symbol_id = getattr(trade_data, "symbolId", None)
                if position_symbol_id is not None and int(position_symbol_id) == target_symbol_id:
                    same_symbol_positions.append(position)

            return evaluate_same_symbol_stack(
                row=row,
                intent=intent,
                same_symbol_positions=tuple(same_symbol_positions),
                symbol_info=symbol_info,
                demo_safety=self.demo,
            )
        except ValueError as exc:
            return str(exc)
        except Exception as exc:
            return f"BROKER_SYMBOL_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}"

    CTraderDemoAutoExecutor._intent_diagnostic = _intent_diagnostic_with_stack_context
    CTraderDemoAutoExecutor._broker_exposure_block = _broker_exposure_block_with_conditional_stack
    CTraderDemoAutoExecutor._demo_conditional_stacking_installed = True
