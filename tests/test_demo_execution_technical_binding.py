from __future__ import annotations

from fx_scanner import demo_execution_technical_producer as runtime


def test_pair_specific_discovery_binds_impulse_retest_v2(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run() -> int:
        captured["scanner"] = runtime.base.scan_demo_deep_candidates_report
        return 0

    monkeypatch.setattr(runtime.base, "run", fake_run)

    assert runtime.run() == 0
    assert captured["scanner"] is runtime.scan_demo_deep_candidates_report
