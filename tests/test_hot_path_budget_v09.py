import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from time import perf_counter

from fx_scanner.config import load_project_config
from fx_scanner.models import Bar
from fx_scanner.ranking import PairRank
from fx_scanner.strategy import scan_deep_candidates_report

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)


def test_research_validation_package_is_not_imported_by_hot_path():
    hot_files = [
        ROOT / "src" / "fx_scanner" / "strategy.py",
        ROOT / "src" / "fx_scanner" / "technical.py",
        ROOT / "src" / "fx_scanner" / "liquidity.py",
        ROOT / "src" / "fx_scanner" / "decision.py",
        ROOT / "src" / "fx_scanner" / "ranking.py",
    ]
    hot_files.extend((ROOT / "src" / "fx_scanner" / "execution").glob("*.py"))

    offenders = []
    for path in hot_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "validation" or name.startswith("fx_scanner.validation") for name in names):
                offenders.append(path.name)
    assert offenders == []


def bars(symbol, tf, count):
    seconds = {
        "D1": 86400,
        "H4": 14400,
        "H1": 3600,
        "M15": 900,
        "M5": 300,
    }[tf]
    start = AS_OF - timedelta(seconds=seconds * (count + 1))
    out = []
    for i in range(count):
        offset = ((i % 9) - 4) * 0.00015
        base = 1.1000 + offset
        close = base + (0.00012 if i % 2 == 0 else -0.00008)
        out.append(
            Bar(
                symbol,
                tf,
                start + timedelta(seconds=seconds * i),
                base,
                max(base, close) + 0.0007,
                min(base, close) - 0.0007,
                close,
                100 + (i % 7),
                0.0001,
                0.0002,
            )
        )
    return out


def rank(symbol, i):
    return PairRank(
        symbol=symbol,
        direction="LONG",
        relative_macro_edge=160 - i,
        relative_technical_edge=120 - i,
        cross_asset_edge=60,
        pair_edge=80 - i,
        absolute_edge=80 - i,
        coverage=1.0,
        missing_components=(),
        rank=i,
    )


def test_top5_deep_scan_stays_inside_cpu_target():
    cfg = load_project_config()
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD"]
    minimum = cfg.strategy["mtf"]["minimum_bars"]
    data = {
        symbol: {
            tf: bars(symbol, tf, int(minimum[tf]) + 5)
            for tf in ("D1", "H4", "H1", "M15", "M5")
        }
        for symbol in symbols
    }
    guards = {
        symbol: {name: False for name in cfg.scoring["hard_guards"]}
        for symbol in symbols
    }
    ranked = [rank(symbol, i + 1) for i, symbol in enumerate(symbols)]

    timings = []
    for _ in range(3):
        started = perf_counter()
        report = scan_deep_candidates_report(
            ranked=ranked,
            bars_by_symbol=data,
            cfg=cfg,
            as_of=AS_OF,
            external_guards_by_symbol=guards,
        )
        timings.append((perf_counter() - started) * 1000.0)
        assert len(report.selection.deep_analysis) == 5

    target = float(cfg.validation["performance_budget"]["deep_scan_top5_target_ms"])
    assert median(timings) <= target
