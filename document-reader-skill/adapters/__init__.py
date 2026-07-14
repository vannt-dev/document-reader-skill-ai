"""Provider adapters for the multi-AI document reader."""

from .anthropic_adapter import AnthropicAdapter
from .gemini_adapter import GeminiAdapter
from .openai_adapter import OpenAIAdapter

ADAPTERS = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
}


def create_adapter(provider: str, **kwargs):
    try:
        adapter_type = ADAPTERS[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider {provider!r}; choose from {sorted(ADAPTERS)}") from exc
    return adapter_type(**kwargs)

