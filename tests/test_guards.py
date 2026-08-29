from fx_scanner.guards import evaluate_hard_guards


def test_any_hard_guard_blocks():
    result = evaluate_hard_guards(NEWS_BLOCK=False, SPREAD_BLOCK=True, DATA_QUALITY_BLOCK=False)
    assert not result.allowed
    assert result.active_guards == ("SPREAD_BLOCK",)


def test_no_guards_allows():
    result = evaluate_hard_guards(NEWS_BLOCK=False, SPREAD_BLOCK=False)
    assert result.allowed
