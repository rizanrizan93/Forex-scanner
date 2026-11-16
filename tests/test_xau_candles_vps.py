from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from scripts.collect_xau_decision_readonly import make_payload, TIMEFRAMES
from fx_scanner.xau_decision_candle_feed_v1 import DIRECT_URL, fetch_decision_candles
from operations.xau_candles.publish import publish_collected

NOW = datetime(2026, 11, 16, 6, 0, tzinfo=UTC)


def payload(at=NOW):
    series = {}
    for tf, cfg in TIMEFRAMES.items():
        series[tf] = [SimpleNamespace(timestamp=at-(cfg['required']-i)*cfg['interval'],
                      open=3900., high=3901., low=3899., close=3900.)
                      for i in range(cfg['required'])]
    return make_payload(series, now=at)


def test_direct_fresh_source_needs_no_github_or_api():
    data = payload()
    urls = []
    def opener(request, timeout):
        urls.append(request.full_url)
        assert request.full_url.startswith(DIRECT_URL)
        assert timeout <= 3
        return BytesIO(json.dumps(data).encode())
    assert fetch_decision_candles(now=NOW, opener=opener) == data
    assert len(urls) == 1


@pytest.mark.parametrize('failure', ['offline', 'old', 'account'])
def test_direct_failure_uses_independent_fresh_github(failure):
    data = payload()
    bad = payload(NOW-timedelta(minutes=2)) if failure == 'old' else payload()
    if failure == 'account':
        bad['account_suffix'] = '7904'
    urls = []
    def opener(request, timeout):
        urls.append(request.full_url)
        if request.full_url.startswith(DIRECT_URL):
            if failure == 'offline':
                raise URLError('offline')
            return BytesIO(json.dumps(bad).encode())
        return BytesIO(json.dumps(data).encode())
    assert fetch_decision_candles(now=NOW, opener=opener) == data
    assert len(urls) == 2


def test_atomic_publication_keeps_original_times_and_preserves_file_on_failure(tmp_path):
    data = payload()
    publish_collected(data, folder=tmp_path, now=NOW)
    saved = (tmp_path/'candles.json').read_text()
    assert json.loads(saved) == data
    assert not (tmp_path/'candles.tmp').exists()
    assert (tmp_path/'candles.json').stat().st_mode & 0o777 == 0o644
    # A dead source cannot refresh the publication timestamp or erase good data.
    with pytest.raises(ValueError, match='SNAPSHOT_STALE'):
        publish_collected(data, folder=tmp_path, now=NOW+timedelta(minutes=20))
    assert (tmp_path/'candles.json').read_text() == saved


def test_vps_installation_isolated_from_trading_and_uses_no_cache():
    from operations.xau_candles.install import BLOCK, UNIT, TIMER_UNIT
    assert 'no-store' in BLOCK and 'etag off' in BLOCK
    assert 'OnUnitActiveSec=20' in TIMER_UNIT
    assert 'TimeoutStartSec=95' in UNIT
    assert 'ReadWritePaths=/var/lib/rizan-xau-candles' in UNIT
    source = (Path(__file__).resolve().parents[1]/'operations/xau_candles/install.py').read_text()
    assert "['systemctl','restart',BRIDGE]" not in source
    assert "['systemctl','stop',BRIDGE]" not in source
