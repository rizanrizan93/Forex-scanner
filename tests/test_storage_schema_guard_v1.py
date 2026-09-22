from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_schema_declares_compact_outcome_ledger_and_500_mib_guard():
    text = (ROOT / "supabase/schemas/fx_core.sql").read_text()
    assert "create table if not exists public.xau_outcome_ledger" in text
    assert "episode_key text not null unique" in text
    assert "missed_execution boolean not null default false" in text
    assert "create table if not exists public.storage_guard_audit" in text
    assert "create or replace function public.fx_storage_guard_v1" in text
    assert "'absolute_ceiling_mib',500" in text
    assert "'critical_mib',475" in text
    assert "'outcome_ledger_pruned',false" in text
    assert "revoke all on function public.fx_storage_guard_v1(boolean)" in text


def test_storage_guard_is_scheduled_and_outcome_ledger_runs_in_maintenance():
    guard = (ROOT / ".github/workflows/ctrader-demo-storage-guard.yml").read_text()
    maintenance = (
        ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml"
    ).read_text()
    assert 'cron: "17 */6 * * *"' in guard
    assert "python -m fx_scanner.demo_storage_guard" in guard
    assert "python -m fx_scanner.demo_xau_outcome_ledger" in maintenance
