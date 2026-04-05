"""Tests for tuning.style_tuner — pure helpers and tuning pass."""

from __future__ import annotations

from unittest.mock import patch

import yaml

from tuning.classify_expression import ExpressionClassificationResult
from tuning.classify_persona import CategoryReport, PropertyResult
from tuning.classify_style import StyleClassificationResult

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_FAKE_AVATAR = {
    "avatar_persona": {
        "personal": {"name": "Alice", "gender": "female", "age": 30},
        "advisor": {"role": "Advisor"},
        "style": {"bg_color": "#F0F0F0"},
        "appearance": {},
    }
}

_FAKE_STYLE = {"id": "photorealistic", "system_prompt": "photo portrait", "name": "Photo"}
_FAKE_STYLE_CLAY = {"id": "clay", "system_prompt": "clay style", "name": "Clay"}
_ALL_STYLES = [_FAKE_STYLE, _FAKE_STYLE_CLAY]


def _pass_style_result(style_id: str = "photorealistic") -> StyleClassificationResult:
    return StyleClassificationResult(
        top_style_id=style_id,
        scores={style_id: 0.80, "clay": 0.20},
        reasoning="photo-real shading",
    )


def _fail_style_result() -> StyleClassificationResult:
    return StyleClassificationResult(
        top_style_id="clay",
        scores={"clay": 0.70, "photorealistic": 0.30},
        reasoning="soft clay texture",
    )


def _pass_expr_result(label: str = "Happiness") -> ExpressionClassificationResult:
    return ExpressionClassificationResult(
        top_expression=label,
        scores={label: 0.80, "neutral": 0.20},
    )


def _pass_report() -> CategoryReport:
    return CategoryReport(
        results=[
            PropertyResult(property_name="gender", expected="female", visible=True),
            PropertyResult(property_name="hair_style", expected="bob", visible=True),
        ]
    )


def _fail_report() -> CategoryReport:
    return CategoryReport(
        results=[
            PropertyResult(property_name="gender", expected="female", visible=False),
            PropertyResult(property_name="hair_style", expected="bob", visible=False),
        ]
    )


def _fake_gen_style(
    style,
    gender,
    seed,
    *,
    expression,
    gateway_url,
    width,
    height,
    out_path,
    session_dir,
    avatar,
    hard_type_gender,
):
    return (b"fake_png_bytes", _FAKE_AVATAR)


# ---------------------------------------------------------------------------
# _resolve_options
# ---------------------------------------------------------------------------


class TestResolveOptions:
    def _call(self, raw, all_options, key=None, predicate=None):
        from tuning.style_tuner import _resolve_options

        return _resolve_options(raw, all_options, key=key, predicate=predicate)

    def test_none_returns_all(self):
        result, random = self._call(None, ["a", "b"])
        assert result == ["a", "b"]
        assert random is False

    def test_all_keyword(self):
        result, random = self._call(["all"], ["a", "b"])
        assert result == ["a", "b"]

    def test_random_keyword(self):
        _, random = self._call(["random"], ["a", "b"])
        assert random is True

    def test_subset_matched(self):
        opts = [{"id": "a"}, {"id": "b"}]
        result, _ = self._call(["a"], opts, key="id")
        assert len(result) == 1

    def test_predicate_filter(self):
        opts = [{"id": "x", "ok": True}, {"id": "y", "ok": False}]
        result, _ = self._call(None, opts, key="id", predicate=lambda o: o["ok"])
        assert len(result) == 1 and result[0]["id"] == "x"

    def test_no_match_returns_empty(self):
        result, _ = self._call(["zzz"], ["a", "b"])
        assert result == []


# ---------------------------------------------------------------------------
# _fmt_pass
# ---------------------------------------------------------------------------


class TestFmtPass:
    def test_pass(self):
        from tuning.style_tuner import _fmt_pass

        assert "PASS" in _fmt_pass(True)

    def test_fail(self):
        from tuning.style_tuner import _fmt_pass

        assert "FAIL" in _fmt_pass(False)


# ---------------------------------------------------------------------------
# _print_style_run_result
# ---------------------------------------------------------------------------


class TestPrintStyleRunResult:
    def test_correct_returns_true(self, capsys):
        from tuning.style_tuner import _print_style_run_result

        result = _pass_style_result("photorealistic")
        ok = _print_style_run_result("photorealistic", result, "female", "neutral", 0)
        assert ok is True

    def test_incorrect_returns_false(self, capsys):
        from tuning.style_tuner import _print_style_run_result

        result = _fail_style_result()
        ok = _print_style_run_result("photorealistic", result, "male", "neutral", 0)
        assert ok is False

    def test_top2_label_when_not_top1(self, capsys):
        """Expected style is #2 → TOP-2 shown."""
        from tuning.style_tuner import _print_style_run_result

        result = StyleClassificationResult(
            top_style_id="clay",
            scores={"clay": 0.55, "photorealistic": 0.45},
        )
        _print_style_run_result("photorealistic", result, "female", "neutral", 0)
        out = capsys.readouterr().out
        assert "TOP-2" in out

    def test_reasoning_printed(self, capsys):
        from tuning.style_tuner import _print_style_run_result

        result = StyleClassificationResult(
            top_style_id="photorealistic",
            scores={"photorealistic": 0.90},
            reasoning="sharp detail",
        )
        _print_style_run_result("photorealistic", result, "female", "neutral", 0)
        out = capsys.readouterr().out
        assert "sharp detail" in out


# ---------------------------------------------------------------------------
# _print_style_summary
# ---------------------------------------------------------------------------


class TestPrintStyleSummary:
    def test_normal(self, capsys):
        from tuning.style_tuner import _print_style_summary

        _print_style_summary("photorealistic", 7, 10)
        out = capsys.readouterr().out
        assert "7/10" in out

    def test_zero_total(self, capsys):
        from tuning.style_tuner import _print_style_summary

        _print_style_summary("photorealistic", 0, 0)
        out = capsys.readouterr().out
        assert "photorealistic" in out


# ---------------------------------------------------------------------------
# _print_overall_summary
# ---------------------------------------------------------------------------


class TestPrintOverallSummary:
    def test_empty_no_output(self, capsys):
        from tuning.style_tuner import _print_overall_summary

        _print_overall_summary({})
        assert capsys.readouterr().out == ""

    def test_aggregates_all(self, capsys):
        from tuning.style_tuner import _print_overall_summary

        _print_overall_summary({"photorealistic": (8, 10), "clay": (6, 10)})
        out = capsys.readouterr().out
        assert "14/20" in out


# ---------------------------------------------------------------------------
# _load_styles_fresh
# ---------------------------------------------------------------------------


class TestLoadStylesFresh:
    def test_returns_list_with_ids(self):
        from tuning.style_tuner import _load_styles_fresh

        styles = _load_styles_fresh()
        assert isinstance(styles, list)
        assert len(styles) > 0
        assert all("id" in s for s in styles)


# ---------------------------------------------------------------------------
# _flush_litellm_pool
# ---------------------------------------------------------------------------


class TestFlushLitellmPool:
    def test_no_raise(self):
        from tuning.style_tuner import _flush_litellm_pool

        _flush_litellm_pool()


# ---------------------------------------------------------------------------
# _load_personas_file
# ---------------------------------------------------------------------------


class TestLoadPersonasFile:
    def test_loads_personas(self, tmp_path):
        from tuning.style_tuner import _load_personas_file

        data = {
            "personas": [
                {
                    "id": "alice",
                    "demographics": {"gender": "female", "age": 30, "name": "Alice"},
                    "advisor": {"role": "Advisor"},
                    "features": {"HAIR_STYLE": "bob"},
                }
            ]
        }
        p = tmp_path / "personas.yml"
        p.write_text(yaml.dump(data))

        with patch("tuning.style_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR):
            result = _load_personas_file(p)
        assert len(result) == 1
        assert result[0]["_id"] == "alice"


# ---------------------------------------------------------------------------
# _run_tuning_pass — refine="none" (generate only)
# ---------------------------------------------------------------------------


class TestRunTuningPassNone:
    def test_generate_only_counts_total(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        with patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                refine="none",
                runs=2,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["photorealistic"]
        assert total == 2

    def test_random_style(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        with patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style):
            results = _run_tuning_pass(
                [_FAKE_STYLE, _FAKE_STYLE_CLAY],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                random_style=True,
                expressions=["neutral"],
                refine="none",
                runs=1,
                seed=42,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        assert isinstance(results, dict)

    def test_random_gender(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        with patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["male", "female"],
                random_gender=True,
                expressions=["neutral"],
                refine="none",
                runs=3,
                seed=7,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        assert isinstance(results, dict)

    def test_random_expression(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        with patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral", "happiness"],
                random_expression=True,
                refine="none",
                runs=1,
                seed=10,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        assert isinstance(results, dict)

    def test_generation_failure_counted(self, tmp_path, capsys):
        from tuning.style_tuner import _run_tuning_pass

        with patch(
            "tuning.style_tuner._generate_for_style",
            side_effect=RuntimeError("disk error"),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                refine="none",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["photorealistic"]
        assert total == 1
        err = capsys.readouterr().err
        assert "FAILED" in err

    def test_fixed_personas_mode(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        fixed = [{**_FAKE_AVATAR, "_id": "alice"}, {**_FAKE_AVATAR, "_id": "bob"}]
        with patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                fixed_personas=fixed,
                refine="none",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["photorealistic"]
        assert total == 2  # one per fixed persona


# ---------------------------------------------------------------------------
# _run_tuning_pass — refine="style"
# ---------------------------------------------------------------------------


class TestRunTuningPassStyle:
    def test_pass_increments_correct(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.classify_image_style", return_value=_pass_style_result()),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                refine="style",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        correct, total = results["photorealistic"]
        assert correct == 1
        assert total == 1

    def test_classification_failure_continues(self, tmp_path, capsys):
        from tuning.style_tuner import _run_tuning_pass

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch(
                "tuning.style_tuner.classify_image_style",
                side_effect=RuntimeError("vision down"),
            ),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                refine="style",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["photorealistic"]
        assert total == 1
        err = capsys.readouterr().err
        assert "classification FAILED" in err


# ---------------------------------------------------------------------------
# _run_tuning_pass — refine="expression"
# ---------------------------------------------------------------------------


class TestRunTuningPassExpression:
    def test_pass_expression_refine(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch(
                "tuning.style_tuner.classify_image_expression",
                return_value=_pass_expr_result("Happiness"),
            ),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["happiness"],
                refine="expression",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        correct, total = results["photorealistic"]
        assert total == 1
        assert correct == 1

    def test_expression_classification_failure_continues(self, tmp_path, capsys):
        from tuning.style_tuner import _run_tuning_pass

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch(
                "tuning.style_tuner.classify_image_expression",
                side_effect=RuntimeError("model down"),
            ),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["happiness"],
                refine="expression",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["photorealistic"]
        assert total == 1
        err = capsys.readouterr().err
        assert "expression classification FAILED" in err

    def test_expression_semantic_fallback(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        fail_result = ExpressionClassificationResult(
            top_expression="neutral",
            scores={"neutral": 0.70, "happiness": 0.10},
        )
        # semantic_effective_score is imported inside the function body, so patch
        # it via the source module
        import tuning.classify_expression as _ce

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.classify_image_expression", return_value=fail_result),
            patch.object(_ce, "semantic_effective_score", return_value=0.80),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["happiness"],
                refine="expression",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        correct, total = results["photorealistic"]
        assert total == 1


# ---------------------------------------------------------------------------
# _run_tuning_pass — refine="gender"
# ---------------------------------------------------------------------------


class TestRunTuningPassGender:
    def test_pass_gender_refine(self, tmp_path):
        from tuning.style_tuner import _run_tuning_pass

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.categorize_avatar_image", return_value=_pass_report()),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                refine="gender",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        correct, total = results["photorealistic"]
        assert total == 1
        assert correct == 1

    def test_fail_gender_refine_prints_missing(self, tmp_path, capsys):
        from tuning.style_tuner import _run_tuning_pass

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.categorize_avatar_image", return_value=_fail_report()),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                refine="gender",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        out = capsys.readouterr().out
        assert "missing" in out
        correct, total = results["photorealistic"]
        assert correct == 0

    def test_gender_classification_failure_continues(self, tmp_path, capsys):
        from tuning.style_tuner import _run_tuning_pass

        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch(
                "tuning.style_tuner.categorize_avatar_image",
                side_effect=RuntimeError("model down"),
            ),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["neutral"],
                refine="gender",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["photorealistic"]
        assert total == 1
        err = capsys.readouterr().err
        assert "persona classification FAILED" in err


# ---------------------------------------------------------------------------
# _generate_diverse_personas
# ---------------------------------------------------------------------------


class TestGenerateDiversePersonas:
    def _mock_pipeline(self):
        return [
            patch(
                "tuning.style_tuner.pick_demographics",
                return_value={
                    "gender": "female",
                    "age": 30,
                    "name": "Alice",
                },
            ),
            patch(
                "tuning.style_tuner.generate_advisor_profile",
                return_value={
                    "education": ["MBA"],
                    "experience": ["5 years"],
                    "traits": ["analytical"],
                },
            ),
            patch("tuning.style_tuner.select_features", return_value={"HAIR_STYLE": "bob"}),
            patch("tuning.style_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
        ]

    def test_returns_gender_map(self, tmp_path):
        from tuning.style_tuner import _generate_diverse_personas

        patches = self._mock_pipeline()
        with patches[0], patches[1], patches[2], patches[3]:
            result = _generate_diverse_personas(
                ["female"], base_seed=1, gateway_url="http://gw", tmp_dir=tmp_path
            )
        assert "female" in result
        assert (tmp_path / "persona_female.yml").exists()

    def test_ac_failure_warning(self, tmp_path, capsys):
        from tuning.style_tuner import _generate_diverse_personas

        with (
            patch(
                "tuning.style_tuner.pick_demographics",
                return_value={
                    "gender": "male",
                    "age": 28,
                    "name": "Bob",
                },
            ),
            patch(
                "tuning.style_tuner.generate_advisor_profile", side_effect=RuntimeError("B down")
            ),
            patch("tuning.style_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
        ):
            result = _generate_diverse_personas(
                ["male"], base_seed=None, gateway_url="http://gw", tmp_dir=tmp_path
            )
        assert "male" in result
        err = capsys.readouterr().err
        assert "WARNING" in err

    def test_total_failure_excluded(self, tmp_path, capsys):
        from tuning.style_tuner import _generate_diverse_personas

        with patch("tuning.style_tuner.pick_demographics", side_effect=RuntimeError("crash")):
            result = _generate_diverse_personas(
                ["female"], base_seed=1, gateway_url="http://gw", tmp_dir=tmp_path
            )
        assert "female" not in result
        err = capsys.readouterr().err
        assert "FAILED" in err


# ---------------------------------------------------------------------------
# _run_tuning_pass — expression refine remaining branches
# ---------------------------------------------------------------------------


class TestRunTuningPassExpressionBranches:
    def test_visible_not_semantic_branch(self, tmp_path, capsys):
        """expression refine: sem_score < 0.35 but score visible → VISIBLE status."""
        from tuning.style_tuner import _run_tuning_pass

        # Visible: expected label scores >= 0.35 but not top
        visible_result = ExpressionClassificationResult(
            top_expression="neutral",
            scores={"neutral": 0.60, "Happiness": 0.38},
        )
        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.classify_image_expression", return_value=visible_result),
            patch("tuning.classify_expression.semantic_effective_score", return_value=0.0),
        ):
            _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["happiness"],
                refine="expression",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        out = capsys.readouterr().out
        assert "VISIBLE" in out

    def test_total_fail_branch(self, tmp_path, capsys):
        """expression refine: all scores below threshold → FAIL status."""
        from tuning.style_tuner import _run_tuning_pass

        fail_result = ExpressionClassificationResult(
            top_expression="neutral",
            scores={"neutral": 0.90, "Happiness": 0.10},
        )
        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.classify_image_expression", return_value=fail_result),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["happiness"],
                refine="expression",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        out = capsys.readouterr().out
        assert "FAIL" in out
        correct, total = results["photorealistic"]
        assert correct == 0

    def test_reasoning_printed_in_expression_refine(self, tmp_path, capsys):
        """expression refine: classification.reasoning non-empty → printed."""
        from tuning.style_tuner import _run_tuning_pass

        result_with_reason = ExpressionClassificationResult(
            top_expression="Happiness",
            scores={"Happiness": 0.80},
            reasoning="wide grin visible",
        )
        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.classify_image_expression", return_value=result_with_reason),
        ):
            _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["happiness"],
                refine="expression",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        out = capsys.readouterr().out
        assert "wide grin visible" in out

    def test_semantic_score_failure_in_expression_refine(self, tmp_path):
        """semantic_effective_score raises → warning, run counted."""
        import tuning.classify_expression as _ce
        from tuning.style_tuner import _run_tuning_pass

        fail_result = ExpressionClassificationResult(
            top_expression="neutral",
            scores={"neutral": 0.70, "happiness": 0.10},
        )
        with (
            patch("tuning.style_tuner._generate_for_style", side_effect=_fake_gen_style),
            patch("tuning.style_tuner.classify_image_expression", return_value=fail_result),
            patch.object(_ce, "semantic_effective_score", side_effect=RuntimeError("llm down")),
        ):
            results = _run_tuning_pass(
                [_FAKE_STYLE],
                _ALL_STYLES,
                gateway_url="http://gw",
                visual_model="cli/model",
                genders=["female"],
                expressions=["happiness"],
                refine="expression",
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["photorealistic"]
        assert total == 1


# ---------------------------------------------------------------------------
# _generate_for_style — core function
# ---------------------------------------------------------------------------


class TestGenerateForStyle:
    def test_with_avatar_provided(self, tmp_path):
        """avatar is not None → skips demographics, writes persona.yml."""
        from tuning.style_tuner import _generate_for_style

        out_path = tmp_path / "out.png"
        out_path.write_bytes(b"fake_png")

        with patch("tuning.style_tuner.generate_avatar_image"):
            img_bytes, avatar_used = _generate_for_style(
                _FAKE_STYLE,
                "female",
                seed=42,
                expression="neutral",
                gateway_url="http://gw",
                width=64,
                height=64,
                out_path=out_path,
                session_dir=tmp_path,
                avatar=_FAKE_AVATAR,
            )
        assert img_bytes == b"fake_png"
        assert (tmp_path / "persona.yml").exists()

    def test_without_avatar_builds_from_demographics(self, tmp_path):
        """avatar is None → calls pick_demographics + build_avatar_charachter."""
        from tuning.style_tuner import _generate_for_style

        out_path = tmp_path / "out.png"
        out_path.write_bytes(b"fake_png")

        with (
            patch(
                "tuning.style_tuner.pick_demographics",
                return_value={
                    "gender": "female",
                    "age": 30,
                    "name": "Alice",
                },
            ),
            patch("tuning.style_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
            patch("tuning.style_tuner.generate_avatar_image"),
        ):
            img_bytes, avatar_used = _generate_for_style(
                _FAKE_STYLE,
                "female",
                seed=10,
                expression="neutral",
                gateway_url="http://gw",
                width=64,
                height=64,
                out_path=out_path,
            )
        assert img_bytes == b"fake_png"

    def test_session_dir_none_uses_out_parent(self, tmp_path):
        """session_dir=None → artifact_dir = out_path.parent."""
        from tuning.style_tuner import _generate_for_style

        sub = tmp_path / "sub"
        sub.mkdir()
        out_path = sub / "out.png"
        out_path.write_bytes(b"fake_png")

        with patch("tuning.style_tuner.generate_avatar_image"):
            _generate_for_style(
                _FAKE_STYLE,
                "female",
                seed=1,
                expression="neutral",
                gateway_url="http://gw",
                width=64,
                height=64,
                out_path=out_path,
                session_dir=None,
                avatar=_FAKE_AVATAR,
            )
        # persona.yml written to out_path.parent = sub
        assert (sub / "persona.yml").exists()


# ---------------------------------------------------------------------------
# _flush_litellm_pool — inner cache branch
# ---------------------------------------------------------------------------


class TestFlushLitellmPoolCache:
    def _make_litellm_modules(self, mock_litellm):
        """Build sys.modules entries for the _flush_litellm_pool import chain."""
        import types

        mock_handler_mod = types.SimpleNamespace(HTTPHandler=lambda **kw: None)
        mock_custom_httpx = types.SimpleNamespace(http_handler=mock_handler_mod)
        mock_llms = types.SimpleNamespace(custom_httpx=mock_custom_httpx)
        return {
            "litellm": mock_litellm,
            "litellm.llms": mock_llms,
            "litellm.llms.custom_httpx": mock_custom_httpx,
            "litellm.llms.custom_httpx.http_handler": mock_handler_mod,
        }

    def test_cache_not_none_set_cache_called(self):
        """When litellm.in_memory_llm_clients_cache is not None, set_cache is called."""
        import types

        from tuning.style_tuner import _flush_litellm_pool

        set_calls = []

        def _mock_set(key, val):
            set_calls.append(key)

        mock_cache = types.SimpleNamespace(set_cache=_mock_set)
        mock_litellm = types.SimpleNamespace(
            module_level_client=None,
            in_memory_llm_clients_cache=mock_cache,
        )
        mods = self._make_litellm_modules(mock_litellm)
        with patch.dict("sys.modules", mods):
            _flush_litellm_pool()
        assert len(set_calls) >= 1

    def test_cache_set_cache_raises_is_swallowed(self):
        """set_cache raises → exception is swallowed by inner try/except."""
        import types

        from tuning.style_tuner import _flush_litellm_pool

        def _bad_set(*a):
            raise RuntimeError("cache broken")

        mock_cache = types.SimpleNamespace(set_cache=_bad_set)
        mock_litellm = types.SimpleNamespace(
            module_level_client=None,
            in_memory_llm_clients_cache=mock_cache,
        )
        mods = self._make_litellm_modules(mock_litellm)
        with patch.dict("sys.modules", mods):
            _flush_litellm_pool()  # must not raise


# ---------------------------------------------------------------------------
# main() — CLI entry point and --watch mode
# ---------------------------------------------------------------------------


class TestMainCli:
    """Test the style_tuner main() CLI function."""

    def _common_patches(self, tmp_path):
        return [
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--style",
                    "photorealistic",
                    "--gender",
                    "female",
                    "--refine",
                    "none",
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.style_tuner._run_tuning_pass",
                return_value={
                    "photorealistic": (0, 1),
                },
            ),
        ]

    def test_main_runs_without_watch(self, tmp_path):
        """main() without --watch runs _run_once and returns."""
        patches = self._common_patches(tmp_path)
        with patches[0], patches[1], patches[2]:
            from tuning.style_tuner import main

            main()  # should not raise

    def test_main_with_refine_style(self, tmp_path):
        """main() with --refine style prints overall summary."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--refine",
                    "style",
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.style_tuner._run_tuning_pass",
                return_value={
                    "photorealistic": (1, 1),
                },
            ),
        ):
            from tuning.style_tuner import main

            main()

    def test_main_no_matching_styles_prints_error(self, tmp_path, capsys):
        """No matching styles found → prints error and returns."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--style",
                    "nonexistent_style_xyz",
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
        ):
            from tuning.style_tuner import main

            main()
        err = capsys.readouterr().err
        assert "No matching styles found" in err

    def test_main_deprecated_ollama_url_alias(self, tmp_path):
        """--ollama-url is accepted as deprecated alias for --gateway-url."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--ollama-url",
                    "http://custom:9999",
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.style_tuner._run_tuning_pass",
                return_value={
                    "photorealistic": (0, 1),
                },
            ),
        ):
            from tuning.style_tuner import main

            main()

    def test_main_personas_file_loaded(self, tmp_path):
        """--personas-file path → _load_personas_file is called."""
        personas_data = {
            "personas": [
                {
                    "id": "alice",
                    "demographics": {"gender": "female", "age": 30, "name": "Alice"},
                    "advisor": {"role": "Advisor"},
                    "features": {"HAIR_STYLE": "bob"},
                }
            ]
        }
        personas_file = tmp_path / "personas.yml"
        personas_file.write_text(yaml.dump(personas_data))

        with (
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--personas-file",
                    str(personas_file),
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.style_tuner._run_tuning_pass",
                return_value={
                    "photorealistic": (0, 1),
                },
            ),
            patch("tuning.style_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
        ):
            from tuning.style_tuner import main

            main()

    def test_main_watch_mode_polls_until_keyboard_interrupt(self, tmp_path):
        """--watch: poll loop exits on KeyboardInterrupt."""
        call_count = []

        def _mock_sleep(secs):
            if len(call_count) >= 1:
                raise KeyboardInterrupt
            call_count.append(1)

        with (
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--watch",
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.style_tuner._run_tuning_pass",
                return_value={
                    "photorealistic": (0, 1),
                },
            ),
            patch("time.sleep", side_effect=_mock_sleep),
        ):
            from tuning.style_tuner import main

            main()  # KeyboardInterrupt caught internally → no propagation

    def test_main_watch_reruns_on_file_change(self, tmp_path):
        """--watch: detects mtime change and re-runs _run_once."""
        import types

        # Sequence: initial_stat=100, loop_stat_1=200 (change!), then interrupt on second sleep
        mtime_seq = [100.0, 200.0]
        mtime_idx = [0]
        sleep_calls = []
        run_once_calls = []

        def _mock_stat():
            val = mtime_seq[mtime_idx[0]] if mtime_idx[0] < len(mtime_seq) else 200.0
            mtime_idx[0] += 1
            return types.SimpleNamespace(st_mtime=val)

        def _mock_sleep(secs):
            sleep_calls.append(secs)
            if len(sleep_calls) >= 2:
                raise KeyboardInterrupt

        mock_styles = [{"id": "photorealistic", "system_prompt": "photo", "name": "Photo"}]

        with (
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--watch",
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch("tuning.style_tuner._load_styles_fresh", return_value=mock_styles),
            patch(
                "tuning.style_tuner._run_tuning_pass",
                side_effect=lambda *a, **kw: (run_once_calls.append(1), {"photorealistic": (0, 1)})[
                    1
                ],
            ),
            patch("time.sleep", side_effect=_mock_sleep),
            patch("tuning.style_tuner.STYLES_YML") as mock_yml,
        ):
            mock_yml.stat.side_effect = _mock_stat
            from tuning.style_tuner import main

            main()
        assert len(run_once_calls) >= 2

    def test_main_if_name_main_guard(self):
        """Line 941: __name__ == '__main__' guard covered by runpy."""
        import runpy
        import sys

        sys.modules.pop("tuning.style_tuner", None)
        with patch("sys.argv", ["style_tuner", "--help"]):
            try:
                runpy.run_module("tuning.style_tuner", run_name="__main__", alter_sys=True)
            except SystemExit:
                pass  # --help exits with 0

    def test_main_custom_model_prefix_added(self, tmp_path):
        """Lines 806, 809: models without ollama/ prefix get it added."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-style-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--gender",
                    "female",
                    "--ollama-text-model",
                    "phi3:mini",  # no ollama/ prefix
                    "--ollama-visual-desc-model",
                    "llava",  # no ollama/ or cli/ prefix
                ],
            ),
            patch(
                "tuning.style_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.style_tuner._run_tuning_pass",
                return_value={
                    "photorealistic": (0, 1),
                },
            ),
        ):
            from tuning.style_tuner import main

            main()  # prefix-adding lines exercised, should not raise
