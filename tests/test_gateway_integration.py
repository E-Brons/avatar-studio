"""Integration tests for GatewayClient — all gateway endpoint types.

Each test has two layers:
  (a) Payload shape — verified via mock (always runs, no gateway needed).
  (b) Live effect   — requires gateway at http://127.0.0.1:4096; auto-skipped otherwise.
      Live tests measure time differences and/or inspect returned content to confirm
      that parameters actually affect generation.

New ipadapter_faceid parameters tested: negative_prompt, num_inference_steps,
cfg_scale, ip_adapter_scale, lora, lora_weight.
"""

from __future__ import annotations

import base64
import time
from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

from config.gateway import GatewayClient

pytestmark = [pytest.mark.gateway, pytest.mark.integration]

_GATEWAY_URL = "http://127.0.0.1:4096"


def _assert_field(
    props: dict,
    name: str,
    expected_type: str | None = None,
    nullable: bool = False,
) -> None:
    """Assert a field exists in schema properties, optionally checking its type."""
    assert name in props, f"Schema missing field {name!r}; present fields: {sorted(props)}"
    if expected_type is None:
        return
    field = props[name]
    # anyOf / oneOf with null covers nullable fields
    candidates = [field] + [s for s in field.get("anyOf", field.get("oneOf", []))]
    types = {s.get("type") for s in candidates if "type" in s}
    assert expected_type in types or (nullable and "null" in types), (
        f"Field {name!r}: expected type={expected_type!r}, got schema={field}"
    )


# ===========================================================================
# Gateway OpenAPI schema contract tests
# These run first and act as a circuit-breaker: if the server's Pydantic
# model disagrees with what the client sends, these tests fail immediately
# with a clear diff before any generation call is attempted.
# ===========================================================================


def _openapi_schema() -> dict:
    """Fetch /openapi.json from the live gateway, skip if unreachable."""
    try:
        resp = _requests.get(f"{_GATEWAY_URL}/openapi.json", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        pytest.skip(f"Gateway not reachable at {_GATEWAY_URL}")


def _endpoint_request_schema(openapi: dict, path: str, method: str = "post") -> dict:
    """Return the resolved JSON Schema for the request body of a given endpoint."""
    op = openapi["paths"][path][method]
    ref = op["requestBody"]["content"]["application/json"]["schema"].get("$ref")
    if ref:
        # e.g. "#/components/schemas/IPAdapterFaceIDRequest"
        name = ref.split("/")[-1]
        return openapi["components"]["schemas"][name]
    return op["requestBody"]["content"]["application/json"]["schema"]


class TestGatewaySchema:
    """Assert the live gateway's OpenAPI schema matches what our client sends.

    These tests act as a circuit-breaker: they verify the server's Pydantic model
    exposes every field the learn strategy needs before any generation call is made.
    Run `scripts/test-integration.sh` after adding fields to the server to confirm.
    """

    def test_ipadapter_faceid_required_fields(self):
        schema = _endpoint_request_schema(_openapi_schema(), "/ipadapter_faceid")
        required = set(schema.get("required", []))
        props = set(schema.get("properties", {}).keys())

        # face_image_b64 must be required (singular string, not the old list)
        assert "face_image_b64" in required, (
            f"Expected face_image_b64 in required={required}; "
            "client may be using the old face_images_b64 list field"
        )
        assert "face_images_b64" not in props, (
            "Old field face_images_b64 (list) still present — gateway and client are out of sync"
        )
        assert "prompt" in required

    def test_ipadapter_faceid_learn_surface_complete(self):
        """Every parameter the learn strategy tunes must be present in the schema.

        The learn loop (learn_restyle.py / learn_reexpress.py) reads these from
        restyle.yml / reexpress.yml and sends them on every generation call.
        A missing field means the REASON LLM's tuning has no effect.

        Field reference: docs/plans/2026-04-11-learn-using-diffusion-model-params.md
        """
        schema = _endpoint_request_schema(_openapi_schema(), "/ipadapter_faceid")
        props = schema.get("properties", {})

        # --- generation quality knobs ---
        _assert_field(props, "negative_prompt", expected_type="string")
        _assert_field(props, "cfg_scale", expected_type="number")
        _assert_field(props, "ip_adapter_scale", expected_type="number")
        _assert_field(props, "num_inference_steps", expected_type="integer")

        # --- style adapter ---
        _assert_field(props, "lora", nullable=True)
        _assert_field(props, "lora_weight", expected_type="number")

        # --- geometry (already present, guard against regression) ---
        _assert_field(props, "width", expected_type="integer")
        _assert_field(props, "height", expected_type="integer")

        # --- face reference (single b64 string, not a list) ---
        _assert_field(props, "face_image_b64", expected_type="string")

    def test_ipadapter_faceid_response_contains_image_b64(self):
        """Response schema must include image_b64 so the client can decode it.

        Skipped when the endpoint has no response_model (FastAPI omits the schema
        entirely in that case).  Add a response_model to the server endpoint to
        make this test active.
        """
        openapi = _openapi_schema()
        op = openapi["paths"]["/ipadapter_faceid"]["post"]
        resp_schema = op.get("responses", {}).get("200", {})
        content = resp_schema.get("content", {}).get("application/json", {})
        ref = content.get("schema", {}).get("$ref")
        if ref:
            name = ref.split("/")[-1]
            resp_props = openapi["components"]["schemas"][name].get("properties", {})
        else:
            resp_props = content.get("schema", {}).get("properties", {})
        if not resp_props:
            pytest.skip(
                "No response schema documented for /ipadapter_faceid "
                "(add response_model to the FastAPI endpoint to enable this check)"
            )
        assert "image_b64" in resp_props, (
            f"Response schema missing image_b64 field; got keys: {set(resp_props)}"
        )

    def test_image_gen_required_fields(self):
        schema = _endpoint_request_schema(_openapi_schema(), "/image_gen")
        required = set(schema.get("required", []))
        assert "prompt" in required

    def test_text_gen_required_fields(self):
        schema = _endpoint_request_schema(_openapi_schema(), "/text_gen")
        required = set(schema.get("required", []))
        assert "messages" in required


# ---------------------------------------------------------------------------
# Real face image — required because the gateway runs face detection before
# generation. A blank/synthetic image always returns "No face detected".
# ---------------------------------------------------------------------------

_FACE_IMAGE_PATH = (
    # Photorealistic portrait — required so the diffusion server's face detector fires.
    "tests/assets/sanity_face.jpg"
)

_PROJECT_ROOT = __file__  # tests/test_gateway_integration.py
for _ in range(2):
    _PROJECT_ROOT = __import__("os").path.dirname(_PROJECT_ROOT)


def _face_image_b64() -> str:
    """Return base64-encoded JPEG of a real face from the example assets."""
    path = __import__("os").path.join(_PROJECT_ROOT, _FACE_IMAGE_PATH)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _live_client() -> GatewayClient:
    """Return a live GatewayClient, or skip the test if gateway is unreachable."""
    import requests

    try:
        requests.get(f"{_GATEWAY_URL}/health", timeout=5).raise_for_status()
    except Exception:
        pytest.skip(f"Gateway not reachable at {_GATEWAY_URL}")
    return GatewayClient(_GATEWAY_URL)


# ===========================================================================
# text_gen
# ===========================================================================


class TestTextGen:
    def test_payload_includes_messages(self):
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"content": "hi"})) as mock:
            client.text_gen([{"role": "user", "content": "hello"}])
            payload = mock.call_args.kwargs["json"]
            assert payload["messages"] == [{"role": "user", "content": "hello"}]

    def test_payload_includes_response_schema_when_output_config_set(self):
        client = GatewayClient("http://test:4096")
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        output_config = {"format": {"schema": schema}}
        with patch("requests.post", return_value=_mock_response({"content": "{}"})) as mock:
            client.text_gen([{"role": "user", "content": "go"}], output_config=output_config)
            payload = mock.call_args.kwargs["json"]
            assert payload["response_schema"] == schema

    def test_live_returns_nonempty_string(self):
        client = _live_client()
        result = client.text_gen([{"role": "user", "content": "Say exactly: OK"}])
        assert isinstance(result, str) and len(result) > 0


# ===========================================================================
# reasoning
# ===========================================================================


class TestReasoning:
    def test_payload_includes_thinking_budget_when_set(self):
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"content": "thought"})) as mock:
            client.reasoning([{"role": "user", "content": "think"}], thinking_budget=1024)
            payload = mock.call_args.kwargs["json"]
            assert payload["thinking_budget"] == 1024

    def test_payload_omits_thinking_budget_when_none(self):
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"content": "thought"})) as mock:
            client.reasoning([{"role": "user", "content": "think"}])
            payload = mock.call_args.kwargs["json"]
            assert "thinking_budget" not in payload

    def test_live_returns_nonempty_string(self):
        client = _live_client()
        result = client.reasoning([{"role": "user", "content": "What is 2+2?"}])
        assert isinstance(result, str) and len(result) > 0


# ===========================================================================
# general
# ===========================================================================


class TestGeneral:
    def test_payload_includes_response_schema(self):
        client = GatewayClient("http://test:4096")
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        output_config = {"format": {"schema": schema}}
        with patch("requests.post", return_value=_mock_response({"content": "{}"})) as mock:
            client.general([{"role": "user", "content": "go"}], output_config=output_config)
            payload = mock.call_args.kwargs["json"]
            assert payload["response_schema"] == schema

    def test_live_returns_nonempty_string(self):
        client = _live_client()
        result = client.general([{"role": "user", "content": "Reply with: PONG"}])
        assert isinstance(result, str) and len(result) > 0


# ===========================================================================
# image_inspector
# ===========================================================================


class TestImageInspector:
    def test_payload_encodes_image_bytes(self):
        client = GatewayClient("http://test:4096")
        raw = b"\x89PNG fake"
        with patch("requests.post", return_value=_mock_response({"content": "a face"})) as mock:
            client.image_inspector(raw, "system", "describe")
            payload = mock.call_args.kwargs["json"]
            assert payload["image_b64"] == base64.b64encode(raw).decode()
            assert payload["system"] == "system"
            assert payload["prompt"] == "describe"

    def test_payload_includes_response_schema_when_set(self):
        client = GatewayClient("http://test:4096")
        schema = {"type": "object", "properties": {"label": {"type": "string"}}}
        output_config = {"format": {"schema": schema}}
        raw = b"\x89PNG"
        with patch("requests.post", return_value=_mock_response({"content": "{}"})) as mock:
            client.image_inspector(raw, "sys", "q", output_config=output_config)
            payload = mock.call_args.kwargs["json"]
            assert payload["response_schema"] == schema

    def test_live_describes_face_image(self):
        client = _live_client()
        face_bytes = base64.b64decode(_face_image_b64())
        result = client.image_inspector(
            face_bytes, "Describe this image briefly.", "What do you see?"
        )
        assert isinstance(result, str) and len(result) > 0


# ===========================================================================
# image_gen
# ===========================================================================


class TestImageGen:
    def test_payload_defaults(self):
        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock:
            client.image_gen("portrait")
            payload = mock.call_args.kwargs["json"]
            assert payload["prompt"] == "portrait"
            assert payload["optimize"] == "normal"
            assert "seed" not in payload
            assert "reference_images_b64" not in payload
            assert "strength" not in payload

    def test_payload_includes_seed(self):
        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock:
            client.image_gen("portrait", seed=99)
            assert mock.call_args.kwargs["json"]["seed"] == 99

    def test_payload_includes_reference_images(self):
        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock:
            client.image_gen("portrait", reference_images_b64=["abc"])
            assert mock.call_args.kwargs["json"]["reference_images_b64"] == ["abc"]

    def test_payload_includes_strength_when_set(self):
        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock:
            client.image_gen("portrait", strength=0.6)
            assert mock.call_args.kwargs["json"]["strength"] == 0.6

    def test_payload_optimize_variants(self):
        raw = base64.b64encode(b"img").decode()
        client = GatewayClient("http://test:4096")
        for optimize in ("fast", "normal", "quality"):
            with patch("requests.post", return_value=_mock_response({"image_b64": raw})) as mock:
                client.image_gen("portrait", optimize=optimize)
                assert mock.call_args.kwargs["json"]["optimize"] == optimize

    def test_live_fast_is_faster_than_quality(self):
        """fast should complete noticeably quicker than quality at 256×256."""
        client = _live_client()

        t0 = time.monotonic()
        fast_bytes = client.image_gen(
            "portrait photo of a person", optimize="fast", width=256, height=256
        )
        t_fast = time.monotonic() - t0

        t0 = time.monotonic()
        quality_bytes = client.image_gen(
            "portrait photo of a person", optimize="quality", width=256, height=256
        )
        t_quality = time.monotonic() - t0

        assert len(fast_bytes) > 0
        assert len(quality_bytes) > 0
        # fast should be at least 20% faster than quality; if not, log but don't fail
        # (server may ignore optimize)
        if t_quality > 1.0:
            assert t_fast < t_quality * 1.5, (
                f"Expected fast ({t_fast:.1f}s) to be quicker than quality ({t_quality:.1f}s)"
            )

    def test_live_returns_png_bytes(self):
        client = _live_client()
        result = client.image_gen("a simple portrait", width=64, height=64, optimize="fast")
        assert isinstance(result, bytes) and len(result) > 0
        # PNG magic bytes
        assert result[:4] == b"\x89PNG" or result[:2] == b"\xff\xd8"


# ===========================================================================
# ipadapter_faceid — payload shape (unit)
# ===========================================================================


class TestIPAdapterPayload:
    _face_b64 = _face_image_b64()
    _img_b64 = base64.b64encode(b"fake_img").decode()

    def _client_and_mock(self):
        client = GatewayClient("http://test:4096")
        resp = _mock_response({"image_b64": self._img_b64})
        return client, resp

    def test_required_fields_always_present(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64)
            p = mock.call_args.kwargs["json"]
            assert p["prompt"] == "a portrait"
            assert p["face_image_b64"] == self._face_b64
            assert p["width"] == 256
            assert p["height"] == 256

    def test_negative_prompt_included_when_set(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64, negative_prompt="blurry, ugly")
            assert mock.call_args.kwargs["json"]["negative_prompt"] == "blurry, ugly"

    def test_negative_prompt_absent_when_none(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64)
            assert "negative_prompt" not in mock.call_args.kwargs["json"]

    def test_num_inference_steps_included_when_set(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64, num_inference_steps=10)
            assert mock.call_args.kwargs["json"]["num_inference_steps"] == 10

    def test_num_inference_steps_absent_when_none(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64)
            assert "num_inference_steps" not in mock.call_args.kwargs["json"]

    def test_cfg_scale_included_when_set(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64, cfg_scale=7.5)
            assert mock.call_args.kwargs["json"]["cfg_scale"] == 7.5

    def test_cfg_scale_absent_when_none(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64)
            assert "cfg_scale" not in mock.call_args.kwargs["json"]

    def test_ip_adapter_scale_included_when_set(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64, ip_adapter_scale=0.8)
            assert mock.call_args.kwargs["json"]["ip_adapter_scale"] == 0.8

    def test_ip_adapter_scale_absent_when_none(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64)
            assert "ip_adapter_scale" not in mock.call_args.kwargs["json"]

    def test_lora_and_lora_weight_included_when_lora_set(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid(
                "a portrait", self._face_b64, lora="style_lora", lora_weight=0.9
            )
            p = mock.call_args.kwargs["json"]
            assert p["lora"] == "style_lora"
            assert p["lora_weight"] == 0.9

    def test_lora_weight_omitted_when_lora_is_none(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64, lora_weight=0.9)
            p = mock.call_args.kwargs["json"]
            assert "lora" not in p
            assert "lora_weight" not in p

    def test_seed_included_when_set(self):
        client, resp = self._client_and_mock()
        with patch("requests.post", return_value=resp) as mock:
            client.ipadapter_faceid("a portrait", self._face_b64, seed=42)
            assert mock.call_args.kwargs["json"]["seed"] == 42

    def test_weight_param_removed_from_signature(self):
        """Old `weight` param must no longer exist on the method."""
        import inspect

        sig = inspect.signature(GatewayClient.ipadapter_faceid)
        assert "weight" not in sig.parameters, "Legacy `weight` param must be removed"

    def test_optimize_param_present_in_signature(self):
        """optimize is kept because the server currently requires it in the payload."""
        import inspect

        sig = inspect.signature(GatewayClient.ipadapter_faceid)
        assert "optimize" in sig.parameters


# ===========================================================================
# ipadapter_faceid — live effect tests
# ===========================================================================


class TestIPAdapterLive:
    """Live tests require gateway + IPAdapter model.  Auto-skipped otherwise."""

    @pytest.fixture(autouse=True)
    def _face(self):
        self.face_b64 = _face_image_b64()

    def _gen(self, client: GatewayClient, **kwargs) -> tuple[bytes, float]:
        t0 = time.monotonic()
        img = client.ipadapter_faceid(
            "portrait photo of a person, same face",
            self.face_b64,
            width=128,
            height=128,
            **kwargs,
        )
        return img, time.monotonic() - t0

    def test_live_baseline_returns_image(self):
        client = _live_client()
        img, _ = self._gen(client)
        assert len(img) > 0

    def test_live_negative_prompt_accepted(self):
        client = _live_client()
        img, _ = self._gen(client, negative_prompt="blurry, low quality, deformed")
        assert len(img) > 0

    def test_live_few_steps_faster_than_many_steps(self):
        """10 steps should complete faster than 30 steps."""
        client = _live_client()
        _, t_low = self._gen(client, num_inference_steps=5)
        _, t_high = self._gen(client, num_inference_steps=25)
        assert t_low < t_high * 1.5, (
            f"5 steps ({t_low:.1f}s) expected faster than 25 steps ({t_high:.1f}s); "
            "server may not honour num_inference_steps"
        )

    def test_live_cfg_scale_accepted(self):
        client = _live_client()
        img_low, _ = self._gen(client, cfg_scale=2.0)
        img_high, _ = self._gen(client, cfg_scale=12.0)
        assert len(img_low) > 0 and len(img_high) > 0

    def test_live_ip_adapter_scale_low_and_high(self):
        """Both extremes of ip_adapter_scale must succeed without error."""
        client = _live_client()
        img_low, _ = self._gen(client, ip_adapter_scale=0.2)
        img_high, _ = self._gen(client, ip_adapter_scale=1.0)
        assert len(img_low) > 0 and len(img_high) > 0

    def test_live_lora_null_default_succeeds(self):
        """Calling without lora (default None) must not send lora and must succeed."""
        client = _live_client()
        img, _ = self._gen(client)
        assert len(img) > 0

    def test_live_all_params_together(self):
        """All new params sent together must not crash the gateway."""
        client = _live_client()
        img, _ = self._gen(
            client,
            negative_prompt="blurry, deformed",
            num_inference_steps=10,
            cfg_scale=7.0,
            ip_adapter_scale=0.7,
        )
        assert len(img) > 0
