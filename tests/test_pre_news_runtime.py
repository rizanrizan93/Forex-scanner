import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def runner():
    path=Path(__file__).resolve().parents[1]/'scripts/run_pre_news_feed.py'
    spec=importlib.util.spec_from_file_location('pre_news_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_loop_repeats_refresh_without_another_scheduler_trigger():
    module=runner();time=[0];calls=[]
    def clock():return time[0]
    def sleep(seconds):time[0]+=seconds
    assert module.run_loop(seconds=721,interval=240,cycle_fn=lambda i:calls.append((i,clock())),clock=clock,sleeper=sleep)==4
    assert [at for i,at in calls]==[0,240,480,720]


def test_loop_recovers_after_transient_failure_and_stops_repeated_failures():
    module=runner();time=[0];calls=[]
    def cycle(i):
        calls.append(i)
        if i==1:raise OSError('Temporary provider issue')
    module.run_loop(seconds=481,cycle_fn=cycle,clock=lambda:time[0],sleeper=lambda s:time.__setitem__(0,time[0]+s))
    assert calls==[1,2,3]
    with pytest.raises(RuntimeError,match='Three consecutive'):
        module.run_loop(seconds=999,cycle_fn=lambda i: (_ for _ in ()).throw(OSError()),clock=lambda:time[0],sleeper=lambda s:time.__setitem__(0,time[0]+s))


def test_publisher_updates_only_feed_branch_without_force():
    from fx_scanner.pre_news_transport import CONTRACT, BRANCH
    module=runner();calls=[]
    def api(method,path,payload=None):
        calls.append((method,path,payload))
        if path.startswith('git/ref/'):return {'object':{'sha':'parent'}}
        if path.startswith('git/commits/') and method=='GET':return {'tree':{'sha':'base'}}
        return {'sha':'result'}
    module.publish({'contract':CONTRACT,'published_at':datetime.now(UTC).isoformat(),
                    'heartbeats':[],'execution_authority':False,'execution_influence':False},api=api)
    assert calls[-1]==('PATCH','git/refs/heads/'+BRANCH,{'sha':'result','force':False})
    assert all('/heads/main' not in path for _,path,_ in calls)


def test_invalid_snapshot_never_reaches_write_api():
    module=runner();calls=[]
    with pytest.raises(ValueError):module.publish({'execution_authority':True},api=lambda *args:calls.append(args))
    assert not calls
