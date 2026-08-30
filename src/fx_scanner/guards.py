from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    active_guards: tuple[str, ...]


def evaluate_hard_guards(
    *,
    required_names: tuple[str, ...] | list[str] | None = None,
    **flags: bool,
) -> GuardResult:
    """Flags use True when the block condition is active.

    When required_names is supplied, any missing guard input itself becomes a
    blocking condition. This prevents a missing guard calculation or typo from
    silently becoming "clear".
    """
    active = [name for name, blocked in flags.items() if blocked]
    if required_names is not None:
        required = {str(name) for name in required_names}
        missing = sorted(required - set(flags))
        active.extend(f"GUARD_INPUT_MISSING:{name}" for name in missing)
    active_tuple = tuple(sorted(set(active)))
    return GuardResult(allowed=not active_tuple, active_guards=active_tuple)
