"""Official statement action parser: anti-inversion and no-lookahead tests."""
from pathlib import Path
import json
import pytest
from scripts.replay_fed_official_statement_actions_r2 import parse_official_actual,run

@pytest.mark.parametrize("verb,action",[
    ("maintain","HOLD"),
    ("leave","HOLD"),
    ("raise","HIKE"),
    ("increase","HIKE"),
    ("lower","CUT"),
    ("reduce","CUT"),
])
def test_committee_rate_action_polarity_not_inverted(verb,action):
    sentence=f"The Committee decided to {verb} the target range for the federal funds rate to 3 percent."
    result=parse_official_actual(sentence)
    assert result["actual"]==action
    assert result["quote"] is not None

def test_hawkish_dissent_never_overrides_actual_hold():
    text=("The Committee decided to maintain the target range for the federal funds rate "
          "at 3-3/4 to 4 percent. Voting against the monetary policy action were "
          "members who preferred to raise the target range for the federal funds rate.")
    assert parse_official_actual(text)["actual"]=="HOLD"

def test_no_clear_committee_action_means_unresolved():
    text=("In a policy discussion, some officials preferred to raise the target range "
          "for the federal funds rate, but others preferred to reduce it.")
    assert parse_official_actual(text)["actual"]=="UNRESOLVED"

def test_two_contradictory_committee_decisions_abstain():
    text=("The Committee decided to raise the target range for the federal funds rate. "
          "The Committee decided to lower the target range for the federal funds rate.")
    assert parse_official_actual(text)["actual"]=="UNRESOLVED"

def test_negated_decision_does_not_force_hike():
    text="The Committee did not decide to raise the target range for the federal funds rate."
    assert parse_official_actual(text)["actual"]=="UNRESOLVED"

def test_empty_or_off_topic_never_infer_rate_from_gold():
    assert parse_official_actual("Gold prices fell as dollar surged.")["actual"]=="UNRESOLVED"

def test_full_replay_requires_exact_eight_year_shards(tmp_path):
    (tmp_path/"2019.json").write_text(json.dumps({"year":2019}))
    with pytest.raises(ValueError,match="MISSING_EIGHT_YEAR_ARCHIVE"):
        run([tmp_path/"2019.json"])

def test_cannot_look_up_actual_action_from_market_oracle():
    # R1's ex-post MP2 BUY/SELL is intentionally NOT a committee action.
    assert parse_official_actual("MP2 surprise hawkish, dollar jumped")["actual"]=="UNRESOLVED"
