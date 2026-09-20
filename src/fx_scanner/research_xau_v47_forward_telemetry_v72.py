from __future__ import annotations

RESEARCH_VERSION = "XAU_V47_FORWARD_TELEMETRY_V72"
ARTIFACT_CONTRACT = "XAU_V47_FORWARD_TELEMETRY_V72_CONTRACT_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

TELEMETRY_CONTRACT = {
    "primary_forward_hypothesis_changed": False,
    "primary_grouping_changed": False,
    "primary_groups": ["SWEEP", "NON_SWEEP"],
    "secondary_telemetry_only": {
        "h1_structure": [
            "swing_structure_state",
            "last_break_event",
            "bars_since_last_break",
            "last_confirmed_swing_high",
            "last_confirmed_swing_low",
        ],
        "h1_volatility": [
            "vol_state",
            "atr14",
            "atr_to_prior_median",
        ],
        "prior_day_realized_skew": [
            "skew_state",
            "realized_skew",
            "realized_variance",
            "intraday_returns",
        ],
    },
    "secondary_features_may_change_primary_decision": False,
    "execution_authority": False,
    "live_money": False,
    "flexible_lot_enabled": False,
}
