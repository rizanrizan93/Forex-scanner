"""Audit official SF Fed USMPD XLSX in memory with stdlib XML.

Research source investigation ONLY. Read-only, hash locked at capture.
No pandas/openpyxl, no spreadsheet edits, no LIVE imports.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from collections import Counter
from pathlib import Path
import hashlib, io, json, os, re, urllib.request, xml.etree.ElementTree as ET, zipfile

SOURCE_URL="https://www.frbsf.org/wp-content/uploads/USMPD.xlsx"
NS={"x":"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p":"http://schemas.openxmlformats.org/package/2006/relationships"}

def _col_ref(ref):
    s=re.match(r"([A-Z]+)",ref or "")
    if not s:raise ValueError("BAD_CELL_ADDRESS")
    n=0
    for c in s.group(1):n=n*26+ord(c)-64
    return n-1

def _unshared(z):
    if "xl/sharedStrings.xml" not in z.namelist():return []
    root=ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join((t.text or "") for t in si.findall(".//x:t",NS))
            for si in root.findall("x:si",NS)]

def _as_value(c,strings):
    t=c.attrib.get("t")
    v=c.find("x:v",NS)
    if t=="inlineStr":
        return "".join((n.text or "") for n in c.findall(".//x:t",NS))
    raw=v.text if v is not None else None
    if raw is None:return None
    if t=="s":
        idx=int(raw)
        return strings[idx]
    if t in ("str","e"):return raw
    try:
        return float(raw) if "." in raw or "E" in raw.upper() else int(raw)
    except ValueError:
        return raw

def inspect_xlsx(raw, *, url=SOURCE_URL):
    if not (1000<=len(raw)<=12_000_000) or not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ValueError("UNTRUSTED_OR_OVERSIZED_XLSX")
    z=zipfile.ZipFile(io.BytesIO(raw))
    if any(x.file_size>30_000_000 for x in z.infolist()):
        raise ValueError("XLSX_ZIP_BOMB_LIMIT")
    strings=_unshared(z)
    workbook=ET.fromstring(z.read("xl/workbook.xml"))
    relations=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets={el.attrib["Id"]:el.attrib.get("Target","")
             for el in relations if "Id" in el.attrib}
    sheets=[]
    for s in workbook.findall("x:sheets/x:sheet",NS):
        rid=s.attrib.get("{"+NS["r"]+"}id")
        target=targets.get(rid)
        if not target:raise ValueError("MISSING_WORKBOOK_RELATION")
        filename=(target.lstrip("/") if target.startswith("/")
                  else "xl/"+target.removeprefix("../"))
        filename=filename.replace("xl/xl/","xl/")
        if ".." in filename or filename not in z.namelist():
            raise ValueError("UNTRUSTED_SHEET_PATH")
        root=ET.fromstring(z.read(filename))
        rows=root.findall(".//x:sheetData/x:row",NS)
        samples=[]; headers=None; event_years=Counter(); matched_events=[]; readme=[]
        count_rows=0
        for row in rows:
            values={}
            for c in row.findall("x:c",NS):
                v=_as_value(c,strings)
                if v is not None: values[_col_ref(c.attrib["r"])]=v
            if not values:continue
            n=max(values)
            record=[values.get(j) for j in range(n+1)]
            if headers is None:
                headers=[str(x or "") for x in record]
                continue
            count_rows+=1
            if s.attrib["name"]=="README":
                readme.append([x for x in record if isinstance(x,str) and x.strip()])
            if len(samples)<4:
                samples.append(record[:20])
            if s.attrib["name"] in ("Statements","Monetary Events","Minutes","Press Conferences"):
                paired={h:record[k] if k<len(record) else None
                        for k,h in enumerate(headers) if h in
                        ("Date","date_time","MP1","MP2","FF1","OIS1Y","UST2Y","UST10Y","DXY","EURUSD")}
                date=paired.get("Date")
                if isinstance(date,(int,float)):
                    actual=(datetime(1899,12,30,tzinfo=timezone.utc)+timedelta(days=date)).date().isoformat()
                    if actual in ("2023-09-20","2026-10-28","2026-07-29","2023-11-01","2023-06-14"):
                        matched_events.append({"actual_date":actual,**paired})
            # Excel native numeric dates are around 43000..47000 in 2019-26
            for i,h in enumerate(headers):
                if h.lower() in {"date","eventdate","fomc date"} and i<len(record):
                    d=record[i]
                    if isinstance(d,(int,float)) and 43000<=d<47000:
                        year=(datetime(1899,12,30,tzinfo=timezone.utc)+timedelta(days=d)).year
                        if 2019<=year<=2026:event_years[str(year)]+=1
        sheets.append({"name":s.attrib["name"],"xml_path":filename,
                       "rows":count_rows,"columns":len(headers or []),
                       "headers":headers[:200] if headers else [],
                       "sample_rows_first20":samples,
                       "date_rows_2019_2026":dict(event_years),
                       "selected_event_rows":matched_events,
                       "README_LINES":readme if s.attrib["name"]=="README" else None})
    return {"contract":"OFFICIAL_FRBSF_USMPD_XLSX_AUDIT_V1",
            "source_url":url,"raw_sha256":hashlib.sha256(raw).hexdigest(),
            "raw_bytes":len(raw),"sheets":sheets,
            "historical_reconstruction_only":True,
            "live_quote_age_verified":False,
            "xau_directional_accuracy_tested":False,
            "production_gate":"LOCKED"}

def fetch_official():
    req=urllib.request.Request(SOURCE_URL,headers={"User-Agent":"RIZAN-Fed-Research/1.0"})
    with urllib.request.urlopen(req,timeout=30) as f:
        return f.read(12_000_001)

def main():
    raw=fetch_official()
    audit=inspect_xlsx(raw)
    p=Path("artifacts/frbsf-usmpd-xlsx-audit.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(audit,indent=2,default=str)+"\n")
    print("FRBSF_USMPD_XLSX_AUDIT",json.dumps(audit,default=str))
if __name__=="__main__":main()
