from fx_scanner import demo_xau_v375_reaction_executor as executor


def test_v392_accepts_legacy_v342_and_frozen_v376_champion() -> None:
    assert "XAU_RIZAN_SD_LIQUIDITY_V342_CURRENT".startswith(
        executor.ACCEPTED_ENGINE_CONTRACT_PREFIXES
    )
    assert "XAU_RIZAN_SD_LIQUIDITY_V376_C4_CHAMPION_V1".startswith(
        executor.ACCEPTED_ENGINE_CONTRACT_PREFIXES
    )


def test_v392_does_not_broadly_authorize_future_contracts() -> None:
    assert not "XAU_RIZAN_SD_LIQUIDITY_V390".startswith(
        executor.ACCEPTED_ENGINE_CONTRACT_PREFIXES
    )
    assert not "ARBITRARY_ENGINE".startswith(executor.ACCEPTED_ENGINE_CONTRACT_PREFIXES)


def test_v392_run_installs_same_allowlist_in_base_router(monkeypatch) -> None:
    monkeypatch.setattr(executor.base, "run", lambda: 0)
    assert executor.run() == 0
    assert executor.base.ENGINE_CONTRACT_PREFIX == executor.ACCEPTED_ENGINE_CONTRACT_PREFIXES
