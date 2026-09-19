from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .research_xau_margin_leverage_v21_runtime import _dynamic_leverage, _expected_margin
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec
from .research_xau_multihorizon_100usd_v20_runtime import _fetch_source_exhausted
from .research_xau_100usd_stopout_v23 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_v23,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_100usd_stopout_v23"


def _margin_call_thresholds(feed):
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAMarginCallListReq
    req = ProtoOAMarginCallListReq()
    req.ctidTraderAccountId = int(feed._session.account_id)
    res = feed._session._send_sync(req, client_msg_id=f"mcall-{uuid4().hex}")
    output = []
    for row in tuple(getattr(res, "marginCall", ())):
        threshold_ratio = float(getattr(row, "marginLevelThreshold", 0.0) or 0.0)
        call_type = int(getattr(row, "marginCallType", 0) or 0)
        if threshold_ratio > 0:
            output.append({
                "type": call_type,
                "threshold_ratio": threshold_ratio,
                "threshold_pct": threshold_ratio * 100.0,
            })
    return output


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V23_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V23_REQUIRE_DEMO")
    pair = next((p for p in cfg.pairs if p.symbol == SYMBOL), None)
    if pair is None:
        raise SystemExit("V23_XAU_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    validation = _validation_cfg()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_source_exhausted(feed, as_of=now)
        info = feed.symbol_info(SYMBOL)
        tiers = _dynamic_leverage(feed, int(getattr(info, "leverageId", 0) or 0))
        margin = _expected_margin(feed, info, 0.01)
        margin_calls = _margin_call_thresholds(feed)
        trader = feed._session.trader()
        trader_stopout = {
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
    lot_size = int(getattr(info, "lotSize", 0) or 0)
    broker_spec = BrokerLotSpec(
        lot_size_cents=lot_size,
        min_volume_cents=int(getattr(info, "minVolume", 0) or 0),
        max_volume_cents=int(getattr(info, "maxVolume", 0) or 0),
        step_volume_cents=int(getattr(info, "stepVolume", 0) or 0),
        expected_margin_001_usd=float(margin["max_margin_usd"]),
        margin_money_digits=int(margin["money_digits"]),
        reference_price=float(bars[-1].close),
    )
    decision = evaluate_v23(
        bars,
        pip_size=float(pair.pip_size),
        base_costs=base_costs,
        stressed_costs=stress_costs,
        broker_spec=broker_spec,
        leverage_tiers=tiers,
        broker_margin_call_thresholds=[x["threshold_pct"] for x in margin_calls],
    )
    decision["broker_margin_call_rows"] = margin_calls
    decision["trader_stopout"] = trader_stopout

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

    path = Path(os.getenv("V23_EVIDENCE_OUTPUT", "artifacts/xau-100usd-stopout-v23.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        "V23_RESULT "
        f"stopout={decision['stopout_pct_used']} "
        f"margin_calls={json.dumps(margin_calls, sort_keys=True)} "
        f"fair={int(trader_stopout['fair_stop_out'])} "
        f"strategy={trader_stopout['stop_out_strategy']} "
        f"artifact={path} promotion_eligible=0"
    )
    for portfolio_id,payload in decision["portfolio_scenarios"].items():
        for row in payload["scenarios"]:
            print(
                "V23_SCENARIO "
                f"portfolio={portfolio_id} lev={row['account_leverage']} "
                f"opened={row['opened_trades']} margin_skip={row['margin_skips']} "
                f"stopout_skip={row['stopout_guard_skips']} "
                f"ending={row['ending_balance_usd']} return_pct={row['return_pct']} "
                f"dd_pct={row['max_realized_drawdown_pct']} "
                f"min_balance={row['minimum_realized_balance_usd']} "
                f"max_active={row['max_active_positions']} "
                f"min_stop_margin_level={row['minimum_planned_stop_margin_level_pct']} "
                f"ruin={int(row['ruin'])} hit1000={int(row['hit_1000'])} "
                f"mean_day={row['mean_accepted_trades_per_day']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
