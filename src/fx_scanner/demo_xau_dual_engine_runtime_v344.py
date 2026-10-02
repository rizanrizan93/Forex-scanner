from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore
from .xau_friend_entry_engine_v343 import evaluate_friend_entry
from .xau_news_zone_source_v346 import collect_news_zone_events
from .xau_news_zone_v346 import evaluate_news_zone
from .xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity

SYMBOL = "XAUUSD"
SD_WORKER = "ctrader_demo_xau_sd_liquidity_v342"
FRIEND_WORKER = "ctrader_demo_xau_friend_entry_v343"
CONTRACT = "XAU_RIZAN_DUAL_ISOLATED_RUNTIME_V344_3_DEMO_EXECUTION_V352"


def _last_close(rows: tuple[Any, ...]) -> float | None:
    if not rows:
        return None
    try:
        return float(rows[-1].close)
    except (TypeError, ValueError, AttributeError):
        return None


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_DUAL_V344_DEMO_RESEARCH_FEED_REQUIRED")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_DUAL_V344_SYMBOL_NOT_CONFIGURED")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    sd_payload: dict[str, Any] = {}
    friend_payload: dict[str, Any] = {}
    news_payload: dict[str, Any] = {}
    news_source_status: dict[str, str] = {}
    error: str | None = None
    counts = {"H4": 0, "H1": 0, "M15": 0, "M5": 0}

    try:
        feed.ensure_connected()
        h4 = tuple(
            feed.historical_bars(
                SYMBOL,
                "H4",
                from_time=now - timedelta(days=260),
                to_time=now,
                count=1800,
            )
        )
        h1 = tuple(
            feed.historical_bars(
                SYMBOL,
                "H1",
                from_time=now - timedelta(days=120),
                to_time=now,
                count=3000,
            )
        )
        m15 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=now - timedelta(days=45),
                to_time=now,
                count=4200,
            )
        )
        m5 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M5",
                from_time=now - timedelta(days=14),
                to_time=now,
                count=4200,
            )
        )
        counts = {"H4": len(h4), "H1": len(h1), "M15": len(m15), "M5": len(m5)}

        price_now = _last_close(m5) or _last_close(m15) or _last_close(h1)
        sd_payload = evaluate_sd_liquidity(
            bars_h1=h1,
            bars_h4=h4,
            bars_m15=m15,
            bars_m5=m5,
            as_of=now,
            price_now=price_now,
        )
        news_events, news_source_status = collect_news_zone_events(cfg, now=now)
        news_payload = evaluate_news_zone(
            sd_evaluation=sd_payload,
            events=news_events,
            bars_m5=m5,
            bars_m15=m15,
            now=now,
            source_status=news_source_status,
        )
        sd_payload["news_zone"] = news_payload
        parent = dict(sd_payload.get("decision_zone") or {})
        friend_payload = evaluate_friend_entry(
            parent_zone=parent,
            bars_m5=m5,
            as_of=now,
            price_now=price_now,
        )
        # External context only. The A/X/Y geometry itself is unchanged.
        friend_payload["news_zone_context"] = {
            "state": news_payload.get("state"),
            "risk_state": news_payload.get("risk_state"),
            "focal_event": news_payload.get("focal_event"),
            "effective_entry_state": news_payload.get("effective_entry_state"),
            "execution_influence": False,
        }
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    common = {
        "runtime_contract": CONTRACT,
        "environment": "DEMO_NEW_ENGINE_RUNTIME",
        "legacy_engines_paused": True,
        "live_execution_enabled": False,
        "bar_counts": counts,
        "news_source_status": news_source_status,
        "error": error,
    }
    store.write_heartbeat(
        SD_WORKER,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            **common,
            "execution_authority": bool(sd_payload.get("execution_authority")),
            "execution_influence": bool(sd_payload.get("execution_influence")),
            "execution_scope": str(sd_payload.get("execution_scope") or "DEMO_ONLY"),
            "evaluation": sd_payload,
        },
    )
    store.write_heartbeat(
        FRIEND_WORKER,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            **common,
            "execution_authority": False,
            "execution_influence": False,
            "execution_scope": "SHADOW_ONLY",
            "evaluation": friend_payload,
        },
    )
    print(
        "XAU_RIZAN_DUAL_V344 "
        f"healthy={int(healthy)} sd={sd_payload.get('state','ERROR')} "
        f"friend={friend_payload.get('state','ERROR')} "
        f"news={news_payload.get('state','ERROR')} "
        f"execution_authority={int(bool(sd_payload.get('execution_authority')))} "
        "scope=DEMO_ONLY live=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
