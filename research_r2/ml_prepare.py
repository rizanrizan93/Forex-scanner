"""Paired, cost-inclusive daily long/short outcome labels for model research."""
import json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
configs=[{'family':f,'window':'EARLY','stop':1.25,'target':2.,'usd':0} for f in ['TIME_LONG','TIME_SHORT']]
(ROOT/'r2_results/ml_label_configs.json').write_text(json.dumps(configs,indent=2))
