from types import SimpleNamespace

import pytest

from fx_scanner.exceptions import CollectorUnavailable
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession


def fake_session(accounts, *, environment="demo", permission_scope=2):
    session = CTraderOpenApiSession.__new__(CTraderOpenApiSession)
    session.environment = environment
    session.account_id = None
    session.granted_accounts = lambda: tuple(
        SimpleNamespace(
            ctid_trader_account_id=account["id"],
            trader_login=account["login"],
            is_live=account["is_live"],
            broker_title_short=account.get("broker", "FPMarkets"),
            permission_scope=permission_scope,
        )
        for account in accounts
    )
    return session


def test_demo_account_resolves_by_visible_trader_login():
    session = fake_session([
        {"id": 9001001, "login": 1121694, "is_live": False},
    ])
    account = session.resolve_granted_account(trader_login=1121694, require_demo=True)
    assert account.ctid_trader_account_id == 9001001
    assert session.account_id == 9001001


def test_live_account_is_rejected_even_when_login_matches():
    session = fake_session([
        {"id": 9002001, "login": 1121694, "is_live": True},
    ])
    with pytest.raises(CollectorUnavailable, match="demo-only guard"):
        session.resolve_granted_account(trader_login=1121694, require_demo=True)


def test_ambiguous_trader_login_fails_closed():
    session = fake_session([
        {"id": 9003001, "login": 1121694, "is_live": False},
        {"id": 9003002, "login": 1121694, "is_live": False},
    ])
    with pytest.raises(CollectorUnavailable, match="match must be unique"):
        session.resolve_granted_account(trader_login=1121694, require_demo=True)


def test_missing_trader_login_fails_closed():
    session = fake_session([
        {"id": 9004001, "login": 1121727, "is_live": False},
    ])
    with pytest.raises(CollectorUnavailable, match="matches=0"):
        session.resolve_granted_account(trader_login=1121694, require_demo=True)


def test_optional_account_id_pin_must_match_resolved_id():
    session = fake_session([
        {"id": 9005001, "login": 1121694, "is_live": False},
    ])
    with pytest.raises(CollectorUnavailable, match="pinned account id"):
        session.resolve_granted_account(
            trader_login=1121694,
            require_demo=True,
            pinned_account_id=9999999,
        )


def test_single_demo_grant_without_optional_trader_login_is_accepted():
    session = fake_session([
        {"id": 9006001, "login": 0, "is_live": False},
    ])
    account = session.resolve_granted_account(trader_login=1121694, require_demo=True)
    assert account.ctid_trader_account_id == 9006001
    assert session.account_id == 9006001


def test_single_explicit_nonmatching_login_still_fails_closed():
    session = fake_session([
        {"id": 9007001, "login": 1121727, "is_live": False},
    ])
    with pytest.raises(CollectorUnavailable, match="matches=0 grants=1"):
        session.resolve_granted_account(trader_login=1121694, require_demo=True)


def test_multiple_grants_without_optional_logins_fail_closed():
    session = fake_session([
        {"id": 9008001, "login": 0, "is_live": False},
        {"id": 9008002, "login": 0, "is_live": False},
    ])
    with pytest.raises(CollectorUnavailable, match="matches=0 grants=2"):
        session.resolve_granted_account(trader_login=1121694, require_demo=True)


def test_single_live_grant_without_optional_login_is_rejected():
    session = fake_session([
        {"id": 9009001, "login": 0, "is_live": True},
    ])
    with pytest.raises(CollectorUnavailable, match="demo-only guard"):
        session.resolve_granted_account(trader_login=1121694, require_demo=True)
