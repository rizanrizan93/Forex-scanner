from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    active_guards: tuple[str, ...]


def evaluate_hard_guards(**flags: bool) -> GuardResult:
    """Flags use `True` when the block condition is active."""
    active = tuple(sorted(name for name, blocked in flags.items() if blocked))
    return GuardResult(allowed=not active, active_guards=active)
