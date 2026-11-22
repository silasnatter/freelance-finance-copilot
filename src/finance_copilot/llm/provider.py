"""Exchangeable LLM providers (RB-06). Only local endpoints are accepted (RB-04)."""

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import urlparse

from finance_copilot.config import Settings

LLM_URL_ENV_VAR = "FINANCE_COPILOT_LLM_URL"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class LlmConfigurationError(ValueError):
    """The configured provider is not allowed or not available."""


class LlmUnavailableError(RuntimeError):
    """The model cannot be reached or did not return a usable answer."""


class LlmProvider(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 300) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTS:
            raise LlmConfigurationError("Only a local Ollama endpoint is allowed.")
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._model = model
        self._timeout = timeout_seconds

    def complete(self, system: str, prompt: str) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        request = urllib.request.Request(  # noqa: S310
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                content = json.loads(response.read())["message"]["content"]
        except (OSError, ValueError, KeyError, TypeError):
            raise LlmUnavailableError("Ollama did not return an answer.") from None
        return str(content)


def build_provider(settings: Settings, env: Mapping[str, str]) -> LlmProvider:
    if settings.llm.provider != "ollama":
        raise LlmConfigurationError("Only the local Ollama provider is implemented.")
    return OllamaProvider(env.get(LLM_URL_ENV_VAR, settings.llm.base_url), settings.llm.model)
