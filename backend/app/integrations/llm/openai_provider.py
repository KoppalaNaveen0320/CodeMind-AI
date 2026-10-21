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
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


class OpenAILLMProvider(LLMProvider):
    """
    OpenAI Cloud LLM Provider.
    Calls OpenAI /v1/chat/completions endpoint when AI_PROVIDER=openai.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        temperature: Optional[float] = None,
        timeout_seconds: float = 45.0,
    ):
        self._api_key = api_key or settings.LLM_API_KEY
        self._model = model or settings.LLM_MODEL or "gpt-4o-mini"
        self._base_url = (base_url or settings.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        self._temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        self._timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(
            self._api_key
            and not self._api_key.startswith("your_")
            and not self._api_key.startswith("sk-placeholder")
        )

    def get_configuration_status(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "configured": self.is_configured,
            "base_url": self._base_url,
            "service_available": self.is_configured,
            "model_available": self.is_configured,
            "message": "OpenAI provider configured" if self.is_configured else "OpenAI API key missing or invalid",
        }

    async def generate_chat_response(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if not self.is_configured:
            raise LLMProviderUnconfiguredError(
                "OpenAI LLM provider is not configured. Set LLM_API_KEY in backend/.env"
            )

        endpoint = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                res = await client.post(endpoint, headers=headers, json=payload)

            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"]
            else:
                raise LLMError(f"OpenAI chat API returned status {res.status_code}: {res.text}")

        except httpx.ConnectError as conn_err:
            raise LLMConnectionError("Failed to connect to OpenAI API endpoint") from conn_err
        except httpx.TimeoutException as timeout_err:
            raise LLMTimeoutError("OpenAI chat request timed out") from timeout_err
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Error communicating with OpenAI: {str(e)}") from e

    async def generate_chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        if not self.is_configured:
            raise LLMProviderUnconfiguredError(
                "OpenAI LLM provider is not configured. Set LLM_API_KEY in backend/.env"
            )

        endpoint = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            line_str = line.strip()
                            if not line_str or line_str == "data: [DONE]":
                                continue
                            if line_str.startswith("data: "):
                                data_str = line_str[6:].strip()
                                try:
                                    data = json.loads(data_str)
                                    choices = data.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content_piece = delta.get("content", "")
                                        if content_piece:
                                            yield content_piece
                                except Exception:
                                    continue
                    else:
                        err_text = await response.aread()
                        raise LLMError(f"OpenAI chat API returned status {response.status_code}: {err_text.decode('utf-8', errors='replace')}")

        except httpx.ConnectError as conn_err:
            raise LLMConnectionError("Failed to connect to OpenAI API endpoint") from conn_err
        except httpx.TimeoutException as timeout_err:
            raise LLMTimeoutError("OpenAI chat request timed out") from timeout_err
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Error communicating with OpenAI streaming: {str(e)}") from e

