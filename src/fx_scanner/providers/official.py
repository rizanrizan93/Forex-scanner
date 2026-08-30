from __future__ import annotations

import calendar
import csv
import io
import json
from datetime import date, datetime, time, timezone
from typing import Any
from urllib.parse import quote, urlencode

from .semantics import (
    Freshness,
    NumericObservation,
    ProviderErrorCategory,
    ProviderResult,
    ProviderStatus,
    Provenance,
)
from .transport import HttpTransportError

UTC = timezone.utc


def _period_to_utc(value: str) -> datetime:
    raw = str(value).strip()
    try:
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            parsed = date.fromisoformat(raw[:10])
            return datetime.combine(parsed, time.min, tzinfo=UTC)
        if len(raw) == 7 and raw[4:6] == "-Q":
            year = int(raw[:4])
            quarter = int(raw[-1])
            if quarter not in (1, 2, 3, 4):
                raise ValueError("quarter out of range")
            month = quarter * 3
            day = calendar.monthrange(year, month)[1]
            return datetime(year, month, day, tzinfo=UTC)
        if len(raw) == 7 and raw[4] == "-":
            year, month = map(int, raw.split("-"))
            day = calendar.monthrange(year, month)[1]
            return datetime(year, month, day, tzinfo=UTC)
        if len(raw) == 4:
            return datetime(int(raw), 12, 31, tzinfo=UTC)
    except (ValueError, TypeError):
        pass
    raise ValueError(f"unsupported observation period: {raw}")


def _failure(provider: str, url: str, series: str, category, message: str):
    return ProviderResult(
        status=ProviderStatus.ERROR,
        value=None,
        provenance=Provenance(provider, url, series, True),
        freshness=None,
        error_category=category,
        message=message,
    )


class EcbDataPortalProvider:
    name = "ECB_DATA_PORTAL"

    def __init__(
        self,
        transport,
        *,
        base_url: str = "https://data-api.ecb.europa.eu/service/data",
        allowed_host: str = "data-api.ecb.europa.eu",
        default_max_age_seconds: float = 172800,
        clock=lambda: datetime.now(tz=UTC),
    ):
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.allowed_host = allowed_host
        self.default_max_age_seconds = float(default_max_age_seconds)
        self.clock = clock

    def fetch_numeric(
        self,
        series: str,
        *,
        max_age_seconds: float | None = None,
    ) -> ProviderResult[NumericObservation]:
        if "+" in series or "*" in series or ".." in series:
            return ProviderResult(
                ProviderStatus.INVALID,
                None,
                Provenance(self.name, self.base_url, series, True),
                None,
                ProviderErrorCategory.CONTRACT,
                "ECB numeric provider requires one exact series",
            )
        encoded = "/".join(quote(part, safe=".,") for part in series.split("/"))
        query = urlencode({"format": "csvdata", "lastNObservations": 2})
        url = f"{self.base_url}/{encoded}?{query}"
        provenance = Provenance(self.name, url, series, True)
        try:
            response = self.transport.get(
                url,
                allowed_host=self.allowed_host,
                headers={"Accept": "text/csv"},
            )
            if response.status_code != 200:
                return _failure(self.name, url, series, ProviderErrorCategory.HTTP, f"HTTP_{response.status_code}")
            text = response.body.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            parsed: list[tuple[datetime, float]] = []
            for row in rows:
                raw_time = row.get("TIME_PERIOD") or row.get("time_period")
                raw_value = row.get("OBS_VALUE") or row.get("obs_value")
                if not raw_time or raw_value in (None, "", "."):
                    continue
                try:
                    parsed.append((_period_to_utc(raw_time), float(raw_value)))
                except (ValueError, TypeError):
                    continue
            parsed.sort(key=lambda x: x[0])
            if not parsed:
                return ProviderResult(
                    ProviderStatus.MISSING,
                    None,
                    provenance,
                    None,
                    ProviderErrorCategory.PARSE,
                    "ECB response contained no numeric observations",
                )
            observed_at, value = parsed[-1]
            previous_value = parsed[-2][1] if len(parsed) >= 2 else None
            previous_at = parsed[-2][0] if len(parsed) >= 2 else None
            observation = NumericObservation(
                series,
                value,
                observed_at,
                previous_value,
                previous_at,
            )
            freshness = Freshness.evaluate(
                observed_at,
                self.clock(),
                max_age_seconds=max_age_seconds or self.default_max_age_seconds,
            )
            status = ProviderStatus.STALE if freshness.stale else ProviderStatus.AVAILABLE
            return ProviderResult(status, observation, provenance, freshness)
        except HttpTransportError as exc:
            message = str(exc)
            category = (
                ProviderErrorCategory.TIMEOUT if "TIMEOUT" in message
                else ProviderErrorCategory.HTTP if message.startswith("HTTP_")
                else ProviderErrorCategory.NETWORK
            )
            return _failure(self.name, url, series, category, message)
        except Exception as exc:
            return _failure(self.name, url, series, ProviderErrorCategory.PARSE, str(exc))


class BankOfCanadaValetProvider:
    name = "BANK_OF_CANADA_VALET"

    def __init__(
        self,
        transport,
        *,
        base_url: str = "https://www.bankofcanada.ca/valet/observations",
        allowed_host: str = "www.bankofcanada.ca",
        default_max_age_seconds: float = 172800,
        clock=lambda: datetime.now(tz=UTC),
    ):
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.allowed_host = allowed_host
        self.default_max_age_seconds = float(default_max_age_seconds)
        self.clock = clock

    def fetch_numeric(
        self,
        series: str,
        *,
        max_age_seconds: float | None = None,
    ) -> ProviderResult[NumericObservation]:
        if "," in series or "+" in series or not series.strip():
            return ProviderResult(
                ProviderStatus.INVALID,
                None,
                Provenance(self.name, self.base_url, series, True),
                None,
                ProviderErrorCategory.CONTRACT,
                "BoC numeric provider requires one exact series",
            )
        encoded = quote(series, safe="")
        query = urlencode({"recent": 2})
        url = f"{self.base_url}/{encoded}/json?{query}"
        provenance = Provenance(self.name, url, series, True)
        try:
            response = self.transport.get(
                url,
                allowed_host=self.allowed_host,
                headers={"Accept": "application/json"},
            )
            if response.status_code != 200:
                return _failure(self.name, url, series, ProviderErrorCategory.HTTP, f"HTTP_{response.status_code}")
            payload: dict[str, Any] = json.loads(response.body.decode("utf-8"))
            observations = payload.get("observations") or []
            parsed: list[tuple[datetime, float]] = []
            for row in observations:
                raw_date = row.get("d")
                cell = row.get(series) or {}
                raw_value = cell.get("v") if isinstance(cell, dict) else None
                if not raw_date or raw_value in (None, "", "NA"):
                    continue
                try:
                    parsed.append((_period_to_utc(str(raw_date)), float(raw_value)))
                except (TypeError, ValueError):
                    continue
            parsed.sort(key=lambda x: x[0])
            if not parsed:
                return ProviderResult(
                    ProviderStatus.MISSING,
                    None,
                    provenance,
                    None,
                    ProviderErrorCategory.PARSE,
                    "BoC response contained no numeric observations",
                )
            observed_at, value = parsed[-1]
            previous_value = parsed[-2][1] if len(parsed) >= 2 else None
            previous_at = parsed[-2][0] if len(parsed) >= 2 else None
            observation = NumericObservation(series, value, observed_at, previous_value, previous_at)
            freshness = Freshness.evaluate(
                observed_at,
                self.clock(),
                max_age_seconds=max_age_seconds or self.default_max_age_seconds,
            )
            status = ProviderStatus.STALE if freshness.stale else ProviderStatus.AVAILABLE
            return ProviderResult(status, observation, provenance, freshness)
        except HttpTransportError as exc:
            message = str(exc)
            category = (
                ProviderErrorCategory.TIMEOUT if "TIMEOUT" in message
                else ProviderErrorCategory.HTTP if message.startswith("HTTP_")
                else ProviderErrorCategory.NETWORK
            )
            return _failure(self.name, url, series, category, message)
        except Exception as exc:
            return _failure(self.name, url, series, ProviderErrorCategory.PARSE, str(exc))
