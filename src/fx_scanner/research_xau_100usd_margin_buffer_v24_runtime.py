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
from .research_xau_multihorizon_100usd_v20_runtime import _fetch_source_exhausted
from .research_xau_100usd_margin_buffer_v24 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_v24,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_100usd_margin_buffer_v24"


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V24_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V24_REQUIRE_DEMO")
    pair = next((p for p in cfg.pairs if p.symbol == SYMBOL), None)
    if pair is None:
        raise SystemExit("V24_XAU_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    validation = _validation_cfg()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_source_exhausted(feed, as_of=now)
        info = feed.symbol_info(SYMBOL)
        tiers = _dynamic_leverage(feed, int(getattr(info, "leverageId", 0) or 0))
        margin = _expected_margin(feed, info, 0.01)
        trader = feed._session.trader()
        account_meta = {
            "account_leverage": float(int(getattr(trader, "leverageInCents", 0) or 0)) / 100.0,
            "account_type": int(getattr(trader, "accountType", 0) or 0),
            "total_margin_calculation_type": int(getattr(trader, "totalMarginCalculationType", 0) or 0),
            "fair_stop_out": bool(getattr(trader, "fairStopOut", False)),
            "stop_out_strategy": int(getattr(trader, "stopOutStrategy", 0) or 0),
        }
    finally:
        try:
            feed.close()
        except Exception:
            pass

    spread = infer_spread_proxy_pips(bars, pip_size=float(pair.pip_size))
    base_costs, stress_costs = _costs(validation, float(spread["median_pips"]))
    broker_spec = BrokerLotSpec(
        lot_size_cents=int(getattr(info, "lotSize", 0) or 0),
        min_volume_cents=int(getattr(info, "minVolume", 0) or 0),
        max_volume_cents=int(getattr(info, "maxVolume", 0) or 0),
        step_volume_cents=int(getattr(info, "stepVolume", 0) or 0),
        expected_margin_001_usd=float(margin["max_margin_usd"]),
        margin_money_digits=int(margin["money_digits"]),
        reference_price=float(bars[-1].close),
    )
    decision = evaluate_v24(
        bars,
        pip_size=float(pair.pip_size),
        base_costs=base_costs,
        stressed_costs=stress_costs,
        broker_spec=broker_spec,
        leverage_tiers=tiers,
    )
    decision["current_account"] = account_meta

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

    path = Path(os.getenv("V24_EVIDENCE_OUTPUT", "artifacts/xau-100usd-margin-buffer-v24.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        "V24_RESULT "
        f"account={json.dumps(account_meta, sort_keys=True)} "
        f"tiers={json.dumps(decision['dynamic_leverage_tiers'], sort_keys=True)} "
        f"artifact={path} promotion_eligible=0"
    )
    for portfolio_id,payload in decision["portfolio_scenarios"].items():
        for row in payload["scenarios"]:
            print(
                "V24_SCENARIO "
                f"portfolio={portfolio_id} floor={row['planned_margin_floor_pct']} "
                f"lev={row['account_leverage']} opened={row['opened_trades']} "
                f"margin_skip={row['margin_skips']} guard_skip={row['stopout_guard_skips']} "
                f"ending={row['ending_balance_usd']} dd_pct={row['max_realized_drawdown_pct']} "
                f"min_balance={row['minimum_realized_balance_usd']} "
                f"max_active={row['max_active_positions']} "
                f"min_planned_margin={row['minimum_planned_stop_margin_level_pct']} "
                f"hit1000={int(row['hit_1000'])} mean_day={row['mean_accepted_trades_per_day']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
