"""Shared, read-only structural admission for the dashboard and DEMO workers."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any



def evaluate_structure_admission(
    *, v226_heartbeat: dict[str, Any], atlas_heartbeat: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    reasons: list[str] = []
    ages: dict[str, float] = {}
    evaluations: dict[str, dict[str, Any]] = {}
    for name, heartbeat, max_age in (
        ("V226", v226_heartbeat, 600.0),
        ("ATLAS", atlas_heartbeat, 900.0),
    ):
        if heartbeat.get("healthy") is not True:
            reasons.append(name + "_UNHEALTHY")
        evaluation = dict(dict(heartbeat.get("details") or {}).get("evaluation") or {})
        evaluations[name] = evaluation
        # A fresh transport heartbeat must not make an old evaluation fresh.
        for label, value in (("HEARTBEAT", heartbeat.get("observed_at")),
                             ("EVALUATION", evaluation.get("as_of"))):
            try:
                timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("timezone missing")
                age = (now.astimezone(UTC) - timestamp.astimezone(UTC)).total_seconds()
            except (TypeError, ValueError):
                reasons.append(name + "_" + label + "_TIMESTAMP_MISSING")
                continue
            ages[name] = max(ages.get(name, 0.0), age)
            if age < -5.0:
                reasons.append(name + "_" + label + "_FUTURE")
            elif age > max_age:
                reasons.append(name + "_" + label + "_STALE")
    if reasons:
        return {"allowed": False, "reason": reasons[0], "reasons": reasons,
                "state": "STALE_WAIT", "canonical": {}}
    return {"allowed": True, "reason": "STRUCTURE_FRESH", "reasons": [],
            "state": "FRESH", "ages_seconds": ages}
