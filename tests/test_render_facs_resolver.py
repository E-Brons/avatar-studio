"""Tests for FACS unilateral resolver."""

from pipeline.render.llm.facs_resolver import resolve_unilateral


class TestResolveUnilateral:
    def test_no_placeholders(self):
        assert resolve_unilateral("AU6+AU12") == "AU6+AU12"

    def test_placeholder_replaced(self):
        result = resolve_unilateral("AU6+AU2x")
        assert "AU2x" not in result
        assert "AU2R" in result or "AU2L" in result

    def test_multiple_placeholders(self):
        result = resolve_unilateral("AU1x+AU2x")
        assert "AU1x" not in result
        assert "AU2x" not in result

    def test_seeded_rng_deterministic(self):
        import random

        rng1 = random.Random(0)
        rng2 = random.Random(0)
        facs = "AU1x+AU2x"
        assert resolve_unilateral(facs, rng1) == resolve_unilateral(facs, rng2)

    def test_empty_string(self):
        assert resolve_unilateral("") == ""
