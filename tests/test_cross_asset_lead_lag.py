import sqlite3
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from fx_scanner.cross_asset_lead_lag import (
    Calibration,
    completed_close,
    fdr_bh,
    independent_events,
    paired_returns,
    pressure_state,
    regimes,
    sessions,
    synchronize,
)
from fx_scanner.cross_asset_research import residuals, select_on_train
from fx_scanner.cross_asset_storage import CrossAssetWriter


def synthetic(minutes=5, n=4000):
    rng = np.random.default_rng(27)
    x = rng.normal(0, 0.001, n)
    y = np.r_[0.0, 0.0, x[:-2]] + rng.normal(0, 0.0001, n)
    index = pd.date_range("2023-01-01", periods=n, freq=f"{minutes}min", tz="UTC")
    return pd.DataFrame(
        {"A": 100 * np.exp(np.cumsum(x)), "B": 100 * np.exp(np.cumsum(y))}, index=index
    )


@pytest.mark.parametrize("minutes", [1, 5])
def test_identifies_known_lag_without_lookahead_selection(minutes):
    p = synthetic(minutes=minutes)
    cutoff = p.index[2500]
    chosen, _ = select_on_train(p, "A", "B", minutes, cutoff)
    assert chosen["lag_minutes"] == 2 * minutes
    # Altering the unseen suffix cannot alter the training selection.
    p.loc[p.index >= cutoff, "B"] = np.linspace(100, 200, len(p.loc[p.index >= cutoff]))
    again, _ = select_on_train(p, "A", "B", minutes, cutoff)
    assert again == chosen


def test_alignment_gap_future_bar_and_resampling():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=20, freq="min", tz="UTC"),
            "close": np.arange(20) + 100.0,
        }
    )
    c = completed_close(frame)
    assert c.index[0] == pd.Timestamp("2025-01-01T00:01Z")
    c = c.drop(c.index[6])
    p = synchronize({"A": c, "B": c}, 5)
    assert np.isnan(p.loc["2025-01-01T00:10Z", "A"])
    f = paired_returns(p, "A", "B", 5, 10, horizon=10)
    assert pd.isna(f.loc["2025-01-01T00:05Z", "y"])
    with pytest.raises(ValueError, match="RESOLVABLE"):
        paired_returns(p, "A", "B", 5, 3)
    with pytest.raises(ValueError, match="TIMEZONE"):
        completed_close(
            pd.DataFrame({"close": [1.0]}, index=pd.date_range("2025-01-01", periods=1))
        )


def test_structural_contemporaneous_relationship_has_no_extra_alpha():
    p = synthetic()
    p["A"] = 10000 / p.B
    f = paired_returns(p, "A", "B", 5, 5)
    # Known target return control removes the mathematical USD inverse.
    assert residuals(f).x.std() < 1e-12


def test_nonoverlap_and_multiple_testing():
    p = synthetic()
    f = paired_returns(p, "A", "B", 5, 10, horizon=30)
    sampled = independent_events(f, 0.1, 30)
    assert (sampled.index.to_series().diff().dropna() > pd.Timedelta(minutes=30)).all()
    assert np.allclose(fdr_bh([0.01, 0.04, 0.2]), [0.03, 0.06, 0.2])


def calibration(**kw):
    return Calibration(
        **dict(
            {
                "leader": "A",
                "target": "XAUUSD",
                "lag_minutes": 10,
                "sign": 1,
                "threshold": 2.0,
                "oos_probability": 0.65,
                "ci_low": 0.58,
                "session": "LONDON",
                "regime": "RANGE",
                "trained_until": "2025-01-01T00:00Z",
                "expires_at": "2027-01-01T00:00Z",
                "approved": True,
                "baseline_improvement_verified": True,
            },
            **kw,
        )
    )


def state(obs=None, cals=None, **context):
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    return pressure_state(
        target="XAUUSD",
        now=now,
        observations=obs or {},
        calibrations=cals or [],
        context=dict(
            {
                "event_state": "CLEAR",
                "session": "LONDON",
                "regime": "RANGE",
                "target_reaction_direction": 0,
                "reference_geometry": {"entry": [100, 101]},
            },
            **context,
        ),
    )


def test_unapproved_missing_stale_event_and_structure_keep_reference():
    assert state(cals=[calibration(approved=False)])["confidence"] is None
    assert state(cals=[calibration()])["state"] == "STALE_DATA"
    import json

    # Missing feed timestamps must remain JSON-safe for the publisher.
    json.dumps(state(cals=[calibration()]), allow_nan=False)
    obs = {
        "A": {"observed_at": "2026-10-09T12:00Z", "source_healthy": True, "zscore": 3}
    }
    s = state(obs, [calibration()])
    assert s["state"] == "CROSS_ASSET_DIVERGENCE"
    assert (
        s["confidence"] == 65
        and not s["execution_authority"]
        and not s["execution_influence"]
    )
    assert state(obs, [calibration()], event_state="UNKNOWN")["state"] == "EVENT_BLOCK"
    assert (
        state(
            obs,
            [calibration()],
            h1_valid=True,
            m15_valid=True,
            valid_sd_liquidity_area=True,
            m5_pocket_valid=True,
        )["state"]
        == "ENTRY_APPROACHING"
    )
    assert s["reference_geometry"]["entry"] == [100, 101]
    assert (
        state(obs, [calibration()], structural_invalidation=True)["state"]
        == "INVALIDATED"
    )


def test_joint_consensus_is_not_probability_and_future_model_rejected():
    obs = {
        n: {"observed_at": "2026-10-09T12:00Z", "source_healthy": True, "zscore": 3}
        for n in ["A", "C"]
    }
    s = state(obs, [calibration(), calibration(leader="C")])
    assert s["consensus"] == 100 and s["confidence"] is None
    assert (
        state(obs, [calibration(trained_until="2026-10-10T00:00Z")])["state"]
        == "NO_SIGNAL"
    )


def test_dst_sessions_and_causal_regimes():
    index = pd.DatetimeIndex(
        ["2026-01-05T13:00Z", "2026-07-06T12:00Z", "2026-07-06T02:00Z"]
    )
    assert list(sessions(index)) == [
        "LONDON_NEW_YORK_OVERLAP",
        "LONDON_NEW_YORK_OVERLAP",
        "ASIA",
    ]
    s = synthetic().B
    r = regimes(s)
    cut = 2000
    s.iloc[cut:] *= 2
    pd.testing.assert_frame_equal(r.iloc[:cut], regimes(s).iloc[:cut])


class SQLite:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.calls = 0

    def batch(self, statements, **kwargs):
        self.calls += 1
        with self.db:
            return [self.db.execute(sql, args).fetchall() for sql, args in statements]


def test_bounded_storage_migration_upsert_failure_and_reference():
    client = SQLite()
    timer = [1000.0]
    w = CrossAssetWriter(client, lambda: timer[0])
    w.migrate()
    s = state()
    assert w.publish([s])["state"] == "PUBLISHED"
    assert w.publish([s])["state"] == "CACHED"
    timer[0] += 61
    assert w.publish([s])["healthy"]
    assert (
        client.db.execute("SELECT COUNT(*) FROM cross_asset_history").fetchone()[0] == 1
    )
    payload = client.db.execute("SELECT payload FROM cross_asset_state").fetchone()[0]
    assert "reference_geometry" in payload
    timer[0] += 61
    client.db.close()
    assert w.publish([s])["state"] == "DATABASE_DEGRADED"
    assert w.publish([s])["state"] == "CACHED"
