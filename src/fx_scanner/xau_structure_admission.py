"""Shared, read-only structural admission for the dashboard and DEMO workers."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .xau_canonical_decision_v240 import build_canonical_xau_decision


def evaluate_structure_admission(
    *, v226_heartbeat: dict[str, Any], atlas_heartbeat: dict[str, Any],
    live_price: float | None, now: datetime,
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
    atlas = evaluations["ATLAS"]
    projection = dict(atlas.get("m5_path_projection") or
                      dict(atlas.get("path_map") or {}).get("m5_path_projection") or {})
    micro = dict(atlas.get("micro_refinement") or {})
    active_path = dict(dict(atlas.get("path_map") or {}).get("active_path") or {})
    direction = (dict(projection.get("current_leg") or {}).get("direction")
                 or micro.get("direction") or active_path.get("reaction_direction"))
    canonical = build_canonical_xau_decision(
        v226_evaluation=evaluations["V226"], atlas_evaluation=atlas,
        price_now=live_price, path_direction=direction,
        v226_age_seconds=ages["V226"], atlas_age_seconds=ages["ATLAS"],
    )
    allowed = canonical.get("state") == "CANONICAL_PLAN_READY"
    return {"allowed": allowed, "state": canonical["state"],
            "reason": "STRUCTURE_READY" if allowed else canonical["state"],
            "reasons": canonical.get("conflicts", []) + canonical.get("remap_reasons", []),
            "canonical": canonical}
