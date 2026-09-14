from __future__ import annotations

from .demo_five_core_candidate_producer import run as run_five_core


def run() -> int:
    # Keep one cTrader session lifecycle per Python process. EURAUD/GBPAUD are
    # intentionally launched by the auto-pipeline in their own process because
    # creating a second cTrader Open API session after closing the Five-Core
    # session can intermittently time out inside the same Twisted reactor.
    return run_five_core()


if __name__ == "__main__":
    raise SystemExit(run())
