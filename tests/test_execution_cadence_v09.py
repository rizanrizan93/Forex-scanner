from pathlib import Path
from shutil import copytree

import pytest
import yaml

from fx_scanner.exceptions import ConfigurationError
from fx_scanner.execution.policy import load_execution_policy

ROOT = Path(__file__).resolve().parents[1]


def copied_root(tmp_path):
    copytree(ROOT / "config", tmp_path / "config")
    return tmp_path


def test_v09_execution_cadence_is_fast_only_near_setup():
    policy = load_execution_policy()
    assert policy.scheduler["heavy_scan_seconds"] == 900
    assert policy.scheduler["fast_setup_seconds"] == 15
    assert policy.scheduler["execution_watch_seconds"] == 0.25
    assert policy.adaptive_cadence["WATCH"] == 1.0
    assert policy.adaptive_cadence["SETUP_FORMING"] == 0.5
    assert policy.adaptive_cadence["ARMED"] == 0.25
    assert policy.adaptive_cadence["EXECUTION_READY"] == 0.25


def test_v09_fast_setup_cannot_be_slowed_back_to_60_seconds(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "execution.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["scheduler"]["fast_setup_seconds"] = 60
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="cannot exceed 15 seconds"):
        load_execution_policy(root)


def test_v09_setup_forming_cadence_cannot_be_slowed(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "execution.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["adaptive_cadence"]["SETUP_FORMING"] = 1.0
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="cannot exceed 500ms"):
        load_execution_policy(root)
