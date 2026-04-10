"""Thin client for the LLM Gateway REST API.

All LLM calls in the pipeline route through this client.
Default gateway URL: http://127.0.0.1:4096
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

_DEFAULT_GATEWAY_URL = "http://127.0.0.1:4096"


class GatewayClient:
    """Synchronous HTTP client for the LLM Gateway."""

    def __init__(self, base_url: str = _DEFAULT_GATEWAY_URL):
        self.base_url = base_url.rstrip("/")

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
        resp = requests.post(
            f"{self.base_url}/text_gen",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["content"]

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
        resp = requests.post(
            f"{self.base_url}/reasoning",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["content"]

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
        resp = requests.post(
            f"{self.base_url}/general",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["content"]

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

        resp = requests.post(
            f"{self.base_url}/image_gen",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return base64.b64decode(resp.json()["image_b64"])

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
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{self.base_url}/image_inspector",
                    json=payload,
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json()["content"]
            except requests.exceptions.ReadTimeout as exc:
                last_exc = exc
                if attempt < 2:
                    wait = 2**attempt
                    logger.warning(
                        "image_inspector: read timeout (attempt %d/3), retrying in %ds",
                        attempt + 1,
                        wait,
                    )
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def ipadapter_faceid(
        self,
        prompt: str,
        face_images_b64: list[str],
        *,
        weight: float = 0.7,
        width: int = 256,
        height: int = 256,
        seed: int | None = None,
        optimize: str = "normal",
        max_retries: int = 3,
        timeout: int = 300,
    ) -> bytes:
        """Call POST /ipadapter_faceid and return raw image bytes."""
        import base64

        payload: dict = {
            "prompt": prompt,
            "face_images_b64": face_images_b64,
            "weight": weight,
            "width": width,
            "height": height,
            "optimize": optimize,
            "max_retries": max_retries,
        }
        if seed is not None:
            payload["seed"] = seed
        resp = requests.post(
            f"{self.base_url}/ipadapter_faceid",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return base64.b64decode(resp.json()["image_b64"])

    def available_models(self) -> list[str]:
        """Return model names from GET /api/tags (Ollama-compatible)."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []
