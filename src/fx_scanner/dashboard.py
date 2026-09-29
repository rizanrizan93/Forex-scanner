from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import FXScannerError


class DashboardReadError(FXScannerError):
    """Read-only dashboard query failed."""


def merge_runtime_heartbeat_rows(
    base_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    overlay_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Overlay fresh compact operational heartbeats without losing cached detail.

    V182/V226 full payloads are intentionally expensive and can stay on the
    ten-minute detail budget. Their current path/candidate fields are projected
    every minute. This merger replaces the operational fields wholesale so an
    empty new candidate clears an old candidate, while retaining historical
    research/detail fields from the cached full heartbeat.
    """

    by_worker: dict[str, dict[str, Any]] = {
        str(dict(row).get("worker_name") or ""): dict(row)
        for row in list(base_rows or [])
        if str(dict(row).get("worker_name") or "")
    }

    for raw in list(overlay_rows or []):
        fresh = dict(raw or {})
        worker = str(fresh.get("worker_name") or "")
        if not worker:
            continue
        base = dict(by_worker.get(worker) or {})
        if not base:
            by_worker[worker] = fresh
            continue

        merged = dict(base)
        for key in ("worker_name", "observed_at", "healthy", "lag_seconds"):
            if key in fresh:
                merged[key] = fresh.get(key)

        old_details = dict(base.get("details") or {})
        new_details = dict(fresh.get("details") or {})
        old_eval = dict(old_details.get("evaluation") or {})
        new_eval = dict(new_details.get("evaluation") or {})

        if worker == "ctrader_demo_xau_supply_demand_atlas_v182":
            for key in (
                "state",
                "as_of",
                "last_closed_m15_price",
                "strategic_bias",
                "nearest_demand",
                "nearest_supply",
            ):
                if key in new_eval:
                    old_eval[key] = new_eval.get(key)

            old_path_map = dict(old_eval.get("path_map") or {})
            new_path_map = dict(new_eval.get("path_map") or {})
            if "active_path" in new_path_map:
                old_path_map["active_path"] = dict(
                    new_path_map.get("active_path") or {}
                )
            if "demand_to_supply" in new_path_map:
                old_d2s = dict(old_path_map.get("demand_to_supply") or {})
                old_d2s.update(dict(new_path_map.get("demand_to_supply") or {}))
                old_path_map["demand_to_supply"] = old_d2s
            if "supply_to_demand" in new_path_map:
                old_s2d = dict(old_path_map.get("supply_to_demand") or {})
                old_s2d.update(dict(new_path_map.get("supply_to_demand") or {}))
                old_path_map["supply_to_demand"] = old_s2d
            old_eval["path_map"] = old_path_map

            old_projection = dict(old_eval.get("m5_path_projection") or {})
            new_projection = dict(new_eval.get("m5_path_projection") or {})
            for leg in ("current_leg", "next_leg"):
                if leg in new_projection:
                    old_projection[leg] = dict(new_projection.get(leg) or {})
            if "state" in new_projection:
                old_projection["state"] = new_projection.get("state")
            old_eval["m5_path_projection"] = old_projection

            if "micro_refinement" in new_eval:
                old_eval["micro_refinement"] = dict(
                    new_eval.get("micro_refinement") or {}
                )

        elif worker == "ctrader_demo_xau_v226_rizan_depth_map":
            for key in (
                "state",
                "focus_direction",
                "price_reference",
                "depth_entry_candidate",
                "entry_candidates",
                "four_order_ladder",
            ):
                if key in new_eval:
                    old_eval[key] = new_eval.get(key)

            for side in ("long", "short"):
                fresh_side = dict(new_eval.get(side) or {})
                if not fresh_side:
                    continue
                old_side = dict(old_eval.get(side) or {})
                for timeframe in ("h4", "h1", "m15"):
                    fresh_layer = dict(fresh_side.get(timeframe) or {})
                    if not fresh_layer:
                        continue
                    old_layer = dict(old_side.get(timeframe) or {})
                    if "zone" in fresh_layer:
                        old_layer["zone"] = dict(fresh_layer.get("zone") or {})
                    if "applicability" in fresh_layer:
                        old_layer["applicability"] = dict(
                            fresh_layer.get("applicability") or {}
                        )
                    old_side[timeframe] = old_layer
                if "h4_selection_mode" in fresh_side:
                    old_side["h4_selection_mode"] = fresh_side.get(
                        "h4_selection_mode"
                    )
                old_eval[side] = old_side
        else:
            old_details.update(new_details)

        if new_eval or "evaluation" in new_details:
            old_details["evaluation"] = old_eval
        for key, value in new_details.items():
            if key != "evaluation":
                old_details[key] = value
        merged["details"] = old_details
        by_worker[worker] = merged

    return sorted(
        by_worker.values(),
        key=lambda row: str(row.get("observed_at") or ""),
        reverse=True,
    )


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    latest_run: dict[str, Any] | None
    rankings: tuple[dict[str, Any], ...]
    signals: tuple[dict[str, Any], ...]
    xau_signals: tuple[dict[str, Any], ...]
    heartbeats: tuple[dict[str, Any], ...]
    macro: tuple[dict[str, Any], ...]
    performance: tuple[dict[str, Any], ...]
    broker_account: dict[str, Any] | None
    broker_positions: tuple[dict[str, Any], ...]
    afic_forecast_states: tuple[dict[str, Any], ...]
    afic_prepared_plans: tuple[dict[str, Any], ...]
    afic_execution_geometry: tuple[dict[str, Any], ...]
    xau_execution_events: tuple[dict[str, Any], ...]
    xau_outcomes: tuple[dict[str, Any], ...] = ()
    xau_prepared_plan_lifecycle: tuple[dict[str, Any], ...] = ()


class SupabaseDashboardReader:
    """Read-only dashboard adapter.

    The dashboard is intentionally outside the scanner/execution hot path.
    It reads durable snapshots already written by runtime/research workers and
    never submits orders or mutates execution state.
    """

    def __init__(self, client: Any):
        self.client = client

    @staticmethod
    def _rows(response: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in (getattr(response, "data", None) or [])]

    def latest_run(self) -> dict[str, Any] | None:
        try:
            response = (
                self.client.table("scanner_runs")
                .select(
                    "id,started_at,finished_at,mode,status,code_version,"
                    "data_contract_version"
                )
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"scanner_runs read failed: {exc}") from exc
        rows = self._rows(response)
        return rows[0] if rows else None

    def rankings_for_run(
        self,
        run_id: str | None,
        *,
        limit: int = 15,
    ) -> tuple[dict[str, Any], ...]:
        if not run_id:
            return ()
        try:
            response = (
                self.client.table("pair_rankings")
                .select(
                    "observed_at,symbol,direction,macro_edge,technical_edge,"
                    "cross_asset_score,session_score,volatility_score,spread_score,"
                    "pair_opportunity_score,rank,coverage"
                )
                .eq("run_id", str(run_id))
                .order("rank")
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"pair_rankings read failed: {exc}") from exc
        return tuple(self._rows(response))

    def latest_signals(self, *, limit: int = 30) -> tuple[dict[str, Any], ...]:
        try:
            response = (
                self.client.table("signals")
                .select(
                    "id,observed_at,symbol,direction,setup_type,state,pair_score,"
                    "execution_score,final_score,entry_low,entry_high,sl,tp1,tp2,tp3,"
                    "rr1,rr2,rr3,macro_bias,h4_bias,h1_bias,active_guards,"
                    "data_coverage,expires_at"
                )
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"signals read failed: {exc}") from exc
        return tuple(self._rows(response))

    def latest_signals_for_symbol(
        self, symbol: str, *, limit: int = 20
    ) -> tuple[dict[str, Any], ...]:
        normalized = str(symbol or "").upper().strip()
        if not normalized:
            return ()
        try:
            response = (
                self.client.table("signals")
                .select(
                    "id,observed_at,symbol,direction,setup_type,state,pair_score,"
                    "execution_score,final_score,entry_low,entry_high,sl,tp1,tp2,tp3,"
                    "rr1,rr2,rr3,macro_bias,h4_bias,h1_bias,active_guards,"
                    "data_coverage,expires_at"
                )
                .eq("symbol", normalized)
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"signals read failed for {normalized}: {exc}") from exc
        return tuple(self._rows(response))

    def heartbeats(self) -> tuple[dict[str, Any], ...]:
        """Return compact observability rows.

        Full heartbeat details are intentionally reserved for
        :meth:`heartbeats_for_workers`, which is bounded to the decision-critical
        worker set. This prevents the System tab from retransmitting multi-megabyte
        diagnostic JSON on every dashboard refresh.
        """
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select("worker_name,observed_at,healthy,lag_seconds")
                .order("observed_at", desc=True)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"runtime_heartbeats read failed: {exc}") from exc
        return tuple(self._rows(response))

    def heartbeat_summaries(self) -> tuple[dict[str, Any], ...]:
        """Return lightweight health rows without large worker detail payloads."""
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select("worker_name,observed_at,healthy,lag_seconds")
                .order("observed_at", desc=True)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"runtime_heartbeat summary read failed: {exc}"
            ) from exc
        return tuple(self._rows(response))

    def heartbeats_for_workers(
        self,
        worker_names: tuple[str, ...] | list[str],
    ) -> tuple[dict[str, Any], ...]:
        """Return full heartbeat details only for dashboard-critical workers.

        This keeps the 60-second decision path fresh without retransmitting every
        observability heartbeat payload on every Streamlit refresh.
        """
        normalized = tuple(
            dict.fromkeys(
                str(name).strip()
                for name in worker_names
                if str(name).strip()
            )
        )
        if not normalized:
            return ()
        if len(normalized) > 64:
            raise ValueError("dashboard heartbeat worker budget exceeds 64")
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select("worker_name,observed_at,healthy,lag_seconds,details")
                .in_("worker_name", list(normalized))
                .order("observed_at", desc=True)
                .limit(len(normalized))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"critical runtime_heartbeats read failed: {exc}"
            ) from exc
        return tuple(self._rows(response))

    def latest_xau_atlas_operational_heartbeat(self) -> dict[str, Any] | None:
        """Return only the V182 fields needed for the current 60-second decision."""

        select_expr = (
            "worker_name,observed_at,healthy,lag_seconds,"
            "state:details->evaluation->>state,"
            "as_of:details->evaluation->>as_of,"
            "last_closed_m15_price:details->evaluation->last_closed_m15_price,"
            "strategic_bias:details->evaluation->>strategic_bias,"
            "active_direction:details->evaluation->path_map->active_path->>reaction_direction,"
            "active_state:details->evaluation->path_map->active_path->>state,"
            "current_leg_direction:details->evaluation->m5_path_projection->current_leg->>direction,"
            "current_leg_path_state:details->evaluation->m5_path_projection->current_leg->>path_state,"
            "current_leg_pocket_state:details->evaluation->m5_path_projection->current_leg->>pocket_state,"
            "current_leg_source_zone:details->evaluation->m5_path_projection->current_leg->source_zone,"
            "current_leg_m5_pocket:details->evaluation->m5_path_projection->current_leg->m5_pocket,"
            "current_leg_reaction_target:details->evaluation->m5_path_projection->current_leg->reaction_target,"
            "current_leg_terminal_target_zone:details->evaluation->m5_path_projection->current_leg->terminal_target_zone,"
            "current_micro_state:details->evaluation->m5_path_projection->current_leg->micro_refinement->>state,"
            "current_micro_direction:details->evaluation->m5_path_projection->current_leg->micro_refinement->>direction,"
            "current_micro_first_touch:details->evaluation->m5_path_projection->current_leg->micro_refinement->>first_eligible_touch_at,"
            "current_micro_sweep:details->evaluation->m5_path_projection->current_leg->micro_refinement->sweep,"
            "current_micro_candidate:details->evaluation->m5_path_projection->current_leg->micro_refinement->candidate_entry_pocket,"
            "current_micro_refined:details->evaluation->m5_path_projection->current_leg->micro_refinement->refined_entry_pocket,"
            "current_micro_parent_rescue:details->evaluation->m5_path_projection->current_leg->micro_refinement->parent_reversal_rescue,"
            "current_micro_reclaim_level:details->evaluation->m5_path_projection->current_leg->micro_refinement->source_proximal_reclaim_level,"
            "current_micro_mss_level:details->evaluation->m5_path_projection->current_leg->micro_refinement->mss_level,"
            "current_micro_reclaim_at:details->evaluation->m5_path_projection->current_leg->micro_refinement->>reclaim_at,"
            "current_micro_mss_at:details->evaluation->m5_path_projection->current_leg->micro_refinement->>mss_at,"
            "current_micro_displacement_at:details->evaluation->m5_path_projection->current_leg->micro_refinement->>displacement_at,"
            "current_leg_touch_cycle_start:details->evaluation->m5_path_projection->current_leg->>touch_cycle_start,"
            "next_leg_direction:details->evaluation->m5_path_projection->next_leg->>direction,"
            "next_leg_path_state:details->evaluation->m5_path_projection->next_leg->>path_state,"
            "next_leg_pocket_state:details->evaluation->m5_path_projection->next_leg->>pocket_state,"
            "next_leg_source_zone:details->evaluation->m5_path_projection->next_leg->source_zone,"
            "next_leg_m5_pocket:details->evaluation->m5_path_projection->next_leg->m5_pocket,"
            "next_leg_reaction_target:details->evaluation->m5_path_projection->next_leg->reaction_target,"
            "next_leg_terminal_target_zone:details->evaluation->m5_path_projection->next_leg->terminal_target_zone,"
            "next_micro_state:details->evaluation->m5_path_projection->next_leg->micro_refinement->>state,"
            "next_micro_direction:details->evaluation->m5_path_projection->next_leg->micro_refinement->>direction,"
            "next_micro_first_touch:details->evaluation->m5_path_projection->next_leg->micro_refinement->>first_eligible_touch_at,"
            "next_micro_sweep:details->evaluation->m5_path_projection->next_leg->micro_refinement->sweep,"
            "next_micro_candidate:details->evaluation->m5_path_projection->next_leg->micro_refinement->candidate_entry_pocket,"
            "next_micro_refined:details->evaluation->m5_path_projection->next_leg->micro_refinement->refined_entry_pocket,"
            "next_micro_reclaim_at:details->evaluation->m5_path_projection->next_leg->micro_refinement->>reclaim_at,"
            "next_micro_mss_at:details->evaluation->m5_path_projection->next_leg->micro_refinement->>mss_at,"
            "projection_state:details->evaluation->m5_path_projection->>state"
        )
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select(select_expr)
                .eq("worker_name", "ctrader_demo_xau_supply_demand_atlas_v182")
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"V182 operational heartbeat read failed: {exc}"
            ) from exc
        rows = self._rows(response)
        if not rows:
            return None
        raw = dict(rows[0])

        current_source = dict(raw.pop("current_leg_source_zone", {}) or {})
        current_target = dict(raw.pop("current_leg_reaction_target", {}) or {})
        current_terminal = dict(
            raw.pop("current_leg_terminal_target_zone", {}) or {}
        )
        active_direction = str(
            raw.pop("active_direction", None)
            or raw.get("current_leg_direction")
            or ""
        ).upper()

        current_micro = {
            "state": raw.pop("current_micro_state", None),
            "direction": raw.pop("current_micro_direction", None),
            "first_eligible_touch_at": raw.pop(
                "current_micro_first_touch", None
            ),
            "sweep": dict(raw.pop("current_micro_sweep", {}) or {}),
            "candidate_entry_pocket": dict(
                raw.pop("current_micro_candidate", {}) or {}
            ),
            "refined_entry_pocket": dict(
                raw.pop("current_micro_refined", {}) or {}
            ),
            "parent_reversal_rescue": dict(
                raw.pop("current_micro_parent_rescue", {}) or {}
            ),
            "source_proximal_reclaim_level": raw.pop(
                "current_micro_reclaim_level", None
            ),
            "mss_level": raw.pop("current_micro_mss_level", None),
            "reclaim_at": raw.pop("current_micro_reclaim_at", None),
            "mss_at": raw.pop("current_micro_mss_at", None),
            "displacement_at": raw.pop(
                "current_micro_displacement_at", None
            ),
        }
        next_micro = {
            "state": raw.pop("next_micro_state", None),
            "direction": raw.pop("next_micro_direction", None),
            "first_eligible_touch_at": raw.pop("next_micro_first_touch", None),
            "sweep": dict(raw.pop("next_micro_sweep", {}) or {}),
            "candidate_entry_pocket": dict(
                raw.pop("next_micro_candidate", {}) or {}
            ),
            "refined_entry_pocket": dict(
                raw.pop("next_micro_refined", {}) or {}
            ),
            "reclaim_at": raw.pop("next_micro_reclaim_at", None),
            "mss_at": raw.pop("next_micro_mss_at", None),
        }

        current_leg = {
            "direction": raw.pop("current_leg_direction", None),
            "path_state": raw.pop("current_leg_path_state", None),
            "pocket_state": raw.pop("current_leg_pocket_state", None),
            "source_zone": current_source,
            "m5_pocket": dict(raw.pop("current_leg_m5_pocket", {}) or {}),
            "reaction_target": current_target,
            "terminal_target_zone": current_terminal,
            "micro_refinement": current_micro,
            "touch_cycle_start": raw.pop("current_leg_touch_cycle_start", None),
        }
        next_leg = {
            "direction": raw.pop("next_leg_direction", None),
            "path_state": raw.pop("next_leg_path_state", None),
            "pocket_state": raw.pop("next_leg_pocket_state", None),
            "source_zone": dict(raw.pop("next_leg_source_zone", {}) or {}),
            "m5_pocket": dict(raw.pop("next_leg_m5_pocket", {}) or {}),
            "reaction_target": dict(raw.pop("next_leg_reaction_target", {}) or {}),
            "terminal_target_zone": dict(
                raw.pop("next_leg_terminal_target_zone", {}) or {}
            ),
            "micro_refinement": next_micro,
            "touch_cycle_start": raw.pop("next_leg_touch_cycle_start", None),
        }

        # For the operational dashboard, current source and current terminal are
        # the actionable nearest same/opposite structural zones. The full V182
        # zone universe remains available in the ten-minute detail heartbeat.
        nearest_demand = (
            current_source if active_direction == "LONG" else current_terminal
        )
        nearest_supply = (
            current_terminal if active_direction == "LONG" else current_source
        )

        evaluation = {
            "state": raw.pop("state", None),
            "as_of": raw.pop("as_of", None),
            "last_closed_m15_price": raw.pop("last_closed_m15_price", None),
            "strategic_bias": raw.pop("strategic_bias", None),
            "nearest_demand": dict(nearest_demand or {}),
            "nearest_supply": dict(nearest_supply or {}),
            "path_map": {
                "active_path": {
                    "reaction_direction": active_direction or None,
                    "state": raw.pop("active_state", None),
                    "source_zone": current_source,
                    "reaction_target": current_target,
                    "primary_opposing_zone": current_terminal,
                    "terminal_target_zone": current_terminal,
                },
            },
            "m5_path_projection": {
                "state": raw.pop("projection_state", None),
                "current_leg": current_leg,
                "next_leg": next_leg,
            },
            "micro_refinement": current_micro,
        }
        raw["details"] = {
            "evaluation": evaluation,
            "transport_projection": "V182_OPERATIONAL_60S",
        }
        return raw

    def latest_xau_v226_operational_heartbeat(self) -> dict[str, Any] | None:
        """Return current V226 candidate identity with only H4 execution geometry."""

        select_expr = (
            "worker_name,observed_at,healthy,lag_seconds,"
            "state:details->evaluation->>state,"
            "focus_direction:details->evaluation->>focus_direction,"
            "price_reference:details->evaluation->price_reference,"
            "depth_entry_candidate:details->evaluation->depth_entry_candidate,"
            "entry_candidates:details->evaluation->entry_candidates,"
            "four_order_ladder:details->evaluation->four_order_ladder,"
            "long_h4_zone:details->evaluation->long->h4->zone,"
            "short_h4_zone:details->evaluation->short->h4->zone"
        )
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select(select_expr)
                .eq("worker_name", "ctrader_demo_xau_v226_rizan_depth_map")
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"V226 operational heartbeat read failed: {exc}"
            ) from exc
        rows = self._rows(response)
        if not rows:
            return None
        raw = dict(rows[0])
        evaluation = {
            "state": raw.pop("state", None),
            "focus_direction": raw.pop("focus_direction", None),
            "price_reference": raw.pop("price_reference", None),
            "depth_entry_candidate": dict(
                raw.pop("depth_entry_candidate", {}) or {}
            ),
            "entry_candidates": dict(raw.pop("entry_candidates", {}) or {}),
            "four_order_ladder": dict(raw.pop("four_order_ladder", {}) or {}),
            "long": {
                "h4": {"zone": dict(raw.pop("long_h4_zone", {}) or {})},
            },
            "short": {
                "h4": {"zone": dict(raw.pop("short_h4_zone", {}) or {})},
            },
        }
        raw["details"] = {
            "evaluation": evaluation,
            "transport_projection": "V226_OPERATIONAL_60S",
        }
        return raw

    def latest_rizan_prepared_heartbeat(self) -> dict[str, Any] | None:
        """Return the current prepared-plan heartbeat without duplicated atlas JSON.

        The prepared worker carries a large supply_demand_context copy that is
        already available from V182. The dashboard only needs scalar admission,
        zone and lifecycle fields from this heartbeat on the 60-second path.
        """
        select_expr = (
            "worker_name,observed_at,healthy,lag_seconds,"
            "forecast_state:details->>forecast_state,"
            "continuation_direction:details->>continuation_direction,"
            "zone_low:details->zone_low,"
            "zone_high:details->zone_high,"
            "forecast_selector_grade:details->>forecast_selector_grade,"
            "live_price:details->live_price,"
            "distance_to_zone_points:details->distance_to_zone_points,"
            "distance_to_zone_atr:details->distance_to_zone_atr,"
            "proximity_state:details->>proximity_state,"
            "effective_scan_seconds:details->effective_scan_seconds,"
            "execution_enabled_env:details->execution_enabled_env,"
            "handoff_allowlisted:details->handoff_allowlisted,"
            "signal_id:details->>signal_id,"
            "map_at:details->>map_at,"
            "first_touch_at:details->>first_touch_at,"
            "map_first_touch_at:details->>map_first_touch_at,"
            "zone_diagnostics:details->zone_diagnostics,"
            "touch_lifecycle:details->touch_lifecycle,"
            "zone_lifecycle:details->zone_lifecycle,"
            "blueprint_block_reason:details->>blueprint_block_reason"
        )
        worker_names = (
            "ctrader_demo_xau_rizan_prepared_plan_producer",
            "ctrader_demo_xau_afic_prepared_plan_producer",
        )
        for worker_name in worker_names:
            try:
                response = (
                    self.client.table("runtime_heartbeats")
                    .select(select_expr)
                    .eq("worker_name", worker_name)
                    .order("observed_at", desc=True)
                    .limit(1)
                    .execute()
                )
            except Exception as exc:
                raise DashboardReadError(
                    f"prepared heartbeat read failed for {worker_name}: {exc}"
                ) from exc
            rows = self._rows(response)
            if not rows:
                continue
            raw = dict(rows[0])
            if isinstance(raw.get("details"), dict):
                return raw
            detail_fields = (
                "forecast_state",
                "continuation_direction",
                "zone_low",
                "zone_high",
                "forecast_selector_grade",
                "live_price",
                "distance_to_zone_points",
                "distance_to_zone_atr",
                "proximity_state",
                "effective_scan_seconds",
                "execution_enabled_env",
                "handoff_allowlisted",
                "signal_id",
                "map_at",
                "first_touch_at",
                "map_first_touch_at",
                "zone_diagnostics",
                "touch_lifecycle",
                "zone_lifecycle",
                "blueprint_block_reason",
            )
            # Operational projection fields are authoritative for the current
            # heartbeat even when their value is NULL. Preserving explicit NULLs
            # is critical: otherwise merge_runtime_heartbeat_rows would retain an
            # older cached live_price/zone/distance and make a fresh heartbeat look
            # current while displaying stale market state.
            details = {
                key: raw.pop(key, None)
                for key in detail_fields
            }
            raw["details"] = details
            return raw
        return None

    def latest_rizan_v229_execution_heartbeat(self) -> dict[str, Any] | None:
        """Return only V229 execution fields consumed by the dashboard.

        Pressure transition and Dynamic Depth are already supplied by V191/V226
        and recomputed by V249/V251 in the dashboard. Projecting the V229 row
        avoids retransmitting those duplicated nested payloads every minute.
        """
        select_expr = (
            "worker_name,observed_at,healthy,lag_seconds,"
            "reason:details->>reason,"
            "signal_id:details->>signal_id,"
            "error:details->>error,"
            "plan_execution_phase:details->plan->>execution_phase,"
            "plan_children:details->plan->children,"
            "plan_diagnostics:details->plan_diagnostics,"
            "structure_admission:details->structure_admission"
        )
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select(select_expr)
                .eq("worker_name", "ctrader_demo_xau_v229_depth_execution")
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"V229 execution heartbeat read failed: {exc}"
            ) from exc
        rows = self._rows(response)
        if not rows:
            return None
        raw = dict(rows[0])
        if isinstance(raw.get("details"), dict):
            return raw
        raw["details"] = {
            "reason": raw.pop("reason", None),
            "signal_id": raw.pop("signal_id", None),
            "error": raw.pop("error", None),
            "plan": ({
                "execution_phase": raw.pop("plan_execution_phase", None),
                "children": list(raw.pop("plan_children", []) or []),
            } if raw.get("plan_execution_phase") is not None or raw.get("plan_children") else {}),
            "plan_diagnostics": dict(raw.pop("plan_diagnostics", {}) or {}),
            "structure_admission": dict(raw.pop("structure_admission", {}) or {}),
        }
        return raw

    def latest_rizan_child_executor_heartbeat(self) -> dict[str, Any] | None:
        """Return only child-executor state consumed by the dashboard."""
        select_expr = (
            "worker_name,observed_at,healthy,lag_seconds,"
            "actions:details->actions,"
            "error:details->>error,"
            "enabled:details->enabled"
        )
        try:
            response = (
                self.client.table("runtime_heartbeats")
                .select(select_expr)
                .eq("worker_name", "ctrader_demo_xau_v229_child_executor")
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"V229 child heartbeat read failed: {exc}"
            ) from exc
        rows = self._rows(response)
        if not rows:
            return None
        raw = dict(rows[0])
        if isinstance(raw.get("details"), dict):
            return raw
        raw["details"] = {
            "actions": list(raw.pop("actions", []) or []),
            "error": raw.pop("error", None),
            "enabled": raw.pop("enabled", None),
        }
        return raw

    def latest_macro(self, *, raw_limit: int = 96) -> tuple[dict[str, Any], ...]:
        """Return the newest durable macro snapshot per currency."""
        try:
            response = (
                self.client.table("currency_macro_state")
                .select(
                    "currency,observed_at,rate_score,central_bank_score,"
                    "inflation_score,growth_score,labour_score,yield_score,"
                    "risk_score,positioning_score,macro_score,coverage,"
                    "freshness_seconds"
                )
                .order("observed_at", desc=True)
                .limit(int(raw_limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"currency_macro_state read failed: {exc}") from exc

        newest: dict[str, dict[str, Any]] = {}
        for row in self._rows(response):
            currency = str(row.get("currency", "")).upper()
            if currency and currency not in newest:
                newest[currency] = row
        return tuple(newest[key] for key in sorted(newest))

    def latest_performance(self, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        try:
            response = (
                self.client.table("model_performance")
                .select(
                    "as_of,setup_type,symbol,session,regime,sample_scope,"
                    "trades,wins,losses,win_rate,expectancy_r,profit_factor,"
                    "max_drawdown_r"
                )
                .order("as_of", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"model_performance read failed: {exc}") from exc
        return tuple(self._rows(response))

    def latest_xau_outcomes(self, *, limit: int = 500) -> tuple[dict[str, Any], ...]:
        """Return recent XAU outcome-ledger rows for read-only evidence panels."""
        try:
            response = (
                self.client.table("xau_outcome_ledger")
                .select(
                    "episode_key,episode_type,strategy_id,observed_at,direction,grade,"
                    "status,execution_authority,outcome_at,outcome_class,tp1_hit,tp2_hit,"
                    "stop_hit,mfe_r,mae_r,metadata"
                )
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(f"xau_outcome_ledger read failed: {exc}") from exc
        return tuple(self._rows(response))

    def latest_broker_account(self) -> dict[str, Any] | None:
        try:
            response = (
                self.client.table("broker_account_state")
                .select(
                    "backend,account_id,snapshot_id,observed_at,broker_name,"
                    "environment,currency,balance,equity,floating_profit,margin,"
                    "margin_free,margin_level,leverage,trade_allowed,"
                    "connection_healthy,metadata"
                )
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"broker_account_state read failed: {exc}"
            ) from exc
        rows = self._rows(response)
        return rows[0] if rows else None

    def broker_positions_for_account(
        self,
        account: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], ...]:
        if not account or not account.get("snapshot_id"):
            return ()
        try:
            response = (
                self.client.table("broker_position_state")
                .select(
                    "observed_at,position_id,symbol,side,volume,open_price,"
                    "current_price,sl,tp,profit,swap,magic,comment,opened_at"
                )
                .eq("backend", str(account["backend"]))
                .eq("account_id", str(account["account_id"]))
                .eq("snapshot_id", str(account["snapshot_id"]))
                .order("profit", desc=True)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"broker_position_state read failed: {exc}"
            ) from exc
        return tuple(self._rows(response))

    def latest_afic_forecast_states(self, *, limit: int = 12) -> tuple[dict[str, Any], ...]:
        """Return compact current forecast state plus transition history.

        Structural/path context is sourced from V182 instead of being duplicated
        inside the minute-level forecast row. Older rows contain only the scalar
        fields rendered by the history table.
        """
        limit = max(1, min(int(limit), 24))
        try:
            latest_response = (
                self.client.table("broker_order_events")
                .select(
                    "observed_at,event_type,code,message,"
                    "map_at:payload->forecast->>map_at,"
                    "state:payload->forecast->>state,"
                    "direction:payload->forecast->>continuation_direction,"
                    "zone:payload->forecast->zone,"
                    "zone_diagnostics:payload->forecast->zone_diagnostics"
                )
                .eq("event_type", "DEMO_XAU_RIZAN_FORECAST_STATE")
                .eq("code", "XAU_RIZAN_PATH_STATE_V1")
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
            latest_rows = self._rows(latest_response)
            if latest_rows:
                latest_raw = latest_rows[0]
                if isinstance(latest_raw.get("payload"), dict):
                    latest = latest_raw
                else:
                    latest = {
                        "observed_at": latest_raw.get("observed_at"),
                        "event_type": latest_raw.get("event_type") or "DEMO_XAU_RIZAN_FORECAST_STATE",
                        "code": latest_raw.get("code") or "XAU_RIZAN_PATH_STATE_V1",
                        "message": latest_raw.get("message"),
                        "payload": {
                            "forecast": {
                                "map_at": latest_raw.get("map_at"),
                                "state": latest_raw.get("state"),
                                "continuation_direction": latest_raw.get("direction"),
                                "zone": dict(latest_raw.get("zone") or {}),
                                "zone_diagnostics": dict(latest_raw.get("zone_diagnostics") or {}),
                            }
                        },
                    }
                history_response = (
                    self.client.table("broker_order_events")
                    .select(
                        "observed_at,"
                        "map_at:payload->forecast->>map_at,"
                        "state:payload->forecast->>state,"
                        "direction:payload->forecast->>continuation_direction,"
                        "zone_low:payload->forecast->zone->>low,"
                        "zone_high:payload->forecast->zone->>high,"
                        "first_touch_at:payload->forecast->>first_touch_at,"
                        "confirm_at:payload->forecast->>confirm_at,"
                        "invalidated_at:payload->forecast->>invalidated_at"
                    )
                    .eq("event_type", "DEMO_XAU_RIZAN_FORECAST_STATE")
                    .eq("code", "XAU_RIZAN_PATH_STATE_V1")
                    .order("observed_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                compact: list[dict[str, Any]] = [latest]
                latest_at = str(latest.get("observed_at") or "")
                for raw in self._rows(history_response):
                    if str(raw.get("observed_at") or "") == latest_at:
                        continue
                    if isinstance(raw.get("payload"), dict):
                        # Test/fallback clients may ignore projected select aliases.
                        compact.append(raw)
                    else:
                        compact.append(
                            {
                                "observed_at": raw.get("observed_at"),
                                "event_type": "DEMO_XAU_RIZAN_FORECAST_STATE",
                                "code": "XAU_RIZAN_PATH_STATE_V1",
                                "message": None,
                                "payload": {
                                    "forecast": {
                                        "map_at": raw.get("map_at"),
                                        "state": raw.get("state"),
                                        "continuation_direction": raw.get("direction"),
                                        "zone": {
                                            "low": raw.get("zone_low"),
                                            "high": raw.get("zone_high"),
                                        },
                                        "first_touch_at": raw.get("first_touch_at"),
                                        "confirm_at": raw.get("confirm_at"),
                                        "invalidated_at": raw.get("invalidated_at"),
                                    }
                                },
                            }
                        )
                    if len(compact) >= limit:
                        break
                return tuple(compact[:limit])

            # Legacy records remain read-only compatibility and are queried only
            # if no RIZAN state exists in the target database.
            response = (
                self.client.table("broker_order_events")
                .select("observed_at,event_type,code,message,payload")
                .eq("event_type", "DEMO_XAU_AFIC_FORECAST_STATE")
                .eq("code", "XAU_AFIC_PATH_STATE_V1")
                .order("observed_at", desc=True)
                .limit(limit)
                .execute()
            )
            return tuple(self._rows(response)[:limit])
        except Exception as exc:
            raise DashboardReadError(f"RIZAN forecast-state read failed: {exc}") from exc

    def latest_afic_prepared_plans(self, *, limit: int = 1) -> tuple[dict[str, Any], ...]:
        """Return only the current prepared plan with the fields the UI consumes."""
        limit = max(1, min(int(limit), 2))
        try:
            response = (
                self.client.table("broker_order_events")
                .select(
                    "observed_at,event_type,code,message,"
                    "prepared_plan:payload->prepared_plan,"
                    "map_at:payload->forecast->>map_at"
                )
                .eq("event_type", "DEMO_XAU_RIZAN_PREPARED_PLAN")
                .eq("code", "XAU_RIZAN_PATH_PREPARED_V1")
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = self._rows(response)
            if rows:
                row = rows[0]
                if isinstance(row.get("payload"), dict):
                    return (row,)
                return (
                    {
                        "observed_at": row.get("observed_at"),
                        "event_type": row.get("event_type") or "DEMO_XAU_RIZAN_PREPARED_PLAN",
                        "code": row.get("code") or "XAU_RIZAN_PATH_PREPARED_V1",
                        "message": row.get("message"),
                        "payload": {
                            "prepared_plan": dict(row.get("prepared_plan") or {}),
                            "forecast": {"map_at": row.get("map_at")},
                        },
                    },
                )
            response = (
                self.client.table("broker_order_events")
                .select("observed_at,event_type,code,message,payload")
                .eq("event_type", "DEMO_XAU_AFIC_PREPARED_PLAN")
                .eq("code", "XAU_AFIC_PATH_PREPARED_V1")
                .order("observed_at", desc=True)
                .limit(1)
                .execute()
            )
            return tuple(self._rows(response)[:1])
        except Exception as exc:
            raise DashboardReadError(f"RIZAN prepared-plan read failed: {exc}") from exc

    def latest_afic_execution_geometry(self, *, limit: int = 12) -> tuple[dict[str, Any], ...]:
        try:
            response = (
                self.client.table("broker_order_events")
                .select("observed_at,event_type,code,message,signal_key,payload")
                .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
                .in_(
                    "code",
                    [
                        "XAU_RIZAN_DEPTH_EXECUTION_V1",
                        "XAU_RIZAN_PATH_EXECUTION_V1",
                    ],
                )
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
            rows = self._rows(response)
            if rows:
                return tuple(rows[: int(limit)])
            response = (
                self.client.table("broker_order_events")
                .select("observed_at,event_type,code,message,payload")
                .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
                .eq("code", "XAU_AFIC_PATH_EXECUTION_V1")
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
            return tuple(self._rows(response)[: int(limit)])
        except Exception as exc:
            raise DashboardReadError(f"RIZAN execution-geometry read failed: {exc}") from exc

    def latest_rizan_execution_geometry_compact(
        self, *, limit: int = 1
    ) -> tuple[dict[str, Any], ...]:
        """Return only fields V240/admission needs from saved RIZAN geometry."""

        limit = max(1, min(int(limit), 4))
        select_expr = (
            "observed_at,event_type,code,accepted,message,signal_key,broker_order_id,"
            "strategy_id:payload->>strategy_id,"
            "direction:payload->>direction,"
            "candidate_low:payload->candidate_low,"
            "candidate_high:payload->candidate_high,"
            "entry_mode:payload->>entry_mode,"
            "planned_entry:payload->planned_entry,"
            "planned_sl:payload->planned_sl,"
            "planned_tp2:payload->planned_tp2"
        )
        try:
            response = (
                self.client.table("broker_order_events")
                .select(select_expr)
                .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
                .in_(
                    "code",
                    [
                        "XAU_RIZAN_DEPTH_EXECUTION_V1",
                        "XAU_RIZAN_PATH_EXECUTION_V1",
                    ],
                )
                .order("observed_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"compact RIZAN execution-geometry read failed: {exc}"
            ) from exc

        rows: list[dict[str, Any]] = []
        for raw_row in self._rows(response):
            raw = dict(raw_row)
            payload = {
                key: raw.pop(key)
                for key in (
                    "strategy_id",
                    "direction",
                    "candidate_low",
                    "candidate_high",
                    "entry_mode",
                    "planned_entry",
                    "planned_sl",
                    "planned_tp2",
                )
                if raw.get(key) is not None
            }
            raw["payload"] = payload
            rows.append(raw)
        return tuple(rows)

    def latest_xau_geometry_events_compact(
        self, *, limit: int = 4
    ) -> tuple[dict[str, Any], ...]:
        """Return compact authorized geometry rows for UI timeline/admission."""

        limit = max(1, min(int(limit), 12))
        codes = (
            "XAU_RIZAN_DEPTH_EXECUTION_V1",
            "XAU_RIZAN_PATH_EXECUTION_V1",
            "XAU_AFIC_PATH_EXECUTION_V1",
            "XAU_M15_EMA_SMC_RECLAIM_V1",
            "XAU_V24_CHAMPION_DEMO_V1",
        )
        select_expr = (
            "observed_at,event_type,code,accepted,message,signal_key,broker_order_id,"
            "symbol:payload->>symbol,"
            "strategy_id:payload->>strategy_id,"
            "direction:payload->>direction,"
            "executed_price:payload->executed_price,"
            "requested_entry:payload->requested_entry,"
            "planned_entry:payload->planned_entry,"
            "attached_stop_loss:payload->attached_stop_loss,"
            "requested_stop_loss:payload->requested_stop_loss,"
            "planned_sl:payload->planned_sl,"
            "attached_take_profit:payload->attached_take_profit,"
            "requested_take_profit:payload->requested_take_profit,"
            "planned_tp2:payload->planned_tp2"
        )
        try:
            response = (
                self.client.table("broker_order_events")
                .select(select_expr)
                .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
                .in_("code", list(codes))
                .order("observed_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"compact XAU geometry-event read failed: {exc}"
            ) from exc

        rows: list[dict[str, Any]] = []
        payload_keys = (
            "symbol",
            "strategy_id",
            "direction",
            "executed_price",
            "requested_entry",
            "planned_entry",
            "attached_stop_loss",
            "requested_stop_loss",
            "planned_sl",
            "attached_take_profit",
            "requested_take_profit",
            "planned_tp2",
        )
        for raw_row in self._rows(response):
            raw = dict(raw_row)
            raw["payload"] = {
                key: raw.pop(key)
                for key in payload_keys
                if raw.get(key) is not None
            }
            rows.append(raw)
        return tuple(rows)

    def latest_xau_prepared_plan_lifecycle(
        self, *, limit: int = 100
    ) -> tuple[dict[str, Any], ...]:
        try:
            response = (
                self.client.table("xau_prepared_plan_lifecycle")
                .select(
                    "plan_key,signal_id,zone_id,map_at,created_at,updated_at,"
                    "direction,grade,zone_low,zone_high,entry_price,stop_price,"
                    "tp1_price,tp2_price,lifecycle_state,cancel_reason,cancelled_at,"
                    "first_touch_at,confirmed_at,execution_ready_at,order_accepted_at,"
                    "protection_verified_at,outcome_at,outcome_class,tp1_hit,tp2_hit,"
                    "stop_hit,mfe_r,mae_r,post_cancel_terminal_hit,metadata"
                )
                .order("created_at", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"XAU prepared-plan lifecycle read failed: {exc}"
            ) from exc
        return tuple(self._rows(response))

    def latest_xau_geometry_events(
        self, *, limit: int = 30
    ) -> tuple[dict[str, Any], ...]:
        """Return only broker-authorized XAU geometry records used by admission/V240."""
        codes = (
            "XAU_RIZAN_DEPTH_EXECUTION_V1",
            "XAU_RIZAN_PATH_EXECUTION_V1",
            "XAU_AFIC_PATH_EXECUTION_V1",
            "XAU_M15_EMA_SMC_RECLAIM_V1",
            "XAU_V24_CHAMPION_DEMO_V1",
        )
        try:
            response = (
                self.client.table("broker_order_events")
                .select(
                    "observed_at,event_type,code,accepted,message,signal_key,"
                    "broker_order_id,payload"
                )
                .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
                .in_("code", list(codes))
                .order("observed_at", desc=True)
                .limit(int(limit))
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"XAU geometry-event read failed: {exc}"
            ) from exc
        return tuple(self._rows(response))

    def latest_xau_execution_events(
        self, *, limit: int = 20
    ) -> tuple[dict[str, Any], ...]:
        """Return compact broker/execution timeline rows.

        Geometry is read from the dedicated geometry feed instead of this
        method. Only display-relevant JSON keys are projected server-side so the
        dashboard does not retransmit large shadow/context payloads.
        """
        limit = max(1, min(int(limit), 40))
        execution_events = (
            "ORDER_ACCEPTED",
            "POSITION_PROTECTION_VERIFIED",
            "POSITION_PROTECTION_FAILED",
            "EXECUTION_BLOCKED",
            "ORDER_OUTCOME_UNCERTAIN",
            "REVALIDATION_PASS",
            "REVALIDATION_BLOCK",
        )
        select_expr = (
            "observed_at,event_type,code,accepted,message,signal_key,broker_order_id,"
            "symbol:payload->>symbol,"
            "strategy_id:payload->>strategy_id,"
            "executed_price:payload->>executed_price,"
            "requested_entry:payload->>requested_entry,"
            "planned_entry:payload->>planned_entry,"
            "attached_stop_loss:payload->>attached_stop_loss,"
            "requested_stop_loss:payload->>requested_stop_loss,"
            "planned_sl:payload->>planned_sl,"
            "attached_take_profit:payload->>attached_take_profit,"
            "requested_take_profit:payload->>requested_take_profit,"
            "planned_tp2:payload->>planned_tp2"
        )
        try:
            response = (
                self.client.table("broker_order_events")
                .select(select_expr)
                .in_("event_type", list(execution_events))
                .order("observed_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            raise DashboardReadError(
                f"XAU compact execution-event read failed: {exc}"
            ) from exc

        payload_fields = (
            "symbol",
            "strategy_id",
            "executed_price",
            "requested_entry",
            "planned_entry",
            "attached_stop_loss",
            "requested_stop_loss",
            "planned_sl",
            "attached_take_profit",
            "requested_take_profit",
            "planned_tp2",
        )
        rows: list[dict[str, Any]] = []
        for raw in self._rows(response):
            row = dict(raw)
            symbol = str(row.get("symbol") or "").upper().strip()
            code = str(row.get("code") or "")
            if symbol not in {"", "XAUUSD"} and "XAU" not in code.upper():
                continue
            row["payload"] = {
                key: row.pop(key)
                for key in payload_fields
                if row.get(key) not in (None, "")
            }
            rows.append(row)
        return tuple(rows)

    def snapshot(self) -> DashboardSnapshot:
        run = self.latest_run()
        rankings = self.rankings_for_run(None if run is None else run.get("id"))
        broker_account = self.latest_broker_account()
        broker_positions = self.broker_positions_for_account(broker_account)
        afic_forecast_states = self.latest_afic_forecast_states()
        afic_prepared_plans = self.latest_afic_prepared_plans()
        afic_execution_geometry = self.latest_afic_execution_geometry()
        xau_execution_events = self.latest_xau_execution_events()
        xau_outcomes = self.latest_xau_outcomes()
        xau_prepared_plan_lifecycle = self.latest_xau_prepared_plan_lifecycle()
        return DashboardSnapshot(
            latest_run=run,
            rankings=rankings,
            signals=self.latest_signals(),
            xau_signals=self.latest_signals_for_symbol("XAUUSD"),
            heartbeats=self.heartbeats(),
            macro=self.latest_macro(),
            performance=self.latest_performance(),
            broker_account=broker_account,
            broker_positions=broker_positions,
            afic_forecast_states=afic_forecast_states,
            afic_prepared_plans=afic_prepared_plans,
            afic_execution_geometry=afic_execution_geometry,
            xau_execution_events=xau_execution_events,
            xau_outcomes=xau_outcomes,
            xau_prepared_plan_lifecycle=xau_prepared_plan_lifecycle,
        )
