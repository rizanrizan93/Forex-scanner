from copy import deepcopy

import pandas as pd

from fx_scanner.cross_asset_replay import replay_account


def test_shadow_filter_preserves_frozen_virtual_feedback_and_cost_monotonicity():
    at = pd.Timestamp("2025-01-02T08:00Z")
    trades = [
        {
            "at": at,
            "exit_at": at + pd.Timedelta(minutes=30),
            "side": 1,
            "entry": 1.1,
            "distance": 0.001,
            "r": 1.0,
            "fast": 0.0,
            "slow": 0.0,
            "mae_r": 0.2,
            "mfe_r": 1.0,
            "holding_minutes": 30,
            "path": [(at, -0.2, 1.0)],
        }
    ]
    before = deepcopy(trades)
    args = {"start": at, "end": at + pd.Timedelta(days=31)}
    base = replay_account(trades, **args)
    stress = replay_account(trades, **args, extra_cost=0.0001)
    skipped = replay_account(trades, **args, accept=lambda t: False)
    assert base["ending_balance_usd"] > stress["ending_balance_usd"] > 100
    assert skipped["trades"] == 0 and skipped["ending_balance_usd"] == 100
    assert trades == before
