from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class EmbeddingResult:
    vector: List[float]
    model: str
    tokens_used: Optional[int] = None


class EmbeddingProvider(ABC):
    """Abstract Base Class for Embedding Providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the embedding provider (e.g. 'openai', 'mock')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the model being used (e.g. 'text-embedding-3-small')."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Expected output dimension of vector embeddings."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True only if all required credentials and configurations exist."""
        pass

    @abstractmethod
    def get_configuration_status(self) -> Dict[str, Any]:
        """
        Returns truthful configuration status and diagnostics.
        """
        pass

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """Generate embedding vector for a single string."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for a batch of strings."""
        pass


class EmbeddingError(Exception):
    """Base exception for embedding failures."""
    pass


class EmbeddingProviderUnconfiguredError(EmbeddingError):
    """Raised when an operation is requested on an unconfigured embedding provider."""
    pass


class EmbeddingRateLimitError(EmbeddingError):
    """Raised when provider returns HTTP 429 rate limit."""
    pass
