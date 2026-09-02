from __future__ import annotations

from typing import Mapping

from .demo_technical_strategy import scan_demo_deep_candidates_report
from .models import ensure_utc
from .ranking import rank_pairs_technical_only
from .signal_producer import CTraderSignalProducer, SignalProducerReport
from .strategy import DeepScanReport, select_pair_candidates


class ExplicitDemoTechnicalSignalProducer(CTraderSignalProducer):
    """DEMO-only producer with an explicit technical strategy dependency path.

    This class intentionally bypasses the parent run_once deep-scan call so the
    DEMO geometry builder is selected by direct function call, not monkeypatch.
    All market fetch, ranking, persistence and guard resolution mechanics remain
    inherited from the proven cTrader signal producer.
    """

    last_deep_report: DeepScanReport | None = None

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
            bars_by_symbol, market_failures = self._fetch_market(as_of=snapshot_at)
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

            decision_at = ensure_utc(self.clock())
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
