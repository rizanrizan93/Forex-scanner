from pathlib import Path
from unittest.mock import patch
import pytest
from scripts.publish_xau_decision_readonly import run_loop, cycle, ARTIFACT


def test_recollects_continuously_after_transient_failure():
    timer=[0.]
    calls=[]
    def tick():
        calls.append(timer[0])
        if len(calls)==2: raise OSError('temporary')
        return str(timer[0])
    def wait(seconds): timer[0]+=seconds
    assert run_loop(duration_seconds=130,cycle_fn=tick,clock=lambda:timer[0],wait=wait)==2
    assert calls==[0,45,90]
    assert timer[0]==130


def test_no_success_is_a_failure_and_never_publishes_old_data():
    timer=[0.]
    def fail(): raise ValueError('stale')
    with pytest.raises(RuntimeError,match='NO_FRESH_PUBLICATIONS'):
        run_loop(duration_seconds=1,cycle_fn=fail,clock=lambda:timer[0],wait=lambda s:timer.__setitem__(0,timer[0]+s))


def test_cycle_removes_old_artifact_before_collection_and_never_publishes_it(tmp_path):
    import scripts.publish_xau_decision_readonly as p
    artifact=tmp_path/'old.json'
    artifact.write_text('{"as_of":"OLD"}')
    with patch.object(p,'ARTIFACT',artifact), patch.object(p.subprocess,'run',side_effect=OSError('offline')), patch.object(p,'publish') as publish:
        with pytest.raises(OSError): p.cycle()
        publish.assert_not_called()
        assert not artifact.exists()


def test_workflow_handoff_keeps_serial_readonly_publisher():
    src=(Path(__file__).resolve().parents[1]/'.github/workflows/xau-decision-readonly-publisher.yml').read_text()
    assert 'cancel-in-progress: false' in src
    assert 'gh workflow run xau-decision-readonly-publisher.yml --ref main' in src
    assert "XAU_DECISION_LOOP_SECONDS: '3300'" in src
    assert 'actions: write' in src
