from __future__ import annotations

from dataclasses import replace

from . import demo_technical_producer as base

_ORIGINAL_LOAD_PROJECT_CONFIG = base.load_project_config


def _load_xau_only_config(root=None):
    cfg = _ORIGINAL_LOAD_PROJECT_CONFIG(root)
    pair = cfg.pair_map.get("XAUUSD")
    if pair is None:
        raise SystemExit("XAUUSD_NOT_CONFIGURED")
    return replace(cfg, pairs=(pair,))


def run() -> int:
    """Run discovery on XAUUSD only; IMPULSE_RETEST_V2 remains the sole strategy authority."""
    base.load_project_config = _load_xau_only_config
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())
