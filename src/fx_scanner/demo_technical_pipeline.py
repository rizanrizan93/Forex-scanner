from __future__ import annotations

from .demo_trade_plan_geometry import install_demo_trade_plan_geometry_patch


def main() -> int:
    install_demo_trade_plan_geometry_patch()
    from .cli import main as cli_main

    return int(cli_main())


if __name__ == "__main__":
    raise SystemExit(main())
