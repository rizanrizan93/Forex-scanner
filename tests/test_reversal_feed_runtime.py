from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from test_manual_reversal_reference import snapshot

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reversal_feed', ROOT/'scripts/run_reversal_feed.py')
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)


def test_publish_updates_only_snapshot_branch_and_preserves_parent():
    calls = []
    def api(method, path, payload=None):
        calls.append((method, path, payload))
        if path.startswith('git/ref/'): return {'object': {'sha': 'parent'}}
        if path == 'git/commits/parent': return {'tree': {'sha': 'base-tree'}}
        return {'sha': 'new'}
    manual = snapshot()
    assert feed.publish(manual, manual, api) == 'new'
    tree = next(payload for _, path, payload in calls if path == 'git/trees')
    assert {x['path'] for x in tree['tree']} == set(feed.PATHS)
    assert tree['base_tree'] == 'base-tree'
    method, path, payload = calls[-1]
    assert method == 'PATCH' and path == 'git/refs/heads/scanner-reversal-snapshots'
    assert payload['force'] is False


@pytest.mark.parametrize('field,value', [('execution_authority', True), ('execution_influence', True), ('symbol', 'EURUSD')])
def test_invalid_publications_never_call_github(field, value):
    manual = snapshot()
    manual[field] = value
    with patch.object(feed, 'github_api') as api:
        with pytest.raises(ValueError): feed.publish(manual, manual, api)
        api.assert_not_called()


def test_old_price_is_not_republished_with_new_timestamp():
    manual = snapshot()
    manual['price_observed_at'] = (datetime.now(UTC)-timedelta(hours=1)).isoformat()
    with patch.object(feed, 'github_api') as api:
        with pytest.raises(ValueError): feed.publish(manual, manual, api)
        api.assert_not_called()


def test_loop_keeps_collecting_and_recovers_one_failed_cycle():
    elapsed = [0]
    cycles = []
    def collect(index):
        cycles.append(index)
        elapsed[0] += 20
        if index == 2: raise TimeoutError()
    def sleep(seconds): elapsed[0] += seconds
    assert feed.run_loop(seconds=900, interval=300, cycle_fn=collect,
                         clock=lambda: elapsed[0], sleeper=sleep) == 3
    assert cycles == [1, 2, 3] and elapsed[0] == 900


def test_cached_old_branch_url_falls_back_to_immutable_commit():
    from fx_scanner import manual_reversal_dashboard as panel
    stale = snapshot()
    stale['price_observed_at'] = (datetime.now(UTC)-timedelta(hours=1)).isoformat()
    fresh = snapshot()
    urls = []
    def read(url):
        urls.append(url)
        return stale if len(urls) == 1 else fresh
    with patch.object(panel, 'read_json', side_effect=read), patch.object(panel, 'latest_commit', return_value='a'*40):
        assert panel.fetch_manual_map()['fresh']
    assert '?rizan_minute=' in urls[0]
    assert '/'+('a'*40)+'/' in urls[1]


def test_manual_tab_does_not_load_legacy_patches():
    from streamlit.testing.v1 import AppTest
    with patch('fx_scanner.xau_event_dashboard_patch_v377.install_event_macro_dashboard_patch', side_effect=KeyError('legacy import')), \
         patch('fx_scanner.manual_reversal_dashboard.fetch_manual_map', new=lambda: snapshot()):
        app = AppTest.from_file(str(ROOT/'main.py')).run(timeout=20)
        assert not app.exception
        assert any(x.label == 'Area acuan H1' for x in app.metric)


def test_v05_publication_rejects_execution_authority():
    from fx_scanner.zone_v05 import blank
    p=blank(datetime.now(UTC));p['execution_authority']=True
    with patch.object(feed,'github_api') as api:
        with pytest.raises(ValueError):feed.publish(snapshot(),snapshot(),v05=p)
        api.assert_not_called()


def test_aligned_collector_removes_mandatory_one_minute_wait():
    elapsed=[0.];wall=[3600.];calls=[]
    def cycle(i):
        calls.append(i);elapsed[0]+=20;wall[0]+=20
    def sleep(n):elapsed[0]+=n;wall[0]+=n
    feed.run_loop(seconds=400,cycle_fn=cycle,clock=lambda:elapsed[0],wall_clock=lambda:wall[0],sleeper=sleep,align_to_close=True)
    assert len(calls)==2
    assert elapsed[0]==400
