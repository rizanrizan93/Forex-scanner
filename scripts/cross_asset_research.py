"""Run from root: PYTHONPATH=src python scripts/cross_asset_research.py DATA OUT."""

import argparse

from fx_scanner.cross_asset_research import run

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="RIZAN causal cross-asset research; no execution"
    )
    p.add_argument("data_directory")
    p.add_argument("output")
    p.add_argument("--minutes", nargs="+", type=int, default=[1, 5, 15])
    p.add_argument(
        "--events",
        help="UTC timestamp/category CSV; must have complete calendar coverage",
    )
    args = p.parse_args()
    report = run(
        args.data_directory,
        args.output,
        minutes_grid=tuple(args.minutes),
        events_path=args.events,
    )
    print(
        f"RESEARCH_ONLY candidates={len(report['candidates'])} tests={report['multiple_tests']}"
    )
