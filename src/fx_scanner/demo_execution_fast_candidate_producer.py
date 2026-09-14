from __future__ import annotations

from .demo_euraud_gbpaud_candidate_producer import run as run_cross_candidates
from .demo_euraud_gbpaud_chandelier import run as run_cross_chandelier
from .demo_five_core_candidate_producer import run as run_five_core


def run() -> int:
    result = run_five_core()
    if result != 0:
        return result
    result = run_cross_candidates()
    if result != 0:
        return result
    # Manage existing promoted cross positions before the shared fresh-signal
    # handoff runs. A newly opened position receives its first D1 Chandelier
    # update on the next pipeline pass after a completed post-entry D1 bar.
    return run_cross_chandelier()


if __name__ == "__main__":
    raise SystemExit(run())
