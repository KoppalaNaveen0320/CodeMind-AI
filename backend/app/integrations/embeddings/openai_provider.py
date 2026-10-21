import asyncio
import logging
from typing import Any, Dict, List
import httpx

from backend.app.core.config import settings
from backend.app.integrations.embeddings.base import (
    EmbeddingProvider,
    EmbeddingError,
    EmbeddingProviderUnconfiguredError,
    EmbeddingRateLimitError,
)

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI and OpenAI-compatible REST API embedding provider.
    Credentials are read exclusively from environment configuration.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        dimension: int = 0,
        base_url: str = "",
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ):
        self._api_key = api_key or settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        self._model = model or settings.EMBEDDING_MODEL or "text-embedding-3-small"
        self._dimension = dimension or settings.EMBEDDING_DIMENSION or 1536
        self._base_url = (base_url or settings.EMBEDDING_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and not self._api_key.startswith("your_"))

    def get_configuration_status(self) -> Dict[str, Any]:
        configured = self.is_configured
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "dimension": self.dimension,
            "configured": configured,
            "base_url": self._base_url,
            "message": "Ready to generate embeddings" if configured else "EMBEDDING_API_KEY is not set in backend/.env",
        }

    async def embed_text(self, text: str) -> List[float]:
        results = await self.embed_batch([text])
        if not results:
            raise EmbeddingError("No embedding returned from provider")
        return results[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        if not self.is_configured:
            raise EmbeddingProviderUnconfiguredError(
                "Cannot generate embeddings: EMBEDDING_API_KEY is unconfigured in backend environment."
            )

        endpoint = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # Process in batches
        batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            payload = {
                "input": chunk,
                "model": self._model,
            }
            # For text-embedding-3 models, dimension can be specified
            if "text-embedding-3" in self._model:
                payload["dimensions"] = self._dimension

            embeddings_chunk = await self._send_request_with_retries(endpoint, headers, payload)
            all_embeddings.extend(embeddings_chunk)

        return all_embeddings

    async def _send_request_with_retries(
        self, endpoint: str, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> List[List[float]]:
        last_error: Exception = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    # Sort by index to maintain original order
                    sorted_data = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
                    embeddings = [item["embedding"] for item in sorted_data]
                    return embeddings

                elif response.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"OpenAI rate limit hit (429). Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    last_error = EmbeddingRateLimitError(f"OpenAI rate limit: {response.text}")
                    continue

                elif response.status_code in (401, 403):
                    raise EmbeddingError(f"OpenAI authentication failed ({response.status_code}): Invalid API key")

                else:
                    error_msg = f"OpenAI embedding request failed ({response.status_code}): {response.text}"
                    logger.error(error_msg)
                    last_error = EmbeddingError(error_msg)
                    await asyncio.sleep(1)

            except httpx.TimeoutException as exc:
                last_error = EmbeddingError(f"Embedding request timed out: {exc}")
                await asyncio.sleep(1)
            except EmbeddingError:
                raise
            except Exception as exc:
                last_error = EmbeddingError(f"Unexpected error communicating with embedding provider: {exc}")
                await asyncio.sleep(1)

        raise last_error or EmbeddingError("Embedding request failed after maximum retries")
