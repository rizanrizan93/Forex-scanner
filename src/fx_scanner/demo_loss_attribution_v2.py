from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

LOSS_EXITS = {"SL_HIT", "STOP_OUT", "STRUCTURAL_PROTECT_LOSS"}
DECISIVE_EXITS = LOSS_EXITS | {"TP_HIT", "STRUCTURAL_PROTECT_PROFIT"}


@dataclass(frozen=True, slots=True)
class LossAttributionFinding:
    code: str
    scope: str
    evidence_count: int
    eligible_losses: int
    rate: float
    severity: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "scope": self.scope,
            "evidence_count": self.evidence_count,
            "eligible_losses": self.eligible_losses,
            "rate": round(self.rate, 4),
            "severity": self.severity,
            "detail": self.detail,
        }


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


def _scope(payload: dict[str, Any]) -> str:
    return "|".join(
        (
            _text(payload, "symbol"),
            _text(payload, "setup_type"),
            _text(payload, "direction"),
            _text(payload, "regime"),
        )
    )


def _evidence_score(payload: dict[str, Any], name: str) -> float | None:
    scores = payload.get("evidence_scores")
    if not isinstance(scores, dict):
        return None
    try:
        value = float(scores.get(name))
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _row_flags(payload: dict[str, Any]) -> set[str]:
    """Return candidate loss explanations without asserting causality."""
    if _text(payload, "exit_type", "") not in LOSS_EXITS:
        return set()
    flags: set[str] = set()
    setup = _text(payload, "setup_type")
    regime = _text(payload, "regime")
    confirmation = _text(payload, "confirmation", "LEGACY")
    pullback = _number(payload, "pullback_atr")
    drift = _number(payload, "live_entry_drift_r")
    mae_r = _number(payload, "mae_r")
    mfe_r = _number(payload, "mfe_r")
    rr2 = _number(payload, "rr2")
    realized_r = _number(payload, "realized_r")
    structure_score = _evidence_score(payload, "structure")

    if setup == "TREND_CONTINUATION" and regime in {"RANGE", "REVERSAL", "MIXED"}:
        flags.add("REGIME_SETUP_MISMATCH_PROBABLE")
    if confirmation in {"LEGACY", "NONE", "UNKNOWN", "UNCONFIRMED"}:
        flags.add("WEAK_CONFIRMATION_PROBABLE")
    if pullback is not None and pullback < 0.20:
        flags.add("ENTRY_TOO_EARLY_PROBABLE")
    if drift is not None and drift > 0.30:
        flags.add("CHASE_ENTRY_PROBABLE")
    if mae_r is not None and mfe_r is not None and mae_r <= -0.90 and mfe_r >= 0.75:
        flags.add("STOP_TOO_TIGHT_PROBABLE")
    if mfe_r is not None and mfe_r >= 1.00 and (realized_r is None or realized_r <= 0.25):
        flags.add("PROFIT_GIVEBACK_PROBABLE")
    if rr2 is not None and mfe_r is not None and rr2 >= 2.0 and mfe_r < 0.75:
        flags.add("TP_TOO_AMBITIOUS_PROBABLE")
    if (
        structure_score is not None
        and structure_score >= 70.0
        and regime in {"TREND_STRONG", "TREND_WEAK"}
        and ((drift is not None and drift > 0.30) or confirmation in {"LEGACY", "NONE", "UNKNOWN"})
    ):
        flags.add("GOOD_SETUP_BAD_EXECUTION_PROBABLE")
    return flags


def build_loss_attribution_v2(rows: Iterable[dict[str, Any]]) -> tuple[LossAttributionFinding, ...]:
    """Aggregate repeated loss explanations; never mutate strategy from one trade."""
    grouped_losses: dict[str, int] = {}
    grouped_flags: dict[tuple[str, str], int] = {}
    global_losses = 0
    global_flags: dict[str, int] = {}

    for row in rows:
        payload = _payload(dict(row))
        exit_type = _text(payload, "exit_type", "")
        if exit_type not in DECISIVE_EXITS:
            continue
        if exit_type not in LOSS_EXITS:
            continue
        scope = _scope(payload)
        flags = _row_flags(payload)
        grouped_losses[scope] = grouped_losses.get(scope, 0) + 1
        global_losses += 1
        for code in flags:
            grouped_flags[(scope, code)] = grouped_flags.get((scope, code), 0) + 1
            global_flags[code] = global_flags.get(code, 0) + 1

    findings: list[LossAttributionFinding] = []
    for (scope, code), count in grouped_flags.items():
        losses = grouped_losses.get(scope, 0)
        if count < 3 or losses < 3:
            continue
        rate = count / losses
        if rate < 0.50:
            continue
        findings.append(
            LossAttributionFinding(
                code=code,
                scope=scope,
                evidence_count=count,
                eligible_losses=losses,
                rate=rate,
                severity="HIGH" if count >= 5 and rate >= 0.60 else "WATCH",
                detail=f"repeated on {count}/{losses} losses; correlation only, not causal proof",
            )
        )

    for code, count in global_flags.items():
        if count < 5 or global_losses < 5:
            continue
        rate = count / global_losses
        if rate < 0.40:
            continue
        findings.append(
            LossAttributionFinding(
                code=code,
                scope="GLOBAL",
                evidence_count=count,
                eligible_losses=global_losses,
                rate=rate,
                severity="HIGH" if count >= 10 and rate >= 0.60 else "WATCH",
                detail=f"repeated on {count}/{global_losses} losses globally; requires cohort validation before policy change",
            )
        )

    return tuple(
        sorted(
            findings,
            key=lambda item: (
                1 if item.severity == "HIGH" else 0,
                item.evidence_count,
                item.rate,
                item.code,
                item.scope,
            ),
            reverse=True,
        )
    )
