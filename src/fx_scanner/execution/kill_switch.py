from __future__ import annotations

import os
from pathlib import Path


class KillSwitch:
    """Two-layer kill switch: environment + optional local STOP file."""

    def __init__(self, env_name: str = "FX_KILL_SWITCH", safe_value: str = "0", stop_file: str | Path | None = None):
        self.env_name = env_name
        self.safe_value = safe_value
        self.stop_file = Path(stop_file) if stop_file else None

    def engaged(self) -> bool:
        env = os.getenv(self.env_name, self.safe_value)
        if env != self.safe_value:
            return True
        return bool(self.stop_file and self.stop_file.exists())
