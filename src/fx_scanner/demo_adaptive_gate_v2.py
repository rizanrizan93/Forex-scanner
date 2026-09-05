from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping

SYSTEM_WINS = {"TP_HIT", "STRUCTURAL_PROTECT_PROFIT"}
SYSTEM_LOSSES = {"SL_HIT", "STOP_OUT", "STRUCTURAL_PROTECT_LOSS"}
WAVE_ENTRY_MODES = {"HL_PULLBACK", "LH_PULLBACK", "MOMENTUM_CONTINUATION"}
MIN_GLOBAL_DECISIVE = 10
MIN_SNAPSHOT_COVERAGE = 0.80
MIN_SPECIFIC_DECISIVE = 5
MIN_PARENT_DECISIVE = 7
MIN_SETUP_REGIME_DECISIVE = 8


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("payload")
    return dict(value) if isinstance(value, dict) else {}


def _text(payload: Mapping[str, Any], key: str, default: str = "UNKNOWN") -> str:
    return str(payload.get(key, default) or default).upper()


def _complete_snapshot(payload: Mapping[str, Any]) -> bool:
    required = ("symbol", "setup_type", "direction", "regime", "entry_mode", "confirmation")
    complete_marker = bool(
        payload.get("v2_feature_snapshot_complete", False)
        or payload.get("snapshot_complete_for_regime", False)
    )
    return complete_marker and all(
        str(payload.get(key, "") or "").strip() for key in required
    )


@dataclass(frozen=True, slots=True)
class GateStats:
    decisive: int = 0
    wins: int = 0
    losses: int = 0

    @property
    def win_rate(self) -> float | None:
        return None if self.decisive <= 0 else self.wins / self.decisive


@dataclass(frozen=True, slots=True)
class GateDecision:
    required_score: float
    base_score: float
    penalty: float
    scope_level: str
    scope_key: str
    evidence_count: int
    win_rate: float | None
    active: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AdaptiveGateV2Policy:
    enabled: bool
    base_floor: float
    max_penalty: float
    snapshot_coverage: float
    wave_decisive: int
    scope_stats: Mapping[str, Mapping[str, GateStats]]
    signal_context: Mapping[str, Mapping[str, Any]]
    root_cause: str

    def _scope_candidates(self, context: Mapping[str, Any]) -> tuple[tuple[str, str, int], ...]:
        symbol = _text(context, "symbol")
        setup = _text(context, "setup_type")
        direction = _text(context, "direction")
        regime = _text(context, "regime")
        return (
            ("SYMBOL_SETUP_DIRECTION_REGIME", "|".join((symbol, setup, direction, regime)), MIN_SPECIFIC_DECISIVE),
            ("SETUP_DIRECTION_REGIME", "|".join((setup, direction, regime)), MIN_PARENT_DECISIVE),
            ("SETUP_REGIME", "|".join((setup, regime)), MIN_SETUP_REGIME_DECISIVE),
            ("GLOBAL", "GLOBAL", MIN_GLOBAL_DECISIVE),
        )

    def _penalty_for(self, stats: GateStats) -> float:
        if stats.decisive <= 0 or stats.win_rate is None:
            return 0.0
        evidence_cap = 2.5 if stats.decisive < 10 else self.max_penalty
        cap = min(self.max_penalty, evidence_cap)
        if stats.win_rate < 0.25:
            return cap
        if stats.win_rate < 0.35:
            return min(cap, 0.75 * self.max_penalty)
        if stats.win_rate < 0.45:
            return min(cap, 0.50 * self.max_penalty)
        return 0.0

    def decision(self, row: Mapping[str, Any]) -> GateDecision:
        base = float(self.base_floor)
        if not self.enabled:
            return GateDecision(base, base, 0.0, "NONE", "NONE", 0, None, False, self.root_cause)
        signal_id = str(row.get("id") or "").strip()
        context = self.signal_context.get(signal_id)
        if not isinstance(context, Mapping) or not _complete_snapshot(context):
            return GateDecision(base, base, 0.0, "NONE", "NONE", 0, None, False, "CURRENT_SIGNAL_SNAPSHOT_MISSING")

        for level, key, minimum in self._scope_candidates(context):
            stats = self.scope_stats.get(level, {}).get(key)
            if stats is None or stats.decisive < minimum:
                continue
            penalty = self._penalty_for(stats)
            return GateDecision(
                required_score=min(100.0, base + penalty),
                base_score=base,
                penalty=penalty,
                scope_level=level,
                scope_key=key,
                evidence_count=stats.decisive,
                win_rate=stats.win_rate,
                active=penalty > 0.0,
                reason="HIERARCHICAL_COHORT_GATE" if penalty > 0.0 else "COHORT_PERFORMANCE_ACCEPTABLE",
            )
        return GateDecision(base, base, 0.0, "NONE", "NONE", 0, None, False, "NO_ELIGIBLE_COHORT")

    def required_score(self, row: Mapping[str, Any]) -> float:
        return self.decision(row).required_score

    def details(self) -> dict[str, Any]:
        return {
            "mode": "DEMO_ADAPTIVE_GATE_V2_HIERARCHICAL",
            "enabled": self.enabled,
            "base_floor": self.base_floor,
            "max_penalty": self.max_penalty,
            "snapshot_coverage": self.snapshot_coverage,
            "minimum_snapshot_coverage": MIN_SNAPSHOT_COVERAGE,
            "wave_decisive": self.wave_decisive,
            "minimum_global_decisive": MIN_GLOBAL_DECISIVE,
            "hierarchy": [
                "symbol+setup+direction+regime",
                "setup+direction+regime",
                "setup+regime",
                "global",
            ],
            "penalty_stacking": False,
            "risk_mutation": False,
            "sl_tp_mutation": False,
            "production_mutation": False,
            "live_unlock": False,
            "root_cause": self.root_cause,
        }


def _increment(stats: GateStats, win: bool, loss: bool) -> GateStats:
    return GateStats(
        decisive=stats.decisive + int(win or loss),
        wins=stats.wins + int(win),
        losses=stats.losses + int(loss),
    )


def build_adaptive_gate_v2_policy(
    rows: Iterable[Mapping[str, Any]],
    *,
    signal_context: Mapping[str, Mapping[str, Any]],
    base_floor: float,
    enabled: bool,
) -> AdaptiveGateV2Policy:
    rows = tuple(dict(row) for row in rows)
    wave_relevant = 0
    complete_relevant = 0
    wave_decisive = 0
    levels: dict[str, dict[str, GateStats]] = {
        "SYMBOL_SETUP_DIRECTION_REGIME": {},
        "SETUP_DIRECTION_REGIME": {},
        "SETUP_REGIME": {},
        "GLOBAL": {},
    }

    for row in rows:
        payload = _payload(row)
        entry_mode = _text(payload, "entry_mode", "LEGACY")
        exit_type = _text(payload, "exit_type", "")
        if entry_mode not in WAVE_ENTRY_MODES or exit_type not in SYSTEM_WINS | SYSTEM_LOSSES:
            continue
        wave_relevant += 1
        if not _complete_snapshot(payload):
            continue
        complete_relevant += 1
        win = exit_type in SYSTEM_WINS
        loss = exit_type in SYSTEM_LOSSES
        wave_decisive += int(win or loss)
        symbol = _text(payload, "symbol")
        setup = _text(payload, "setup_type")
        direction = _text(payload, "direction")
        regime = _text(payload, "regime")
        keys = {
            "SYMBOL_SETUP_DIRECTION_REGIME": "|".join((symbol, setup, direction, regime)),
            "SETUP_DIRECTION_REGIME": "|".join((setup, direction, regime)),
            "SETUP_REGIME": "|".join((setup, regime)),
            "GLOBAL": "GLOBAL",
        }
        for level, key in keys.items():
            levels[level][key] = _increment(levels[level].get(key, GateStats()), win, loss)

    coverage = 1.0 if wave_relevant == 0 else complete_relevant / wave_relevant
    safe_base = float(base_floor)
    if not isfinite(safe_base) or safe_base < 0 or safe_base > 100:
        raise ValueError("ADAPTIVE_V2_BASE_FLOOR_INVALID")
    max_penalty = 0.0 if wave_decisive < 10 else 2.5 if wave_decisive < 20 else 5.0
    ready = bool(enabled and wave_decisive >= MIN_GLOBAL_DECISIVE and coverage >= MIN_SNAPSHOT_COVERAGE)
    if not enabled:
        root = "DISABLED"
    elif wave_decisive < MIN_GLOBAL_DECISIVE:
        root = "WAVE_SAMPLE_INSUFFICIENT"
    elif coverage < MIN_SNAPSHOT_COVERAGE:
        root = "SNAPSHOT_COVERAGE_INSUFFICIENT"
    else:
        root = "V2_GATE_READY"
    return AdaptiveGateV2Policy(
        enabled=ready,
        base_floor=safe_base,
        max_penalty=max_penalty,
        snapshot_coverage=coverage,
        wave_decisive=wave_decisive,
        scope_stats=levels,
        signal_context={str(k): dict(v) for k, v in signal_context.items()},
        root_cause=root,
    )


@dataclass(frozen=True, slots=True)
class CompositeAdaptiveScorePolicy:
    legacy_policy: Any
    v2_policy: AdaptiveGateV2Policy

    def _legacy_required_score(self, row: Mapping[str, Any]) -> float:
        if self.legacy_policy is None:
            return self.v2_policy.base_floor
        return float(self.legacy_policy.required_score(dict(row)))

    def required_score(self, row: Mapping[str, Any]) -> float:
        if self.v2_policy.enabled:
            decision = self.v2_policy.decision(row)
            if decision.reason == "CURRENT_SIGNAL_SNAPSHOT_MISSING":
                return self._legacy_required_score(row)
            return decision.required_score
        return self._legacy_required_score(row)

    def details(self) -> dict[str, Any]:
        return {
            "mode": "DEMO_ADAPTIVE_SCORE_POLICY_COMPOSITE",
            "active_policy": "V2" if self.v2_policy.enabled else "LEGACY_FALLBACK",
            "missing_current_snapshot_policy": "LEGACY_FALLBACK",
            "penalty_stacking": False,
            "v2": self.v2_policy.details(),
            "legacy_fallback_present": self.legacy_policy is not None,
            "risk_mutation": False,
            "sl_tp_mutation": False,
            "production_mutation": False,
            "live_unlock": False,
        }
