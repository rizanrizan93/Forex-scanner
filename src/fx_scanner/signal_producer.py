from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from time import sleep
from typing import Any, Callable, Mapping, Sequence

from .config import ProjectConfig
from .macro import CurrencyMacroScore, MacroStatus
from .models import Bar, SignalState, ensure_utc
from .ranking import CurrencyStrength, PairRank, compute_currency_strength, rank_pairs
from .strategy import DeepScanReport, scan_deep_candidates_report, select_pair_candidates
from .technical import StructureSnapshot, structure_snapshot

UTC = timezone.utc

_FACTOR_COLUMNS = {
    "interest_rate": "rate_score",
    "central_bank_bias": "central_bank_score",
    "inflation": "inflation_score",
    "growth": "growth_score",
    "labour": "labour_score",
    "yield_momentum": "yield_score",
    "risk_commodity": "risk_score",
    "positioning": "positioning_score",
}


@dataclass(frozen=True, slots=True)
class SignalProducerReport:
    run_id: str
    observed_at: datetime
    market_symbols: int
    macro_currencies: int
    ranked_pairs: int
    deep_candidates: int
    analyses: int
    signals_written: int
    execution_ready: int
    skipped: Mapping[str, str]
    missing_macro: tuple[str, ...]
    guard_missing: Mapping[str, tuple[str, ...]]
    calendar_error: str | None


def _closed_bars(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    timeframe_seconds: int,
) -> tuple[Bar, ...]:
    cutoff = ensure_utc(as_of)
    return tuple(
        bar
        for bar in bars
        if bar.timestamp + timedelta(seconds=int(timeframe_seconds)) <= cutoff
    )


def _signed_structure_score(snapshot: StructureSnapshot) -> float | None:
    """Convert observed structure into a bounded signed technical-strength input.

    UNKNOWN is missing evidence. RANGE is an observed neutral structure, not
    missing evidence. The score only reuses existing structure/BOS/MSS/
    displacement outputs and does not alter strategy state thresholds.
    """
    if snapshot.trend == "UNKNOWN":
        return None
    score = 0.0
    if snapshot.trend == "BULLISH":
        score += 50.0
    elif snapshot.trend == "BEARISH":
        score -= 50.0

    if snapshot.bos == "BULLISH":
        score += 20.0
    elif snapshot.bos == "BEARISH":
        score -= 20.0

    if snapshot.mss == "BULLISH":
        score += 20.0
    elif snapshot.mss == "BEARISH":
        score -= 20.0

    displacement = snapshot.displacement
    if displacement is not None and displacement.valid:
        if displacement.direction == "BULLISH":
            score += 10.0
        elif displacement.direction == "BEARISH":
            score -= 10.0
    return max(-100.0, min(100.0, score))


def _durable_macro_score(
    currency: str,
    row: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    cfg: ProjectConfig,
) -> CurrencyMacroScore | None:
    """Validate a durable macro row without converting stale/missing evidence to zero."""
    if not row:
        return None
    try:
        observed_at = datetime.fromisoformat(
            str(row["observed_at"]).replace("Z", "+00:00")
        )
    except Exception:
        return None
    if observed_at.tzinfo is None:
        return None
    observed_at = observed_at.astimezone(UTC)
    now = ensure_utc(as_of)
    row_age = (now - observed_at).total_seconds()
    if row_age < -1.0:
        return None
    row_age = max(0.0, row_age)

    raw_score = row.get("macro_score")
    raw_coverage = row.get("coverage")
    if raw_score is None or raw_coverage is None:
        return None
    if isinstance(raw_score, bool) or isinstance(raw_coverage, bool):
        return None
    try:
        score = float(raw_score)
        coverage = float(raw_coverage)
    except (TypeError, ValueError):
        return None
    if not isfinite(score) or not -100.0 <= score <= 100.0:
        return None
    if not isfinite(coverage) or not 0.0 <= coverage <= 1.0:
        return None
    if coverage < float(cfg.macro["minimum_coverage"]):
        return None

    evidence = row.get("evidence")
    if not isinstance(evidence, Mapping) or not evidence:
        return None

    missing: list[str] = []
    observed_weight = 0.0
    total_weight = sum(float(v) for v in cfg.macro["weights"].values())
    for factor, weight in cfg.macro["weights"].items():
        column = _FACTOR_COLUMNS[factor]
        factor_score = row.get(column)
        if factor_score is None:
            missing.append(factor)
            continue
        if isinstance(factor_score, bool):
            return None
        try:
            numeric = float(factor_score)
        except (TypeError, ValueError):
            return None
        if not isfinite(numeric) or not -100.0 <= numeric <= 100.0:
            return None

        factor_evidence = evidence.get(factor)
        if not isinstance(factor_evidence, Mapping):
            return None
        providers_used = {
            str(name) for name in (factor_evidence.get("providers_used") or [])
        }
        sources = factor_evidence.get("sources")
        if not providers_used or not isinstance(sources, list):
            return None

        fresh_used: set[str] = set()
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            provider = str(source.get("provider", ""))
            if provider not in providers_used:
                continue
            if str(source.get("status", "")).upper() not in {"AVAILABLE", "PARTIAL"}:
                continue
            try:
                age_at_snapshot = float(source["age_seconds"])
                max_age = float(source["max_age_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                isfinite(age_at_snapshot)
                and isfinite(max_age)
                and max_age > 0
                and age_at_snapshot >= 0
                and age_at_snapshot + row_age <= max_age
            ):
                fresh_used.add(provider)
        if not providers_used.issubset(fresh_used):
            return None
        observed_weight += float(weight)

    derived_coverage = observed_weight / total_weight
    if derived_coverage + 1e-9 < float(cfg.macro["minimum_coverage"]):
        return None
    if abs(derived_coverage - coverage) > 0.051:
        return None

    status = MacroStatus.AVAILABLE if coverage >= 0.999999 else MacroStatus.PARTIAL
    return CurrencyMacroScore(
        currency=currency,
        score=score,
        coverage=coverage,
        status=status,
        missing_factors=tuple(sorted(missing)),
    )


class CTraderSignalProducer:
    """Production signal producer over the read-only cTrader research facade.

    The producer never submits orders. It only persists scanner evidence and
    strategy states. Missing external hard-guard evidence is intentionally left
    absent so the existing decision engine fails closed.
    """

    def __init__(
        self,
        cfg: ProjectConfig,
        feed: Any,
        store: Any,
        *,
        code_version: str,
        historical_request_delay_seconds: float = 0.25,
        signal_ttl_seconds: float = 300.0,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        guard_resolver: Any | None = None,
    ):
        if historical_request_delay_seconds < 0.20:
            raise ValueError(
                "historical request delay must preserve cTrader 5 requests/sec limit"
            )
        if signal_ttl_seconds <= 0 or signal_ttl_seconds > 300:
            raise ValueError("signal TTL must be in (0,300] seconds")
        self.cfg = cfg
        self.feed = feed
        self.store = store
        self.code_version = str(code_version or "UNKNOWN")
        self.request_delay = float(historical_request_delay_seconds)
        self.signal_ttl_seconds = float(signal_ttl_seconds)
        self.sleeper = sleeper
        self.clock = clock
        self.guard_resolver = guard_resolver

    def _bar_window(self, timeframe: str, count: int, now: datetime) -> tuple[datetime, datetime]:
        seconds = int(self.cfg.timeframes[timeframe])
        return now - timedelta(seconds=seconds * (count + 12)), now

    def _fetch_market(
        self,
        *,
        as_of: datetime,
    ) -> tuple[
        dict[str, Mapping[str, tuple[Bar, ...]]],
        dict[str, str],
    ]:
        bars_by_symbol: dict[str, Mapping[str, tuple[Bar, ...]]] = {}
        failures: dict[str, str] = {}
        required_tfs = tuple(self.cfg.strategy["mtf"]["required_timeframes"])
        minimum = self.cfg.strategy["mtf"]["minimum_bars"]

        for pair in self.cfg.pairs:
            symbol = pair.symbol
            try:
                quote = self.feed.quote(symbol)
                quote_age = (as_of - quote.timestamp).total_seconds()
                if quote_age < -1.0 or quote_age > 2.0:
                    failures[symbol] = f"QUOTE_STALE:{quote_age:.3f}"
                    continue
                if not (float(quote.bid) > 0 and float(quote.ask) >= float(quote.bid)):
                    failures[symbol] = "QUOTE_INVALID"
                    continue

                bundle: dict[str, tuple[Bar, ...]] = {}
                for tf in required_tfs:
                    count = int(minimum[tf]) + 12
                    start, end = self._bar_window(tf, count, as_of)
                    fetched = tuple(
                        self.feed.historical_bars(
                            symbol,
                            tf,
                            from_time=start,
                            to_time=end,
                            count=count,
                        )
                    )
                    closed = _closed_bars(
                        fetched,
                        as_of=as_of,
                        timeframe_seconds=int(self.cfg.timeframes[tf]),
                    )
                    if len(closed) < int(minimum[tf]):
                        raise ValueError(
                            f"{tf} closed bars {len(closed)} < {int(minimum[tf])}"
                        )
                    bundle[tf] = closed
                    self.sleeper(self.request_delay)
                bars_by_symbol[symbol] = bundle
            except Exception as exc:
                failures[symbol] = f"{type(exc).__name__}:{exc}"
        return bars_by_symbol, dict(sorted(failures.items()))

    def _technical_strength(
        self,
        bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
    ) -> tuple[
        dict[str, CurrencyStrength],
        dict[str, dict[str, CurrencyStrength]],
    ]:
        strength_tfs = ("M15", "H1", "H4", "D1")
        pair_scores_by_tf: dict[str, dict[str, float]] = {
            tf: {} for tf in strength_tfs
        }
        combined_pair_scores: dict[str, float] = {}
        mtf_cfg = self.cfg.strategy["mtf"]
        swing = int(mtf_cfg["swing_lookback"])
        atr_period = int(mtf_cfg["atr_period"])
        reclaim = int(self.cfg.strategy["liquidity"]["sweep_reclaim_bars"])

        for pair in self.cfg.pairs:
            bundle = bars_by_symbol.get(pair.symbol)
            if not bundle:
                continue
            observed: list[float] = []
            for tf in strength_tfs:
                try:
                    snapshot = structure_snapshot(
                        list(bundle[tf]),
                        swing_lookback=swing,
                        atr_period=atr_period,
                        sweep_reclaim_bars=reclaim,
                    )
                    score = _signed_structure_score(snapshot)
                except Exception:
                    score = None
                if score is None:
                    continue
                pair_scores_by_tf[tf][pair.symbol] = score
                observed.append(score)
            if observed:
                combined_pair_scores[pair.symbol] = sum(observed) / len(observed)

        per_tf = {
            tf: compute_currency_strength(values, self.cfg.pairs)
            for tf, values in pair_scores_by_tf.items()
            if values
        }
        combined = (
            compute_currency_strength(combined_pair_scores, self.cfg.pairs)
            if combined_pair_scores
            else {}
        )
        return combined, per_tf

    def _macro_scores(
        self,
        *,
        as_of: datetime,
    ) -> tuple[dict[str, CurrencyMacroScore], tuple[str, ...]]:
        currencies = tuple(
            sorted({p.base for p in self.cfg.pairs}.union({p.quote for p in self.cfg.pairs}))
        )
        rows = self.store.get_latest_currency_macro_states(list(currencies))
        scores: dict[str, CurrencyMacroScore] = {}
        missing: list[str] = []
        for currency in currencies:
            score = _durable_macro_score(
                currency,
                rows.get(currency),
                as_of=as_of,
                cfg=self.cfg,
            )
            if score is None:
                missing.append(currency)
            else:
                scores[currency] = score
        return scores, tuple(missing)

    def _persist_strength(
        self,
        run_id: str,
        *,
        as_of: datetime,
        combined: Mapping[str, CurrencyStrength],
        per_tf: Mapping[str, Mapping[str, CurrencyStrength]],
    ) -> None:
        del run_id  # currency_strength schema is timestamp-scoped, not run-scoped.
        rows: list[dict[str, Any]] = []
        currencies = sorted(
            set(combined).union(*(set(values) for values in per_tf.values()))
            if per_tf
            else set(combined)
        )
        for currency in currencies:
            item = combined.get(currency)
            if item is None:
                continue
            rows.append(
                {
                    "currency": currency,
                    "observed_at": as_of.isoformat(),
                    "strength_15m": (
                        per_tf.get("M15", {}).get(currency).score
                        if currency in per_tf.get("M15", {})
                        else None
                    ),
                    "strength_1h": (
                        per_tf.get("H1", {}).get(currency).score
                        if currency in per_tf.get("H1", {})
                        else None
                    ),
                    "strength_4h": (
                        per_tf.get("H4", {}).get(currency).score
                        if currency in per_tf.get("H4", {})
                        else None
                    ),
                    "strength_1d": (
                        per_tf.get("D1", {}).get(currency).score
                        if currency in per_tf.get("D1", {})
                        else None
                    ),
                    "combined_strength": item.score,
                    "coverage": item.coverage,
                }
            )
        self.store.write_currency_strength_rows(rows)

    def _persist_rankings(
        self,
        run_id: str,
        *,
        as_of: datetime,
        ranked: Sequence[PairRank],
    ) -> None:
        rows = [
            {
                "run_id": run_id,
                "observed_at": as_of.isoformat(),
                "symbol": item.symbol,
                "direction": item.direction,
                "macro_edge": item.relative_macro_edge,
                "technical_edge": item.relative_technical_edge,
                "cross_asset_score": item.cross_asset_edge,
                "session_score": None,
                "volatility_score": None,
                "spread_score": None,
                "pair_opportunity_score": item.absolute_edge,
                "rank": item.rank,
                "coverage": item.coverage,
            }
            for item in ranked
        ]
        self.store.write_pair_ranking_rows(rows)

    def _persist_signals(
        self,
        run_id: str,
        *,
        as_of: datetime,
        report: DeepScanReport,
    ) -> tuple[int, int]:
        ranks = {item.symbol: item for item in report.selection.deep_analysis}
        rows: list[dict[str, Any]] = []
        ready = 0
        expires_at = as_of + timedelta(seconds=self.signal_ttl_seconds)
        for analysis in report.analyses:
            rank = ranks[analysis.symbol]
            decision = analysis.decision
            plan = analysis.trade_plan
            state = decision.state.value
            if decision.state == SignalState.EXECUTION_READY:
                ready += 1
            rows.append(
                {
                    "run_id": run_id,
                    "observed_at": as_of.isoformat(),
                    "symbol": analysis.symbol,
                    "direction": analysis.direction,
                    "setup_type": (
                        analysis.setup_type.value if analysis.setup_type is not None else "NONE"
                    ),
                    "state": state,
                    "pair_score": rank.absolute_edge,
                    "execution_score": decision.conviction_score,
                    "final_score": decision.conviction_score,
                    "entry_low": None if plan is None else plan.entry_low,
                    "entry_high": None if plan is None else plan.entry_high,
                    "sl": None if plan is None else plan.stop_loss,
                    "tp1": None if plan is None else plan.tp1,
                    "tp2": None if plan is None else plan.tp2,
                    "tp3": None,
                    "rr1": None if plan is None else plan.rr1,
                    "rr2": None if plan is None else plan.rr2,
                    "rr3": None,
                    "macro_bias": analysis.direction,
                    "h4_bias": analysis.h4.trend,
                    "h1_bias": analysis.h1.trend,
                    "active_guards": list(decision.guards),
                    "data_coverage": min(decision.coverage, decision.pair_coverage),
                    "expires_at": expires_at.isoformat(),
                }
            )
        self.store.write_signal_rows(rows)
        return len(rows), ready

    def run_once(
        self,
        *,
        external_guards_by_symbol: Mapping[str, Mapping[str, bool]] | None = None,
    ) -> SignalProducerReport:
        as_of = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            started_at=as_of,
        )
        failures: dict[str, str] = {}
        try:
            self.feed.ensure_connected()
            bars_by_symbol, market_failures = self._fetch_market(as_of=as_of)
            failures.update(market_failures)

            combined_strength, strength_by_tf = self._technical_strength(bars_by_symbol)
            self._persist_strength(
                run_id,
                as_of=as_of,
                combined=combined_strength,
                per_tf=strength_by_tf,
            )

            macro_scores, missing_macro = self._macro_scores(as_of=as_of)
            ranked = rank_pairs(
                self.cfg.pairs,
                macro_scores=macro_scores,
                technical_strength=combined_strength,
                cross_asset_edges={},
                minimum_coverage=0.80,
            )
            self._persist_rankings(run_id, as_of=as_of, ranked=ranked)

            guard_missing: Mapping[str, tuple[str, ...]] = {}
            calendar_error: str | None = None
            guard_inputs = external_guards_by_symbol
            if guard_inputs is None and self.guard_resolver is not None:
                selection = select_pair_candidates(
                    ranked,
                    macro_compatible_top=int(
                        self.cfg.strategy["selection"]["macro_compatible_top"]
                    ),
                    deep_analysis_top=int(
                        self.cfg.strategy["selection"]["deep_analysis_top"]
                    ),
                )
                guard_resolution = self.guard_resolver.resolve(
                    candidates=selection.deep_analysis,
                    bars_by_symbol=bars_by_symbol,
                    as_of=as_of,
                )
                guard_inputs = guard_resolution.flags_by_symbol
                guard_missing = guard_resolution.missing_by_symbol
                calendar_error = guard_resolution.calendar_error

            deep = scan_deep_candidates_report(
                ranked=ranked,
                bars_by_symbol=bars_by_symbol,
                cfg=self.cfg,
                as_of=as_of,
                external_guards_by_symbol=guard_inputs or {},
            )
            failures.update(deep.skipped)
            signals_written, ready = self._persist_signals(
                run_id,
                as_of=as_of,
                report=deep,
            )
            self.store.finish_scanner_run(run_id, status="COMPLETED", finished_at=self.clock())
            return SignalProducerReport(
                run_id=run_id,
                observed_at=as_of,
                market_symbols=len(bars_by_symbol),
                macro_currencies=len(macro_scores),
                ranked_pairs=len(ranked),
                deep_candidates=len(deep.selection.deep_analysis),
                analyses=len(deep.analyses),
                signals_written=signals_written,
                execution_ready=ready,
                skipped=dict(sorted(failures.items())),
                missing_macro=missing_macro,
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
