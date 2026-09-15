import pytest

from fx_scanner.demo_donchian_export_evidence import ALLOWED_WORKERS, export_latest


def test_exporter_allows_only_two_donchian_runtime_workers():
    assert ALLOWED_WORKERS == {
        "ctrader_demo_donchian_adaptive_tournament",
        "ctrader_demo_donchian_forward_shadow",
    }


def test_exporter_rejects_unknown_worker_before_any_database_access(tmp_path):
    with pytest.raises(SystemExit, match="DONCHIAN_EVIDENCE_WORKER_NOT_ALLOWED"):
        export_latest("execution_worker", str(tmp_path / "evidence.json"))
