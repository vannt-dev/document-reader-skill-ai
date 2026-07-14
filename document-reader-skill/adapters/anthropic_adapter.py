"""Anthropic Messages API adapter."""

from __future__ import annotations

from typing import Any

from .base import AIResult, BaseAdapter, ProviderError


class AnthropicAdapter(BaseAdapter):
    provider = "anthropic"
    api_key_env = "ANTHROPIC_API_KEY"

    def build_request(self, model: str, system: str, user: str, max_tokens: int):
        return (
            f"{self.base_url}/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            {"model": model, "system": system, "messages": [{"role": "user", "content": user}], "max_tokens": max_tokens},
        )

    def parse_response(self, model: str, payload: dict[str, Any]) -> AIResult:
        parts = [item["text"] for item in payload.get("content", []) if item.get("type") == "text" and isinstance(item.get("text"), str)]
        if not parts:
            raise ProviderError("Anthropic response did not contain text")
        return AIResult(self.provider, model, "\n".join(parts), payload.get("id"), payload.get("usage"))

