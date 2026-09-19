from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .research_xau_margin_leverage_v21_runtime import _dynamic_leverage, _expected_margin
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec
from .research_xau_multihorizon_100usd_v20_runtime import (
    _fetch_source_exhausted,
)
from .research_xau_100usd_leverage_v22 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_v22,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_100usd_leverage_v22"


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V22_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V22_REQUIRE_DEMO")

    pair = next((p for p in cfg.pairs if p.symbol == SYMBOL), None)
    if pair is None:
        raise SystemExit("V22_XAU_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    validation = _validation_cfg()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_source_exhausted(feed, as_of=now)
        info = feed.symbol_info(SYMBOL)
        tiers = _dynamic_leverage(feed, int(getattr(info, "leverageId", 0) or 0))
        margin = _expected_margin(feed, info, 0.01)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    spread = infer_spread_proxy_pips(bars, pip_size=float(pair.pip_size))
    if len(bars) < 100_000 or not bool(spread.get("available")):
        decision = {
            "stage": "DATA_INSUFFICIENT",
            "history_bars": len(bars),
            "promotion_eligible": False,
        }
    else:
        base_costs, stress_costs = _costs(validation, float(spread["median_pips"]))
        lot_size = int(getattr(info, "lotSize", 0) or 0)
        min_volume = int(getattr(info, "minVolume", 0) or 0)
        max_volume = int(getattr(info, "maxVolume", 0) or 0)
        step_volume = int(getattr(info, "stepVolume", 0) or 0)
        broker_spec = BrokerLotSpec(
            lot_size_cents=lot_size,
            min_volume_cents=min_volume,
            max_volume_cents=max_volume,
            step_volume_cents=step_volume,
            expected_margin_001_usd=float(margin["max_margin_usd"]),
            margin_money_digits=int(margin["money_digits"]),
            reference_price=float(bars[-1].close),
        )
        decision = evaluate_v22(
            bars,
            pip_size=float(pair.pip_size),
            base_costs=base_costs,
            stressed_costs=stress_costs,
            broker_spec=broker_spec,
            leverage_tiers=tiers,
        )

    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
        "history_pages": pages,
        "spread_proxy": spread,
        "decision": decision,
    }
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME, healthy=True, lag_seconds=0.0, details=details
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(os.getenv("V22_EVIDENCE_OUTPUT", "artifacts/xau-100usd-leverage-v22.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    d = decision
    if d.get("stage") == "DATA_INSUFFICIENT":
        print(f"V22 stage=DATA_INSUFFICIENT bars={d['history_bars']} artifact={path}")
        return 0

    print(
        "V22_RESULT "
        f"m15={d['history']['m15_rows']} "
        f"tiers={json.dumps(d['dynamic_leverage_tiers'], sort_keys=True)} "
        f"artifact={path} promotion_eligible=0"
    )
    for portfolio_id, payload in d["portfolio_scenarios"].items():
        for row in payload["scenarios"]:
            print(
                "V22_SCENARIO "
                f"portfolio={portfolio_id} lev={row['account_leverage']} "
                f"mode={row['lot_mode']} opened={row['opened_trades']} "
                f"skip_margin={row['margin_skips']} ending={row['ending_balance_usd']} "
                f"return_pct={row['return_pct']} dd={row['max_realized_drawdown_usd']} "
                f"dd_pct={row['max_realized_drawdown_pct']} "
                f"min_balance={row['minimum_realized_balance_usd']} "
                f"max_active={row['max_active_positions']} "
                f"worst_stop_equity={row['minimum_worst_case_equity_at_planned_stops_usd']} "
                f"stop_below0={row['planned_stop_equity_below_zero_events']} "
                f"ruin={int(row['ruin'])} hit1000={int(row['hit_1000'])} "
                f"mean_day={row['mean_accepted_trades_per_day']} "
                f"days_ge5={row['days_ge_5_fraction']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
