from __future__ import annotations

import json

from .config import load_project_config
from .demo_broker_risk_sizing import (
    _all_light_symbols,
    _ensure_conversion_symbols_loaded,
    _expected_margin_deposit,
    _symbol_volume_grid,
)
from .execution.factory import build_broker_gateway
from .execution.models import OrderSide
from .execution.policy import load_execution_policy


def run() -> int:
    cfg=load_project_config(None)
    policy=load_execution_policy(None)
    if str(policy.ctrader.get("environment","")).upper()!="DEMO":
        raise SystemExit("CTRADER_GOLD_CAPABILITY_AUDIT_DEMO_ONLY")

    symbols=[pair.symbol for pair in cfg.pairs]
    gateway,session=build_broker_gateway(policy,symbols,backend="CTRADER")
    try:
        session.ensure_connected()
        lights=_all_light_symbols(session)
        candidates=[]
        for sid,light in sorted(lights.items()):
            name=str(getattr(light,"symbolName","") or "").upper()
            if "XAU" not in name and "GOLD" not in name:
                continue
            try:
                if int(sid) not in session.symbol_full_by_id:
                    _ensure_conversion_symbols_loaded(session,(light,))
                full=session.symbol_info(name)
                minimum,step,maximum,lot_size=_symbol_volume_grid(full)
                row={
                    "symbol":name,
                    "symbol_id":int(sid),
                    "min_volume_cents":int(minimum),
                    "step_volume_cents":int(step),
                    "max_volume_cents":None if maximum is None else int(maximum),
                    "lot_size_cents":int(lot_size),
                    "min_lots":float(minimum)/float(lot_size),
                    "step_lots":float(step)/float(lot_size),
                }
                try:
                    buy_margin=_expected_margin_deposit(
                        session=session,symbol_id=int(sid),volume_cents=int(minimum),side=OrderSide.BUY
                    )
                    sell_margin=_expected_margin_deposit(
                        session=session,symbol_id=int(sid),volume_cents=int(minimum),side=OrderSide.SELL
                    )
                    row["buy_margin_at_min_volume"]=float(buy_margin)
                    row["sell_margin_at_min_volume"]=float(sell_margin)
                except Exception as exc:
                    row["margin_error"]=f"{type(exc).__name__}:{exc}"
                try:
                    quote=gateway.market_quote(name)
                    row["bid"]=float(quote.bid)
                    row["ask"]=float(quote.ask)
                except Exception as exc:
                    row["quote_error"]=f"{type(exc).__name__}:{exc}"
                candidates.append(row)
            except Exception as exc:
                candidates.append({
                    "symbol":name,
                    "symbol_id":int(sid),
                    "spec_error":f"{type(exc).__name__}:{exc}",
                })

        payload={
            "environment":"DEMO",
            "candidate_count":len(candidates),
            "gold_symbols":candidates,
            "orders_mutated":0,
            "positions_mutated":0,
            "live_unlock":False,
        }
        print("CTRADER_GOLD_SYMBOL_CAPABILITY "+json.dumps(payload,sort_keys=True))
        return 0
    finally:
        session.close()


if __name__=="__main__":
    raise SystemExit(run())
