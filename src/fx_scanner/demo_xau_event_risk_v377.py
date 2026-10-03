from __future__ import annotations

from typing import Any

from . import demo_xau_event_risk_v192 as base
from .xau_event_confidence_v377 import decorate_event_dict

CONTRACT = "XAU_USD_EVENT_RISK_LAYER_V377_CONFIDENCE_COVERAGE"
WORKER_NAME = base.WORKER_NAME

_INSTALLED = False
_ORIGINAL_AS_DICT = base.RiskEvent.as_dict


def install_v377() -> None:
    """Install additive V377 serialization on top of the proven V192 worker."""

    global _INSTALLED
    if _INSTALLED:
        return

    def _as_dict_v377(self: base.RiskEvent) -> dict[str, Any]:
        return decorate_event_dict(_ORIGINAL_AS_DICT(self))

    base.RiskEvent.as_dict = _as_dict_v377
    base.CONTRACT = CONTRACT
    _INSTALLED = True


def run() -> int:
    install_v377()
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
