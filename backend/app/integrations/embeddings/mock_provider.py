import hashlib
import math
from typing import Any, Dict, List
from backend.app.core.config import settings
from backend.app.integrations.embeddings.base import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic pseudo-embedding provider for testing, evaluation, and offline workflows.
    Produces unit-length normalized vectors derived deterministically from input text hash.
    """

    def __init__(self, dimension: int = 0, model: str = "mock-embedding-v1"):
        self._dimension = dimension or settings.EMBEDDING_DIMENSION or 1536
        self._model = model

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_configured(self) -> bool:
        return True

    def get_configuration_status(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "dimension": self.dimension,
            "configured": True,
            "message": "Deterministic mock embedding provider active for testing",
        }

    async def embed_text(self, text: str) -> List[float]:
        return self._generate_deterministic_vector(text)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._generate_deterministic_vector(t) for t in texts]

    def _generate_deterministic_vector(self, text: str) -> List[float]:
        """Generates a normalized float vector deterministically from text."""
        seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        vector = []
        for i in range(self._dimension):
            byte_val = seed_bytes[i % len(seed_bytes)]
            val = (byte_val - 128) / 128.0 + ((i % 17) - 8) / 50.0
            vector.append(val)

        # Normalize to unit length
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]
        return vector
