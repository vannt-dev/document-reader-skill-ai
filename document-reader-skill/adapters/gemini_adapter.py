"""Google Gemini generateContent API adapter."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .base import AIResult, BaseAdapter, ProviderError


class GeminiAdapter(BaseAdapter):
    provider = "gemini"
    api_key_env = "GEMINI_API_KEY"

    def build_request(self, model: str, system: str, user: str, max_tokens: int):
        safe_model = quote(model, safe="-._")
        return (
            f"{self.base_url}/v1beta/models/{safe_model}:generateContent",
            {"x-goog-api-key": self.api_key},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
        )

    def parse_response(self, model: str, payload: dict[str, Any]) -> AIResult:
        parts = []
        for candidate in payload.get("candidates", []):
            for item in candidate.get("content", {}).get("parts", []):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
        if not parts:
            reason = payload.get("promptFeedback", {}).get("blockReason")
            suffix = f" (blocked: {reason})" if reason else ""
            raise ProviderError(f"Gemini response did not contain text{suffix}")
        return AIResult(self.provider, model, "\n".join(parts), payload.get("responseId"), payload.get("usageMetadata"))

