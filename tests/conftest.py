"""Shared pytest fixtures for avatar-studio integration tests."""
from __future__ import annotations

import os
import requests as _requests
import pytest


_GATEWAY_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:4096")


class GatewayClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")


@pytest.fixture(scope="session")
def gateway() -> GatewayClient:
    try:
        r = _requests.get(f"{_GATEWAY_URL}/health", timeout=5)
        r.raise_for_status()
    except Exception:
        pytest.skip(f"LLM Gateway not reachable at {_GATEWAY_URL}")
    return GatewayClient(_GATEWAY_URL)
