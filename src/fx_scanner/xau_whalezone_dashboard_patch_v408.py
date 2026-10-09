from __future__ import annotations

"""Install the V408 tiered-zone map ahead of the canonical XAU dashboard.

The project already uses a small presentation patch during Streamlit bootstrap.
V408 follows the same pattern so the established V393/C4/legacy dashboard code
stays untouched while the new visual map is promoted to the first XAU screen.
"""

from functools import wraps
from typing import Any

from .xau_whalezone_visual_v408 import render_whalezone_visual_v408

_INSTALLED = False


def install_whalezone_dashboard_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import xau_dual_engine_dashboard_v344 as dashboard

    original = dashboard.render_xau_dual_engine_dashboard
    if bool(getattr(original, "__rizan_whalezone_v408__", False)):
        _INSTALLED = True
        return

    @wraps(original)
    def wrapped(
        *,
        sd_heartbeat: dict[str, Any] | None,
        friend_heartbeat: dict[str, Any] | None,
        event_heartbeat: dict[str, Any] | None = None,
        macro_heartbeat: dict[str, Any] | None = None,
    ) -> None:
        render_whalezone_visual_v408(sd_heartbeat)
        original(
            sd_heartbeat=sd_heartbeat,
            friend_heartbeat=friend_heartbeat,
            event_heartbeat=event_heartbeat,
            macro_heartbeat=macro_heartbeat,
        )

    setattr(wrapped, "__rizan_whalezone_v408__", True)
    dashboard.render_xau_dual_engine_dashboard = wrapped
    _INSTALLED = True


__all__ = ["install_whalezone_dashboard_patch"]
