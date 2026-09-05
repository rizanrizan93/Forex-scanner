from __future__ import annotations

import os
from datetime import timedelta

from .exceptions import CollectorUnavailable, ConfigurationError
from .execution.ctrader_session import CTraderOpenApiSession
from .execution.ctrader_tokens import CTraderTokenStateStore
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

PROACTIVE_ROTATION_AGE = timedelta(days=20)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _token_invalid(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}:{exc}".upper()
    return "CH_ACCESS_TOKEN_INVALID" in text or "ACCESS_TOKEN_EXPIRED" in text


def _rotation_reason(
    *,
    had_durable_state: bool,
    durable_age_seconds: float | None,
    validation_error: BaseException | None = None,
) -> str:
    """Return an explicit safe rotation reason or propagate non-token failures.

    Routing/timeouts are deliberately not interpreted as token expiry. Refresh
    tokens rotate on use, so refreshing on ambiguous transport failures could
    strand every worker on an already-invalidated refresh credential.
    """
    if not had_durable_state:
        return "BOOTSTRAP_DURABLE_STATE"
    if (
        durable_age_seconds is not None
        and durable_age_seconds >= PROACTIVE_ROTATION_AGE.total_seconds()
    ):
        return "PROACTIVE_20D_ROTATION"
    if validation_error is None:
        return "NONE"
    if _token_invalid(validation_error):
        return "ACCESS_TOKEN_INVALID"
    raise validation_error


def run() -> int:
    policy = load_execution_policy(None)
    cfg = policy.ctrader
    if str(cfg.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_TOKEN_MAINTAINER_DEMO_ONLY")
    if os.getenv("CTRADER_TOKEN_STATE_DURABLE", "0").strip() != "1":
        raise SystemExit("CTRADER_TOKEN_MAINTAINER_DURABLE_STATE_REQUIRED")

    token_store = CTraderTokenStateStore(_required_env(cfg["token_state_path_env"]))
    # A refresh invalidates the old refresh token. Prove the durable backend is
    # writable before crossing that irreversible boundary.
    token_store.probe_durable_backend()
    had_durable_state = token_store.has_durable_state()
    durable_age = token_store.durable_state_age_seconds()
    tokens = token_store.load(
        fallback_access=_required_env(cfg["access_token_env"]),
        fallback_refresh=_required_env(cfg["refresh_token_env"]),
    )

    pinned_account_id = _optional_env(cfg["account_id_env"])
    session = CTraderOpenApiSession(
        client_id=_required_env(cfg["client_id_env"]),
        client_secret=_required_env(cfg["client_secret_env"]),
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_update_callback=token_store.save,
        account_id=None,
        environment="demo",
        request_timeout_seconds=float(cfg.get("request_timeout_seconds", 10)),
        # This process is the only token writer. We intentionally perform
        # refresh explicitly so transient routing errors never rotate tokens.
        allow_token_refresh=False,
    )

    try:
        session.connect_application()
        validation_error: BaseException | None = None
        if had_durable_state and not (
            durable_age is not None
            and durable_age >= PROACTIVE_ROTATION_AGE.total_seconds()
        ):
            try:
                session.granted_accounts()
            except CollectorUnavailable as exc:
                validation_error = exc

        rotation_reason = _rotation_reason(
            had_durable_state=had_durable_state,
            durable_age_seconds=durable_age,
            validation_error=validation_error,
        )

        if rotation_reason != "NONE":
            # _refresh_tokens persists the newly rotated access+refresh pair via
            # token_update_callback before this process continues. There is no
            # blind refresh retry on an ambiguous transport outcome.
            session._refresh_tokens()

        account = session.resolve_granted_account(
            trader_login=int(_required_env(cfg["trader_login_env"])),
            require_demo=True,
            pinned_account_id=None if pinned_account_id is None else int(pinned_account_id),
        )
        if bool(policy.demo_safety.get("require_trade_scope", True)) and account.permission_scope != 1:
            raise ConfigurationError("cTrader token does not have SCOPE_TRADE")

        SupabaseOperationalStore.from_env().write_heartbeat(
            "ctrader_demo_token_maintainer",
            healthy=True,
            lag_seconds=0.0,
            details={
                "environment": "DEMO",
                "durable_state": True,
                "rotation_reason": rotation_reason,
                "trader_login_match": True,
                "account_is_live": bool(account.is_live),
                "permission_scope": int(account.permission_scope),
                "contains_secret": False,
            },
        )
        print(
            "CTRADER_DEMO_TOKEN_MAINTAINER_OK "
            f"rotation={rotation_reason} durable_state=1 account_demo={int(not account.is_live)} "
            f"trade_scope={int(account.permission_scope == 1)}"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())
