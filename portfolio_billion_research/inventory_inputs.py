import os,json,fnmatch
root='/home/Rizanrizan';found=[]
names={'xau_2012_2026.csv','eur_2012_2026_recovered.csv','eur_2012_2026.csv','BTCUSD_M1.csv'}
for base,dirs,files in os.walk(root):
 depth=base[len(root):].count(os.sep)
 dirs[:]=[d for d in dirs if not d.startswith('.') and d not in ['node_modules','venv','__pycache__','site-packages','ticks','raw_ticks','tick_cache'] and depth<7]
 for name in files:
  if name in names or (name.lower().endswith(('.zip','.tar.gz')) and any(q in name.lower() for q in ['settlement','long_harness','2012_2026','full_input'])):
   p=os.path.join(base,name)
   try:found.append({'path':p,'bytes':os.stat(p).st_size})
   except OSError:pass
print(json.dumps({'read_only':True,'roots':[root],'files':found},indent=2))
