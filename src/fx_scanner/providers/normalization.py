from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from ..exceptions import DataContractError
from .semantics import NumericObservation


@dataclass(frozen=True, slots=True)
class DeltaNormalizer:
    """Convert a current-vs-previous observation into a bounded signed score.

    A scale is domain-specific and must be explicitly configured. No previous
    observation means no score; it is never converted into neutral zero.
    """

    scale: float
    polarity: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.scale, bool) or not isfinite(float(self.scale)) or self.scale <= 0:
            raise DataContractError("normalizer scale must be positive finite")
        if isinstance(self.polarity, bool) or self.polarity not in (-1, 1):
            raise DataContractError("normalizer polarity must be -1 or 1")

    def score(self, observation: NumericObservation) -> float | None:
        if observation.previous_value is None:
            return None
        delta = (observation.value - observation.previous_value) * self.polarity
        raw = 100.0 * delta / float(self.scale)
        return max(-100.0, min(100.0, raw))


@dataclass(frozen=True, slots=True)
class LevelNormalizer:
    """Score a numeric level relative to an explicit reference and scale."""

    reference: float
    scale: float
    polarity: int = 1

    def __post_init__(self) -> None:
        for name, raw in (("reference", self.reference), ("scale", self.scale)):
            if isinstance(raw, bool) or not isfinite(float(raw)):
                raise DataContractError(f"{name} must be finite numeric")
        if self.scale <= 0:
            raise DataContractError("normalizer scale must be positive")
        if isinstance(self.polarity, bool) or self.polarity not in (-1, 1):
            raise DataContractError("normalizer polarity must be -1 or 1")

    def score(self, observation: NumericObservation) -> float:
        raw = (
            100.0
            * (observation.value - float(self.reference))
            / float(self.scale)
            * self.polarity
        )
        return max(-100.0, min(100.0, raw))
