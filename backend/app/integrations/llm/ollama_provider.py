import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx

from backend.app.core.config import settings
from backend.app.integrations.llm.base import (
    LLMProvider,
    LLMError,
    LLMProviderUnconfiguredError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


class OllamaLLMProvider(LLMProvider):
    """
    Local Ollama LLM Provider.
    Invokes local Ollama chat API (/api/chat) using non-streaming JSON responses.
    Validates model availability, handles timeouts and retries, and protects against
    hallucination/fabrication when the local AI runtime is stopped or degraded.
    """

    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        temperature: Optional[float] = None,
        context_limit: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: int = 2,
    ):
        self._base_url = (base_url or settings.OLLAMA_BASE_URL or "http://127.0.0.1:11434").rstrip("/")
        self._model = model or settings.LLM_MODEL or "qwen2.5:3b"
        self._temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        self._context_limit = context_limit or getattr(settings, "LLM_CONTEXT_WINDOW", 4096)
        self._timeout_seconds = timeout_seconds or settings.LLM_TIMEOUT_SECONDS
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        """Local mode does not require cloud API keys; configured if base_url and model are present."""
        return bool(self._base_url and self._model)

    def get_configuration_status(self) -> Dict[str, Any]:
        """
        Truthfully probes whether Ollama is reachable and whether the configured LLM model exists.
        """
        service_available = False
        model_available = False
        message = ""

        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{self._base_url}/api/tags")
                if res.status_code == 200:
                    service_available = True
                    models = res.json().get("models", [])
                    target_lower = self._model.lower()
                    for m in models:
                        m_name = m.get("name", "").lower()
                        if (
                            m_name == target_lower
                            or m_name == f"{target_lower}:latest"
                            or target_lower in m_name
                        ):
                            model_available = True
                            break

                    if model_available:
                        message = f"Local Ollama is running and LLM '{self._model}' is available."
                    else:
                        message = (
                            f"Ollama is running, but LLM '{self._model}' is not pulled. "
                            f"Run: ollama pull {self._model}"
                        )
                else:
                    message = f"Ollama returned HTTP {res.status_code} on /api/tags."
        except httpx.ConnectError:
            message = f"Cannot connect to Ollama at {self._base_url}. Ensure Ollama is running ('ollama serve')."
        except httpx.TimeoutException:
            message = f"Connection to Ollama at {self._base_url} timed out."
        except Exception as e:
            message = f"Diagnostic probe to Ollama failed: {str(e)}"

        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "configured": self.is_configured,
            "base_url": self._base_url,
            "service_available": service_available,
            "model_available": model_available,
            "context_limit": self._context_limit,
            "temperature": self._temperature,
            "message": message,
        }

    async def generate_chat_response(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Executes local chat completion via POST /api/chat.
        """
        if not self.is_configured:
            raise LLMProviderUnconfiguredError(
                "Ollama LLM provider is not configured. Base URL and model name are required."
            )

        endpoint = f"{self._base_url}/api/chat"
        temp = temperature if temperature is not None else self._temperature

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temp,
                "num_ctx": self._context_limit,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    res = await client.post(endpoint, json=payload)

                if res.status_code == 200:
                    data = res.json()
                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    if not content and not data.get("done", False):
                        raise LLMError(f"Ollama returned incomplete or empty chat response: {res.text}")
                    return content

                elif res.status_code == 404:
                    err_text = res.text
                    raise LLMModelNotFoundError(
                        f"Ollama LLM model '{self._model}' not found on local runtime. "
                        f"Please pull the model using: ollama pull {self._model} (Detail: {err_text})"
                    )

                else:
                    err_msg = f"Ollama chat API returned status {res.status_code}: {res.text}"
                    logger.warning(err_msg)
                    last_error = LLMError(err_msg)
                    await asyncio.sleep(1)

            except httpx.ConnectError as conn_err:
                raise LLMConnectionError(
                    f"Cannot connect to local Ollama runtime at {self._base_url}. "
                    "Ensure Ollama is running ('ollama serve')."
                ) from conn_err

            except httpx.TimeoutException as timeout_err:
                raise LLMTimeoutError(
                    f"Ollama LLM request timed out after {self._timeout_seconds}s. "
                    "The local model may be overloaded or context size too large for local hardware. "
                    "Please try with a more focused question or click Retry."
                ) from timeout_err

            except (LLMModelNotFoundError, LLMConnectionError):
                raise

            except Exception as e:
                last_error = LLMError(f"Unexpected error calling local Ollama LLM: {str(e)}")
                await asyncio.sleep(1)

        raise last_error or LLMError("Local Ollama chat request failed after maximum retries")

    async def generate_chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Executes local chat completion via POST /api/chat with stream=True.
        Yields text tokens as they arrive from Ollama runtime without buffering.
        """
        if not self.is_configured:
            raise LLMProviderUnconfiguredError(
                "Ollama LLM provider is not configured. Base URL and model name are required."
            )

        endpoint = f"{self._base_url}/api/chat"
        temp = temperature if temperature is not None else self._temperature

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temp,
                "num_ctx": self._context_limit,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                async with client.stream("POST", endpoint, json=payload) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            line_str = line.strip()
                            if not line_str:
                                continue
                            try:
                                data = json.loads(line_str)
                            except Exception:
                                continue
                            msg = data.get("message", {})
                            content_piece = msg.get("content", "")
                            if content_piece:
                                yield content_piece
                            if data.get("done", False):
                                break
                    elif response.status_code == 404:
                        err_text = await response.aread()
                        raise LLMModelNotFoundError(
                            f"Ollama LLM model '{self._model}' not found on local runtime. "
                            f"Please pull the model using: ollama pull {self._model} (Detail: {err_text.decode('utf-8', errors='replace')})"
                        )
                    else:
                        err_text = await response.aread()
                        raise LLMError(f"Ollama chat API returned status {response.status_code}: {err_text.decode('utf-8', errors='replace')}")

        except httpx.ConnectError as conn_err:
            raise LLMConnectionError(
                f"Cannot connect to local Ollama runtime at {self._base_url}. "
                "Ensure Ollama is running ('ollama serve')."
            ) from conn_err

        except httpx.TimeoutException as timeout_err:
            raise LLMTimeoutError(
                f"Ollama LLM request timed out after {self._timeout_seconds}s. "
                "The local model may be overloaded or context size too large for local hardware. "
                "Please try with a more focused question or click Retry."
            ) from timeout_err

        except (LLMModelNotFoundError, LLMConnectionError, LLMTimeoutError, LLMError):
            raise

        except Exception as e:
            raise LLMError(f"Unexpected error during local Ollama streaming: {str(e)}") from e

