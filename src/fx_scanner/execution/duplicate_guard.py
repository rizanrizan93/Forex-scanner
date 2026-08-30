from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


class DuplicateOrderGuard:
    """Thread-safe idempotency guard keyed by immutable signal_id.

    Executed and indeterminate IDs are persisted. An indeterminate ID means an
    order submission crossed the broker side-effect boundary but no definitive
    response was received. Such IDs remain blocked until explicit reconciliation.
    """

    def __init__(self, state_path: str | Path | None = None):
        self.path = Path(state_path) if state_path else None
        self._lock = Lock()
        self._seen: set[str] = set()
        self._uncertain: set[str] = set()
        self._inflight: set[str] = set()
        if self.path and self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                self._seen = set(map(str, payload.get("executed_signal_ids", [])))
                self._uncertain = set(map(str, payload.get("uncertain_signal_ids", [])))
            except Exception as exc:
                raise RuntimeError(f"duplicate-guard state is unreadable: {self.path}") from exc

    def _persist_locked(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(
                {
                    "executed_signal_ids": sorted(self._seen),
                    "uncertain_signal_ids": sorted(self._uncertain),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def is_duplicate(self, signal_id: str) -> bool:
        with self._lock:
            return (
                signal_id in self._seen
                or signal_id in self._uncertain
                or signal_id in self._inflight
            )

    def is_uncertain(self, signal_id: str) -> bool:
        with self._lock:
            return signal_id in self._uncertain

    def try_claim(self, signal_id: str) -> bool:
        with self._lock:
            if (
                signal_id in self._seen
                or signal_id in self._uncertain
                or signal_id in self._inflight
            ):
                return False
            self._inflight.add(signal_id)
            return True

    def release_claim(self, signal_id: str) -> None:
        with self._lock:
            self._inflight.discard(signal_id)

    def mark_uncertain(self, signal_id: str) -> None:
        with self._lock:
            self._inflight.discard(signal_id)
            self._uncertain.add(signal_id)
            self._persist_locked()

    def resolve_uncertain(self, signal_id: str, *, executed: bool) -> None:
        """Resolve only after broker order/position reconciliation."""
        with self._lock:
            if signal_id not in self._uncertain:
                raise RuntimeError(f"signal is not uncertain: {signal_id}")
            self._uncertain.discard(signal_id)
            if executed:
                self._seen.add(signal_id)
            self._persist_locked()

    def mark_executed(self, signal_id: str) -> None:
        with self._lock:
            self._inflight.discard(signal_id)
            self._uncertain.discard(signal_id)
            self._seen.add(signal_id)
            self._persist_locked()
