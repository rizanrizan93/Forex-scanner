import json
from pathlib import Path
import pytest
from fx_scanner.selected_raw_reference import manifest, reference, geometry, EXECUTION_SCOPE


def test_selected_frozen_candidates_and_costs():
    xau = reference('XAUUSD'); eur = reference('EURUSD')
    assert xau['metrics']['ending_balance_usd'] == pytest.approx(24852.008274284195)
    assert xau['leverage'] == 100 and xau['layering']['confirmed']
    assert eur['metrics']['ending_balance_usd'] == pytest.approx(78880.01371425317)
    assert eur['metrics']['max_dd_m1_percent'] == pytest.approx(44.844858602281555)
    assert eur['leverage'] == 200 and eur['policy']['equity_dd_trigger'] == .25
    assert eur['layering']['depths_r'] == [0,.2,.4]
    assert EXECUTION_SCOPE == 'MANUAL_REFERENCE_ONLY'
    for ref in [xau,eur]:
        activation = ref['frozen']['activation']
        assert activation.get('live_execution_authority', activation.get('live_execution_authorized')) is False
        assert ref['account_type'] == 'RAW'


@pytest.mark.parametrize('symbol',['EURUSD','XAUUSD'])
def test_tampered_contract_rejected(symbol,tmp_path):
    value=manifest(symbol);value['contract']['account_type']='STANDARD'
    path=tmp_path/'changed.json';path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError,match='HASH_MISMATCH'):manifest(symbol,path)


@pytest.mark.parametrize('symbol',['EURUSD','XAUUSD'])
@pytest.mark.parametrize('side',[1,-1])
def test_manual_depths_preserve_protection_and_confirmation(symbol,side):
    entry=2000 if symbol=='XAUUSD' else 1.1;distance=10 if symbol=='XAUUSD' else .002
    stop=entry-side*distance;target=entry+side*distance*4
    stages=geometry(symbol,entry,stop,target)
    for stage in stages:
        assert stage['sl']==stop and stage['tp']==target
        assert side*(stage['trigger']-stop)>0
        assert side*(entry-stage['trigger'])>=0
        assert stage['requires_confirmation']==bool(symbol=='XAUUSD' and stage['stage'])
    assert stages[-1]['trigger']==pytest.approx(entry-side*distance*(29/60 if symbol=='XAUUSD' else .4))


@pytest.mark.parametrize('values',[(0,1,2),(float('nan'),1,2),(1,float('inf'),2),(1,1,2),(1,2,3)])
def test_invalid_geometry_cannot_generate_levels(values):
    with pytest.raises(ValueError):geometry('EURUSD',*values)


def test_manual_reference_has_no_broker_dependencies():
    from fx_scanner import selected_raw_reference
    import ast
    tree=ast.parse(Path(selected_raw_reference.__file__).read_text())
    imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    assert not any('execution' in name or 'ctrader' in name for name in imports)
