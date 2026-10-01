from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fx_scanner.demo_existing_protection_repair import (
    _safe_unprotected_position_summary,
)


def test_v341_safe_unprotected_position_summary_exposes_only_bounded_identity_fields() -> None:
    position = SimpleNamespace(
        position_id="41985040",
        symbol="XAUUSD",
        side="BUY",
        volume=0.01,
        open_price=4159.4,
        current_price=4161.37,
        stop_loss=None,
        take_profit=None,
        comment=None,
        opened_at=datetime(2026, 10, 1, 9, 8, 10, tzinfo=UTC),
    )
    row = _safe_unprotected_position_summary(position, scanner_key=None)
    assert row == {
        "position_id": "41985040",
        "symbol": "XAUUSD",
        "side": "BUY",
        "volume": 0.01,
        "open_price": 4159.4,
        "current_price": 4161.37,
        "opened_at": "2026-10-01T09:08:10+00:00",
        "has_stop_loss": False,
        "has_take_profit": False,
        "comment_present": False,
        "scanner_linkage": "UNVERIFIED",
    }
    assert "comment" not in row


def test_v341_verified_scanner_comment_is_classified_without_persisting_comment_text() -> None:
    position = SimpleNamespace(
        position_id="p1",
        symbol="XAUUSD",
        side="SELL",
        volume=0.01,
        open_price=4200.0,
        current_price=4190.0,
        stop_loss=4210.0,
        take_profit=None,
        comment="FXIS:secret-ish-value",
        opened_at=None,
    )
    row = _safe_unprotected_position_summary(position, scanner_key="known-signal")
    assert row["scanner_linkage"] == "VERIFIED_COMMENT_ID"
    assert row["comment_present"] is True
    assert row["has_stop_loss"] is True
    assert row["has_take_profit"] is False
    assert "comment" not in row
