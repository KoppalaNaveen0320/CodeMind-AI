import logging
from typing import Any, Dict, Optional

from backend.app.core.config import settings
from backend.app.integrations.llm.base import LLMProvider
from backend.app.integrations.llm.ollama_provider import OllamaLLMProvider
from backend.app.integrations.llm.openai_provider import OpenAILLMProvider

logger = logging.getLogger(__name__)


def get_llm_provider(provider_type: Optional[str] = None) -> LLMProvider:
    """Factory to retrieve the configured LLMProvider."""
    if provider_type:
        target_type = provider_type.lower()
    elif settings.LLM_API_KEY:
        target_type = "openai"
    else:
        target_type = (settings.LLM_PROVIDER or settings.AI_PROVIDER or "ollama").lower()

    if target_type == "ollama":
        return OllamaLLMProvider(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            context_limit=getattr(settings, "LLM_CONTEXT_WINDOW", 4096),
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )
    elif target_type in ("openai", "azure"):
        return OpenAILLMProvider(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL,
            temperature=settings.LLM_TEMPERATURE,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )
    else:
        return OllamaLLMProvider()


class LLMService:
    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Returns truthful diagnostic status of the active LLM provider."""
        provider = get_llm_provider()
        return provider.get_configuration_status()
