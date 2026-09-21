"""Sending an HTTP request, and nothing else.

Isolated behind a protocol so the whole model layer can be exercised in tests with
no network and no credentials — which is what lets the suite run on every push. The
real implementation uses the standard library, so calling a model adds no dependency.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Protocol

from rag_eval.hashing import JSONValue


class TransportError(Exception):
    """The request could not be completed at all — no response was received."""


class Transport(Protocol):
    """Performs one HTTP request and returns the status and decoded body."""

    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, JSONValue]:
        """Fetch ``url`` and return ``(status_code, decoded_body)``."""
        ...

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: JSONValue,
        timeout: float,
    ) -> tuple[int, JSONValue]:
        """Send ``payload`` as JSON and return ``(status_code, decoded_body)``."""
        ...


class HttpTransport:
    """The real transport, over the standard library."""

    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, JSONValue]:
        """Fetch ``url`` and return ``(status_code, decoded_body)``."""
        return self._send(urllib.request.Request(url, headers=dict(headers), method="GET"), timeout)

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: JSONValue,
        timeout: float,
    ) -> tuple[int, JSONValue]:
        """Send ``payload`` as JSON and return ``(status_code, decoded_body)``.

        An HTTP error status is returned rather than raised, because the caller
        decides which statuses are worth retrying. Only a failure to get any
        response at all raises.
        """
        # The URL is built from our own base URL, not from user input.
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **dict(headers)},
            method="POST",
        )
        return self._send(request, timeout)

    def _send(self, request: urllib.request.Request, timeout: float) -> tuple[int, JSONValue]:
        """Send a prepared request, returning error statuses rather than raising them."""
        url = request.full_url
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body: JSONValue = json.loads(response.read().decode("utf-8"))
                return int(response.status), body
        except urllib.error.HTTPError as exc:
            try:
                detail: JSONValue = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                detail = {"error": exc.reason}
            return int(exc.code), detail
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"{url} could not be reached: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise TransportError(f"{url} returned a body that is not JSON: {exc}") from exc
