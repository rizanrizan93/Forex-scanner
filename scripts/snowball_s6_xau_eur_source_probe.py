"""S6 multi-asset FXCM hourly M1 feed availability probe. Research only."""
import gzip,io,hashlib,json,requests,pandas as pd
session=requests.Session()
for sym in ("XAUUSD","XAU/USD","GOLD","EURUSD"):
    for year,week in ((2012,4),(2019,20),(2024,10),(2025,20),(2026,30)):
        url=f"https://candledata.fxcorporate.com/m1/{sym}/{year}/{week}.csv.gz"
        try:
            resp=session.get(url,timeout=(8,25))
            if resp.status_code!=200:
                print("SOURCE_CHECK",json.dumps({"symbol":sym,"year":year,"week":week,"http":resp.status_code,"present":False}),flush=True)
                continue
            raw=resp.content
            data=pd.read_csv(io.BytesIO(gzip.decompress(raw)),nrows=3)
            print("SOURCE_CHECK",json.dumps({"symbol":sym,"year":year,"week":week,"http":200,"present":True,
              "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"columns":data.columns.tolist(),
              "first":data.iloc[0].astype(str).to_dict() if len(data) else {}}),flush=True)
        except Exception as e:
            print("SOURCE_CHECK",json.dumps({"symbol":sym,"year":year,"week":week,"error":str(e)[:300]}),flush=True)
