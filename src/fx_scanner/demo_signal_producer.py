from __future__ import annotations

from datetime import datetime
from typing import Mapping

from .demo_technical_strategy import scan_demo_deep_candidates_report
from .models import ensure_utc
from .ranking import rank_pairs_technical_only
from .signal_producer import CTraderSignalProducer, SignalProducerReport, _closed_bars
from .strategy import DeepScanReport, select_pair_candidates


class ExplicitDemoTechnicalSignalProducer(CTraderSignalProducer):
    """DEMO-only producer with an explicit technical strategy dependency path.

    The DEMO path uses a two-stage market fetch. M5/M15/H1 are fetched for the
    whole universe first so technical ranking and near-entry monitoring happen
    as early as possible. Slower D1/H4 history is then hydrated only for the
    shortlist that can reach deep analysis. Request pacing remains unchanged, so
    the cTrader 5 requests/sec safety limit is preserved.

    A usable last-known quote may supply the historical-bar spread proxy, but a
    symbol is admitted to ranking only after a fresh quote is observed *after*
    its fast historical hydration. This prevents a long discovery pass from
    rejecting the entire universe because the pre-hydration spot snapshot aged
    out, without relaxing the configured quote-freshness limit.
    """

    last_deep_report: DeepScanReport | None = None
    last_bars_by_symbol: dict[str, dict[str, tuple]] | None = None
    last_decision_at: datetime | None = None

    def _fetch_fast_market(self, *, as_of):
        bars_by_symbol: dict[str, dict[str, tuple]] = {}
        failures: dict[str, str] = {}
        fast_tfs = ("H1", "M15", "M5")
        minimum = self.cfg.strategy["mtf"]["minimum_bars"]

        def available_quote(symbol):
            """Require a structurally valid quote, but defer freshness until post-hydration."""
            try:
                quote = self.feed.quote(symbol)
            except Exception:
                quote, quote_error = self._fresh_quote(symbol)
                if quote is None:
                    return None, quote_error or "QUOTE_UNAVAILABLE:UNKNOWN"
            if not (float(quote.bid) > 0 and float(quote.ask) >= float(quote.bid)):
                return None, "QUOTE_INVALID"
            return quote, None

        def fetch_pair(pair):
            symbol = pair.symbol
            try:
                quote, quote_error = available_quote(symbol)
                if quote is None:
                    return None, quote_error or "QUOTE_UNAVAILABLE:UNKNOWN"

                bundle: dict[str, tuple] = {}
                for tf in fast_tfs:
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

                # Freshness is enforced at the point where the hydrated symbol
                # becomes ranking-eligible. Never widen max_quote_age_seconds.
                fresh_quote, quote_error = self._fresh_quote(symbol)
                if fresh_quote is None:
                    return None, quote_error or "QUOTE_UNAVAILABLE:UNKNOWN"
                return bundle, None
            except Exception as exc:
                return None, f"{type(exc).__name__}:{exc}"

        for pair in self.cfg.pairs:
            bundle, error = fetch_pair(pair)
            if bundle is None:
                failures[pair.symbol] = error or "UNKNOWN"
            else:
                bars_by_symbol[pair.symbol] = bundle

        retry_symbols = [
            symbol
            for symbol, reason in failures.items()
            if reason.startswith(("QUOTE_STALE:", "QUOTE_UNAVAILABLE:"))
        ]
        for symbol in retry_symbols:
            pair = self.cfg.pair_map[symbol]
            bundle, error = fetch_pair(pair)
            if bundle is None:
                failures[symbol] = error or failures[symbol]
            else:
                bars_by_symbol[symbol] = bundle
                failures.pop(symbol, None)
        return bars_by_symbol, dict(sorted(failures.items()))

    def _hydrate_slow_timeframes(self, *, bars_by_symbol, symbols, as_of):
        minimum = self.cfg.strategy["mtf"]["minimum_bars"]
        failures: dict[str, str] = {}
        for symbol in symbols:
            bundle = bars_by_symbol.get(symbol)
            if bundle is None:
                continue
            try:
                for tf in ("D1", "H4"):
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
            except Exception as exc:
                failures[symbol] = f"SLOW_TF:{type(exc).__name__}:{exc}"
        return dict(sorted(failures.items()))

    def run_once(
        self,
        *,
        external_guards_by_symbol: Mapping[str, Mapping[str, bool]] | None = None,
    ) -> SignalProducerReport:
        if not self.technical_only_scalping:
            raise RuntimeError("ExplicitDemoTechnicalSignalProducer requires technical_only_scalping")

        snapshot_at = ensure_utc(self.clock())
        run_id = self.store.start_scanner_run(
            mode="DEMO_ONLY",
            code_version=self.code_version,
            started_at=snapshot_at,
        )
        failures: dict[str, str] = {}
        try:
            self.feed.ensure_connected()
            bars_by_symbol, market_failures = self._fetch_fast_market(as_of=snapshot_at)
            failures.update(market_failures)

            combined_strength, strength_by_tf = self._technical_strength(bars_by_symbol)
            self._persist_strength(
                run_id,
                as_of=snapshot_at,
                combined=combined_strength,
                per_tf=strength_by_tf,
            )

            ranked = rank_pairs_technical_only(
                self.cfg.pairs,
                technical_strength=combined_strength,
                minimum_coverage=0.80,
            )
            self._persist_rankings(
                run_id,
                as_of=snapshot_at,
                ranked=ranked,
                technical_only=True,
            )

            selection_cfg = self.cfg.strategy["selection"]
            preselection = select_pair_candidates(
                ranked,
                macro_compatible_top=int(selection_cfg["macro_compatible_top"]),
                deep_analysis_top=max(
                    int(selection_cfg["deep_analysis_top"]),
                    int(selection_cfg["macro_compatible_top"]),
                ),
                compatibility_mode="TECHNICAL",
            )
            hydration_symbols = tuple(rank.symbol for rank in preselection.deep_analysis)
            failures.update(
                self._hydrate_slow_timeframes(
                    bars_by_symbol=bars_by_symbol,
                    symbols=hydration_symbols,
                    as_of=snapshot_at,
                )
            )

            decision_at = ensure_utc(self.clock())
            guard_missing: Mapping[str, tuple[str, ...]] = {}
            calendar_error: str | None = None
            guard_inputs = external_guards_by_symbol
            if guard_inputs is None and self.guard_resolver is not None:
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
                external_guards_by_symbol=guard_inputs or {},
            )
            self.last_deep_report = deep
            self.last_bars_by_symbol = {
                symbol: dict(bundle) for symbol, bundle in bars_by_symbol.items()
            }
            self.last_decision_at = decision_at
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