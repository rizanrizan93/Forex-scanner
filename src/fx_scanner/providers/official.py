from __future__ import annotations

import calendar
import csv
import io
import json
from html.parser import HTMLParser
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
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


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


class FredCsvProvider:
    """Keyless FRED graph CSV adapter for exact single series."""

    name = "FEDERAL_RESERVE_FRED"

    def __init__(
        self,
        transport,
        *,
        base_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv",
        allowed_host: str = "fred.stlouisfed.org",
        default_max_age_seconds: float = 259200,
        clock=lambda: datetime.now(tz=UTC),
    ):
        self.transport = transport
        self.base_url = base_url
        self.allowed_host = allowed_host
        self.default_max_age_seconds = float(default_max_age_seconds)
        self.clock = clock


    def fetch_numeric(
        self,
        series: str,
        *,
        max_age_seconds: float | None = None,
    ) -> ProviderResult[NumericObservation]:
        if not series.strip() or any(x in series for x in (",", "+", "*", "/", " ")):
            return ProviderResult(
                ProviderStatus.INVALID,
                None,
                Provenance(self.name, self.base_url, series, True),
                None,
                ProviderErrorCategory.CONTRACT,
                "FRED numeric provider requires one exact series ID",
            )
        url = f"{self.base_url}?{urlencode({'id': series})}"
        provenance = Provenance(self.name, url, series, True)
        try:
            response = self.transport.get(
                url,
                allowed_host=self.allowed_host,
                headers={"Accept": "text/csv"},
            )
            if response.status_code != 200:
                return _failure(self.name, url, series, ProviderErrorCategory.HTTP, f"HTTP_{response.status_code}")
            rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8-sig"))))
            parsed: list[tuple[datetime, float]] = []
            for row in rows:
                raw_date = row.get("observation_date") or row.get("DATE") or row.get("date")
                raw_value = row.get(series)
                if not raw_date or raw_value in (None, "", "."):
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
                    ProviderErrorCategory.NONE,
                    "FRED response contained no numeric observations",
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
            return ProviderResult(
                ProviderStatus.STALE if freshness.stale else ProviderStatus.AVAILABLE,
                observation,
                provenance,
                freshness,
            )
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


class RbaCashRateProvider:
    name = "RBA_CASH_RATE"

    def __init__(
        self,
        transport,
        *,
        base_url: str = "https://www.rba.gov.au/statistics/cash-rate/",
        allowed_host: str = "www.rba.gov.au",
        default_max_age_seconds: float = 3888000,
        clock=lambda: datetime.now(tz=UTC),
    ):
        self.transport = transport
        self.base_url = base_url
        self.allowed_host = allowed_host
        self.default_max_age_seconds = float(default_max_age_seconds)
        self.clock = clock

    def fetch_numeric(
        self,
        series: str,
        *,
        max_age_seconds: float | None = None,
    ) -> ProviderResult[NumericObservation]:
        if series != "CASH_RATE_TARGET":
            return ProviderResult(
                ProviderStatus.INVALID,
                None,
                Provenance(self.name, self.base_url, series, True),
                None,
                ProviderErrorCategory.CONTRACT,
                "RBA cash-rate provider supports CASH_RATE_TARGET only",
            )
        provenance = Provenance(self.name, self.base_url, series, True)
        try:
            response = self.transport.get(
                self.base_url,
                allowed_host=self.allowed_host,
                headers={"Accept": "text/html"},
            )
            if response.status_code != 200:
                return _failure(self.name, self.base_url, series, ProviderErrorCategory.HTTP, f"HTTP_{response.status_code}")
            parser = _TableParser()
            parser.feed(response.body.decode("utf-8", errors="strict"))
            parsed: list[tuple[datetime, float]] = []
            for row in parser.rows:
                if len(row) < 3:
                    continue
                try:
                    observed_at = datetime.strptime(row[0], "%d %b %Y").replace(tzinfo=UTC)
                    value = float(row[2].replace("%", "").strip())
                except (ValueError, TypeError):
                    continue
                parsed.append((observed_at, value))
            parsed.sort(key=lambda x: x[0])
            if not parsed:
                return ProviderResult(
                    ProviderStatus.MISSING,
                    None,
                    provenance,
                    None,
                    ProviderErrorCategory.NONE,
                    "RBA page contained no cash-rate decision rows",
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
            return ProviderResult(
                ProviderStatus.STALE if freshness.stale else ProviderStatus.AVAILABLE,
                observation,
                provenance,
                freshness,
            )
        except HttpTransportError as exc:
            message = str(exc)
            category = (
                ProviderErrorCategory.TIMEOUT if "TIMEOUT" in message
                else ProviderErrorCategory.HTTP if message.startswith("HTTP_")
                else ProviderErrorCategory.NETWORK
            )
            return _failure(self.name, self.base_url, series, category, message)
        except Exception as exc:
            return _failure(self.name, self.base_url, series, ProviderErrorCategory.PARSE, str(exc))


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


class OecdSdmxCsvProvider:
    """Official OECD SDMX CSV provider for one exact macro series."""

    name = "OECD_SDMX"

    def __init__(
        self,
        transport,
        *,
        base_url: str = "https://sdmx.oecd.org/public/rest/data",
        allowed_host: str = "sdmx.oecd.org",
        default_max_age_seconds: float = 10368000,
        history_days: int = 550,
        clock=lambda: datetime.now(tz=UTC),
    ):
        if history_days < 120 or history_days > 1095:
            raise ValueError("OECD history_days must be in [120,1095]")
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.allowed_host = allowed_host
        self.default_max_age_seconds = float(default_max_age_seconds)
        self.history_days = int(history_days)
        self.clock = clock

    @staticmethod
    def _valid_dataset(value: str) -> bool:
        return bool(value) and value.startswith("OECD.") and all(
            ch.isalnum() or ch in "._,@-" for ch in value
        )

    @staticmethod
    def _valid_key(value: str) -> bool:
        return bool(value) and all(ch.isalnum() or ch in "._-" for ch in value)

    def fetch_numeric_batch(
        self,
        series_by_label: Mapping[str, str],
        *,
        max_age_seconds: float | None = None,
    ) -> dict[str, ProviderResult[NumericObservation]]:
        """Fetch many exact OECD series in grouped SDMX requests.

        Series are grouped by dataset and all dimensions except REF_AREA.
        This keeps request volume well below OECD download limits while each
        returned ProviderResult retains exact per-series provenance semantics.
        """
        requested: dict[str, tuple[str, str, str, str]] = {}
        invalid: dict[str, ProviderResult[NumericObservation]] = {}
        for label, raw_series in series_by_label.items():
            series = str(raw_series)
            parts = series.split("|")
            if len(parts) != 2:
                invalid[label] = ProviderResult(
                    ProviderStatus.INVALID,
                    None,
                    Provenance(self.name, self.base_url, series, True),
                    None,
                    ProviderErrorCategory.CONTRACT,
                    "OECD numeric provider requires dataset|exact_key",
                )
                continue
            dataset, key = (part.strip() for part in parts)
            area, sep, suffix = key.partition(".")
            if (
                not self._valid_dataset(dataset)
                or not self._valid_key(key)
                or not sep
                or not area
                or not suffix
            ):
                invalid[label] = ProviderResult(
                    ProviderStatus.INVALID,
                    None,
                    Provenance(self.name, self.base_url, series, True),
                    None,
                    ProviderErrorCategory.CONTRACT,
                    "OECD dataset/key contract is invalid",
                )
                continue
            requested[label] = (series, dataset, area, suffix)

        now = self.clock()
        if now.tzinfo is None:
            return {
                label: _failure(
                    self.name,
                    self.base_url,
                    requested[label][0],
                    ProviderErrorCategory.CONTRACT,
                    "OECD provider clock must be timezone-aware",
                )
                for label in requested
            } | invalid
        now = now.astimezone(UTC)
        start = (now.date() - timedelta(days=self.history_days)).strftime("%Y-%m")

        groups: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
        for label, (series, dataset, area, suffix) in requested.items():
            groups.setdefault((dataset, suffix), []).append((label, series, area))

        output: dict[str, ProviderResult[NumericObservation]] = dict(invalid)

        for (dataset, suffix), members in groups.items():
            areas = sorted({area for _, _, area in members})
            dataset_path = quote(dataset, safe=",@")
            area_path = "+".join(quote(area, safe="") for area in areas)
            suffix_path = quote(suffix, safe="._-")
            key_path = f"{area_path}.{suffix_path}"
            query = urlencode(
                {
                    "startPeriod": start,
                    "dimensionAtObservation": "AllDimensions",
                    "format": "csvfile",
                }
            )
            url = f"{self.base_url}/{dataset_path}/{key_path}?{query}"

            try:
                response = self.transport.get(
                    url,
                    allowed_host=self.allowed_host,
                    headers={"Accept": "text/csv"},
                )
                if response.status_code != 200:
                    raise HttpTransportError(f"HTTP_{response.status_code}")

                rows = csv.DictReader(io.StringIO(response.body.decode("utf-8-sig")))
                by_area_time: dict[str, dict[datetime, set[float]]] = {}
                for row in rows:
                    raw_area = row.get("REF_AREA") or row.get("ref_area")
                    raw_time = row.get("TIME_PERIOD") or row.get("time_period")
                    raw_value = row.get("OBS_VALUE") or row.get("obs_value")
                    if (
                        not raw_area
                        or not raw_time
                        or raw_value in (None, "", ".", "..", "NA")
                    ):
                        continue
                    area = str(raw_area).strip()
                    if area not in areas:
                        continue
                    try:
                        ts = _period_to_utc(str(raw_time))
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    by_area_time.setdefault(area, {}).setdefault(ts, set()).add(value)

                for label, series, area in members:
                    provenance = Provenance(self.name, url, series, True)
                    by_time = by_area_time.get(area, {})
                    if not by_time:
                        output[label] = ProviderResult(
                            ProviderStatus.MISSING,
                            None,
                            provenance,
                            None,
                            ProviderErrorCategory.PARSE,
                            "OECD response contained no numeric observations for reference area",
                        )
                        continue
                    if any(len(values) != 1 for values in by_time.values()):
                        output[label] = ProviderResult(
                            ProviderStatus.INVALID,
                            None,
                            provenance,
                            None,
                            ProviderErrorCategory.CONTRACT,
                            "OECD exact series resolved to conflicting observations",
                        )
                        continue

                    parsed = sorted(
                        (ts, next(iter(values))) for ts, values in by_time.items()
                    )
                    observed_at, value = parsed[-1]
                    previous_at = parsed[-2][0] if len(parsed) >= 2 else None
                    previous_value = parsed[-2][1] if len(parsed) >= 2 else None
                    observation = NumericObservation(
                        series,
                        value,
                        observed_at,
                        previous_value,
                        previous_at,
                    )
                    freshness = Freshness.evaluate(
                        observed_at,
                        now,
                        max_age_seconds=max_age_seconds
                        or self.default_max_age_seconds,
                    )
                    status = (
                        ProviderStatus.STALE
                        if freshness.stale
                        else ProviderStatus.AVAILABLE
                    )
                    output[label] = ProviderResult(
                        status,
                        observation,
                        provenance,
                        freshness,
                    )
            except HttpTransportError as exc:
                message = str(exc)
                category = (
                    ProviderErrorCategory.TIMEOUT
                    if "TIMEOUT" in message
                    else ProviderErrorCategory.HTTP
                    if message.startswith("HTTP_")
                    else ProviderErrorCategory.NETWORK
                )
                for label, series, _area in members:
                    output[label] = _failure(
                        self.name,
                        url,
                        series,
                        category,
                        message,
                    )
            except Exception as exc:
                for label, series, _area in members:
                    output[label] = _failure(
                        self.name,
                        url,
                        series,
                        ProviderErrorCategory.PARSE,
                        str(exc),
                    )

        return output

    def fetch_numeric(
        self,
        series: str,
        *,
        max_age_seconds: float | None = None,
    ) -> ProviderResult[NumericObservation]:
        parts = str(series).split("|")
        if len(parts) != 2:
            return ProviderResult(
                ProviderStatus.INVALID,
                None,
                Provenance(self.name, self.base_url, str(series), True),
                None,
                ProviderErrorCategory.CONTRACT,
                "OECD numeric provider requires dataset|exact_key",
            )
        dataset, key = (part.strip() for part in parts)
        if not self._valid_dataset(dataset) or not self._valid_key(key):
            return ProviderResult(
                ProviderStatus.INVALID,
                None,
                Provenance(self.name, self.base_url, str(series), True),
                None,
                ProviderErrorCategory.CONTRACT,
                "OECD dataset/key contract is invalid",
            )

        now = self.clock()
        if now.tzinfo is None:
            return _failure(
                self.name,
                self.base_url,
                str(series),
                ProviderErrorCategory.CONTRACT,
                "OECD provider clock must be timezone-aware",
            )
        now = now.astimezone(UTC)
        start = (now.date() - timedelta(days=self.history_days)).strftime("%Y-%m")
        dataset_path = quote(dataset, safe=",@")
        key_path = quote(key, safe="._-")
        query = urlencode(
            {
                "startPeriod": start,
                "dimensionAtObservation": "AllDimensions",
                "format": "csvfile",
            }
        )
        url = f"{self.base_url}/{dataset_path}/{key_path}?{query}"
        provenance = Provenance(self.name, url, str(series), True)
        try:
            response = self.transport.get(
                url,
                allowed_host=self.allowed_host,
                headers={"Accept": "text/csv"},
            )
            if response.status_code != 200:
                return _failure(
                    self.name,
                    url,
                    str(series),
                    ProviderErrorCategory.HTTP,
                    f"HTTP_{response.status_code}",
                )
            rows = csv.DictReader(io.StringIO(response.body.decode("utf-8-sig")))
            by_time: dict[datetime, set[float]] = {}
            for row in rows:
                raw_time = row.get("TIME_PERIOD") or row.get("time_period")
                raw_value = row.get("OBS_VALUE") or row.get("obs_value")
                if not raw_time or raw_value in (None, "", ".", "..", "NA"):
                    continue
                try:
                    ts = _period_to_utc(str(raw_time))
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                by_time.setdefault(ts, set()).add(value)

            if not by_time:
                return ProviderResult(
                    ProviderStatus.MISSING,
                    None,
                    provenance,
                    None,
                    ProviderErrorCategory.PARSE,
                    "OECD response contained no numeric observations",
                )
            if any(len(values) != 1 for values in by_time.values()):
                return ProviderResult(
                    ProviderStatus.INVALID,
                    None,
                    provenance,
                    None,
                    ProviderErrorCategory.CONTRACT,
                    "OECD exact series resolved to conflicting observations",
                )

            parsed = sorted((ts, next(iter(values))) for ts, values in by_time.items())
            observed_at, value = parsed[-1]
            previous_at = parsed[-2][0] if len(parsed) >= 2 else None
            previous_value = parsed[-2][1] if len(parsed) >= 2 else None
            observation = NumericObservation(
                str(series),
                value,
                observed_at,
                previous_value,
                previous_at,
            )
            freshness = Freshness.evaluate(
                observed_at,
                now,
                max_age_seconds=max_age_seconds or self.default_max_age_seconds,
            )
            status = ProviderStatus.STALE if freshness.stale else ProviderStatus.AVAILABLE
            return ProviderResult(status, observation, provenance, freshness)
        except HttpTransportError as exc:
            message = str(exc)
            category = (
                ProviderErrorCategory.TIMEOUT
                if "TIMEOUT" in message
                else ProviderErrorCategory.HTTP
                if message.startswith("HTTP_")
                else ProviderErrorCategory.NETWORK
            )
            return _failure(self.name, url, str(series), category, message)
        except Exception as exc:
            return _failure(
                self.name,
                url,
                str(series),
                ProviderErrorCategory.PARSE,
                str(exc),
            )
