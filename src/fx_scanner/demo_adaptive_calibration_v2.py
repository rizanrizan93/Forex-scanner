from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

SYSTEM_WINS = {"TP_HIT", "STRUCTURAL_PROTECT_PROFIT"}
SYSTEM_LOSSES = {"SL_HIT", "STOP_OUT", "STRUCTURAL_PROTECT_LOSS"}
SYSTEM_BREAKEVENS = {
    "BREAKEVEN",
    "PROTECTION_CLOSE_BREAKEVEN",
    "STRUCTURAL_PROTECT_BREAKEVEN",
}
V2_REQUIRED_SNAPSHOT_FIELDS = (
    "symbol",
    "direction",
    "setup_type",
    "entry_mode",
    "confirmation",
    "regime",
)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload")
    return dict(value) if isinstance(value, dict) else {}


def _text(payload: dict[str, Any], key: str, default: str = "UNKNOWN") -> str:
    return str(payload.get(key, default) or default).upper()


def _number(payload: dict[str, Any], key: str) -> float | None:
    try:
        value = float(payload.get(key))
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def calibration_v2_stage(decisive: int) -> str:
    if decisive < 10:
        return "OBSERVE"
    if decisive < 20:
        return "GATE_ADAPT"
    if decisive < 50:
        return "PATTERN_ADAPT"
    if decisive < 100:
        return "SLTP_SHADOW"
    return "BOUNDED_SLTP_READY"


@dataclass(frozen=True, slots=True)
class V2CohortKey:
    symbol: str
    setup: str
    direction: str
    regime: str
    entry_mode: str
    confirmation: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "V2CohortKey":
        return cls(
            symbol=_text(payload, "symbol"),
            setup=_text(payload, "setup_type"),
            direction=_text(payload, "direction"),
            regime=_text(payload, "regime"),
            entry_mode=_text(payload, "entry_mode", "LEGACY"),
            confirmation=_text(payload, "confirmation", "LEGACY"),
        )

    def compact(self) -> str:
        return "|".join(
            (
                self.symbol,
                self.setup,
                self.direction,
                self.regime,
                self.entry_mode,
                self.confirmation,
            )
        )


@dataclass(frozen=True, slots=True)
class V2CohortStats:
    decisive: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    net_pnl: float = 0.0
    r_sum: float = 0.0
    r_count: int = 0
    pullback_sum: float = 0.0
    pullback_count: int = 0
    drift_sum: float = 0.0
    drift_count: int = 0
    mae_sum: float = 0.0
    mae_count: int = 0
    mfe_sum: float = 0.0
    mfe_count: int = 0

    @property
    def win_rate(self) -> float | None:
        return None if self.decisive <= 0 else self.wins / self.decisive

    @property
    def avg_r(self) -> float | None:
        return None if self.r_count <= 0 else self.r_sum / self.r_count

    @property
    def avg_pullback_atr(self) -> float | None:
        return None if self.pullback_count <= 0 else self.pullback_sum / self.pullback_count

    @property
    def avg_live_drift_r(self) -> float | None:
        return None if self.drift_count <= 0 else self.drift_sum / self.drift_count

    @property
    def avg_mae_r(self) -> float | None:
        return None if self.mae_count <= 0 else self.mae_sum / self.mae_count

    @property
    def avg_mfe_r(self) -> float | None:
        return None if self.mfe_count <= 0 else self.mfe_sum / self.mfe_count


@dataclass(frozen=True, slots=True)
class V2Diagnostic:
    code: str
    scope: str
    evidence_count: int
    severity: str
    detail: str


@dataclass(frozen=True, slots=True)
class AdaptiveCalibrationV2Report:
    stage: str
    decisive: int
    snapshot_coverage: float
    cohorts: dict[str, V2CohortStats]
    diagnostics: tuple[V2Diagnostic, ...]
    automatic_gate_mutation_allowed: bool
    automatic_pattern_mutation_allowed: bool
    automatic_sltp_mutation_allowed: bool

    def details(self) -> dict[str, Any]:
        ordered = sorted(
            self.cohorts.items(),
            key=lambda item: (item[1].decisive, item[0]),
            reverse=True,
        )
        return {
            "mode": "DEMO_ADAPTIVE_CALIBRATION_V2",
            "stage": self.stage,
            "decisive": self.decisive,
            "snapshot_coverage": round(self.snapshot_coverage, 4),
            "automatic_gate_mutation_allowed": self.automatic_gate_mutation_allowed,
            "automatic_pattern_mutation_allowed": self.automatic_pattern_mutation_allowed,
            "automatic_sltp_mutation_allowed": self.automatic_sltp_mutation_allowed,
            "cohorts": {
                key: {
                    "decisive": stats.decisive,
                    "wins": stats.wins,
                    "losses": stats.losses,
                    "win_rate": stats.win_rate,
                    "net_pnl": stats.net_pnl,
                    "avg_r": stats.avg_r,
                    "avg_pullback_atr": stats.avg_pullback_atr,
                    "avg_live_drift_r": stats.avg_live_drift_r,
                    "avg_mae_r": stats.avg_mae_r,
                    "avg_mfe_r": stats.avg_mfe_r,
                }
                for key, stats in ordered[:50]
            },
            "diagnostics": [
                {
                    "code": item.code,
                    "scope": item.scope,
                    "evidence_count": item.evidence_count,
                    "severity": item.severity,
                    "detail": item.detail,
                }
                for item in self.diagnostics
            ],
        }


def _realized_r(payload: dict[str, Any]) -> float | None:
    direct = _number(payload, "realized_r")
    if direct is not None:
        return max(-10.0, min(10.0, direct))
    direction = _text(payload, "direction", "")
    entry_low = _number(payload, "entry_low")
    entry_high = _number(payload, "entry_high")
    stop = _number(payload, "planned_sl")
    exit_price = _number(payload, "exit_price")
    if (
        direction not in {"LONG", "SHORT"}
        or entry_low is None
        or entry_high is None
        or stop is None
        or exit_price is None
        or entry_low <= 0
        or entry_high < entry_low
    ):
        return None
    entry = (entry_low + entry_high) / 2.0
    risk = abs(entry - stop)
    if risk <= 1e-12:
        return None
    value = (exit_price - entry) / risk if direction == "LONG" else (entry - exit_price) / risk
    return max(-10.0, min(10.0, value)) if isfinite(value) else None


def _add(stats: V2CohortStats, payload: dict[str, Any]) -> V2CohortStats:
    exit_type = _text(payload, "exit_type", "")
    win = exit_type in SYSTEM_WINS
    loss = exit_type in SYSTEM_LOSSES
    breakeven = exit_type in SYSTEM_BREAKEVENS
    decisive = win or loss
    net = _number(payload, "net_pnl_estimate") or 0.0
    realized_r = _realized_r(payload)
    pullback = _number(payload, "pullback_atr")
    drift = _number(payload, "live_entry_drift_r")
    mae = _number(payload, "mae_r")
    if mae is None:
        mae = _number(payload, "sampled_mae_r")
    mfe = _number(payload, "mfe_r")
    if mfe is None:
        mfe = _number(payload, "sampled_mfe_r")
    return V2CohortStats(
        decisive=stats.decisive + int(decisive),
        wins=stats.wins + int(win),
        losses=stats.losses + int(loss),
        breakevens=stats.breakevens + int(breakeven),
        net_pnl=stats.net_pnl + net,
        r_sum=stats.r_sum + (0.0 if realized_r is None else realized_r),
        r_count=stats.r_count + int(realized_r is not None),
        pullback_sum=stats.pullback_sum + (0.0 if pullback is None else pullback),
        pullback_count=stats.pullback_count + int(pullback is not None),
        drift_sum=stats.drift_sum + (0.0 if drift is None else drift),
        drift_count=stats.drift_count + int(drift is not None),
        mae_sum=stats.mae_sum + (0.0 if mae is None else mae),
        mae_count=stats.mae_count + int(mae is not None),
        mfe_sum=stats.mfe_sum + (0.0 if mfe is None else mfe),
        mfe_count=stats.mfe_count + int(mfe is not None),
    )


def _diagnose(cohorts: dict[str, V2CohortStats]) -> tuple[V2Diagnostic, ...]:
    findings: list[V2Diagnostic] = []
    for scope, stats in cohorts.items():
        if stats.decisive < 5:
            continue
        win_rate = stats.win_rate
        if win_rate is not None and win_rate < 0.30:
            findings.append(
                V2Diagnostic(
                    code="COHORT_PERSISTENT_WEAKNESS",
                    scope=scope,
                    evidence_count=stats.decisive,
                    severity="HIGH" if stats.decisive >= 10 else "WATCH",
                    detail=f"win_rate={win_rate:.3f}; cohort should be penalized before any global strategy mutation",
                )
            )
        if stats.pullback_count >= 5 and stats.avg_pullback_atr is not None and stats.avg_pullback_atr < 0.20 and stats.losses > stats.wins:
            findings.append(
                V2Diagnostic(
                    code="ENTRY_TOO_EARLY_PROBABLE",
                    scope=scope,
                    evidence_count=stats.pullback_count,
                    severity="WATCH",
                    detail=f"avg_pullback_atr={stats.avg_pullback_atr:.3f} with losses>wins",
                )
            )
        if stats.drift_count >= 5 and stats.avg_live_drift_r is not None and stats.avg_live_drift_r > 0.30 and stats.losses > stats.wins:
            findings.append(
                V2Diagnostic(
                    code="CHASE_ENTRY_PROBABLE",
                    scope=scope,
                    evidence_count=stats.drift_count,
                    severity="WATCH",
                    detail=f"avg_live_drift_r={stats.avg_live_drift_r:.3f} with losses>wins",
                )
            )
        if (
            stats.mae_count >= 5
            and stats.mfe_count >= 5
            and stats.avg_mae_r is not None
            and stats.avg_mfe_r is not None
            and stats.avg_mae_r <= -0.90
            and stats.avg_mfe_r >= 1.00
            and stats.losses > stats.wins
        ):
            findings.append(
                V2Diagnostic(
                    code="STOP_TOO_TIGHT_PROBABLE",
                    scope=scope,
                    evidence_count=min(stats.mae_count, stats.mfe_count),
                    severity="SHADOW_ONLY",
                    detail=f"avg_mae_r={stats.avg_mae_r:.3f} avg_mfe_r={stats.avg_mfe_r:.3f}; do not mutate SL before 100 decisive trades",
                )
            )
    return tuple(sorted(findings, key=lambda item: (item.severity, item.evidence_count, item.code), reverse=True))


def build_adaptive_calibration_v2_report(rows: Iterable[dict[str, Any]]) -> AdaptiveCalibrationV2Report:
    rows = tuple(dict(row) for row in rows)
    cohorts: dict[str, V2CohortStats] = {}
    decisive = 0
    complete_snapshot = 0
    relevant = 0
    for row in rows:
        payload = _payload(row)
        exit_type = _text(payload, "exit_type", "")
        if exit_type not in SYSTEM_WINS | SYSTEM_LOSSES | SYSTEM_BREAKEVENS:
            continue
        relevant += 1
        if all(str(payload.get(field, "") or "").strip() for field in V2_REQUIRED_SNAPSHOT_FIELDS):
            complete_snapshot += 1
        key = V2CohortKey.from_payload(payload).compact()
        cohorts[key] = _add(cohorts.get(key, V2CohortStats()), payload)
        decisive += int(exit_type in SYSTEM_WINS or exit_type in SYSTEM_LOSSES)
    stage = calibration_v2_stage(decisive)
    coverage = 1.0 if relevant == 0 else complete_snapshot / relevant
    return AdaptiveCalibrationV2Report(
        stage=stage,
        decisive=decisive,
        snapshot_coverage=coverage,
        cohorts=cohorts,
        diagnostics=_diagnose(cohorts),
        automatic_gate_mutation_allowed=decisive >= 10,
        automatic_pattern_mutation_allowed=decisive >= 20,
        automatic_sltp_mutation_allowed=False,
    )
