from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


class DuplicateOrderGuard:
    """Thread-safe idempotency guard keyed by immutable signal_id.

    Executed IDs are persistent. In-flight claims are process-local by design so a
    process crash cannot leave a permanent false duplicate lock on disk.
    """

    def __init__(self, state_path: str | Path | None = None):
        self.path = Path(state_path) if state_path else None
        self._lock = Lock()
        self._seen: set[str] = set()
        self._inflight: set[str] = set()
        if self.path and self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                self._seen = set(map(str, payload.get("executed_signal_ids", [])))
            except Exception:
                raise RuntimeError(f"duplicate-guard state is unreadable: {self.path}")

    def is_duplicate(self, signal_id: str) -> bool:
        with self._lock:
            return signal_id in self._seen or signal_id in self._inflight

    def try_claim(self, signal_id: str) -> bool:
        with self._lock:
            if signal_id in self._seen or signal_id in self._inflight:
                return False
            self._inflight.add(signal_id)
            return True

    def release_claim(self, signal_id: str) -> None:
        with self._lock:
            self._inflight.discard(signal_id)

    def mark_executed(self, signal_id: str) -> None:
        with self._lock:
            self._inflight.discard(signal_id)
            self._seen.add(signal_id)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.path.with_suffix(self.path.suffix + ".tmp")
                temp.write_text(
                    json.dumps({"executed_signal_ids": sorted(self._seen)}, indent=2),
                    encoding="utf-8",
                )
                temp.replace(self.path)
