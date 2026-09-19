from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_margin_leverage_v21 import (
    ARTIFACT_CONTRACT,
    LOT,
    RESEARCH_VERSION,
    SYMBOL,
    LeverageTier,
    MarginSnapshot,
    evaluate_margin,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_margin_leverage_v21"


def _money(raw: int | float, digits: int) -> float:
    return float(raw) / (10 ** int(digits or 0))


def _expected_margin(feed, info, lot: float) -> dict:
    lot_size = int(getattr(info, "lotSize", 0) or 0)
    volume = int(round(float(lot) * lot_size))
    res = feed._session.expected_margin(int(info.symbolId), volume)
    rows = tuple(getattr(res, "margin", ()))
    if not rows:
        raise SystemExit("V21_EXPECTED_MARGIN_EMPTY")
    row = rows[0]
    digits = int(getattr(res, "moneyDigits", 0) or 0)
    buy = _money(int(getattr(row, "buyMargin", 0) or 0), digits)
    sell = _money(int(getattr(row, "sellMargin", 0) or 0), digits)
    return {
        "volume_cents": volume,
        "money_digits": digits,
        "buy_margin_usd": buy,
        "sell_margin_usd": sell,
        "max_margin_usd": max(buy, sell),
    }


def _dynamic_leverage(feed, leverage_id: int) -> tuple[LeverageTier, ...]:
    if leverage_id <= 0:
        return ()
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAGetDynamicLeverageByIDReq,
    )

    req = ProtoOAGetDynamicLeverageByIDReq()
    req.ctidTraderAccountId = int(feed._session.account_id)
    req.leverageId = int(leverage_id)
    res = feed._session._send_sync(
        req,
        client_msg_id=f"lev-{uuid4().hex}",
    )
    entity = getattr(res, "leverage", None)
    if entity is None:
        return ()
    tiers = []
    for row in tuple(getattr(entity, "tiers", ())):
        # Protocol volume is USD cents.
        volume_usd = float(int(getattr(row, "volume", 0) or 0)) / 100.0
        raw_leverage = int(getattr(row, "leverage", 0) or 0)
        # cTrader leverage is represented in cents in account metadata and the
        # broker's dynamic-leverage payload follows the same observed scaling.
        # Example: raw 50000 => 1:500, not 1:50000.
        leverage = float(raw_leverage) / 100.0
        if volume_usd > 0 and leverage > 0:
            tiers.append(LeverageTier(volume_usd, leverage))
    return tuple(tiers)


def _latest_reference_price(feed) -> float:
    now = datetime.now(tz=UTC)
    rows = feed.historical_bars(
        SYMBOL,
        "M15",
        from_time=now - timedelta(days=7),
        to_time=now,
        count=500,
    )
    if not rows:
        raise SystemExit("V21_REFERENCE_PRICE_UNAVAILABLE")
    return float(rows[-1].close)


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V21_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V21_REQUIRE_DEMO")

    if SYMBOL not in {p.symbol for p in cfg.pairs}:
        raise SystemExit("V21_XAU_NOT_CONFIGURED")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        info = feed.symbol_info(SYMBOL)
        trader = feed._session.trader()
        margin = _expected_margin(feed, info, LOT)
        tiers = _dynamic_leverage(
            feed,
            int(getattr(info, "leverageId", 0) or 0),
        )
        reference_price = _latest_reference_price(feed)

        lot_size = int(getattr(info, "lotSize", 0) or 0)
        min_volume = int(getattr(info, "minVolume", 0) or 0)
        step_volume = int(getattr(info, "stepVolume", 0) or 0)
        if lot_size <= 0 or min_volume <= 0 or step_volume <= 0:
            raise SystemExit("V21_VOLUME_SPEC_INVALID")

        leverage_cents = int(getattr(trader, "leverageInCents", 0) or 0)
        max_leverage_raw = int(getattr(trader, "maxLeverage", 0) or 0)
        account_leverage = (
            float(leverage_cents) / 100.0 if leverage_cents > 0 else None
        )
        max_account_leverage = (
            float(max_leverage_raw) / 100.0
            if max_leverage_raw >= 100
            else (float(max_leverage_raw) if max_leverage_raw > 0 else None)
        )

        snapshot = MarginSnapshot(
            reference_price=reference_price,
            contract_units_per_lot=float(lot_size) / 100.0,
            min_lot=float(min_volume) / float(lot_size),
            step_lot=float(step_volume) / float(lot_size),
            account_leverage=account_leverage,
            max_account_leverage=max_account_leverage,
            leverage_id=(
                int(getattr(info, "leverageId", 0) or 0) or None
            ),
            dynamic_tiers=tiers,
            expected_margin_001_usd=float(margin["max_margin_usd"]),
            expected_margin_buy_001_usd=float(margin["buy_margin_usd"]),
            expected_margin_sell_001_usd=float(margin["sell_margin_usd"]),
        )
        decision = evaluate_margin(snapshot)
        decision["broker_raw"] = {
            "symbol_id": int(info.symbolId),
            "digits": int(getattr(info, "digits", 0) or 0),
            "lot_size_cents": lot_size,
            "min_volume_cents": min_volume,
            "step_volume_cents": step_volume,
            "leverage_in_cents": leverage_cents,
            "max_leverage_raw": max_leverage_raw,
            "leverage_id": int(getattr(info, "leverageId", 0) or 0),
            "measurement_units": str(
                getattr(info, "measurementUnits", "") or ""
            ),
            "margin": margin,
        }
    finally:
        try:
            feed.close()
        except Exception:
            pass

    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "decision": decision,
    }
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
            "V21_EVIDENCE_OUTPUT",
            "artifacts/xau-margin-leverage-v21.json",
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

    d = decision
    hard = d["hard_feasibility"]
    print(
        "V21_RESULT "
        f"account_leverage={d['snapshot']['account_leverage']} "
        f"symbol_leverage={d['symbol_leverage_for_001']} "
        f"inferred={d['inferred_effective_leverage_from_margin']} "
        f"margin001={d['snapshot']['expected_margin_001_usd']} "
        f"notional001={d['notional_001_usd']} "
        f"can_open={int(hard['can_open_001_with_100_current'])} "
        f"required_open={hard['required_effective_leverage_to_open']} "
        f"required_20free={hard['required_effective_leverage_for_20pct_free_margin']} "
        f"artifact={path} execution_influence=0"
    )
    for key,row in d["hypothetical_account_leverage"].items():
        print(
            "V21_HYP "
            f"account={key} effective={row['effective_leverage']} "
            f"margin={row['estimated_margin_usd']} "
            f"can_open={int(row['can_open_with_100'])} "
            f"free={row['free_margin_before_pnl_usd']}"
        )
    print(
        "V21_TIERS "
        + json.dumps(d["snapshot"]["dynamic_tiers"], sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
