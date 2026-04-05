"""Tests for render postprocess metadata writer."""

import io

from PIL import Image

from pipeline.render.postprocess.metadata import write_metadata


def _blank_png(w: int = 32, h: int = 32) -> bytes:
    img = Image.new("RGB", (w, h), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestWriteMetadata:
    def test_output_is_valid_png(self):
        result = write_metadata(_blank_png())
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"

    def test_copyright_embedded(self):
        result = write_metadata(_blank_png())
        img = Image.open(io.BytesIO(result))
        info = img.text if hasattr(img, "text") else {}
        assert "Copyright" in info
        assert "MyBoard" in info["Copyright"]

    def test_gateway_url_embedded(self):
        result = write_metadata(_blank_png(), gateway_url="http://test:4096")
        img = Image.open(io.BytesIO(result))
        assert img.text.get("GatewayUrl") == "http://test:4096"

    def test_prompt_embedded(self):
        result = write_metadata(_blank_png(), full_prompt="test prompt content")
        img = Image.open(io.BytesIO(result))
        assert img.text.get("Prompt") == "test prompt content"

    def test_persona_yaml_embedded(self):
        result = write_metadata(_blank_png(), persona_yaml="gender: female\n")
        img = Image.open(io.BytesIO(result))
        assert "gender" in img.text.get("PersonaYaml", "")

    def test_empty_fields_not_written(self):
        result = write_metadata(_blank_png())
        img = Image.open(io.BytesIO(result))
        assert "GatewayUrl" not in img.text
        assert "Prompt" not in img.text

    def test_style_entry_dict_serialized(self):
        result = write_metadata(_blank_png(), style_entry={"id": "photorealistic"})
        img = Image.open(io.BytesIO(result))
        assert "photorealistic" in img.text.get("StyleYaml", "")

    def test_output_size_unchanged(self):
        png = _blank_png(64, 64)
        result = write_metadata(png)
        out_img = Image.open(io.BytesIO(result))
        assert out_img.size == (64, 64)
