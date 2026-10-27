import os,json
home=os.path.expanduser('~');roots=list(dict.fromkeys([home+'/rizan-ticks/REPLAY_RESULTS','/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS']));found=[];status=[]
for root in roots:
 status.append({'path':root,'exists':os.path.isdir(root)})
 if not os.path.isdir(root):continue
 for base,dirs,files in os.walk(root,followlinks=False):
  depth=base[len(root):].count(os.sep)
  dirs[:]=[d for d in dirs if not d.startswith('.') and d not in ['node_modules','venv','__pycache__','site-packages'] and depth<12]
  for name in files:
   if name.lower().endswith(('.zip','.tar.gz','.csv','.csv.gz','.npz')):
    p=os.path.join(base,name)
    try:found.append({'path':p,'bytes':os.stat(p).st_size})
    except OSError:pass
print(json.dumps({'read_only':True,'roots':status,'files':found},indent=2))
