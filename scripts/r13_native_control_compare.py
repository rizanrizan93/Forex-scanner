"""Compare rerun summary to recovered native reference; never certify ledger parity."""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REF=ROOT/'research/RIZAN_R13_NATIVE_CONTROL_REFERENCE.json'
def compare(actual,reference):
    expected={(r['Profile']['Year'],r['Path'],r['Cost']):r for r in reference['unique_control_cases']}
    rows=[]
    for r in actual:
        key=(r['Profile']['Year'],r['Path'],r['Cost'])
        if key not in expected:continue
        e=expected[key]['Summary'];s=r['Summary'];errors=[]
        if r['Profile'].get('Addon') is not None:errors.append('ADDON_NOT_CONTROL')
        for field in ('Mode','Seed','GrowthRisk','EndYear','Addon'):
            if r['Profile'].get(field)!=expected[key]['Profile'].get(field):errors.append('PROFILE_'+field)
        for field in ('EndingBalance','MaxEquityDDPct','PF'):
            if field not in s or abs(s[field]-e[field])>1e-8*max(1,abs(e[field])):errors.append(field)
        for field in ('Baskets','Orders','ErrorCount','OpenPositions'):
            if s.get(field)!=e.get(field):errors.append(field)
        rows.append({'key':list(key),'summary_match':not errors,'mismatches':errors})
    observed={tuple(r['key']) for r in rows}
    duplicate=len(observed)!=len(rows)
    ok=observed==set(expected) and not duplicate and all(r['summary_match'] for r in rows)
    return {'status':'SUMMARY_MATCH_ONLY' if ok else 'BLOCKED_OR_MISMATCH','rows':rows,'duplicates':duplicate,
        'missing':[list(k) for k in expected if k not in observed],
        'summary_reference_matched':ok,'native_ledger_parity':False,'promotion_allowed':False,
        'note':'Even matching summaries cannot establish order/settlement/floating-equity equality.'}
def selftest():
    import copy
    ref=json.loads(REF.read_text());actual=copy.deepcopy(ref['unique_control_cases'])
    assert compare(actual,ref)['summary_reference_matched']
    actual[0]['Summary']['EndingBalance']+=1
    assert not compare(actual,ref)['summary_reference_matched']
    assert not compare([],ref)['summary_reference_matched']
    actual=copy.deepcopy(ref['unique_control_cases']);actual[0]['Profile']['Seed']['Risk']=0
    assert not compare(actual,ref)['summary_reference_matched']
    actual=copy.deepcopy(ref['unique_control_cases']);actual.append(actual[0])
    assert not compare(actual,ref)['summary_reference_matched']
    print('R13_COMPARATOR_SELFTEST_PASS summary, profile, missing and duplicate guards; never ledger parity')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true');p.add_argument('--results');a=p.parse_args()
    if a.selftest:selftest()
    elif a.results:
        result=compare(json.loads(Path(a.results).read_text()),json.loads(REF.read_text()));print(json.dumps(result,indent=2));raise SystemExit(0 if result['summary_reference_matched'] else 1)
    else:p.error('Supply --results or --selftest')
