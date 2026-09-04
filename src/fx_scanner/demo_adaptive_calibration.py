from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .demo_incremental_calibration import (
    CalibrationStats,
    summarize_closed_events,
    suggested_score_floor_penalty,
)

WAVE_ENTRY_MODES = frozenset({"HL_PULLBACK", "LH_PULLBACK", "MOMENTUM_CONTINUATION"})
LEGACY_ENTRY_MODE = "LEGACY"
DEFAULT_MAX_ADAPTIVE_FLOOR = 60.0
MIN_DECISIVE_FOR_MUTATION = 10


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload")
    return dict(value) if isinstance(value, dict) else {}


def _entry_mode(row: dict[str, Any]) -> str:
    return str(_payload(row).get("entry_mode", LEGACY_ENTRY_MODE) or LEGACY_ENTRY_MODE).upper()


def _stats_for(rows: Iterable[dict[str, Any]]) -> CalibrationStats:
    return summarize_closed_events(tuple(rows)).overall


def _penalty(stats: CalibrationStats) -> float:
    if stats.decisive_system < MIN_DECISIVE_FOR_MUTATION:
        return 0.0
    return suggested_score_floor_penalty(stats)


def _direction_stats(rows: Iterable[dict[str, Any]]) -> dict[str, CalibrationStats]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        direction = str(_payload(row).get("direction", "UNKNOWN") or "UNKNOWN").upper()
        grouped.setdefault(direction, []).append(row)
    return {key: _stats_for(value) for key, value in grouped.items()}


@dataclass(frozen=True, slots=True)
class AdaptiveCalibrationPolicy:
    enabled: bool
    base_floor: float
    max_floor: float
    global_penalty: float
    symbol_penalties: dict[str, float]
    setup_penalties: dict[str, float]
    direction_penalties: dict[str, float]
    wave_stats: CalibrationStats
    legacy_stats: CalibrationStats
    root_cause: str

    def required_score(self, row: dict[str, Any]) -> float:
        if not self.enabled:
            return self.base_floor
        symbol = str(row.get("symbol", "UNKNOWN") or "UNKNOWN").upper()
        setup = str(row.get("setup_type", "UNKNOWN") or "UNKNOWN").upper()
        direction = str(row.get("direction", "UNKNOWN") or "UNKNOWN").upper()
        penalty = max(
            self.global_penalty,
            self.symbol_penalties.get(symbol, 0.0),
            self.setup_penalties.get(setup, 0.0),
            self.direction_penalties.get(direction, 0.0),
        )
        return min(self.max_floor, self.base_floor + penalty)

    def details(self) -> dict[str, Any]:
        return {
            "mode": "DEMO_BOUNDED_ADAPTIVE_SCORE_FLOOR",
            "enabled": self.enabled,
            "base_score_floor": self.base_floor,
            "max_score_floor": self.max_floor,
            "global_penalty": self.global_penalty,
            "symbol_penalties": dict(sorted(self.symbol_penalties.items())),
            "setup_penalties": dict(sorted(self.setup_penalties.items())),
            "direction_penalties": dict(sorted(self.direction_penalties.items())),
            "wave_decisive": self.wave_stats.decisive_system,
            "wave_wins": self.wave_stats.wins,
            "wave_losses": self.wave_stats.losses,
            "wave_win_rate": self.wave_stats.win_rate,
            "legacy_decisive": self.legacy_stats.decisive_system,
            "legacy_wins": self.legacy_stats.wins,
            "legacy_losses": self.legacy_stats.losses,
            "legacy_win_rate": self.legacy_stats.win_rate,
            "legacy_excluded_from_mutation": True,
            "minimum_decisive_for_mutation": MIN_DECISIVE_FOR_MUTATION,
            "automatic_strategy_mutation": "DEMO_SCORE_FLOOR_ONLY",
            "risk_mutation": False,
            "sl_tp_mutation": False,
            "root_cause": self.root_cause,
        }


def build_adaptive_policy_from_rows(
    rows: Iterable[dict[str, Any]],
    *,
    base_floor: float,
    enabled: bool,
    max_floor: float = DEFAULT_MAX_ADAPTIVE_FLOOR,
) -> AdaptiveCalibrationPolicy:
    rows = tuple(dict(row) for row in rows)
    wave_rows = tuple(row for row in rows if _entry_mode(row) in WAVE_ENTRY_MODES)
    legacy_rows = tuple(row for row in rows if _entry_mode(row) == LEGACY_ENTRY_MODE)

    wave_summary = summarize_closed_events(wave_rows)
    legacy_summary = summarize_closed_events(legacy_rows)
    wave_stats = wave_summary.overall
    legacy_stats = legacy_summary.overall

    direction_stats = _direction_stats(wave_rows)
    global_penalty = _penalty(wave_stats)
    symbol_penalties = {
        symbol: _penalty(stats)
        for symbol, stats in wave_summary.by_symbol.items()
        if _penalty(stats) > 0.0
    }
    setup_penalties = {
        setup: _penalty(stats)
        for setup, stats in wave_summary.by_setup.items()
        if _penalty(stats) > 0.0
    }
    direction_penalties = {
        direction: _penalty(stats)
        for direction, stats in direction_stats.items()
        if _penalty(stats) > 0.0
    }

    if wave_stats.decisive_system < MIN_DECISIVE_FOR_MUTATION:
        root_cause = (
            "LEGACY_LOSS_DOMINANT"
            if legacy_stats.losses >= 5 and legacy_stats.losses > wave_stats.losses
            else "WAVE_SAMPLE_INSUFFICIENT"
        )
    elif global_penalty > 0.0:
        root_cause = "WAVE_WIN_RATE_BELOW_TARGET"
    else:
        root_cause = "NO_ADAPTIVE_PENALTY_REQUIRED"

    safe_base = float(base_floor)
    safe_max = max(safe_base, min(float(max_floor), DEFAULT_MAX_ADAPTIVE_FLOOR))
    return AdaptiveCalibrationPolicy(
        enabled=bool(enabled),
        base_floor=safe_base,
        max_floor=safe_max,
        global_penalty=global_penalty if enabled else 0.0,
        symbol_penalties=symbol_penalties if enabled else {},
        setup_penalties=setup_penalties if enabled else {},
        direction_penalties=direction_penalties if enabled else {},
        wave_stats=wave_stats,
        legacy_stats=legacy_stats,
        root_cause=root_cause,
    )


def load_adaptive_policy(
    store,
    *,
    account_id: str | None,
    base_floor: float,
    enabled: bool,
    limit: int = 200,
) -> AdaptiveCalibrationPolicy:
    query = (
        store.client.table("broker_order_events")
        .select("observed_at,account_id,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", "DEMO_TRADE_CLOSED")
        .order("observed_at", desc=True)
        .limit(int(limit))
    )
    if account_id:
        query = query.eq("account_id", str(account_id))
    response = query.execute()
    rows = tuple(dict(row) for row in (response.data or []))
    return build_adaptive_policy_from_rows(
        rows,
        base_floor=base_floor,
        enabled=enabled,
    )
