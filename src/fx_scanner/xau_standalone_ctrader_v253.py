from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .demo_xau_dom_v191 import (
    DEFAULT_MAX_LEVELS,
    DOM_STALE_SECONDS,
    DomFrame,
    analyze_dom_frames,
)
from .execution.ctrader_research import CTraderResearchFeed
from .execution.ctrader_session import CTraderOpenApiSession
from .xau_standalone_mode_v253 import (
    build_standalone_xau_state,
    load_frozen_depth_prior,
)

SYMBOL = "XAUUSD"


def build_standalone_ctrader_feed(
    *,
    client_id: str,
    client_secret: str,
    access_token: str,
    refresh_token: str | None,
    trader_login: int,
    account_id: int | None = None,
) -> CTraderResearchFeed:
    """Create a read-only DEMO cTrader feed from explicit server-side secrets."""
    session = CTraderOpenApiSession(
        client_id=str(client_id),
        client_secret=str(client_secret),
        access_token=str(access_token),
        refresh_token=(str(refresh_token) if refresh_token else None),
        token_update_callback=None,
        account_id=None,
        environment="demo",
        request_timeout_seconds=10.0,
        allow_token_refresh=bool(refresh_token),
    )
    try:
        session.resolve_granted_account(
            trader_login=int(trader_login),
            require_demo=True,
            pinned_account_id=(None if account_id is None else int(account_id)),
        )
        session.connect()
        session.load_symbols([SYMBOL])
        session.subscribe_spots([SYMBOL])
        return CTraderResearchFeed(session, (SYMBOL,))
    except Exception:
        try:
            session.close()
        except Exception:
            pass
        raise


def _dom_frame(snapshot) -> DomFrame:
    return DomFrame(
        observed_at=snapshot.observed_at.astimezone(UTC),
        bids=tuple((float(row.price), float(row.size_units)) for row in snapshot.bids),
        asks=tuple((float(row.price), float(row.size_units)) for row in snapshot.asks),
        event_count=int(snapshot.event_count),
        quote_count=int(snapshot.quote_count),
    )


def collect_standalone_xau_snapshot(
    feed: CTraderResearchFeed,
    *,
    root: Path,
    previous_dom_analysis: dict[str, Any] | None = None,
    sample_seconds: float = 6.0,
    sample_interval_seconds: float = 0.75,
    max_levels: int = DEFAULT_MAX_LEVELS,
) -> dict[str, Any]:
    """Read cTrader directly and build one non-executable dashboard snapshot."""
    now = datetime.now(tz=UTC)
    feed.ensure_connected()

    quote = None
    for attempt in range(3):
        try:
            quote = feed.quote(SYMBOL, at=now)
            break
        except Exception:
            if attempt == 0:
                try:
                    feed.refresh_quote_snapshot(SYMBOL)
                except Exception:
                    pass
            time.sleep(0.8)
    if quote is None:
        raise RuntimeError("CTRADER_STANDALONE_QUOTE_UNAVAILABLE")

    m15_bars = tuple(
        feed.historical_bars(
            SYMBOL,
            "M15",
            from_time=now - timedelta(days=45),
            to_time=now,
            count=3000,
        )
    )
    m5_bars = tuple(
        feed.historical_bars(
            SYMBOL,
            "M5",
            from_time=now - timedelta(days=10),
            to_time=now,
            count=1800,
        )
    )

    frames: list[DomFrame] = []
    subscribed = False
    try:
        feed.clear_depth_snapshot(SYMBOL)
        feed.subscribe_depth((SYMBOL,))
        subscribed = True
        deadline = time.monotonic() + max(3.0, float(sample_seconds))
        last_event_count = -1
        while time.monotonic() < deadline:
            try:
                snapshot = feed.depth_snapshot(
                    SYMBOL,
                    max_levels=max(5, min(25, int(max_levels))),
                )
                age = (datetime.now(tz=UTC) - snapshot.observed_at).total_seconds()
                if -1.0 <= age <= DOM_STALE_SECONDS:
                    if int(snapshot.event_count) != last_event_count:
                        frames.append(_dom_frame(snapshot))
                        last_event_count = int(snapshot.event_count)
            except Exception:
                pass
            feed.heartbeat()
            time.sleep(max(0.5, min(2.0, float(sample_interval_seconds))))
    finally:
        if subscribed:
            try:
                feed.unsubscribe_depth((SYMBOL,))
            except Exception:
                pass

    dom_analysis = analyze_dom_frames(frames)
    history = load_frozen_depth_prior(Path(root))
    state = build_standalone_xau_state(
        m15_bars=m15_bars,
        m5_bars=m5_bars,
        bid=float(quote.bid),
        ask=float(quote.ask),
        quote_timestamp=quote.timestamp,
        dom_analysis=dom_analysis,
        previous_dom_analysis=previous_dom_analysis,
        history_details=history,
        as_of=datetime.now(tz=UTC),
    )
    state["collection"] = {
        "m15_bars": len(m15_bars),
        "m5_bars": len(m5_bars),
        "dom_frames": len(frames),
        "source": "FP_MARKETS_CTRADER_OPEN_API_DIRECT",
        "supabase_reads": 0,
        "supabase_writes": 0,
    }
    return state
