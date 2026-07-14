"""OpenAI Responses API adapter."""

from __future__ import annotations

from typing import Any

from .base import AIResult, BaseAdapter, ProviderError


class OpenAIAdapter(BaseAdapter):
    provider = "openai"
    api_key_env = "OPENAI_API_KEY"

    def build_request(self, model: str, system: str, user: str, max_tokens: int):
        return (
            f"{self.base_url}/responses",
            {"Authorization": f"Bearer {self.api_key}"},
            {"model": model, "instructions": system, "input": user, "max_output_tokens": max_tokens},
        )

    def parse_response(self, model: str, payload: dict[str, Any]) -> AIResult:
        parts = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    parts.append(content["text"])
        if not parts:
            raise ProviderError("OpenAI response did not contain output text")
        return AIResult(self.provider, model, "\n".join(parts), payload.get("id"), payload.get("usage"))

