from fx_scanner.execution.cadence import AdaptiveExecutionCadence


def test_adaptive_cadence_accelerates_by_state():
    now = [100.0]
    cadence = AdaptiveExecutionCadence(
        {
            "NO_TRADE": 2.0,
            "WATCH": 2.0,
            "SETUP_FORMING": 1.0,
            "ARMED": 0.25,
            "EXECUTION_READY": 0.05,
            "MISSED": 2.0,
            "INVALIDATED": 2.0,
            "COOLDOWN": 2.0,
        },
        clock=lambda: now[0],
    )
    assert cadence.due("global", "ARMED")
    cadence.mark_checked("global")
    now[0] = 100.20
    assert not cadence.due("global", "ARMED")
    now[0] = 100.25
    assert cadence.due("global", "ARMED")
    cadence.mark_checked("global")
    now[0] = 100.30
    assert cadence.due("global", "EXECUTION_READY")
    assert cadence.interval_for("WATCH") == 2.0
    assert cadence.interval_for("SETUP_FORMING") == 1.0
