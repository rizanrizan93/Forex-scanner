from __future__ import annotations

import pytest

from fx_scanner.demo_ctrader_token_maintainer import (
    PROACTIVE_ROTATION_AGE,
    _rotation_reason,
)
from fx_scanner.exceptions import CollectorUnavailable


def test_bootstrap_requires_rotation_even_with_fresh_age():
    assert _rotation_reason(
        had_durable_state=False,
        durable_age_seconds=0.0,
    ) == "BOOTSTRAP_DURABLE_STATE"


def test_proactive_rotation_starts_at_twenty_days():
    threshold = PROACTIVE_ROTATION_AGE.total_seconds()
    assert _rotation_reason(
        had_durable_state=True,
        durable_age_seconds=threshold - 1,
    ) == "NONE"
    assert _rotation_reason(
        had_durable_state=True,
        durable_age_seconds=threshold,
    ) == "PROACTIVE_20D_ROTATION"


def test_invalid_access_token_allows_explicit_rotation():
    error = CollectorUnavailable("cTrader API error CH_ACCESS_TOKEN_INVALID: Invalid access token")
    assert _rotation_reason(
        had_durable_state=True,
        durable_age_seconds=60.0,
        validation_error=error,
    ) == "ACCESS_TOKEN_INVALID"


def test_cant_route_request_never_triggers_token_rotation():
    error = CollectorUnavailable("cTrader API error CANT_ROUTE_REQUEST: Cannot route request")
    with pytest.raises(CollectorUnavailable, match="CANT_ROUTE_REQUEST"):
        _rotation_reason(
            had_durable_state=True,
            durable_age_seconds=60.0,
            validation_error=error,
        )


def test_timeout_never_triggers_token_rotation():
    error = CollectorUnavailable("cTrader request timeout after 10.0s")
    with pytest.raises(CollectorUnavailable, match="timeout"):
        _rotation_reason(
            had_durable_state=True,
            durable_age_seconds=60.0,
            validation_error=error,
        )
