from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .exceptions import CollectorUnavailable
from .research_xau_m15_continuation_tournament import PIP_SIZE
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .research_xau_multihorizon_100usd_v20 import (
    ARTIFACT_CONTRACT,
    BrokerLotSpec,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_v20,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_multihorizon_100usd_v20"
HISTORY_TARGET = 130_000
MIN_HISTORY = 100_000
PAGE_BARS = 5_000
MAX_PAGES = 30
TIMEFRAME_SECONDS = 900


def _fetch_source_exhausted(feed, *, as_of: datetime):
    merged = {}
    cursor = as_of
    pages = []
    previous_earliest = None
    for page in range(1, MAX_PAGES + 1):
        remaining = HISTORY_TARGET - len(merged)
        if remaining <= 0:
            break
        count = min(PAGE_BARS, remaining)
        try:
            got = tuple(
                feed.historical_bars(
                    SYMBOL,
                    "M15",
                    from_time=cursor - timedelta(seconds=count * TIMEFRAME_SECONDS * 3),
                    to_time=cursor,
                    count=count,
                )
            )
        except CollectorUnavailable as exc:
            pages.append(
                {
                    "page": page,
                    "requested": count,
                    "received": 0,
                    "merged": len(merged),
                    "terminal": f"COLLECTOR_UNAVAILABLE:{exc}",
                }
            )
            break
        if not got:
            break
        for row in got:
            merged[row.timestamp] = row
        earliest = min(x.timestamp for x in got)
        latest = max(x.timestamp for x in got)
        pages.append(
            {
                "page": page,
                "requested": count,
                "received": len(got),
                "merged": len(merged),
                "earliest": earliest.isoformat(),
                "latest": latest.isoformat(),
            }
        )
        if previous_earliest is not None and earliest >= previous_earliest:
            break
        previous_earliest = earliest
        cursor = earliest - timedelta(seconds=1)

    rows = tuple(sorted(merged.values(), key=lambda x: x.timestamp))
    closed = tuple(
        x for x in rows
        if x.timestamp.astimezone(UTC) + timedelta(seconds=TIMEFRAME_SECONDS) <= as_of
    )
    return closed[-HISTORY_TARGET:] if len(closed) > HISTORY_TARGET else closed, pages


def _margin_usd(feed, symbol_info, *, lot: float) -> tuple[float, int, int]:
    lot_size = int(getattr(symbol_info, "lotSize", 0) or 0)
    if lot_size <= 0:
        raise SystemExit("V20_XAU_LOT_SIZE_UNAVAILABLE")
    volume_cents = int(round(float(lot) * lot_size))
    response = feed._session.expected_margin(int(symbol_info.symbolId), volume_cents)
    margins = tuple(getattr(response, "margin", ()))
    if not margins:
        raise SystemExit("V20_EXPECTED_MARGIN_UNAVAILABLE")
    row = margins[0]
    raw = int(getattr(row, "buyMargin", 0) or getattr(row, "sellMargin", 0) or 0)
    if raw <= 0:
        raise SystemExit("V20_EXPECTED_MARGIN_INVALID")
    digits = int(getattr(response, "moneyDigits", 0) or 0)
    value = float(raw) / (10 ** digits) if digits > 0 else float(raw)
    return value, digits, volume_cents


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V20_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V20_REQUIRE_DEMO")

    pair = next((p for p in cfg.pairs if p.symbol == SYMBOL), None)
    if pair is None:
        raise SystemExit("V20_XAU_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    validation = _validation_cfg()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_source_exhausted(feed, as_of=now)
        info = feed.symbol_info(SYMBOL)
        margin_001, margin_digits, volume_001 = _margin_usd(
            feed, info, lot=0.01
        )
    finally:
        # Keep the symbol metadata gathered before closing the session.
        try:
            feed.close()
        except Exception:
            pass

    spread = infer_spread_proxy_pips(bars, pip_size=float(pair.pip_size)) if bars else {
        "available": False,
        "coverage": 0.0,
        "median_pips": None,
    }
    details: dict[str, Any] = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
        "history_target_bars": HISTORY_TARGET,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
        "spread_proxy": spread,
    }

    if len(bars) < MIN_HISTORY or not bool(spread.get("available")):
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": (
                f"M15_HISTORY_BELOW_MINIMUM:{len(bars)}<{MIN_HISTORY}"
                if len(bars) < MIN_HISTORY
                else "CTRADER_SPREAD_PROXY_UNAVAILABLE"
            ),
            "promotion_eligible": False,
        }
    else:
        base_costs, stress_costs = _costs(
            validation, float(spread["median_pips"])
        )
        lot_size = int(getattr(info, "lotSize", 0) or 0)
        min_volume = int(getattr(info, "minVolume", 0) or 0)
        max_volume = int(getattr(info, "maxVolume", 0) or 0)
        step_volume = int(getattr(info, "stepVolume", 0) or 0)
        reference_price = float(bars[-1].close)
        broker_spec = BrokerLotSpec(
            lot_size_cents=lot_size,
            min_volume_cents=min_volume,
            max_volume_cents=max_volume,
            step_volume_cents=step_volume,
            expected_margin_001_usd=float(margin_001),
            margin_money_digits=margin_digits,
            reference_price=reference_price,
        )
        details["broker_raw"] = {
            "symbol_id": int(info.symbolId),
            "digits": int(getattr(info, "digits", 0) or 0),
            "lot_size_cents": lot_size,
            "min_volume_cents": min_volume,
            "max_volume_cents": max_volume,
            "step_volume_cents": step_volume,
            "volume_001_cents": volume_001,
            "expected_margin_001_usd": margin_001,
            "margin_money_digits": margin_digits,
        }
        details["decision"] = evaluate_v20(
            bars,
            pip_size=float(pair.pip_size),
            base_costs=base_costs,
            stressed_costs=stress_costs,
            broker_spec=broker_spec,
        )

    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(
        os.getenv(
            "V20_EVIDENCE_OUTPUT",
            "artifacts/xau-multihorizon-100usd-v20.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": details,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )

    d = details["decision"]
    if d.get("stage") == "DATA_INSUFFICIENT":
        print(
            f"V20 stage=DATA_INSUFFICIENT reason={d['reason']} artifact={path}"
        )
    else:
        print(
            "V20_RESULT "
            f"m15={d['history']['m15_rows']} "
            f"selected={d['selected_portfolio']} "
            f"lot001={int(d['broker_001_lot']['lot_feasible_001'])} "
            f"margin001={d['broker_001_lot']['expected_margin_001_usd']} "
            f"promotion_eligible=0 artifact={path}"
        )
        for row in d["portfolio_candidates"]:
            dm = row["development_stressed"]
            hm = row["holdout_stressed"]
            hf = row["holdout_frequency"]
            print(
                "V20_PORT "
                f"id={row['portfolio_id']} "
                f"dev_n={dm['completed_trades']} dev_pf={dm['profit_factor']} "
                f"dev_exp={dm['expectancy_r']} "
                f"hold_n={hm['completed_trades']} hold_pf={hm['profit_factor']} "
                f"hold_exp={hm['expectancy_r']} "
                f"hold_mean={hf['mean_trades_per_day']} "
                f"hold_ge5={hf['days_ge_5_fraction']} "
                f"concurrency={row['holdout_concurrency']['max_active']}"
            )
        cash = d.get("cash_simulation_holdout")
        if cash:
            for key, row in cash.items():
                print(
                    "V20_CASH "
                    f"mode={key} opened={row['opened_trades']} "
                    f"skipped_margin={row['skipped_margin']} "
                    f"ending={row['ending_balance_usd']} "
                    f"return_pct={row['return_pct']} "
                    f"max_dd={row['max_realized_drawdown_usd']} "
                    f"worst_stop_equity={row['minimum_worst_case_equity_at_planned_stops_usd']} "
                    f"ruin={int(row['ruin'])} hit1000={int(row['hit_1000'])}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
