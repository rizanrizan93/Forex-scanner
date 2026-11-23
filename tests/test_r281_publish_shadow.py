"""Snapshot publication stays fail-closed when source or model is stale."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from r281_publish_shadow import compose, TF_FILES, CONTRACT


def fixture(tmp_path, now):
    for tf, name in TF_FILES.items():
        doc = {
            "contract": "RIZAN_R281_SHADOW_PARITY_V1", "tf": tf,
            "execution_authority": False, "execution_influence": False,
            "model_r28_live": False, "research_only": True,
            "model_sha256": "a" * 64, "generated_at": now.isoformat(),
            "historical_parity": {
                "status": "PASS", "year": 2025, "sample": 100,
                "group": "price", "expected": {"BUY": {"n": 10, "correct": 6}},
                "recomputed": {"BUY": {"n": 10, "correct": 6}},
            },
            "market_source": {
                "source": "CTRADER_MARKET_DATA_READ_ONLY",
                "as_of": now.isoformat(),
            },
            "signal": {
                "status": "SHADOW_ONLY", "direction": "SELL", "reason": "RESEARCH_SIGNAL",
                "source": "CTRADER_MARKET_DATA_READ_ONLY", "execution_authority": False,
                "candle_closed_at": (now-timedelta(minutes=15)).isoformat(),
                "target_close_at": (now+timedelta(minutes=45)).isoformat(),
                "buy_head_score": 0.45, "sell_head_score": 0.55, "last_close": 3800.,
            },
        }
        (tmp_path / name).write_text(json.dumps(doc))
    return tmp_path


def test_model_shadow_publishes_only_with_proof_and_fresh_candles(tmp_path):
    now = datetime(2026,11,23,1,tzinfo=UTC)
    root = fixture(tmp_path, now)
    packet = compose(root,now=now)
    assert packet["contract"] == CONTRACT
    assert packet["rows"]["H1"]["direction"] == "SELL"
    assert packet["rows"]["W1"]["direction"] == "SELL"
    assert packet["execution_authority"] is False
    assert not packet["rows"]["H1"]["execution_authority"]


def test_provenance_mismatch_fails_closed(tmp_path):
    now = datetime(2026,11,23,1,tzinfo=UTC)
    root = fixture(tmp_path, now)
    path = root / TF_FILES["H1"]
    doc=json.loads(path.read_text())
    doc["historical_parity"]["recomputed"]["BUY"]["correct"]=5
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match="PROVENANCE_OR_PARITY"):
        compose(root,now=now)


def test_model_target_expiry_never_promotes_old_sell(tmp_path):
    now = datetime(2026,11,23,1,tzinfo=UTC)
    root = fixture(tmp_path, now)
    doc=json.loads((root / TF_FILES["H1"]).read_text())
    doc["signal"]["target_close_at"]=(now-timedelta(minutes=5)).isoformat()
    (root / TF_FILES["H1"]).write_text(json.dumps(doc))
    result=compose(root,now=now)
    assert result["rows"]["H1"]["direction"]=="WAIT"
    assert result["rows"]["H1"]["state"]=="WAIT_DATA"
    assert result["rows"]["H1"]["reason"]=="TARGET_CANDLE_EXPIRED"


@pytest.mark.parametrize("reason",["HEAD_CONFLICT","BELOW_THRESHOLD"])
def test_model_wait_preserves_threshold_reason_and_times(tmp_path,reason):
    now = datetime(2026,11,23,1,tzinfo=UTC)
    root = fixture(tmp_path, now)
    path = root / TF_FILES["H4"]
    doc=json.loads(path.read_text())
    doc["signal"].update(direction="WAIT",reason=reason)
    path.write_text(json.dumps(doc))
    row=compose(root,now=now)["rows"]["H4"]
    assert row["state"]=="R281_MODEL_ABSTAIN" and row["reason"]==reason
    assert row["direction"]=="WAIT" and row["target_close_at"]


def test_missing_source_reason_is_not_overwritten_by_generic_stale(tmp_path):
    now = datetime(2026,11,23,1,tzinfo=UTC)
    root = fixture(tmp_path, now)
    path = root / TF_FILES["D1"]
    doc=json.loads(path.read_text())
    doc["signal"].update(status="WAIT_DATA",direction="WAIT",reason="LIVE_HISTORY_GAP_OR_PRICE_SCALE")
    path.write_text(json.dumps(doc))
    row=compose(root,now=now)["rows"]["D1"]
    assert row["state"]=="WAIT_DATA" and row["reason"]=="LIVE_HISTORY_GAP_OR_PRICE_SCALE"
