from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Mapping, Sequence

from ..exceptions import CollectorUnavailable


@dataclass(frozen=True, slots=True)
class ResolvedSymbol:
    canonical: str
    broker_symbol: str
    contract_size: float


class MT5SymbolResolver:
    """Resolve canonical FX symbols to the execution broker's MT5 symbols.

    Explicit mappings win. Otherwise candidates are tested against the connected
    terminal and filtered by expected contract size. Ambiguity fails closed.
    """

    def __init__(
        self,
        gateway,
        *,
        explicit_map: Mapping[str, str] | None = None,
        suffix_candidates: Sequence[str] = ("", "c"),
        expected_contract_size: float | None = 1000.0,
        contract_rel_tol: float = 1e-9,
    ):
        self.gateway = gateway
        self.explicit_map = {str(k).upper(): str(v) for k, v in (explicit_map or {}).items()}
        self.suffix_candidates = tuple(str(x) for x in suffix_candidates)
        self.expected_contract_size = expected_contract_size
        self.contract_rel_tol = float(contract_rel_tol)
        self._cache: dict[str, ResolvedSymbol] = {}

    def _valid_contract(self, symbol: str) -> tuple[bool, float]:
        size = float(self.gateway.symbol_contract_size(symbol))
        if self.expected_contract_size is None:
            return True, size
        return isclose(size, float(self.expected_contract_size), rel_tol=self.contract_rel_tol, abs_tol=1e-9), size

    def _checked(self, canonical: str, candidate: str) -> ResolvedSymbol:
        if not self.gateway.symbol_available(candidate):
            raise CollectorUnavailable(f"MT5_SYMBOL_UNAVAILABLE:{canonical}:{candidate}")
        ok, size = self._valid_contract(candidate)
        if not ok:
            raise CollectorUnavailable(
                f"MT5_CONTRACT_SIZE_MISMATCH:{candidate}:{size}!={self.expected_contract_size}"
            )
        self.gateway.ensure_symbol(candidate)
        return ResolvedSymbol(canonical, candidate, size)

    def resolve(self, canonical: str) -> ResolvedSymbol:
        canonical = str(canonical).upper().strip()
        if not canonical:
            raise CollectorUnavailable("MT5_EMPTY_CANONICAL_SYMBOL")
        cached = self._cache.get(canonical)
        if cached is not None:
            return cached

        explicit = self.explicit_map.get(canonical)
        if explicit:
            resolved = self._checked(canonical, explicit)
            self._cache[canonical] = resolved
            return resolved

        valid: list[ResolvedSymbol] = []
        seen: set[str] = set()
        for suffix in self.suffix_candidates:
            candidate = f"{canonical}{suffix}"
            if candidate in seen:
                continue
            seen.add(candidate)
            if not self.gateway.symbol_available(candidate):
                continue
            ok, size = self._valid_contract(candidate)
            if ok:
                valid.append(ResolvedSymbol(canonical, candidate, size))

        if not valid:
            raise CollectorUnavailable(
                f"MT5_CENT_SYMBOL_NOT_FOUND:{canonical}:expected_contract={self.expected_contract_size}"
            )
        if len(valid) > 1:
            names = ",".join(x.broker_symbol for x in valid)
            raise CollectorUnavailable(f"MT5_SYMBOL_AMBIGUOUS:{canonical}:{names}")

        resolved = valid[0]
        self.gateway.ensure_symbol(resolved.broker_symbol)
        self._cache[canonical] = resolved
        return resolved
