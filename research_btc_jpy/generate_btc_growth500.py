import csv,pathlib,itertools,sys
out=pathlib.Path(sys.argv[1]);catalog=list(csv.DictReader((out/'CATALOG.csv').open()))
buyers=[int(r['profile']) for r in catalog if r['growth']=='1'];assert len(buyers)==2592
sellers=[0,4936,7488,2269,6938,5253,1777,1168,1126]
fields=['id','buy_profile','sell_profile','buy_risk','sell_risk','buy_margin','sell_margin']
with (out/'STAGE1_CONFIGS.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for n,(a,b) in enumerate(itertools.product(buyers,sellers),1):w.writerow(dict(id=n,buy_profile=a,sell_profile=b,buy_risk=.23,sell_risk=.075,buy_margin=.95,sell_margin=.75))
assert n==23328;print('EXACT_STAGE1',n,flush=True)
