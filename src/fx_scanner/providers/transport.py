from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..exceptions import FXScannerError


class HttpTransportError(FXScannerError):
    pass


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    final_url: str


class UrllibHttpTransport:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_048_576,
        user_agent: str = "FX-Institutional-Scanner/0.7",
    ):
        if timeout_seconds <= 0 or max_response_bytes <= 0:
            raise ValueError("HTTP transport limits must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)
        self.user_agent = str(user_agent)

    @staticmethod
    def _validate_url(url: str, allowed_host: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise HttpTransportError("provider URL must use HTTPS")
        if parsed.hostname != allowed_host:
            raise HttpTransportError(
                f"provider host mismatch: {parsed.hostname!r} != {allowed_host!r}"
            )
        if parsed.username or parsed.password:
            raise HttpTransportError("provider URL credentials are forbidden")

    def get(
        self,
        url: str,
        *,
        allowed_host: str,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        self._validate_url(url, allowed_host)
        request_headers = {"User-Agent": self.user_agent, **dict(headers or {})}
        req = Request(url, headers=request_headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                final_url = str(response.geturl())
                self._validate_url(final_url, allowed_host)
                body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise HttpTransportError("provider response exceeds size limit")
                return HttpResponse(
                    status_code=int(response.status),
                    body=body,
                    headers={str(k).lower(): str(v) for k, v in response.headers.items()},
                    final_url=final_url,
                )
        except HTTPError as exc:
            raise HttpTransportError(f"HTTP_{exc.code}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise HttpTransportError(f"NETWORK:{reason}") from exc
        except TimeoutError as exc:
            raise HttpTransportError("TIMEOUT") from exc
