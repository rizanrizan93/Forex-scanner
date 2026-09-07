from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def fresh_execution_ready_rows(
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime,
    max_age_seconds: float,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    """Return newest durable EXECUTION_READY rows that are still executable by time.

    This is intentionally a handoff filter only. It never promotes WATCH/ARMED/
    SETUP_FORMING rows and never changes score, guards, entry, SL, TP or RR.
    """
    current = now.astimezone(UTC)
    cutoff = current - timedelta(seconds=float(max_age_seconds))
    fresh: list[tuple[datetime, dict[str, Any]]] = []
    for raw in rows:
        row = dict(raw)
        if str(row.get("state", "")).upper() != "EXECUTION_READY":
            continue
        observed = _dt(row.get("observed_at"))
        expires = _dt(row.get("expires_at"))
        if observed is None or observed < cutoff or observed > current + timedelta(seconds=1):
            continue
        if expires is not None and current > expires:
            continue
        fresh.append((observed, row))
    fresh.sort(key=lambda item: item[0], reverse=True)
    return tuple(row for _observed, row in fresh[: max(0, int(limit))])


def install_fresh_execution_ready_handoff(*, max_age_seconds: float) -> None:
    """Replace the DEMO read boundary with a freshness-aware durable query.

    The executor still performs its own timestamp, quote, RR and geometry checks.
    This only prevents an old EXECUTION_READY backlog from occupying the bounded
    executor poll while a newer signal is waiting behind it.
    """
    age_limit = float(max_age_seconds)
    if age_limit <= 0:
        raise ValueError("max_age_seconds must be positive")

    def _list_execution_ready_signals(self, *, limit: int = 10):
        requested = max(1, int(limit))
        fetch_limit = max(50, min(250, requested * 10))
        response = (
            self.client.table("signals")
            .select("*")
            .eq("state", "EXECUTION_READY")
            .order("observed_at", desc=True)
            .limit(fetch_limit)
            .execute()
        )
        rows = tuple(dict(row) for row in (response.data or []))
        return fresh_execution_ready_rows(
            rows,
            now=datetime.now(tz=UTC),
            max_age_seconds=age_limit,
            limit=requested,
        )

    SupabaseOperationalStore.list_execution_ready_signals = _list_execution_ready_signals


def main() -> int:
    policy = load_execution_policy(None)
    max_age_seconds = float(policy.order.get("max_signal_age_seconds", 300))
    install_fresh_execution_ready_handoff(max_age_seconds=max_age_seconds)

    # DEMO-only execution semantics: same-direction stacking is allowed while
    # opposite reversals close scanner-linked exposure only, quarantine any
    # uncertain close, and force fresh post-close revalidation before entry.
    from .demo_position_reversal import install_demo_position_policy

    install_demo_position_policy()

    from .demo_calibration_autotrade import main as calibration_main

    return calibration_main()


if __name__ == "__main__":
    raise SystemExit(main())
