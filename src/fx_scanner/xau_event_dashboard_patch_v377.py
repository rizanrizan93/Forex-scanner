from __future__ import annotations

from typing import Any

from .xau_event_confidence_v377 import prepare_dashboard_heartbeat


def install_event_macro_dashboard_patch() -> None:
    """Patch the V344 renderer to make event data quality explicit.

    The patch is display-only.  Storage/runtime payloads keep numeric fields as
    floats/None and execution semantics remain unchanged.
    """

    from . import xau_dual_engine_dashboard_v344 as dashboard

    current = dashboard.render_xau_dual_engine_dashboard
    if bool(getattr(current, "_v377_event_confidence_patch", False)):
        return

    def _render_v377(
        *,
        sd_heartbeat: dict[str, Any] | None,
        friend_heartbeat: dict[str, Any] | None,
        event_heartbeat: dict[str, Any] | None = None,
    ) -> None:
        current(
            sd_heartbeat=sd_heartbeat,
            friend_heartbeat=friend_heartbeat,
            event_heartbeat=prepare_dashboard_heartbeat(event_heartbeat),
        )

    _render_v377._v377_event_confidence_patch = True  # type: ignore[attr-defined]
    dashboard.render_xau_dual_engine_dashboard = _render_v377
