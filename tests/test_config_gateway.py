"""Tests for config/gateway.py GatewayClient — mocked requests."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestGatewayClient:
    def test_text_gen_returns_content(self):
        from config.gateway import GatewayClient

        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"content": "hello"})) as mock_post:
            result = client.text_gen([{"role": "user", "content": "hi"}])
            assert result == "hello"
            mock_post.assert_called_once()

    def test_image_gen_returns_bytes(self):
        from config.gateway import GatewayClient

        raw = b"fake_image_bytes"
        encoded = base64.b64encode(raw).decode()
        client = GatewayClient("http://test:4096")
        with patch(
            "requests.post", return_value=_mock_response({"image_b64": encoded})
        ) as mock_post:
            result = client.image_gen("a portrait")
            assert result == raw
            mock_post.assert_called_once()

    def test_image_gen_includes_seed_when_provided(self):
        from config.gateway import GatewayClient

        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock_post:
            client.image_gen("portrait", seed=42)
            payload = mock_post.call_args.kwargs["json"]
            assert payload["seed"] == 42

    def test_image_gen_excludes_seed_when_none(self):
        from config.gateway import GatewayClient

        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock_post:
            client.image_gen("portrait")
            payload = mock_post.call_args.kwargs["json"]
            assert "seed" not in payload

    def test_image_gen_includes_reference_images(self):
        from config.gateway import GatewayClient

        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock_post:
            client.image_gen("portrait", reference_images_b64=["abc123"])
            payload = mock_post.call_args.kwargs["json"]
            assert payload["reference_images_b64"] == ["abc123"]

    def test_image_inspector_returns_content(self):
        from config.gateway import GatewayClient

        client = GatewayClient("http://test:4096")
        with patch(
            "requests.post", return_value=_mock_response({"content": "description"})
        ) as mock_post:
            result = client.image_inspector(b"img", "sys", "describe")
            assert result == "description"
            mock_post.assert_called_once()

    def test_available_models_returns_list(self):
        from config.gateway import GatewayClient

        client = GatewayClient("http://test:4096")
        with patch(
            "requests.get",
            return_value=_mock_response({"models": [{"name": "flux"}, {"name": "phi3"}]}),
        ):
            models = client.available_models()
            assert "flux" in models
            assert "phi3" in models

    def test_available_models_returns_empty_on_error(self):
        from config.gateway import GatewayClient

        client = GatewayClient("http://test:4096")
        with patch("requests.get", side_effect=ConnectionError("refused")):
            models = client.available_models()
            assert models == []
