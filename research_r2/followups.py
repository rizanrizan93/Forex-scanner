"""Fixed feature ablations on training-chosen entry configurations."""
import json,pathlib,itertools
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'r2_results'
leaders=json.loads((OUT/'diagnostic_leaders.json').read_text());leaders.append({'family':'R1_FVG_REF','window':'FULL','stop':3.5,'target':3.,'usd':0});configs=[]
for base in leaders:
 for macro,news,vol in itertools.product([0,1],['ALL','AFTER','QUIET'],[0,1]):
  c=dict(base);c.update(macro=macro,news=news,vol_veto=vol,suffix=f'_MAC{macro}_NEWS{news}_VOL{vol}');configs.append(c)
(OUT/'ablation_configs.json').write_text(json.dumps(configs,indent=2));print('Ablation experiments:',len(configs))
