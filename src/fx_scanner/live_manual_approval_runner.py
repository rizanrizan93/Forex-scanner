from __future__ import annotations

from . import live_manual_approval as approval
from .execution.ctrader_live_manual_gateway import LiveManualCTraderExecutionGateway


def main() -> None:
    # Keep the generic/demo gateway behavior unchanged. Only the explicit LIVE
    # manual-approval lane consumes normalized ProtoOA expected-margin values.
    approval.CTraderExecutionGateway = LiveManualCTraderExecutionGateway
    approval.main()


if __name__ == "__main__":
    main()
