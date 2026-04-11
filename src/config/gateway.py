"""Thin client for the LLM Gateway REST API.

All LLM calls in the pipeline route through this client.
Default gateway URL: http://127.0.0.1:4096
"""

from __future__ import annotations

import base64
import logging
import time

import requests

logger = logging.getLogger(__name__)

_DEFAULT_GATEWAY_URL = "http://127.0.0.1:4096"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class GatewayClient:
    """Synchronous HTTP client for the LLM Gateway."""

    def __init__(self, base_url: str = _DEFAULT_GATEWAY_URL):
        self.base_url = base_url.rstrip("/")

    def _post(self, endpoint: str, payload: dict, *, timeout: int) -> dict:
        """POST to an endpoint with retry on ReadTimeout and retryable HTTP errors.

        Retries up to _MAX_ATTEMPTS total on:
          - ReadTimeout
          - HTTP 429, 500, 502, 503, 504
        All other exceptions propagate immediately.
        """
        url = f"{self.base_url}/{endpoint}"
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = requests.post(url, json=payload, timeout=timeout)
                if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
                    wait = 2**attempt
                    logger.warning(
                        "%s: HTTP %d (attempt %d/%d), retrying in %ds",
                        endpoint,
                        resp.status_code,
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        wait,
                    )
                    last_exc = requests.exceptions.HTTPError(response=resp)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.ReadTimeout as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    wait = 2**attempt
                    logger.warning(
                        "%s: read timeout (attempt %d/%d), retrying in %ds",
                        endpoint,
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        wait,
                    )
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def text_gen(
        self,
        messages: list[dict],
        *,
        max_retries: int = 3,
        timeout: int = 120,
        output_config: dict | None = None,
    ) -> str:
        """Call POST /text_gen and return the response content string."""
        payload: dict = {"messages": messages, "max_retries": max_retries}
        if output_config is not None:
            schema = output_config.get("format", {}).get("schema")
            if schema:
                payload["response_schema"] = schema
        return self._post("text_gen", payload, timeout=timeout)["content"]

    def reasoning(
        self,
        messages: list[dict],
        *,
        thinking_budget: int | None = None,
        timeout: int = 300,
    ) -> str:
        """Call POST /reasoning (claude-opus with extended thinking) and return free-form text."""
        payload: dict = {"messages": messages}
        if thinking_budget is not None:
            payload["thinking_budget"] = thinking_budget
        return self._post("reasoning", payload, timeout=timeout)["content"]

    def general(
        self,
        messages: list[dict],
        *,
        max_retries: int = 3,
        timeout: int = 120,
        output_config: dict | None = None,
    ) -> str:
        """Call POST /general (claude-sonnet) and return the response content string."""
        payload: dict = {"messages": messages, "max_retries": max_retries}
        if output_config is not None:
            schema = output_config.get("format", {}).get("schema")
            if schema:
                payload["response_schema"] = schema
        return self._post("general", payload, timeout=timeout)["content"]

    def image_gen(
        self,
        prompt: str,
        *,
        width: int = 256,
        height: int = 256,
        seed: int | None = None,
        optimize: str = "normal",
        reference_images_b64: list[str] | None = None,
        strength: float | None = None,
        max_retries: int = 3,
        timeout: int = 300,
    ) -> bytes:
        """Call POST /image_gen and return raw image bytes."""
        import base64

        payload: dict = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "optimize": optimize,
            "max_retries": max_retries,
        }
        if seed is not None:
            payload["seed"] = seed
        if reference_images_b64:
            payload["reference_images_b64"] = reference_images_b64
        if strength is not None:
            payload["strength"] = strength
        return base64.b64decode(self._post("image_gen", payload, timeout=timeout)["image_b64"])

    def image_inspector(
        self,
        image_bytes: bytes,
        system: str,
        prompt: str,
        *,
        max_retries: int = 3,
        timeout: int = 120,
        output_config: dict | None = None,
    ) -> str:
        """Call POST /image_inspector and return the response content string."""
        import base64

        payload: dict = {
            "image_b64": base64.b64encode(image_bytes).decode(),
            "system": system,
            "prompt": prompt,
            "max_retries": max_retries,
        }
        if output_config is not None:
            schema = output_config.get("format", {}).get("schema")
            if schema:
                payload["response_schema"] = schema
        return self._post("image_inspector", payload, timeout=timeout)["content"]

    def ipadapter_faceid(
        self,
        prompt: str,
        face_image_b64: str,
        *,
        negative_prompt: str | None = None,
        width: int = 256,
        height: int = 256,
        num_inference_steps: int | None = None,
        cfg_scale: float | None = None,
        ip_adapter_scale: float | None = None,
        lora: str | None = None,
        lora_weight: float | None = None,
        seed: int | None = None,
        optimize: str = "normal",
        max_retries: int = 3,
        timeout: int = 300,
    ) -> bytes:
        """Call POST /ipadapter_faceid and return raw image bytes."""
        payload: dict = {
            "prompt": prompt,
            "face_image_b64": face_image_b64,
            "width": width,
            "height": height,
            "optimize": optimize,
            "max_retries": max_retries,
        }
        if negative_prompt is not None:
            payload["negative_prompt"] = negative_prompt
        if num_inference_steps is not None:
            payload["num_inference_steps"] = num_inference_steps
        if cfg_scale is not None:
            payload["cfg_scale"] = cfg_scale
        if ip_adapter_scale is not None:
            payload["ip_adapter_scale"] = ip_adapter_scale
        if lora is not None:
            payload["lora"] = lora
            if lora_weight is not None:
                payload["lora_weight"] = lora_weight
        if seed is not None:
            payload["seed"] = seed
        return base64.b64decode(
            self._post("ipadapter_faceid", payload, timeout=timeout)["image_b64"]
        )

    def available_models(self) -> list[str]:
        """Return model names from GET /api/tags (Ollama-compatible)."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []
