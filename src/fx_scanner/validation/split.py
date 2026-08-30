from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ..exceptions import DataContractError
from .backtest import TradeIntent


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    train: tuple[TradeIntent, ...]
    validation: tuple[TradeIntent, ...]
    oos: tuple[TradeIntent, ...]
    train_end: datetime | None
    validation_end: datetime | None


def chronological_split(
    intents: Sequence[TradeIntent],
    *,
    train_fraction: float,
    validation_fraction: float,
    oos_fraction: float,
) -> ChronologicalSplit:
    for name, value in (
        ("train_fraction", train_fraction),
        ("validation_fraction", validation_fraction),
        ("oos_fraction", oos_fraction),
    ):
        if not 0 < value < 1:
            raise DataContractError(f"{name} must be in (0,1)")
    if abs(train_fraction + validation_fraction + oos_fraction - 1.0) > 1e-9:
        raise DataContractError("dataset split fractions must sum to 1")

    ordered = sorted(intents, key=lambda x: (x.signal_at, x.symbol, x.trade_id))
    if not ordered:
        return ChronologicalSplit((), (), (), None, None)

    unique_times = sorted({x.signal_at for x in ordered})
    if len(unique_times) < 3:
        raise DataContractError("chronological split requires at least three distinct signal times")

    n_times = len(unique_times)
    train_idx = max(1, min(n_times - 2, int(n_times * train_fraction)))
    validation_idx = max(
        train_idx + 1,
        min(n_times - 1, int(n_times * (train_fraction + validation_fraction))),
    )
    train_cutoff = unique_times[train_idx]
    validation_cutoff = unique_times[validation_idx]

    train = tuple(x for x in ordered if x.signal_at < train_cutoff)
    validation = tuple(
        x for x in ordered
        if train_cutoff <= x.signal_at < validation_cutoff
    )
    oos = tuple(x for x in ordered if x.signal_at >= validation_cutoff)
    if not train or not validation or not oos:
        raise DataContractError("chronological split produced an empty partition")

    return ChronologicalSplit(
        train,
        validation,
        oos,
        max(x.signal_at for x in train),
        max(x.signal_at for x in validation),
    )
