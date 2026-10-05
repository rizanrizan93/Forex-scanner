from __future__ import annotations
"""V389 research-only liquidity-sweep reversal discovery.

Purpose: test a materially different entry hypothesis after V388 showed that
exit management cannot rescue V387 admission quality.

Discovery/calibration is 2025 only. 2026 is holdout and MUST NOT participate
in threshold selection. This module is intentionally execution-authority-free.

Signal concept:
1. price reaches a frozen C4 target/main reversal zone,
2. extends through the zone/target (liquidity sweep),
3. closes/reclaims back toward the pre-sweep side,
4. subsequent micro bar confirms displacement away from the swept extreme,
5. structural invalidation stays beyond the sweep extreme,
6. terminal objective remains the opposing structural destination.

The full M1 implementation is built by adapting V387's causal replay; this file
defines the predeclared discovery grid and promotion contract.
"""
import json
from pathlib import Path

SCHEMA="XAU_V389_LIQUIDITY_SWEEP_REVERSAL_V1"
C4_SELECTOR="M15_LB12_B020_FROZEN"
# Small economically interpretable grid; never expanded after looking at 2026.
DISCOVERY_2025_GRID=[
 {"name":"SWEEP_R025_RECLAIM_M5","min_sweep_r":0.25,"confirm_tf":"M5","min_displacement_r":0.15},
 {"name":"SWEEP_R050_RECLAIM_M5","min_sweep_r":0.50,"confirm_tf":"M5","min_displacement_r":0.15},
 {"name":"SWEEP_R025_RECLAIM_M15","min_sweep_r":0.25,"confirm_tf":"M15","min_displacement_r":0.20},
]
PROMOTION={
 "selection_period":"2025_ONLY",
 "holdout_period":"2026_BLIND",
 "target_pf_after_cost":1.50,
 "minimum_pf_after_cost":1.00,
 "requires_positive_expectancy":True,
 "requires_structural_sl":True,
 "requires_opposing_terminal_tp":True,
 "requires_mae_mfe":True,
 "requires_realistic_cost_model":True,
 "requires_walk_forward_if_candidate_passes":True,
 "live_execution_enabled":False,
 "execution_authority":False,
}
def manifest(path:Path):
 p={"schema":SCHEMA,"c4_selector":C4_SELECTOR,"discovery_grid":DISCOVERY_2025_GRID,
    "promotion_contract":PROMOTION,
    "anti_overfit":["No 2026 threshold tuning","No tiny-sample winner promotion",
      "Do not change C4 selector during V389","Reject if edge disappears after costs"],
    "next_if_fail":"V390_REACCELERATION_CONTINUATION"}
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(p,indent=2,sort_keys=True)+"\n")
if __name__=="__main__":
 import sys; manifest(Path(sys.argv[1] if len(sys.argv)>1 else "artifacts/xau-v389-manifest.json"))
