"""Batch and reuse SELECT results for one read-only dashboard publication."""
from __future__ import annotations

from copy import deepcopy
from .turso_client import Query, Result


def _key(sql, args):
    return sql, tuple(args)


class ReadPlanner:
    def __init__(self):
        self.statements = {}

    def table(self, name):
        return Query(self, name)

    def batch(self, statements, **kwargs):
        for sql, args in statements:
            if not sql.startswith("SELECT "):
                raise ValueError("dashboard planner accepts SELECT only")
            self.statements[_key(sql, args)] = (sql, args)
        return [Result([]) for _ in statements]


class DashboardReadClient:
    """Cache lifetime is exactly one build_snapshot call, never across cycles."""
    def __init__(self, client):
        self.client = client
        self.cache = {}
        self.prefetch_errors = []
        self.prefetched_statements = 0
        self.cached_reads = 0

    def table(self, name):
        return Query(self, name)

    def prefetch(self, statements, chunk_size=24):
        statements = list(statements)
        for offset in range(0, len(statements), chunk_size):
            chunk = statements[offset:offset + chunk_size]
            try:
                results = self.client.batch(chunk)
                if len(results) != len(chunk):
                    raise ValueError("incomplete read batch")
                for (sql, args), result in zip(chunk, results):
                    self.cache[_key(sql, args)] = result
                self.prefetched_statements += len(chunk)
            except Exception as exc:
                # The normal reader performs its existing per-worker fallback.
                # No failed/partial batch is cached as an empty successful read.
                self.prefetch_errors.append(type(exc).__name__)

    def batch(self, statements, **kwargs):
        if any(not sql.startswith("SELECT ") for sql, args in statements):
            raise ValueError("dashboard client is read-only")
        if all(_key(sql, args) in self.cache for sql, args in statements):
            self.cached_reads += len(statements)
            return [deepcopy(self.cache[_key(sql, args)]) for sql, args in statements]
        return self.client.batch(statements, **kwargs)

    def usage_snapshot(self):
        return {**self.client.usage_snapshot(),
                "dashboard_prefetched_statements": self.prefetched_statements,
                "dashboard_cached_reads": self.cached_reads,
                "dashboard_prefetch_errors": self.prefetch_errors}


def prepare_dashboard_reads(client, reader_type, *, hot_workers, structural_workers,
                            support_workers, structural_due, support_due, cold_due,
                            outcomes_due):
    planner = ReadPlanner()
    reader = reader_type(planner)
    reader.heartbeats_for_workers(list(hot_workers))
    # Prime current decisions before bulky diagnostic tiers.
    for method in (
        "latest_xau_sd_liquidity_operational_heartbeat",
        "latest_xau_friend_entry_operational_heartbeat",
        "latest_rizan_prepared_heartbeat", "latest_rizan_v229_execution_heartbeat",
        "latest_rizan_child_executor_heartbeat",
        "latest_xau_atlas_operational_heartbeat", "latest_xau_v226_operational_heartbeat",
        "latest_xau_decision_center_operational_heartbeat",
        "latest_xau_micro_destination_operational_heartbeat",
        "latest_xau_event_risk_operational_heartbeat",
        "latest_xau_macro_attribution_operational_heartbeat",
    ):
        getattr(reader, method)()
    if structural_due:
        reader.heartbeats_for_workers(list(structural_workers))
    if support_due:
        reader.heartbeat_summaries()
        reader.heartbeats_for_workers(list(support_workers))
    if cold_due:
        reader.latest_run()
        reader.latest_signals()
        reader.latest_macro()
        reader.latest_performance()
    if outcomes_due:
        reader.latest_xau_outcomes()
    reader.latest_signals_for_symbol("XAUUSD", limit=8)
    reader.latest_afic_forecast_states(limit=6)
    reader.latest_afic_prepared_plans(limit=1)
    reader.latest_xau_geometry_events_compact(limit=2)
    reader.latest_xau_execution_events(limit=4)
    reader.latest_xau_prepared_plan_lifecycle(limit=4)
    reader.latest_rizan_execution_geometry_compact(limit=1)
    out = DashboardReadClient(client)
    out.prefetch(planner.statements.values())
    return out
