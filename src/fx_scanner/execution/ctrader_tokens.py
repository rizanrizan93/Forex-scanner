from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..exceptions import ConfigurationError

UTC = timezone.utc
_DURABLE_WORKER = "ctrader_token_state_v1"
_DURABLE_PROBE_WORKER = "ctrader_token_state_vault_probe"
_ASSOCIATED_DATA = b"forex-scanner/ctrader-token-state/v1"


@dataclass(frozen=True, slots=True)
class CTraderTokens:
    access_token: str
    refresh_token: str

    def __post_init__(self) -> None:
        if not self.access_token or not self.refresh_token:
            raise ConfigurationError("cTrader access and refresh tokens are required")


class CTraderTokenStateStore:
    """Atomic local token state with optional encrypted Supabase persistence.

    Local state remains useful on a controlled VPS. GitHub-hosted runners are
    ephemeral, so when CTRADER_TOKEN_STATE_DURABLE=1 the canonical state is an
    AES-GCM encrypted blob stored in the backend-only runtime_heartbeats table.
    The encryption key is derived from CTRADER_CLIENT_SECRET; Supabase never
    receives access or refresh tokens in plaintext.
    """

    def __init__(self, path: str | Path):
        raw = str(path).strip()
        if not raw:
            raise ConfigurationError("cTrader token-state path is required")
        self.path = Path(raw)
        self._client: Any | None = None

    @staticmethod
    def _durable_enabled() -> bool:
        return os.getenv("CTRADER_TOKEN_STATE_DURABLE", "0").strip() == "1"

    @staticmethod
    def _client_secret() -> str:
        value = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
        if not value:
            raise ConfigurationError("CTRADER_CLIENT_SECRET is required for durable token encryption")
        return value

    @staticmethod
    def _derive_key(client_secret: str) -> bytes:
        return hashlib.sha256(_ASSOCIATED_DATA + b"\x00" + client_secret.encode("utf-8")).digest()

    @classmethod
    def _encrypt_tokens(cls, tokens: CTraderTokens) -> dict[str, Any]:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ModuleNotFoundError as exc:
            raise ConfigurationError("cryptography is required for durable cTrader token state") from exc
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = AESGCM(cls._derive_key(cls._client_secret())).encrypt(
            nonce,
            plaintext,
            _ASSOCIATED_DATA,
        )
        return {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "nonce_b64": base64.b64encode(nonce).decode("ascii"),
            "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
            "saved_at": datetime.now(tz=UTC).isoformat(),
        }

    @classmethod
    def _decrypt_tokens(cls, details: dict[str, Any]) -> CTraderTokens:
        if int(details.get("version", 0) or 0) != 1:
            raise ConfigurationError("unsupported durable cTrader token-state version")
        if str(details.get("algorithm", "")) != "AES-256-GCM":
            raise ConfigurationError("unsupported durable cTrader token-state algorithm")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ModuleNotFoundError as exc:
            raise ConfigurationError("cryptography is required for durable cTrader token state") from exc
        try:
            nonce = base64.b64decode(str(details["nonce_b64"]), validate=True)
            ciphertext = base64.b64decode(str(details["ciphertext_b64"]), validate=True)
            plaintext = AESGCM(cls._derive_key(cls._client_secret())).decrypt(
                nonce,
                ciphertext,
                _ASSOCIATED_DATA,
            )
            payload = json.loads(plaintext.decode("utf-8"))
            return CTraderTokens(
                str(payload["access_token"]),
                str(payload["refresh_token"]),
            )
        except Exception as exc:
            raise ConfigurationError("durable cTrader token state cannot be decrypted") from exc

    def _supabase_client(self):
        if self._client is not None:
            return self._client
        url = os.getenv("SUPABASE_URL", "").strip()
        secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip() or os.getenv(
            "SUPABASE_SERVICE_ROLE_KEY", ""
        ).strip()
        if not url or not secret_key:
            raise ConfigurationError("SUPABASE_URL and backend secret are required for durable token state")
        try:
            from supabase import create_client
        except ModuleNotFoundError as exc:
            raise ConfigurationError("supabase is required for durable cTrader token state") from exc
        self._client = create_client(url, secret_key)
        return self._client

    def _read_durable_row(self) -> dict[str, Any] | None:
        try:
            response = (
                self._supabase_client()
                .table("runtime_heartbeats")
                .select("worker_name,observed_at,details")
                .eq("worker_name", _DURABLE_WORKER)
                .limit(2)
                .execute()
            )
            rows = list(response.data or [])
        except Exception as exc:
            raise ConfigurationError("durable cTrader token-state read failed") from exc
        if len(rows) > 1:
            raise ConfigurationError("durable cTrader token state is ambiguous")
        return None if not rows else dict(rows[0])

    def has_durable_state(self) -> bool:
        if not self._durable_enabled():
            return False
        row = self._read_durable_row()
        return bool(row and isinstance(row.get("details"), dict) and row["details"].get("ciphertext_b64"))

    def durable_state_age_seconds(self) -> float | None:
        if not self._durable_enabled():
            return None
        row = self._read_durable_row()
        if not row:
            return None
        details = dict(row.get("details") or {})
        raw = str(details.get("saved_at") or row.get("observed_at") or "").replace("Z", "+00:00")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return max(0.0, (datetime.now(tz=UTC) - parsed.astimezone(UTC)).total_seconds())

    def probe_durable_backend(self) -> None:
        """Prove durable writes work before a refresh invalidates old tokens."""
        if not self._durable_enabled():
            raise ConfigurationError("durable cTrader token state is not enabled")
        payload = {
            "worker_name": _DURABLE_PROBE_WORKER,
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "healthy": True,
            "lag_seconds": 0.0,
            "details": {"purpose": "CTRADER_TOKEN_VAULT_WRITE_PROBE", "contains_secret": False},
        }
        try:
            self._supabase_client().table("runtime_heartbeats").upsert(
                payload,
                on_conflict="worker_name",
            ).execute()
        except Exception as exc:
            raise ConfigurationError("durable cTrader token-state write probe failed") from exc

    def _load_local(self) -> CTraderTokens | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return CTraderTokens(
                str(payload["access_token"]),
                str(payload["refresh_token"]),
            )
        except Exception as exc:
            raise ConfigurationError("cTrader token-state file is unreadable") from exc

    def load(self, *, fallback_access: str, fallback_refresh: str) -> CTraderTokens:
        if self._durable_enabled():
            row = self._read_durable_row()
            if row is not None:
                details = row.get("details")
                if not isinstance(details, dict) or not details.get("ciphertext_b64"):
                    raise ConfigurationError("durable cTrader token-state row is malformed")
                return self._decrypt_tokens(dict(details))
        local = self._load_local()
        if local is not None:
            return local
        return CTraderTokens(fallback_access, fallback_refresh)

    def _save_local(self, tokens: CTraderTokens) -> None:
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

    def _save_durable(self, tokens: CTraderTokens) -> None:
        details = self._encrypt_tokens(tokens)
        payload = {
            "worker_name": _DURABLE_WORKER,
            "observed_at": details["saved_at"],
            "healthy": True,
            "lag_seconds": 0.0,
            "details": details,
        }
        last_exc: Exception | None = None
        for delay in (0.0, 0.5, 1.0):
            if delay:
                time.sleep(delay)
            try:
                self._supabase_client().table("runtime_heartbeats").upsert(
                    payload,
                    on_conflict="worker_name",
                ).execute()
                return
            except Exception as exc:
                last_exc = exc
        raise ConfigurationError("durable cTrader token-state persistence failed") from last_exc

    def save(self, access_token: str, refresh_token: str) -> None:
        tokens = CTraderTokens(access_token, refresh_token)
        self._save_local(tokens)
        if self._durable_enabled():
            self._save_durable(tokens)
