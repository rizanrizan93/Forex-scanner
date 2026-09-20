from __future__ import annotations

RESEARCH_VERSION = "XAU_V47_FORWARD_SWEEP_TELEMETRY_V82"
ARTIFACT_CONTRACT = "XAU_V47_FORWARD_SWEEP_TELEMETRY_V82_CONTRACT_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

SWEEP_TELEMETRY_CONTRACT = {
    "primary_forward_hypothesis_changed": False,
    "primary_grouping_changed": False,
    "v69_primary_groups": ["SWEEP", "NON_SWEEP"],
    "v77_target_groups_changed": False,
    "raw_fields_only": [
        "latest_sweep_at",
        "latest_sweep_age_m15_bars",
        "latest_sweep_source",
        "latest_sweep_level",
        "penetration_atr",
        "reclaim_atr",
        "body_atr",
        "close_location",
        "all_recent_sweep_events",
    ],
    "thresholds_added": False,
    "score_added": False,
    "feature_can_change_primary_decision": False,
    "execution_authority": False,
    "live_money": False,
    "flexible_lot_enabled": False,
}
