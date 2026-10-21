import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from backend.app.core.config import settings
from backend.app.integrations.embeddings.base import (
    EmbeddingProvider,
    EmbeddingError,
    EmbeddingProviderUnconfiguredError,
)

logger = logging.getLogger(__name__)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Local Ollama Embedding Provider.
    Generates real vector embeddings using local Ollama HTTP endpoints (/api/embed).
    Validates output dimensions, enforces bounded retries and timeouts, and never
    fabricates mock or random vectors.
    """

    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        dimension: int = 0,
        max_retries: int = 2,
        timeout_seconds: float = 30.0,
    ):
        self._base_url = (base_url or settings.OLLAMA_BASE_URL or "http://127.0.0.1:11434").rstrip("/")
        self._model = model or settings.EMBEDDING_MODEL or "nomic-embed-text"
        self._dimension = dimension or settings.EMBEDDING_DIMENSION or 768
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds or settings.EMBEDDING_TIMEOUT_SECONDS

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_configured(self) -> bool:
        """Local Ollama does not require API keys; it is configured if URL and model are set."""
        return bool(self._base_url and self._model)

    def get_configuration_status(self) -> Dict[str, Any]:
        """
        Truthfully checks whether Ollama is reachable and whether the configured
        embedding model has been pulled.
        """
        service_available = False
        model_available = False
        verified_dim: Optional[int] = None
        message = ""

        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{self._base_url}/api/tags")
                if res.status_code == 200:
                    service_available = True
                    models_list = res.json().get("models", [])
                    pulled_names = [m.get("name", "").lower() for m in models_list]
                    target_lower = self._model.lower()
                    
                    for m in models_list:
                        m_name = m.get("name", "").lower()
                        if (
                            m_name == target_lower
                            or m_name == f"{target_lower}:latest"
                            or target_lower in m_name
                        ):
                            model_available = True
                            details = m.get("details", {})
                            if "embedding_length" in details:
                                verified_dim = details["embedding_length"]
                            break

                    if model_available:
                        message = f"Local Ollama is running and model '{self._model}' is ready."
                    else:
                        message = (
                            f"Ollama is running, but embedding model '{self._model}' is not pulled. "
                            f"Run: ollama pull {self._model}"
                        )
                else:
                    message = f"Ollama returned HTTP status {res.status_code} on /api/tags."
        except httpx.ConnectError:
            message = f"Cannot connect to Ollama at {self._base_url}. Ensure Ollama is running ('ollama serve')."
        except httpx.TimeoutException:
            message = f"Connection to Ollama at {self._base_url} timed out."
        except Exception as e:
            message = f"Diagnostic probe to Ollama failed: {str(e)}"

        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "dimension": self.dimension,
            "configured": self.is_configured,
            "base_url": self._base_url,
            "service_available": service_available,
            "model_available": model_available,
            "verified_dimension": verified_dim,
            "message": message,
        }

    async def embed_text(self, text: str) -> List[float]:
        results = await self.embed_batch([text])
        if not results:
            raise EmbeddingError("No embedding returned from Ollama provider")
        return results[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        if not self.is_configured:
            raise EmbeddingProviderUnconfiguredError(
                "Cannot generate embeddings: Ollama base URL or model name is not configured."
            )

        endpoint = f"{self._base_url}/api/embed"
        batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            payload = {
                "model": self._model,
                "input": chunk,
            }
            embeddings_chunk = await self._send_request_with_retries(endpoint, payload)
            
            # Validate output dimensions for every vector in the batch
            for idx, vec in enumerate(embeddings_chunk):
                if len(vec) != self._dimension:
                    raise EmbeddingError(
                        f"Dimension mismatch from Ollama embedding model '{self._model}': "
                        f"expected {self._dimension}, got {len(vec)}. "
                        "Vector cannot be safely stored in the database."
                    )

            all_embeddings.extend(embeddings_chunk)

        return all_embeddings

    async def _send_request_with_retries(
        self, endpoint: str, payload: Dict[str, Any]
    ) -> List[List[float]]:
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(endpoint, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    embeddings = data.get("embeddings", [])
                    if not embeddings:
                        raise EmbeddingError(f"Ollama returned empty embeddings array: {response.text}")
                    return embeddings

                elif response.status_code == 404:
                    err_text = response.text
                    raise EmbeddingError(
                        f"Ollama embedding model '{self._model}' not found. "
                        f"Please pull the model using: ollama pull {self._model} (Detail: {err_text})"
                    )

                else:
                    err_msg = f"Ollama embedding request failed ({response.status_code}): {response.text}"
                    logger.warning(err_msg)
                    last_error = EmbeddingError(err_msg)
                    await asyncio.sleep(1)

            except httpx.ConnectError as conn_err:
                raise EmbeddingError(
                    f"Cannot connect to local Ollama runtime at {self._base_url}. "
                    "Ensure Ollama is running ('ollama serve')."
                ) from conn_err

            except httpx.TimeoutException as timeout_err:
                last_error = EmbeddingError(
                    f"Ollama embedding request timed out after {self._timeout_seconds}s. "
                    "Your local system may be under heavy load."
                )
                await asyncio.sleep(1)

            except EmbeddingError:
                raise

            except Exception as exc:
                last_error = EmbeddingError(f"Unexpected error communicating with Ollama: {exc}")
                await asyncio.sleep(1)

        raise last_error or EmbeddingError("Ollama embedding request failed after maximum retries")
