from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from math import isfinite

from ..exceptions import DataContractError


@dataclass(frozen=True, slots=True)
class SymbolTradeSpec:
    tick_size: float
    tick_value_loss: float
    volume_min: float
    volume_max: float
    volume_step: float
    contract_size: float | None = None

    def __post_init__(self) -> None:
        vals = (self.tick_size, self.tick_value_loss, self.volume_min, self.volume_max, self.volume_step)
        if not all(isfinite(x) and x > 0 for x in vals):
            raise DataContractError("trade spec values must be positive finite numbers")
        if self.contract_size is not None and (not isfinite(self.contract_size) or self.contract_size <= 0):
            raise DataContractError("contract_size must be positive when supplied")
        if self.volume_max < self.volume_min:
            raise DataContractError("volume_max must be >= volume_min")


def _floor_to_step(value: float, step: float) -> float:
    v = Decimal(str(value))
    s = Decimal(str(step))
    units = (v / s).to_integral_value(rounding=ROUND_FLOOR)
    return float(units * s)


def size_position(
    *,
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    spec: SymbolTradeSpec,
) -> float:
    """Calculate volume from monetary risk using broker symbol tick economics.

    risk_pct is expressed in percentage points, e.g. 0.25 for 0.25%.
    """
    if not isfinite(equity) or equity <= 0:
        raise DataContractError("equity must be positive")
    if not 0 < risk_pct <= 1.0:
        raise DataContractError("risk_pct must be >0 and <=1.0 percentage point per trade")
    entry_d = Decimal(str(entry_price))
    stop_d = Decimal(str(stop_loss))
    distance = abs(entry_d - stop_d)
    if distance <= 0:
        raise DataContractError("entry and stop must differ")

    ticks_to_stop = distance / Decimal(str(spec.tick_size))
    risk_per_lot = ticks_to_stop * Decimal(str(spec.tick_value_loss))
    if risk_per_lot <= 0:
        raise DataContractError("invalid broker tick economics")
    risk_capital = Decimal(str(equity)) * Decimal(str(risk_pct)) / Decimal("100")
    raw = risk_capital / risk_per_lot
    floored = _floor_to_step(float(raw), spec.volume_step)
    if floored < spec.volume_min:
        raise DataContractError("calculated position is below broker minimum volume")
    return min(floored, spec.volume_max)
