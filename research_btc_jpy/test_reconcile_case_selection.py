import tempfile,pathlib,subprocess,sys,json
p=pathlib.Path(tempfile.mkdtemp());r=p/'raw_validation';r.mkdir()
(r/'RAW_TOP20_STRESS.csv').write_text('id,case,equity\n1,BASE,110\n1,COST2,95\n')
h='side,exit_price,entry_average,quantity,entry_commission,exit_commission,financing,net_pnl,balance\n'
(r/'raw_1_ledger.csv').write_text(h+'1,110,100,1,0,0,0,10,110\n')
(r/'raw_1_COST2_ledger.csv').write_text(h+'1,95,100,1,0,0,0,-5,95\n')
subprocess.run([sys.executable,'research_btc_jpy/reconcile_raw.py',str(p),'BTCUSD'],check=True)
q=json.load(open(r/'RAW_CASH_RECONCILIATION.json'));assert len(q['checks'])==1 and q['max_error']==0
print('PASS BASE_LEDGER_CASE_SELECTION_REGRESSION')
