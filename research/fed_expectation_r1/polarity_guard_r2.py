"""Conservative Fed rate language polarity guards — research only.

Prevents inverted annotations. This is NOT a comprehensive NLP sentiment
classifier and never produces a trading order. Unfamiliar formulations,
negation, both hike and cut, or ambiguous attribution -> UNRESOLVED, WAIT.

Policy/action surprise, statement tone, minutes tone, and market repricing
are separate categories; they must not be overwritten by one another.
"""
from __future__ import annotations
import re
from fractions import Fraction

HIKE=(r"\brais(?:e|es|ing)\b",r"\bincreas(?:e|es|ing)\b",
      r"\btighten(?:ing|ed)?\b",r"\bhigher policy rate\b",
      r"\badditional firming\b")
CUT=(r"\blower(?:s|ed|ing)?\b",r"\breduc(?:e|es|ed|tion|tions|ing)\b",
     r"\bcut(?:s|ting)?\b",r"\beas(?:e|es|ing)\b")
NEGATION=(r"\bnot\b",r"\bno\b",r"\bnever\b",
          r"\bwithout\b",r"\bunlikely\b",
          r"\bneither\b",r"\bwon't\b",
          r"\bwouldn't\b",r"\bdisagreed\b")
RATE_CONTEXT=(r"\brate",r"\bfederal funds\b",
              r"\bmonetary policy\b",r"\btarget range\b")
ACTUAL_ACTION_RE=re.compile(
    r"\b(?:committee\s+)?decided\s+to\s+"
    r"(?P<verb>maintain|raise|increase|lower|reduce|decrease|cut|leave)\b",
    re.I)

def conservative_policy_polarity(excerpt):
    """HAWKISH/DOVISH/NEUTRAL/UNRESOLVED; fail closed on negation.

    Words such as higher unemployment or lower inflation are NOT
    automatically policy-action signals. A direct policy anchor required.
    """
    s=re.sub(r"\s+"," ",str(excerpt).strip().lower())
    if not any(re.search(p,s) for p in RATE_CONTEXT):
        return "UNRESOLVED"
    if any(re.search(p,s) for p in NEGATION):
        return "UNRESOLVED"
    up=any(re.search(p,s) for p in HIKE)
    down=any(re.search(p,s) for p in CUT)
    if up and down:
        return "UNRESOLVED"
    if up:return "HAWKISH"
    if down:return "DOVISH"
    if re.search(r"\b(?:maintain|unchanged|hold|leave)\b",s):
        return "NEUTRAL"
    return "UNRESOLVED"

def actual_decision_phrase(excerpt):
    """Verify official FOMC *committee* action; dissent can't masquerade.

    The word preferred is not an actual policy action; this function
    requires 'Committee decided to ...' phrasing.
    """
    s=re.sub(r"\s+"," ",str(excerpt))
    m=ACTUAL_ACTION_RE.search(s)
    if not m:
        return "UNRESOLVED"
    verb=m.group("verb").lower()
    if verb in ("maintain","leave"):return "HOLD"
    if verb in ("raise","increase"):return "HIKE"
    return "CUT"

def safe_interpretation(reviewer_tone,excerpt):
    """Disagree -> ambiguous and suppress BUY/SELL. Do NOT flip side."""
    p=conservative_policy_polarity(excerpt)
    if p=="UNRESOLVED":
        return "UNRESOLVED"
    if reviewer_tone!=p:
        return "CONTRADICTORY_LABEL"
    return p
