"""Fed R2 dashboard data contract — READ ONLY, no Streamlit dependency.

Never collapse RATE ACTION, monetary-policy SURPRISE, official
COMMUNICATION tone, and XAU trading bias into one 'Fed RESULT' field.
An actual HIKE is a HIKE even if a dovish surprise vs the expectation.

The client must display the source, release timestamp, ingestion status,
text provenance and explicit UNKNOWN/WAIT cases. This module cannot
generate a trade, confidence %, live market quote, or buy/sell order.
"""
from __future__ import annotations
from research.fed_expectation_r1.engine import utc

ACTION_LABEL={
    "HIKE":"ACTUAL RATE HIKE",
    "HOLD":"ACTUAL RATE HOLD",
    "CUT":"ACTUAL RATE CUT",
}
TONE_LABEL={
    "HAWKISH":"HAWKISH COMMUNICATION",
    "DOVISH":"DOVISH COMMUNICATION",
    "MIXED":"MIXED COMMUNICATION",
    "NEUTRAL":"NEUTRAL COMMUNICATION",
    "UNKNOWN":"NO VERIFIED TONE",
}
BIAS_LABEL={
    "SEARCH_BUY_DIP":"BUY THE DIP — WATCH ONLY",
    "SEARCH_SELL_REBOUND":"SELL ON REBOUND — WATCH ONLY",
    "WAIT":"WAIT",
}
def present_r2(report):
    if report.get("contract")!="FED_COMMUNICATION_R2_RESEARCH":
        raise ValueError("WRONG_R2_RESEARCH_CONTRACT")
    if report.get("authority_to_deploy") is not False or report.get("authority_to_send_orders") is not False:
        raise ValueError("UNSAFE_DEPLOYMENT_AUTHORITY")
    a=report.get("last_fomc_actual_record")
    if a is not None and a.get("decision") not in ACTION_LABEL:
        raise ValueError("UNVERIFIED_RATE_ACTION")
    tone=report.get("headline_stance","UNKNOWN")
    communication_tone=report.get("communication_tone","UNKNOWN")
    if tone not in TONE_LABEL or communication_tone not in TONE_LABEL:
        raise ValueError("UNKNOWN_COMMUNICATION_TONE")
    watch=report.get("macro_watch_bias","WAIT")
    if watch not in BIAS_LABEL:raise ValueError("UNKNOWN_MACRO_BIAS")
    expect=("SEARCH_SELL_REBOUND" if tone=="HAWKISH"
            else "SEARCH_BUY_DIP" if tone=="DOVISH" else "WAIT")
    if watch!=expect:
        raise ValueError("INVERTED_HAWKISH_DOVISH_UI_MAPPING")
    confirmed=report.get("trade_search_bias","NONE")
    if confirmed not in ("NONE",watch):
        raise ValueError("INVERTED_MARKET_BIAS_UI_MAPPING")
    if confirmed!="NONE" and watch=="WAIT":
        raise ValueError("TRADING_BIAS_DURING_WAIT")
    src=report.get("source_url")
    if src is not None and not str(src).startswith("https://"):
        raise ValueError("INVALID_DISPLAY_SOURCE")
    if report.get("released_at") is not None:
        utc(report["released_at"])
    if a:
        utc(a["released_at"])
    last={
        "section":"OFFICIAL_FOMC_RATE_DECISION",
        "title":ACTION_LABEL[a["decision"]] if a else "NO VERIFIED FOMC RATE DECISION",
        "actual_range_pct":a["target_range_pct"] if a else None,
        "actual_delta_bp":a["actual_delta_bp"] if a else None,
        "rate_surprise_bp":a["surprise_bp"] if a else None,
        "rate_surprise_status":("PRE_RELEASE_EXPECTATION_MATCHED" if
                                a and a["surprise_bp"] is not None
                                else "NOT_VERIFIED"),
        "dissenting_hike_votes":a["dissenting_hike_votes"] if a else None,
        "official_release_at":a["released_at"] if a else None,
        "official_source_url":a["official_source_url"] if a else None,
        "is_historical_fact_not_current_signal":True,
    }
    latest={
        "section":"LATEST_OFFICIAL_COMMUNICATION",
        "title":TONE_LABEL[communication_tone],
        "chosen_directional_stance":tone,
        "communication_tone_is_distinct_from_policy_surprise":True,
        "document_kind":report.get("source_kind"),
        "document_released_at":report.get("released_at"),
        "minutes_meeting_date":report.get("meeting_end_date"),
        "speaker":report.get("speaker"),
        "source_url":src,
        "source_text_sha256":report.get("source_sha256"),
        "evidence_quotes":report.get("evidence_quotes",[]),
        "tone_score_is_a_probability":False,
        "distinct_from_actual_rate_decision":True,
    }
    gold={
        "section":"XAU_MACRO_DIRECTION",
        "watch":BIAS_LABEL[watch],
        "watch_basis":("ACTUAL_POLICY_SURPRISE" if
                      str(report.get("stage","")).startswith("ACTUAL_POLICY_SURPRISE") else
                      "ACTUAL_POLICY_ACTION" if
                      str(report.get("stage","")).startswith("ACTUAL_POLICY_ACTION") else
                      "COMMUNICATION_TEXT_OR_WAIT"),
        "statement_vs_surprise_conflict":(
            tone!=communication_tone and
            tone in ("HAWKISH","DOVISH") and
            communication_tone in ("HAWKISH","DOVISH")),
        "search_bias_after_market_confirmation":confirmed,
        "market_confirmation_status":("CONFIRMED_RESEARCH_ONLY"
                                      if confirmed!="NONE" else "NOT_CONFIRMED"),
        "reason_codes":report.get("reason_codes",[]),
        "not_an_entry_order":True,
        "must_obtain_structure_and_risk_gate_before_entry":True,
    }
    return {
        "contract":"FED_COMMUNICATION_R2_USER_PRESENTATION_V1",
        "at_utc":report["at"],"actual_fomc":last,
        "communication":latest,"gold_bias":gold,
        "status":"RESEARCH_ONLY_NO_LIVE_EXECUTION",
        "confidence_probability":None,
        "forecast_accuracy":None,
        "no_order_authority":True,
    }
