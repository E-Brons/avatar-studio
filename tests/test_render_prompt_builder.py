"""Tests for LLM render prompt builder."""

from pipeline.render.llm.prompt_builder import build_prompt


class TestBuildPrompt:
    _PERSONA = {
        "personal": {"gender": "female", "age": 35},
        "appearance": {"hair_style": "bob"},
    }
    _EXPR_ENTRY = {
        "expression": "Happiness",
        "facs_action_units": "AU6+AU12",
        "description": "A warm genuine smile",
    }

    def test_contains_persona_content(self):
        prompt = build_prompt(self._PERSONA, self._EXPR_ENTRY, "")
        assert "female" in prompt or "Advisor" in prompt

    def test_contains_expression_content(self):
        prompt = build_prompt(self._PERSONA, self._EXPR_ENTRY, "")
        assert "Happiness" in prompt or "AU6" in prompt

    def test_style_directive_prepended(self):
        prompt = build_prompt(self._PERSONA, self._EXPR_ENTRY, "STYLE: photorealistic")
        assert prompt.startswith("STYLE: photorealistic")

    def test_no_style_directive(self):
        prompt = build_prompt(self._PERSONA, self._EXPR_ENTRY, "")
        assert "STYLE" not in prompt.split("\n")[0]

    def test_reference_image_note_added(self):
        prompt = build_prompt(self._PERSONA, self._EXPR_ENTRY, "", reference_image=True)
        assert "reference image" in prompt.lower()

    def test_no_reference_image_note_when_false(self):
        prompt = build_prompt(self._PERSONA, self._EXPR_ENTRY, "", reference_image=False)
        assert "reference image" not in prompt.lower()

    def test_style_key_stripped_from_persona(self):
        persona_with_style = dict(self._PERSONA)
        persona_with_style["style"] = {"bg_color": "#ABCDEF"}
        prompt = build_prompt(persona_with_style, self._EXPR_ENTRY, "")
        assert "#ABCDEF" not in prompt
