"""Fast path must reuse the frozen refit, never train or forge broker signals."""
import hashlib
import json

import joblib
import pandas as pd
import pytest

import r281_fast_live_inference as fast


def cached(tmp_path, monkeypatch):
    monkeypatch.setattr(fast, "OUTPUT", tmp_path)
    cfg = {"C": 0.3, "threshold": 0.53}
    policy = {"BUY_config": cfg, "SELL_config": cfg}
    monkeypatch.setattr(
        fast, "record", lambda tf: ({}, {"year": 2025}, "price", policy))
    model = {
        "tf": "1h", "features": ["clv"],
        "training_end_exclusive": "2026-01-01T00:00:00+00:00",
        "heads": {"BUY": object(), "SELL": object()},
        "selected_policy": {"BUY": cfg, "SELL": cfg},
    }
    model_path, report_path = fast.cache_paths("1h")
    joblib.dump(model, model_path)
    report = {
        "contract": fast.CONTRACT,
        "tf": "H1", "research_only": True, "execution_authority": False,
        "execution_influence": False, "model_r28_live": False,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "feature_count": 1,
        "training_end": "2025-12-31",
        "refit_policy": {"BUY": cfg, "SELL": cfg},
        "historical_parity": {
            "status": "PASS", "year": 2025, "sample": 5633,
            "group": "price", "expected": {"BUY": {"n": 2}},
            "recomputed": {"BUY": {"n": 2}},
        },
    }
    report_path.write_text(json.dumps(report))
    return report


def test_fast_path_reuses_hash_verified_refit_with_fresh_readonly_prices(tmp_path, monkeypatch):
    original = cached(tmp_path, monkeypatch)
    observed = pd.Timestamp("2026-11-23T10:22:00+00:00")
    monkeypatch.setattr(fast, "load_tf", lambda tf: (pd.DataFrame({"c":[1.0]}),))
    monkeypatch.setattr(fast, "extended_ecb",
                        lambda: (_ for _ in ()).throw(AssertionError("irrelevant FX")))
    calls = []
    def infer(tf, d, fx, heads, saved, now, columns):
        calls.append((tf, fx, columns))
        return (
            {"direction": "SELL", "status": "SHADOW_ONLY",
             "reason": "RESEARCH_SIGNAL", "source": "CTRADER_MARKET_DATA_READ_ONLY",
             "execution_authority": False},
            {"source": "CTRADER_MARKET_DATA_READ_ONLY", "as_of":now.isoformat()},
        )
    monkeypatch.setattr(fast, "contemporary_signal", infer)
    result = fast.run("1h", now=observed)
    assert result["signal"]["direction"] == "SELL"
    assert result["model_sha256"] == original["model_sha256"]
    assert result["historical_parity"] == original["historical_parity"]
    assert result["fast_inference"] is True
    assert result["execution_authority"] is False
    assert calls == [("1h", None, ["clv"])]
    assert json.loads((tmp_path/"r281-1h-shadow.json").read_text()) == result


def test_tampered_model_cache_is_rejected_before_deserialization(tmp_path, monkeypatch):
    cached(tmp_path, monkeypatch)
    model_path, _ = fast.cache_paths("1h")
    model_path.write_bytes(b"corrupt-not-a-valid-model")
    with pytest.raises(ValueError, match="CACHE_PROVENANCE_INVALID"):
        fast.validated_cache("1h")


def test_policy_or_training_end_cannot_silently_change(tmp_path, monkeypatch):
    cached(tmp_path, monkeypatch)
    _, proof_path = fast.cache_paths("1h")
    proof = json.loads(proof_path.read_text())
    proof["refit_policy"]["SELL"]["threshold"] = 0.75
    proof_path.write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="CACHE_PROVENANCE_INVALID"):
        fast.validated_cache("1h")


def test_fast_path_preserves_model_abstain_and_no_execution(tmp_path, monkeypatch):
    cached(tmp_path, monkeypatch)
    now = pd.Timestamp("2026-11-23T10:22:00+00:00")
    monkeypatch.setattr(fast, "load_tf", lambda tf: (pd.DataFrame({"c":[1.0]}),))
    monkeypatch.setattr(fast, "contemporary_signal",
                        lambda *args, **kwargs: (
                            {"status":"SHADOW_ONLY", "direction":"WAIT",
                             "reason":"BELOW_THRESHOLD", "execution_authority":False,
                             "source":"CTRADER_MARKET_DATA_READ_ONLY"},
                            {"source":"CTRADER_MARKET_DATA_READ_ONLY",
                             "as_of":now.isoformat()}))
    report=fast.run("1h",now=now)
    assert report["signal"]["direction"]=="WAIT"
    assert report["signal"]["reason"]=="BELOW_THRESHOLD"
    assert report["execution_authority"] is False
