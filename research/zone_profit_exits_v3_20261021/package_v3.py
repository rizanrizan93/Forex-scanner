from pathlib import Path
import hashlib,json,zipfile,shutil
ROOT=Path(__file__).resolve().parent
DEST=ROOT.parent/'profit_v3_delivery'

def main():
    DEST.mkdir(exist_ok=True);files=[]
    for f in sorted(ROOT.iterdir()):
        if f.is_file() and f.suffix in ['.py','.md','.json','.csv','.log','.txt','.sha256','.png'] and f.name!='SHA256_MANIFEST.json':files.append(f)
    for f in sorted((ROOT/'derived').iterdir()):
        if f.is_file() and f.suffix in ['.npz','.json']:files.append(f)
    for name in ['challenger.py','download_inputs.py','prepare_inputs.py','book_adapter.py','test_challenger.py','EVENT_LEDGER.csv','requirements.txt','LOCKED_PROTOCOL.json','SOURCE_PROVENANCE.json']:
        files.append(ROOT/'baseline_v2'/name)
    files += [ROOT/'upstream/manual_reversal_map.py',ROOT/'baseline_v2/upstream/manual_reversal_map.py']
    manifest={str(f.relative_to(ROOT)):{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in files}
    (ROOT/'SHA256_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');files.append(ROOT/'SHA256_MANIFEST.json')
    zp=DEST/'RIZAN_PROFIT_EXIT_V3_20261021.zip'
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in files:z.write(f,str(f.relative_to(ROOT)))
    with zipfile.ZipFile(zp) as z:
        assert z.testzip() is None
        m=json.loads(z.read('SHA256_MANIFEST.json'));assert set(z.namelist())==set(m)|{'SHA256_MANIFEST.json'}
        for name,r in m.items():
            b=z.read(name);assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
    sha=hashlib.sha256(zp.read_bytes()).hexdigest();(DEST/'PACKAGE_SHA256.txt').write_text(f'{sha}  {zp.name}\n')
    for name in ['LAPORAN_PROFIT_EXIT_V3_20261021.md','NEW_VALIDATION_PROFIT.png']:
        shutil.copyfile(ROOT/name,DEST/name)
    print(json.dumps({'zip':str(zp),'bytes':zp.stat().st_size,'sha256':sha,'members':len(files),'all_member_hashes_and_zip_crc':'PASS'},indent=2),flush=True)

if __name__=='__main__':main()
