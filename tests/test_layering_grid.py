import numpy as np
import pytest

pytest.importorskip("numba")

from fx_scanner.layering_grid import (
    BASELINE_ID,
    N_CONFIGS,
    PATTERNS,
    SIZERS,
    configuration,
    replay_batch,
)


def fixture_inputs():
    geom = np.array([[2000.0, 2.0, 0.05, 1.0, 1.0, -2.05, 20.0, 0.30]])
    info = np.array([[100, 103, 20250101, 2025]], np.int64)
    lengths = np.array([3], np.int64)
    returns = np.array(
        [[[-0.4, 0.1, -0.2, 1.0], [-1.4, -0.4, -0.6, 0.0], [-2.05, -2.05, -2.05, 0.0]]]
    )
    idx = np.full((1001, 1, 6), -1, np.int16)
    slots = np.zeros((1001, 1, 6, 6))
    sizes = np.ones((1001, 2), np.int64)
    idx[:, 0, 0] = 0
    slots[:, 0, 0] = [0, 20, 2.05, -0.30, 0, 0.30]
    for p, (depth, n, confirm, ttl) in enumerate(PATTERNS):
        sizes[p] = n, int(confirm)
        idx[p, 0, 1] = 1
        slots[p, 0, 1] = [1, 19.99, 1.05, -1, 0, 0.30]
    policies = np.asarray(SIZERS, float)
    return geom, info, lengths, returns, idx, slots, sizes, policies


def test_grid_has_exactly_100000_unique_parameter_sets():
    assert N_CONFIGS == 100000
    keys = [tuple(configuration(i).values()) for i in range(N_CONFIGS)]
    assert len(set(keys)) == N_CONFIGS


@pytest.mark.parametrize("identifier", [0, 82, 90, 57390, 99999, BASELINE_ID])
def test_exact_m1_marking_preserves_sizing_and_closed_pnl(identifier):
    inputs = fixture_inputs()
    marked, _ = replay_batch(
        np.array([identifier]), *inputs, True, 0, 200, 1000.0, True
    )
    closed, _ = replay_batch(
        np.array([identifier]), *inputs, True, 0, 200, 1000.0, False
    )
    np.testing.assert_allclose(
        marked[0, [0, 1, 3, 4, 5, 6, 7, 8, 9]], closed[0, [0, 1, 3, 4, 5, 6, 7, 8, 9]]
    )
    assert marked[0, 2] >= marked[0, 3]
    assert marked[0, 8] <= 12.5 + 1e-8
    assert marked[0, 9] <= 50 + 1e-8


def test_native_baseline_expected_cash_and_risk():
    out, _ = replay_batch(
        np.array([BASELINE_ID]), *fixture_inputs(), True, 0, 200, 1000.0
    )
    assert out[0, 0] == pytest.approx(979.5)
    assert out[0, 6] == 10
    assert out[0, 8] == pytest.approx(2.05)
    assert out[0, 7] == 0


def test_suffix_mutation_cannot_change_prefix_metrics():
    inputs = list(fixture_inputs())
    # Duplicate opportunity at a future year, retaining independent array axes.
    inputs[0] = np.repeat(inputs[0], 2, axis=0)
    inputs[1] = np.array(
        [[100, 103, 20200101, 2020], [300, 303, 20250101, 2025]], np.int64
    )
    inputs[2] = np.repeat(inputs[2], 2)
    inputs[3] = np.repeat(inputs[3], 2, axis=0)
    inputs[4] = np.repeat(inputs[4], 2, axis=1)
    inputs[5] = np.repeat(inputs[5], 2, axis=1)
    first, _ = replay_batch(np.array([57390]), *inputs, True, 0, 200, 1000.0)
    inputs[0][1, 5] *= 100
    inputs[3][1] *= 100
    again, _ = replay_batch(np.array([57390]), *inputs, True, 0, 200, 1000.0)
    np.testing.assert_allclose(first, again)


@pytest.mark.parametrize("gap", [True, False])
def test_cache_never_fills_pending_limit_on_gap_or_expiry_liquidation(tmp_path, gap):
    import hashlib
    import json
    import pickle
    import runpy
    from pathlib import Path

    import pandas as pd

    builder = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/research_layering_100k.py")
    )["build"]
    at = pd.Timestamp("2025-01-02 08:00", tz="UTC")
    ix = (
        pd.DatetimeIndex([at, at + pd.Timedelta(minutes=10)])
        if gap
        else pd.date_range(at, periods=241, freq="min")
    )
    trace = pd.DataFrame(
        {
            "open": 1.1,
            "high": 1.1001,
            "low": 1.0999,
            "close": 1.1,
            "buy_confirm": False,
            "sell_confirm": False,
            "confirm_at": pd.NaT,
        },
        index=ix,
    )
    trace.loc[ix[-1], ["open", "high", "low", "close"]] = [
        1.0995,
        1.0996,
        1.0994,
        1.0995,
    ]
    opportunity = {"at": at, "side": 1, "distance": 0.001, "fast": 0.0, "slow": 0.0}
    cache = tmp_path / "cache"
    cache.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    fingerprint = hashlib.sha256(json.dumps([], sort_keys=True).encode()).hexdigest()
    (cache / f"EURUSD_{fingerprint}_frozen.pkl").write_bytes(
        pickle.dumps(([opportunity], [trace]))
    )
    # First pattern TTL=15 suffices for gap; last TTL=240 for frozen expiry.
    pattern = 0 if gap else 9
    inputs, _ = builder(data, "EURUSD", cache, pattern_ids=[pattern])
    assert inputs[4][pattern, 0, 0] == 0
    assert inputs[4][pattern, 0, 1] == -1
