"""Read-only audit of ACTUAL official FOMC decision and delayed minutes.

Fetch two verified official HTML pages; validate excerpt anchors and
independent release timestamps. Never pretend current fetch existed when
the 2026 meeting occurred. No trading or production connector.
"""
from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import json,re,urllib.request
from research.fed_expectation_r1.official_communications_r2 import (
    validate_document,decide_communication,
)

# Waller speech has a date-only official page. The exact public release
# minute is NOT established; audit text but do not assign a fake timestamp.
SPEECH_AUDIT_ONLY={
    "id":"WALLER-SPEECH-2026-11-10",
    "source_url":"https://www.federalreserve.gov/newsevents/speech/waller20261110a.htm",
    "reported_published_date":"2026-11-10",
    "speaker":"Christopher J. Waller",
    "excerpt":"I would still support a 25 basis point increase in the FOMC's policy rate at our December meeting",
    "tone":"HAWKISH",
    "scope":"INDIVIDUAL",
}
PAGES=[
    {
        "id":"FOMC-2026-10-28-STATEMENT",
        "kind":"FOMC_STATEMENT",
        "source_url":"https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm",
        "released_at":"2026-10-28T18:00:00Z", # source says 2:00pm EDT
        "actual_policy_evidence":"The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent",
        "actual":{
            "target_lower_bp":375,"target_upper_bp":400,
            "prior_lower_bp":375,"prior_upper_bp":400,
            "dissenting_hike_votes":2,
        },
        "evidence":[{
            "excerpt":"who preferred to raise the target range for the federal funds rate by 1/4 percentage point at this meeting",
            "tone":"HAWKISH","scope":"DISSENT",
            "topic":"MONETARY_POLICY","review_status":"HUMAN_REVIEWED",
        }],
    },
    {
        "id":"FOMC-2026-10-28-MINUTES-RELEASED-2026-11-18",
        "kind":"FOMC_MINUTES",
        "source_url":"https://www.federalreserve.gov/monetarypolicy/fomcminutes20261028.htm",
        "released_at":"2026-11-18T19:00:00Z", # source says 2:00pm EST
        "meeting_end_date":"2026-10-28",
        "evidence":[{
            "excerpt":"further action to raise the target range for the federal funds rate",
            "tone":"HAWKISH","scope":"COMMITTEE_OUTLOOK",
            "topic":"MONETARY_POLICY","review_status":"HUMAN_REVIEWED",
        }],
    },
]

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored=0;self.tokens=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"):self.ignored+=1
    def handle_endtag(self,tag):
        if tag in ("script","style") and self.ignored:self.ignored-=1
    def handle_data(self,data):
        if not self.ignored:self.tokens.append(data)

def extract_visible_text(html):
    p=VisibleText()
    p.feed(html)
    return re.sub(r"\s+"," "," ".join(p.tokens)).strip()

def fetch_one(meta,*,now):
    req=urllib.request.Request(meta["source_url"],
        headers={"User-Agent":"RIZAN-Research-Audit/2.0"})
    with urllib.request.urlopen(req,timeout=20) as f:
        raw=f.read(2_000_001)
    if len(raw)>2_000_000 or not raw:
        raise ValueError("OFFICIAL_PAGE_MISSING_OR_OVERSIZED")
    doc={**meta,"source_text":extract_visible_text(raw.decode("utf-8","replace")),
         "source_raw_sha256":sha256(raw).hexdigest(),
         "ingested_at":now}
    doc["source_text_sha256"]=sha256(doc["source_text"].encode()).hexdigest()
    validated=validate_document(doc)
    return doc,validated

def main():
    now=datetime.now(timezone.utc).isoformat()
    documents=[];checks=[]
    for p in PAGES:
        raw,validated=fetch_one(p,now=now)
        documents.append(raw)
        checks.append({
            "event_id":validated["id"],
            "kind":validated["kind"],
            "source_url":validated["source_url"],
            "released_at":validated["published_utc"].isoformat(),
            "actually_downloaded_at":now,
            "source_raw_sha256":validated["source_raw_sha256"],
            "source_text_sha256":validated["source_text_sha256"],
            "official_excerpt_verified":True,
            "verified_excerpt_texts":[e["excerpt"] for e in validated["checked_evidence"]],
            "actual_policy":validated["actual_policy"],
            "note":"Excerpt review is human-curated, not a validated sentiment model",
        })
    # Never convert date-only speeches into minute-precise historical
    # alerts; only timestamped capture creates prospective eligibility.
    req=urllib.request.Request(SPEECH_AUDIT_ONLY["source_url"],
        headers={"User-Agent":"RIZAN-Research-Audit/2.0"})
    with urllib.request.urlopen(req,timeout=20) as response:
        speech_html=response.read(2_000_001)
    speech_text=extract_visible_text(speech_html.decode("utf-8","replace"))
    if len(speech_html)>2_000_000 or SPEECH_AUDIT_ONLY["excerpt"].casefold() not in speech_text.casefold():
        raise ValueError("OFFICIAL_SPEECH_QUOTE_NOT_VERIFIED")
    speech_audit={
        **SPEECH_AUDIT_ONLY,"source_raw_sha256":sha256(speech_html).hexdigest(),
        "source_text_sha256":sha256(speech_text.encode()).hexdigest(),
        "first_observed_at":now,
        "actual_publication_minute_verified":False,
        "historical_signal_eligible":False,
        "note":"This is one Fed governor's view, not the FOMC decision",
    }
    out=decide_communication(documents,decision_at=now)
    if out["event_id"]!=PAGES[1]["id"] or out["headline_stance"]!="HAWKISH":
        raise AssertionError("NEWER_RELEASED_MINUTES_NOT_SELECTED_CORRECTLY")
    if out["trade_search_bias"]!="NONE":
        raise AssertionError("NO_TRUE_PIT_MARKET_QUOTES_YET")
    report={
        "contract":"FED_COMMUNICATION_R2_ACTUAL_SOURCE_AUDIT",
        "ingested_utc":now,"official_documents":checks,
        "speech_date_only_source_audit":speech_audit,
        "current_directional_watch":out,
        "production_eligible":False,
        "model_predictive_accuracy_tested":False,
        "explanation":"Actual target was HOLD; minutes are later text, not an October live signal. This retrospective source fetch provides no before/after futures yield or DXY feed.",
    }
    path=Path("artifacts/fed-communication-r2-official-document-audit.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print("FED_COMMUNICATION_R2_OFFICIAL_AUDIT",json.dumps(report,allow_nan=False))
if __name__=="__main__":main()
