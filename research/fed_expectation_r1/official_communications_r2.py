"""Fed actual decision + minutes + speech context for XAU: R2 RESEARCH ONLY.

This module never fetches, trades or writes. Every document must carry
the verifiable official-source text, published+ingested timestamps, SHA256,
and an evidence ledger whose quotes occur in that text. Hawkish/dovish
evidence is human-reviewed context, NOT a measured win rate.

Actual FOMC target range is the highest authority *within its release
cycle*, while later published minutes can update the current narrative.
Trade-search authorization remains locked until the R1 PIT market repricing
confirms the same event and direction.
"""
from __future__ import annotations
from datetime import timedelta, date
from hashlib import sha256
from math import isfinite
from urllib.parse import urlsplit
import re
from research.fed_expectation_r1.engine import utc
from research.fed_expectation_r1.polarity_guard_r2 import safe_interpretation,actual_decision_phrase

EXECUTION_AUTHORITY=False
EXECUTION_INFLUENCE=False
RESEARCH_ONLY=True
EVENT_PRIORITY={
    "FOMC_STATEMENT":100,
    "FOMC_PRESS_CONFERENCE":95,
    "FOMC_MINUTES":85,
    "FOMC_SEP":80,
    "FED_CHAIR_SPEECH":70,
    "FED_VOTING_MEMBER_SPEECH":55,
    "FED_NONVOTING_MEMBER_SPEECH":35,
}
MAX_AGE={
    "FOMC_STATEMENT":timedelta(days=7),
    "FOMC_PRESS_CONFERENCE":timedelta(days=3),
    "FOMC_MINUTES":timedelta(days=7),
    "FOMC_SEP":timedelta(days=7),
    "FED_CHAIR_SPEECH":timedelta(days=3),
    "FED_VOTING_MEMBER_SPEECH":timedelta(days=2),
    "FED_NONVOTING_MEMBER_SPEECH":timedelta(days=1),
}
STANCE={"HAWKISH":1,"DOVISH":-1,"NEUTRAL":0}
SCOPE_WEIGHT={"COMMITTEE":1.0,"COMMITTEE_OUTLOOK":1.0,
              "CHAIR":1.0,"INDIVIDUAL":1.0,"DISSENT":0.25}
OFFICIAL_HOSTS={
    "federalreserve.gov","newyorkfed.org","frbsf.org","stlouisfed.org",
    "bostonfed.org","chicagofed.org","clevelandfed.org","dallasfed.org",
    "richmondfed.org","philadelphiafed.org","atlantafed.org",
    "minneapolisfed.org","kansascityfed.org",
}

def official_https(value):
    try:
        parsed=urlsplit(str(value))
        host=(parsed.hostname or "").lower()
        return parsed.scheme=="https" and parsed.username is None and (
            host in OFFICIAL_HOSTS or
            any(host.endswith("."+h) for h in OFFICIAL_HOSTS))
    except (ValueError,TypeError):
        return False

def _norm(s):
    return re.sub(r"\s+"," ",str(s)).strip().casefold()

def _numeric_actual(doc):
    """Bps range, actual-vs-prior, then optionally actual-vs-prior EXPECTED delta."""
    a=doc.get("actual")
    if a is None:return None
    if doc["kind"]!="FOMC_STATEMENT":
        raise ValueError("ONLY_FOMC_STATEMENT_CAN_OWN_ACTUAL_POLICY_ACTION")
    keys={"target_lower_bp","target_upper_bp","prior_lower_bp","prior_upper_bp"}
    if not keys.issubset(a):raise ValueError("ACTUAL_FOMC_RANGE_INCOMPLETE")
    v={k:float(a[k]) for k in keys}
    if not all(isfinite(x) for x in v.values()):raise ValueError("NONFINITE_RATE")
    if v["target_lower_bp"]>v["target_upper_bp"] or v["prior_lower_bp"]>v["prior_upper_bp"]:
        raise ValueError("INVALID_RANGE")
    delta_lower=v["target_lower_bp"]-v["prior_lower_bp"]
    delta_upper=v["target_upper_bp"]-v["prior_upper_bp"]
    if abs(delta_lower-delta_upper)>0.001:
        raise ValueError("ASYMMETRIC_POLICY_RANGE_CHANGE")
    if delta_lower%25!=0:
        raise ValueError("RATE_DELTA_NOT_MULTIPLE_OF_25BP")
    action=("HIKE" if delta_lower>0 else "CUT" if delta_lower<0 else "HOLD")
    result={"decision":action,"actual_delta_bp":round(delta_lower,2),
            "target_range_pct":[v["target_lower_bp"]/100,v["target_upper_bp"]/100],
            "expected_delta_bp":None,"surprise_bp":None,
            "expectation_provenance":"UNAVAILABLE"}
    if a.get("expected_delta_bp") is not None:
        e=float(a["expected_delta_bp"])
        if not isfinite(e) or abs(e)>150:raise ValueError("INVALID_RATE_EXPECTATION")
        if not official_https(a.get("expectation_source_url","")) and not (
                a.get("expectation_source_url","").startswith("https://www.cmegroup.com/")):
            raise ValueError("UNVERIFIED_EXPECTATION_SOURCE")
        observed=utc(a["expected_observed_at"])
        release=utc(doc["released_at"])
        captured=utc(a["expected_ingested_at"])
        if observed>release or captured>release:
            raise ValueError("POST_RELEASE_EXPECTATION_IS_LOOKAHEAD")
        result.update({"expected_delta_bp":e,
                       "surprise_bp":round(delta_lower-e,2),
                       "expectation_provenance":"PRE_RELEASE_CAPTURED_EXPECTATION"})
    # Dissents are disclosed, not reinterpreted as a committee rate hike.
    dissents=a.get("dissenting_hike_votes",0)
    if not isinstance(dissents,int) or dissents<0 or dissents>12:
        raise ValueError("INVALID_DISSENT_COUNT")
    result["dissenting_hike_votes"]=dissents
    return result

def validate_document(doc):
    required={"id","kind","released_at","ingested_at",
              "source_url","source_text","source_text_sha256","evidence"}
    if not required.issubset(doc):raise ValueError("MISSING_DOCUMENT_PROVENANCE")
    if doc["kind"] not in EVENT_PRIORITY:raise ValueError("UNRECOGNIZED_COMMUNICATION")
    if not official_https(doc["source_url"]):
        raise ValueError("DOCUMENT_MUST_BE_OFFICIAL_FED_SOURCE")
    release=utc(doc["released_at"]);ingested=utc(doc["ingested_at"])
    text=doc["source_text"]
    if not isinstance(text,str) or len(text)<30 or len(text)>1_000_000:
        raise ValueError("DOCUMENT_TEXT_LENGTH_INVALID")
    digest=sha256(text.encode("utf-8")).hexdigest()
    if digest!=doc["source_text_sha256"]:
        raise ValueError("OFFICIAL_DOCUMENT_SHA_MISMATCH")
    evidence=doc["evidence"]
    if not isinstance(evidence,list) or len(evidence)>20:
        raise ValueError("BAD_EVIDENCE")
    checked=[]
    for item in evidence:
        if not {"excerpt","tone","scope","topic","review_status"}.issubset(item):
            raise ValueError("EVIDENCE_FIELDS_INCOMPLETE")
        excerpt=item["excerpt"]
        if not 8<=len(str(excerpt))<=600 or _norm(excerpt) not in _norm(text):
            raise ValueError("EVIDENCE_QUOTE_NOT_IN_OFFICIAL_DOCUMENT")
        if item["tone"] not in STANCE or item["scope"] not in SCOPE_WEIGHT:
            raise ValueError("INVALID_TONE_OR_SCOPE")
        if doc["kind"].endswith("_SPEECH") and item["scope"] not in ("INDIVIDUAL","CHAIR"):
            raise ValueError("INDIVIDUAL_SPEECH_CANNOT_CLAIM_FOMC_CONSENSUS")
        if item["topic"]!="MONETARY_POLICY" or item["review_status"]!="HUMAN_REVIEWED":
            raise ValueError("UNREVIEWED_OR_NONMONETARY_POLICY_EVIDENCE")
        observed=safe_interpretation(item["tone"],excerpt)
        if observed=="CONTRADICTORY_LABEL":
            raise ValueError("HAWKISH_DOVISH_LABEL_INVERTED")
        if observed=="UNRESOLVED" and item["tone"]!="NEUTRAL":
            raise ValueError("NEGATED_MIXED_OR_AMBIGUOUS_POLICY_TEXT")
        checked.append(item)
    if doc["kind"]=="FOMC_MINUTES":
        if not doc.get("meeting_end_date"):
            raise ValueError("MINUTES_MEETING_DATE_FOR_DISPLAY_REQUIRED")
        try:
            meeting_day=date.fromisoformat(doc["meeting_end_date"])
        except (TypeError,ValueError):
            raise ValueError("MINUTES_MEETING_DATE_NOT_ISO_DATE")
        if meeting_day>release.date():
            raise ValueError("FUTURE_MINUTES_MEETING_DATE")
    if doc["kind"].endswith("_SPEECH") and not str(doc.get("speaker","")).strip():
        raise ValueError("SPEAKER_ID_REQUIRED")
    actual=_numeric_actual(doc)
    if actual is not None:
        anchor=doc.get("actual_policy_evidence")
        if (not isinstance(anchor,str) or
                len(anchor)<24 or _norm(anchor) not in _norm(text)):
            raise ValueError("ACTUAL_RATE_ACTION_ANCHOR_MISSING_FROM_OFFICIAL_DOCUMENT")
        if actual_decision_phrase(anchor)!=actual["decision"]:
            raise ValueError("ACTUAL_RATE_ACTION_CONFLICTS_WITH_OFFICIAL_TEXT")
    return {**doc,"published_utc":release,"available_at":max(release,ingested),
            "digest_verified_locally":True,"checked_evidence":checked,
            "actual_policy":actual}

def _tone(doc):
    scores=[(STANCE[e["tone"]],SCOPE_WEIGHT[e["scope"]])
            for e in doc["checked_evidence"]]
    up=sum(w for s,w in scores if s>0)
    down=sum(w for s,w in scores if s<0)
    if up>=.7 and down>=.7:
        return "MIXED",up-down
    net=up-down
    return ("HAWKISH" if net>=.7 else "DOVISH" if net<=-.7 else "NEUTRAL",net)

def decide_communication(documents,*,decision_at,market_context=None):
    """Prioritize actual FOMC release, then newer minutes and speeches.

    A document can create an informative WATCH direction. Any actionable
    search bias additionally needs verified matching PIT market repricing.
    All decisions remain RESEARCH-ONLY; no order authority.
    """
    now=utc(decision_at)
    result={
        "contract":"FED_COMMUNICATION_R2_RESEARCH",
        "at":now.isoformat(),"stage":"NO_VERIFIED_COMMUNICATION",
        "headline_stance":"UNKNOWN","macro_watch_bias":"WAIT",
        "trade_search_bias":"NONE",
        "actual_fomc":None,"last_fomc_actual_record":None,
        "recent_communication_timeline":[],
        "source_kind":None,"source_url":None,
        "released_at":None,"source_sha256":None,
        "evidence_quotes":[],"event_id":None,
        "score_units":"EVIDENCE_TONE_NOT_A_PROBABILITY",
        "reason_codes":[],"authority_to_deploy":False,
        "authority_to_send_orders":False,
        "execution_influence":False,
    }
    verified=[validate_document(d) for d in documents]
    # Keep the last formally decided target range visible as historic
    # FACT, even after its announcement has expired as a directional
    # signal. Never use a later document to rewrite earlier decisions.
    history=[d for d in verified if d["available_at"]<=now]
    actual_docs=[d for d in history if d["kind"]=="FOMC_STATEMENT"
                 and d["actual_policy"] is not None]
    if actual_docs:
        last=max(actual_docs,key=lambda d:d["published_utc"])
        result["last_fomc_actual_record"]={
            "id":last["id"],"released_at":last["published_utc"].isoformat(),
            "decision":last["actual_policy"]["decision"],
            "target_range_pct":last["actual_policy"]["target_range_pct"],
            "actual_delta_bp":last["actual_policy"]["actual_delta_bp"],
            "surprise_bp":last["actual_policy"]["surprise_bp"],
            "dissenting_hike_votes":last["actual_policy"]["dissenting_hike_votes"],
            "official_source_url":last["source_url"],
            "historical_fact_not_current_directional_signal":True,
        }
    result["recent_communication_timeline"]=[
        {"id":d["id"],"kind":d["kind"],
         "released_at":d["published_utc"].isoformat(),
         "source_url":d["source_url"],"tone":_tone(d)[0]}
        for d in sorted(history,key=lambda d:d["published_utc"],reverse=True)[:8]]
    eligible=[d for d in verified if d["available_at"]<=now and
              timedelta(0)<=now-d["published_utc"]<=MAX_AGE[d["kind"]]]
    if not eligible:
        result["reason_codes"]=["NO_PUBLISHED_FRESH_OFFICIAL_DOCUMENT"]
        return result
    latest=max(d["published_utc"] for d in eligible)
    # Within a single communication cycle prefer actual committee
    # statement. New minutes three weeks later can become the new latest.
    cycle=[d for d in eligible if latest-d["published_utc"]<=timedelta(hours=24)]
    doc=max(cycle,key=lambda d:(EVENT_PRIORITY[d["kind"]],d["published_utc"]))
    result.update({
        "event_id":doc["id"],"source_kind":doc["kind"],
        "source_url":doc["source_url"],
        "source_sha256":doc["source_text_sha256"],
        "released_at":doc["published_utc"].isoformat(),
        "stage":"DOCUMENT_VERIFIED",
        "actual_fomc":doc["actual_policy"],
        "speaker":doc.get("speaker"),
        "meeting_end_date":doc.get("meeting_end_date"),
        "source_priority":EVENT_PRIORITY[doc["kind"]],
        "evidence_quotes":[{"excerpt":e["excerpt"],"tone":e["tone"],
                            "scope":e["scope"]} for e in doc["checked_evidence"]],
    })
    communication,score=_tone(doc)
    result["communication_tone"]=communication
    result["communication_evidence_net"]=round(score,2)
    action=doc["actual_policy"]
    surprise=(action or {}).get("surprise_bp")
    if surprise is not None and abs(surprise)>=2:
        stance="HAWKISH" if surprise>0 else "DOVISH"
        result["headline_stance"]=stance
        result["stage"]="ACTUAL_POLICY_SURPRISE_CONFIRMED"
    elif action and action["actual_delta_bp"]!=0 and communication in ("NEUTRAL",):
        # Rate move is actual, but expected-move surprise remains unknown.
        stance=("HAWKISH" if action["actual_delta_bp"]>0 else "DOVISH")
        result["headline_stance"]=stance
        result["stage"]="ACTUAL_POLICY_ACTION_EXPECTATION_UNVERIFIED"
    else:
        stance=communication
        result["headline_stance"]=stance
    if stance not in ("HAWKISH","DOVISH"):
        result["macro_watch_bias"]="WAIT"
        result["reason_codes"].append("MIXED_OR_NEUTRAL_COMMUNICATION")
        return result
    expected_bias="SEARCH_SELL_REBOUND" if stance=="HAWKISH" else "SEARCH_BUY_DIP"
    result["macro_watch_bias"]=expected_bias
    if market_context is None:
        result["stage"]+="_PENDING_MARKET_CONFIRMATION"
        result["reason_codes"].append("MISSING_PIT_MARKET_REPRICING")
        return result
    if market_context.get("event_id")!=doc["id"]:
        result["reason_codes"].append("MARKET_CONTEXT_EVENT_ID_MISMATCH")
        return result
    if market_context.get("source_quality")!="CAPTURED_REALTIME" or (
            market_context.get("data_ready") is not True):
        result["reason_codes"].append("MARKET_CONFIRMATION_NOT_CAPTURED_REALTIME")
        return result
    market_at=utc(market_context["decision_at"])
    if market_at>now or market_at<doc["available_at"]:
        result["reason_codes"].append("MARKET_CONFIRMATION_CLOCK_INVALID")
        return result
    if market_context.get("search_bias")!=expected_bias:
        result["stage"]="MACRO_CONTRADICTION_WAIT"
        result["reason_codes"].append("PIT_YIELD_DXY_EXPECTATION_DISAGREE_WITH_TEXT")
        return result
    result["trade_search_bias"]=expected_bias
    result["stage"]="MACRO_DIRECTION_CONFIRMED_RESEARCH_ONLY"
    return result
