"""FXCM EURUSD M1 data-source probe. Research only: NOT frozen FP Markets."""
import gzip,io,hashlib,json,requests,pandas as pd
for year,week in [(2012,4),(2019,20),(2024,10),(2026,30)]:
    url=f"https://candledata.fxcorporate.com/m1/EURUSD/{year}/{week}.csv.gz"
    r=requests.get(url,timeout=(10,35));r.raise_for_status()
    data=gzip.decompress(r.content)
    frame=pd.read_csv(io.BytesIO(data),nrows=7)
    print("SOURCE_PROBE",json.dumps({"year":year,"week":week,"url":url,"sha256":hashlib.sha256(r.content).hexdigest(),"bytes_gzip":len(r.content),"header":frame.columns.to_list(),"rows_preview":frame.astype(str).head(2).to_dict(orient="records")}),flush=True)
