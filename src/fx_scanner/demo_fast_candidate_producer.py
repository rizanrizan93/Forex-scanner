from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from .cli import _apply_demo_technical_only_profile, _demo_spread_limit_overrides
from .config import ProjectConfig, load_project_config
from .demo_calibration import (
    apply_demo_calibration_risk,
    apply_demo_calibration_threshold,
    apply_demo_deep_analysis_top,
    build_demo_calibration_store,
)
from .demo_correlation_evidence import EvidenceProductionGuardResolver
from .demo_market_schedule import apply_demo_market_schedule
from .demo_technical_strategy import scan_demo_deep_candidates_report
from .demo_technical_producer import _apply_demo_chase_block, _persist_geometry_events
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .ranking import PairRank
from .signal_producer import CTraderSignalProducer, SignalProducerReport
from .strategy import DeepScanReport, select_pair_candidates

UTC = timezone.utc
_ALLOWED_STATES = {"EXECUTION_READY", "ARMED", "SETUP_FORMING", "WATCH"}
_STATE_PRIORITY = {"EXECUTION_READY": 4, "ARMED": 3, "SETUP_FORMING": 2, "WATCH": 1}


def _safe_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name}_INVALID") from exc
    if not minimum <= value <= maximum:
        raise SystemExit(f"{name}_OUT_OF_RANGE")
    return value


def _safe_float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name}_INVALID") from exc
    if not isfinite(value) or not minimum <= value <= maximum:
        raise SystemExit(f"{name}_OUT_OF_RANGE")
    return value


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


def recent_candidate_symbols(
    store,
    cfg: ProjectConfig,
    *,
    now: datetime,
    lookback_minutes: int,
    max_symbols: int,
) -> tuple[str, ...]:
    """Select a bounded symbol set; selection never refreshes signal validity."""
    response = (
        store.client.table("signals")
        .select("observed_at,symbol,state,final_score")
        .order("observed_at", desc=True)
        .limit(250)
        .execute()
    )
    cutoff = now.astimezone(UTC) - timedelta(minutes=int(lookback_minutes))
    allowed_symbols = set(cfg.pair_map)
    best: dict[str, tuple[int, float, datetime]] = {}
    for raw in response.data or []:
        row = dict(raw)
        symbol = str(row.get("symbol", "") or "").upper().strip()
        state = str(row.get("state", "") or "").upper().strip()
        observed = _dt(row.get("observed_at"))
        if symbol not in allowed_symbols or state not in _ALLOWED_STATES or observed is None:
            continue
        if observed < cutoff or observed > now.astimezone(UTC) + timedelta(seconds=1):
            continue
        try:
            score = float(row.get("final_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        key = (_STATE_PRIORITY[state], score, observed)
        if symbol not in best or key > best[symbol]:
            best[symbol] = key
    ordered = sorted(best, key=lambda symbol: best[symbol], reverse=True)
    return tuple(ordered[: int(max_symbols)])


def latest_discovery_rankings(
    store,
    cfg: ProjectConfig,
    symbols: tuple[str, ...],
    *,
    now: datetime,
    max_age_minutes: int,
) -> tuple[PairRank, ...]:
    """Reuse full-universe discovery direction so subset ranking cannot drift."""
    if not symbols:
        return ()
    response = (
        store.client.table("pair_rankings")
        .select(
            "run_id,observed_at,symbol,direction,technical_edge,"
            "pair_opportunity_score,rank,coverage"
        )
        .order("observed_at", desc=True)
        .limit(500)
        .execute()
    )
    cutoff = now.astimezone(UTC) - timedelta(minutes=int(max_age_minutes))
    wanted = set(symbols)
    latest: dict[str, dict[str, Any]] = {}
    for raw in response.data or []:
        row = dict(raw)
        symbol = str(row.get("symbol", "") or "").upper().strip()
        if symbol not in wanted or symbol in latest or symbol not in cfg.pair_map:
            continue
        observed = _dt(row.get("observed_at"))
        direction = str(row.get("direction", "") or "").upper().strip()
        if observed is None or observed < cutoff or observed > now.astimezone(UTC) + timedelta(seconds=1):
            continue
        if direction not in {"LONG", "SHORT"}:
            continue
        latest[symbol] = row

    ranks: list[PairRank] = []
    for symbol in symbols:
        row = latest.get(symbol)
        if row is None:
            continue
        direction = str(row["direction"]).upper()
        try:
            absolute_edge = abs(float(row.get("pair_opportunity_score") or 0.0))
            technical_edge = float(row.get("technical_edge") or 0.0)
            coverage = float(row.get("coverage") or 0.0)
            rank = int(row.get("rank") or 0)
        except (TypeError, ValueError):
            continue
        if not (0.0 < absolute_edge <= 100.0 and 0.80 <= coverage <= 1.0 and rank > 0):
            continue
        signed_edge = absolute_edge if direction == "LONG" else -absolute_edge
        ranks.append(
            PairRank(
                symbol=symbol,
                direction=direction,
                relative_macro_edge=0.0,
                relative_technical_edge=technical_edge,
                cross_asset_edge=None,
                pair_edge=signed_edge,
                absolute_edge=absolute_edge,
                coverage=coverage,
                missing_components=(),
                rank=rank,
            )
        )
    return tuple(ranks)


def _subset_cfg(cfg: ProjectConfig, symbols: tuple[str, ...]) -> ProjectConfig:
    selected = tuple(cfg.pair_map[symbol] for symbol in symbols if symbol in cfg.pair_map)
    return replace(cfg, pairs=selected)


class FastCandidateSignalProducer(CTraderSignalProducer):
    """Freshly re-analyze a small symbol set using slow-lane full-universe ranks."""

    last_deep_report: DeepScanReport | None = None

    def __init__(self, *args, discovery_rankings: tuple[PairRank, ...], **kwargs):
        super().__init__(*args, **kwargs)
        self.discovery_rankings = tuple(discovery_rankings)

    def run_once(self) -> SignalProducerReport:
        snapshot_at = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            started_at=snapshot_at,
        )
        failures: dict[str, str] = {}
        try:
            self.feed.ensure_connected()
            bars_by_symbol, market_failures = self._fetch_market(as_of=snapshot_at)
            failures.update(market_failures)
            ranked = [
                item for item in self.discovery_rankings if item.symbol in bars_by_symbol
            ]
            selection_cfg = self.cfg.strategy["selection"]
            decision_at = ensure_utc(self.clock())
            guard_missing = {}
            calendar_error = None
            guard_inputs = {}
            if self.guard_resolver is not None and ranked:
                selection = select_pair_candidates(
                    ranked,
                    macro_compatible_top=int(selection_cfg["macro_compatible_top"]),
                    deep_analysis_top=int(selection_cfg["deep_analysis_top"]),
                    compatibility_mode="TECHNICAL",
                )
                guard_resolution = self.guard_resolver.resolve(
                    candidates=selection.deep_analysis,
                    bars_by_symbol=bars_by_symbol,
                    as_of=decision_at,
                )
                guard_inputs = guard_resolution.flags_by_symbol
                guard_missing = guard_resolution.missing_by_symbol
                calendar_error = guard_resolution.calendar_error

            deep = scan_demo_deep_candidates_report(
                ranked=ranked,
                bars_by_symbol=bars_by_symbol,
                cfg=self.cfg,
                as_of=decision_at,
                external_guards_by_symbol=guard_inputs,
            )
            self.last_deep_report = deep
            failures.update(deep.skipped)
            signals_written, ready = self._persist_signals(
                run_id,
                as_of=decision_at,
                report=deep,
            )
            self.store.finish_scanner_run(
                run_id,
                status="COMPLETED",
                finished_at=self.clock(),
            )
            return SignalProducerReport(
                run_id=run_id,
                observed_at=decision_at,
                market_symbols=len(bars_by_symbol),
                macro_currencies=0,
                ranked_pairs=len(ranked),
                deep_candidates=len(deep.selection.deep_analysis),
                analyses=len(deep.analyses),
                signals_written=signals_written,
                execution_ready=ready,
                skipped=dict(sorted(failures.items())),
                missing_macro=(),
                guard_missing=guard_missing,
                calendar_error=calendar_error,
            )
        except Exception:
            try:
                self.store.finish_scanner_run(
                    run_id,
                    status="FAILED",
                    finished_at=self.clock(),
                )
            except Exception:
                pass
            raise


def run() -> int:
    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_FAST_CANDIDATE_PRODUCER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_FAST_CANDIDATE_PRODUCER_REQUIRE_DEMO")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg, production_chase_block = _apply_demo_chase_block(cfg)
    cfg = apply_demo_deep_analysis_top(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(
        cfg,
        max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
    )
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    max_symbols = _safe_int_env(
        "CTRADER_DEMO_FAST_MAX_SYMBOLS", 5, minimum=1, maximum=8
    )
    signal_lookback_minutes = _safe_int_env(
        "CTRADER_DEMO_FAST_CANDIDATE_LOOKBACK_MINUTES", 45, minimum=5, maximum=180
    )
    ranking_max_age_minutes = _safe_int_env(
        "CTRADER_DEMO_FAST_RANKING_MAX_AGE_MINUTES", 20, minimum=5, maximum=60
    )
    request_delay = _safe_float_env(
        "CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS", 1.20, minimum=0.20, maximum=2.0
    )

    store = build_demo_calibration_store(execution_ready_score_floor=demo_execution_min)
    now = datetime.now(tz=UTC)
    symbols = recent_candidate_symbols(
        store,
        cfg,
        now=now,
        lookback_minutes=signal_lookback_minutes,
        max_symbols=max_symbols,
    )
    discovery_rankings = latest_discovery_rankings(
        store,
        cfg,
        symbols,
        now=now,
        max_age_minutes=ranking_max_age_minutes,
    )
    symbols = tuple(item.symbol for item in discovery_rankings)
    if not symbols:
        store.write_heartbeat(
            "ctrader_demo_fast_candidate_producer",
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "FAST_REVALIDATION",
                "candidate_symbols": [],
                "candidate_count": 0,
                "signal_lookback_minutes": signal_lookback_minutes,
                "ranking_max_age_minutes": ranking_max_age_minutes,
                "market_schedule_mode": market_schedule_mode,
                "result": "NO_FRESH_DISCOVERY_CANDIDATES",
            },
        )
        print(
            "CTRADER_DEMO_FAST_CANDIDATE_PRODUCER_OK "
            "candidates=0 result=NO_FRESH_DISCOVERY_CANDIDATES"
        )
        return 0

    cfg = _subset_cfg(cfg, symbols)
    store.ensure_reference_symbols(cfg.pairs)
    feed = build_ctrader_research_feed(policy, symbols)
    spread_overrides = _demo_spread_limit_overrides(cfg)
    guard_resolver = EvidenceProductionGuardResolver(
        cfg,
        feed,
        calendar_provider=None,
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        max_spread_pips=float(policy.reconciliation["max_execution_spread_pips"]),
        demo_max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
        max_spread_pips_by_symbol=spread_overrides,
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        clock=lambda: datetime.now(tz=UTC),
        disabled_guards=("NEWS_BLOCK",),
    )
    producer = FastCandidateSignalProducer(
        cfg,
        feed,
        store,
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        historical_request_delay_seconds=request_delay,
        signal_ttl_seconds=min(300.0, float(policy.order.get("max_signal_age_seconds", 300))),
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        guard_resolver=guard_resolver,
        technical_only_scalping=True,
        discovery_rankings=discovery_rankings,
    )

    started = datetime.now(tz=UTC)
    report = producer.run_once()
    persisted = store.list_signals_for_run(report.run_id)
    analyses = {
        item.symbol: item
        for item in (
            producer.last_deep_report.analyses if producer.last_deep_report else ()
        )
    }
    geometry_written, geometry_missing = _persist_geometry_events(
        store=store,
        policy=policy,
        persisted=persisted,
        analyses=analyses,
    )
    elapsed = (datetime.now(tz=UTC) - started).total_seconds()
    store.write_heartbeat(
        "ctrader_demo_fast_candidate_producer",
        healthy=True,
        lag_seconds=0.0,
        details={
            "mode": "FAST_REVALIDATION",
            "candidate_symbols": list(symbols),
            "candidate_count": len(symbols),
            "signal_lookback_minutes": signal_lookback_minutes,
            "ranking_max_age_minutes": ranking_max_age_minutes,
            "request_delay_seconds": request_delay,
            "market_schedule_mode": market_schedule_mode,
            "signals_written": report.signals_written,
            "execution_ready": report.execution_ready,
            "geometry_written": geometry_written,
            "geometry_missing_nonready": geometry_missing,
            "elapsed_seconds": elapsed,
            "production_execution_min": production_execution_min,
            "demo_execution_min": demo_execution_min,
            "production_chase_block_atr": production_chase_block,
            "risk_per_trade_pct": demo_risk_pct,
            "ranking_source": "LATEST_FULL_UNIVERSE_DISCOVERY",
        },
    )
    print(
        "CTRADER_DEMO_FAST_CANDIDATE_PRODUCER_OK "
        f"candidates={len(symbols)} symbols={','.join(symbols)} "
        f"market={report.market_symbols}/{len(symbols)} ranked={report.ranked_pairs} "
        f"deep={report.deep_candidates} signals={report.signals_written} "
        f"execution_ready={report.execution_ready} geometry={geometry_written} "
        f"elapsed_s={elapsed:.1f} request_delay_s={request_delay:g} "
        "ranking_source=LATEST_FULL_UNIVERSE_DISCOVERY"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
