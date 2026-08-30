from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class CTraderTokens:
    access_token: str
    refresh_token: str

    def __post_init__(self) -> None:
        if not self.access_token or not self.refresh_token:
            raise ConfigurationError("cTrader access and refresh tokens are required")


class CTraderTokenStateStore:
    """Atomic local secret state for cTrader token rotation.

    The file belongs on the controlled VPS, is git-ignored, and is chmod 0600
    where the host supports POSIX permissions.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not str(self.path):
            raise ConfigurationError("cTrader token-state path is required")

    def load(self, *, fallback_access: str, fallback_refresh: str) -> CTraderTokens:
        if not self.path.exists():
            return CTraderTokens(fallback_access, fallback_refresh)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return CTraderTokens(
                str(payload["access_token"]),
                str(payload["refresh_token"]),
            )
        except Exception as exc:
            raise ConfigurationError("cTrader token-state file is unreadable") from exc

    def save(self, access_token: str, refresh_token: str) -> None:
        tokens = CTraderTokens(access_token, refresh_token)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(
                {
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                }
            ),
            encoding="utf-8",
        )
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
