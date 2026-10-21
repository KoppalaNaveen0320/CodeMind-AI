from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional


class LLMError(Exception):
    """Base exception for LLM operations."""
    pass


class LLMProviderUnconfiguredError(LLMError):
    """Raised when an operation is requested on an unconfigured LLM provider."""
    pass


class LLMConnectionError(LLMError):
    """Raised when connection to LLM runtime fails."""
    pass


class LLMModelNotFoundError(LLMError):
    """Raised when configured model is not pulled or available."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when request times out."""
    pass


class LLMProvider(ABC):
    """Abstract Base Class for LLM Providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the LLM provider (e.g. 'ollama', 'openai', 'mock')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the model being used (e.g. 'qwen2.5:3b', 'gpt-4o-mini')."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if provider has required configuration/URLs/keys."""
        pass

    @abstractmethod
    def get_configuration_status(self) -> Dict[str, Any]:
        """
        Returns truthful configuration status and diagnostics.
        """
        pass

    @abstractmethod
    async def generate_chat_response(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generates a non-streaming chat response from the LLM.
        """
        pass

    async def generate_chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streams chat response tokens/fragments from the LLM.
        Default implementation yields the non-streaming response as a single fragment.
        Providers supporting native streaming override this method.
        """
        full_response = await self.generate_chat_response(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield full_response
