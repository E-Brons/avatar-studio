"""Tests for step_b_generate_cv — mocked GatewayClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_client(responses):
    """Return a mock GatewayClient whose text_gen cycles through *responses*."""
    client = MagicMock()
    client.text_gen.side_effect = responses
    return client


_VALID_YAML = (
    "education:\n"
    "  - MBA, Harvard\n"
    "experience:\n"
    "  - Senior Analyst, Goldman Sachs\n"
    "traits:\n"
    "  - analytical\n"
    "  - strategic\n"
    "  - detail-oriented\n"
)


class TestGenerateAdvisorProfile:
    def test_happy_path(self):
        with patch(
            "pipeline.persona.aggregator_llm.GatewayClient",
            return_value=_mock_client([_VALID_YAML]),
        ):
            from pipeline.persona.aggregator_llm import generate_advisor_profile

            result = generate_advisor_profile("Advisor", {"gender": "female", "age": 35})
            assert "education" in result
            assert "experience" in result
            assert "traits" in result

    def test_strips_code_fences(self):
        fenced = f"```yaml\n{_VALID_YAML}```"
        with patch(
            "pipeline.persona.aggregator_llm.GatewayClient",
            return_value=_mock_client([fenced]),
        ):
            from pipeline.persona.aggregator_llm import generate_advisor_profile

            result = generate_advisor_profile("Advisor", {"gender": "male", "age": 40})
            assert len(result["education"]) > 0

    def test_non_dict_response_retries_then_succeeds(self):
        """Covers lines 77-83: non-dict YAML skipped, second attempt succeeds."""
        non_dict = "- item1\n- item2\n"
        with patch(
            "pipeline.persona.aggregator_llm.GatewayClient",
            return_value=_mock_client([non_dict, _VALID_YAML]),
        ):
            from pipeline.persona.aggregator_llm import generate_advisor_profile

            result = generate_advisor_profile(
                "Advisor", {"gender": "female", "age": 30}, max_retries=2
            )
            assert "traits" in result

    def test_missing_fields_retries_then_succeeds(self):
        """Covers the missing-fields warning branch (lines 89-99)."""
        missing_fields = "education:\n  - MBA\n"  # no experience or traits
        with patch(
            "pipeline.persona.aggregator_llm.GatewayClient",
            return_value=_mock_client([missing_fields, _VALID_YAML]),
        ):
            from pipeline.persona.aggregator_llm import generate_advisor_profile

            result = generate_advisor_profile(
                "Advisor", {"gender": "male", "age": 50}, max_retries=2
            )
            assert "experience" in result

    def test_all_retries_exhausted_raises(self):
        """Covers line 111-114: ValueError raised after all retries fail."""
        with patch(
            "pipeline.persona.aggregator_llm.GatewayClient",
            return_value=_mock_client(["- bad\n- yaml\n", "- also\n- bad\n"]),
        ):
            from pipeline.persona.aggregator_llm import generate_advisor_profile

            with pytest.raises(ValueError, match="Failed to generate"):
                generate_advisor_profile("Advisor", {"gender": "female", "age": 40}, max_retries=2)

    def test_network_error_reraises_on_last_attempt(self):
        """Covers the `if attempt == max_retries: raise` branch."""
        with patch(
            "pipeline.persona.aggregator_llm.GatewayClient",
            return_value=_mock_client([RuntimeError("conn error"), RuntimeError("conn error")]),
        ):
            from pipeline.persona.aggregator_llm import generate_advisor_profile

            with pytest.raises(RuntimeError, match="conn error"):
                generate_advisor_profile("Advisor", {"gender": "male", "age": 30}, max_retries=2)

    def test_network_error_retries_then_succeeds(self):
        """First call raises, second succeeds — covers the warning+continue path."""
        with patch(
            "pipeline.persona.aggregator_llm.GatewayClient",
            return_value=_mock_client([RuntimeError("timeout"), _VALID_YAML]),
        ):
            from pipeline.persona.aggregator_llm import generate_advisor_profile

            result = generate_advisor_profile(
                "Advisor", {"gender": "female", "age": 45}, max_retries=2
            )
            assert "traits" in result
