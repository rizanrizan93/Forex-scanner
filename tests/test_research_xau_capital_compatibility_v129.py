from types import SimpleNamespace

from fx_scanner.research_xau_capital_compatibility_v129 import (
    EXECUTION_INFLUENCE,
    MARGIN_CAPS,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _capital_floor,
)


class Spec:
    contract_units_per_lot=100.0


def test_v129_is_shadow_only_and_caps_are_preregistered():
    assert POLICY_EFFECT=="SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert MARGIN_CAPS==(25.0,50.0,75.0)


def test_margin_cap_changes_only_margin_floor():
    t=SimpleNamespace(entry_price=4000.0,stop_loss=3990.0)
    f25=_capital_floor(t,spec=Spec(),tiers=(),account_leverage=100.0,margin_cap_pct=25.0)
    f50=_capital_floor(t,spec=Spec(),tiers=(),account_leverage=100.0,margin_cap_pct=50.0)
    # loss=$10 -> risk floor=$50; margin=$40. At 25% margin floor=$160,
    # at 50% margin floor=$80.
    assert abs(f25-160.0)<1e-9
    assert abs(f50-80.0)<1e-9
