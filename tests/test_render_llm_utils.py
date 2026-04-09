"""Tests for render LLM style_directive and persona_sanitizer."""

from pipeline.render.llm.persona_sanitizer import sanitize_persona
from pipeline.render.llm.style_directive import build_style_directive

# ---------------------------------------------------------------------------
# style_directive
# ---------------------------------------------------------------------------


class TestBuildStyleDirective:
    def test_substitutes_bg_color(self):
        entry = {"system_prompt": "Background: [BG_COLOR] style."}
        result = build_style_directive(entry, bg_color="#FF0000")
        assert result == "Background: #FF0000 style."

    def test_no_placeholder_returns_as_is(self):
        entry = {"system_prompt": "Photorealistic portrait."}
        result = build_style_directive(entry)
        assert result == "Photorealistic portrait."

    def test_missing_system_prompt_returns_empty(self):
        result = build_style_directive({})
        assert result == ""

    def test_none_system_prompt_returns_empty(self):
        result = build_style_directive({"system_prompt": None})
        assert result == ""

    def test_multiple_placeholders_all_replaced(self):
        entry = {"system_prompt": "[BG_COLOR] and [BG_COLOR]"}
        result = build_style_directive(entry, bg_color="#ABCDEF")
        assert result == "#ABCDEF and #ABCDEF"


# ---------------------------------------------------------------------------
# persona_sanitizer
# ---------------------------------------------------------------------------


class TestSanitizePersona:
    _PERSONA = {
        "personal": {"name": "Alice", "gender": "female", "age": 35},
        "personality": {
            "traits": ["analytical"],
        },
        "appearance": {"hair_style": "bob", "eye_shape": "almond"},
    }

    def test_returns_dict(self):
        result = sanitize_persona(self._PERSONA)
        assert isinstance(result, dict)

    def test_removes_name(self):
        result = sanitize_persona(self._PERSONA)
        assert "name" not in result.get("personal", {})

    def test_excludes_personality_section(self):
        result = sanitize_persona(self._PERSONA)
        assert "personality" not in result

    def test_includes_eye_shape(self):
        result = sanitize_persona(self._PERSONA)
        assert "eye_shape" in result.get("appearance", {})

    def test_keeps_hair_style(self):
        result = sanitize_persona(self._PERSONA)
        assert result.get("appearance", {}).get("hair_style") == "bob"
