"""Shared HTTP and response contracts for AI provider adapters."""

from __future__ import annotations

import json
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class AIResult:
    provider: str
    model: str
    text: str
    response_id: str | None = None
    usage: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "text": self.text,
            "response_id": self.response_id,
            "usage": self.usage or {},
        }


class ProviderError(RuntimeError):
    """Raised for safe, user-facing provider failures."""


class BaseAdapter(ABC):
    provider: str
    api_key_env: str

    def __init__(self, api_key: str, base_url: str, timeout: float = 60.0):
        if not api_key:
            raise ValueError(f"Missing API key ({self.api_key_env})")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @abstractmethod
    def build_request(self, model: str, system: str, user: str, max_tokens: int) -> tuple[str, dict[str, str], dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def parse_response(self, model: str, payload: dict[str, Any]) -> AIResult:
        raise NotImplementedError

    def generate(self, model: str, system: str, user: str, max_tokens: int) -> AIResult:
        url, headers, payload = self.build_request(model, system, user, max_tokens)
        response = post_json(url, headers, payload, self.timeout)
        return self.parse_response(model, response)


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ProviderError(f"Provider returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise ProviderError(f"Could not reach provider: {exc.reason}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("Provider returned an invalid JSON response") from exc

