"""Tests for tuning.expression_tuner — pure helpers and tuning pass."""

from __future__ import annotations

from unittest.mock import patch

from tuning.classify_expression import ExpressionClassificationResult

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

_FAKE_EXPR = {"id": "happiness", "expression": "Happiness", "synonyms": ["happy", "joy"]}
_FAKE_STYLE = {"id": "photorealistic", "system_prompt": "photo portrait", "name": "Photo"}


def _pass_result(label: str = "Happiness") -> ExpressionClassificationResult:
    return ExpressionClassificationResult(
        top_expression=label,
        scores={label: 0.80, "neutral": 0.20},
        reasoning="clear smile",
    )


def _fail_result(label: str = "Happiness") -> ExpressionClassificationResult:
    return ExpressionClassificationResult(
        top_expression="neutral",
        scores={"neutral": 0.80, label: 0.10},
        reasoning="flat expression",
    )


def _fake_gen(
    expr_id,
    style,
    gender,
    seed,
    *,
    gateway_url,
    width,
    height,
    optimize,
    out_path,
    session_dir,
    avatar,
    hard_type_gender,
):
    """Fake _generate_for_expression — no disk I/O."""
    return (b"fake_png_bytes", _FAKE_AVATAR)


# ---------------------------------------------------------------------------
# _resolve_options
# ---------------------------------------------------------------------------


class TestResolveOptions:
    def _call(self, raw, all_options, key=None, predicate=None):
        from tuning.expression_tuner import _resolve_options

        return _resolve_options(raw, all_options, key=key, predicate=predicate)

    def test_none_returns_all(self):
        result, random = self._call(None, ["a", "b", "c"])
        assert result == ["a", "b", "c"]
        assert random is False

    def test_all_returns_all(self):
        result, random = self._call(["all"], ["a", "b"])
        assert result == ["a", "b"]
        assert random is False

    def test_random_returns_all_use_random_true(self):
        result, random = self._call(["random"], ["a", "b"])
        assert result == ["a", "b"]
        assert random is True

    def test_subset_matched_by_key(self):
        opts = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result, random = self._call(["a", "c"], opts, key="id")
        assert [o["id"] for o in result] == ["a", "c"]
        assert random is False

    def test_no_match_returns_empty(self):
        result, random = self._call(["nonexistent"], ["a", "b"])
        assert result == []
        assert random is False

    def test_predicate_filters_all(self):
        opts = [{"id": "a", "ok": True}, {"id": "b", "ok": False}]
        result, _ = self._call(None, opts, key="id", predicate=lambda o: o["ok"])
        assert len(result) == 1
        assert result[0]["id"] == "a"


# ---------------------------------------------------------------------------
# _fmt_pass
# ---------------------------------------------------------------------------


class TestFmtPass:
    def test_ok_returns_pass(self):
        from tuning.expression_tuner import _fmt_pass

        assert "PASS" in _fmt_pass(True)

    def test_semantic_ok_returns_semantic(self):
        from tuning.expression_tuner import _fmt_pass

        assert "SEMANTIC" in _fmt_pass(False, semantic=True)

    def test_visible_returns_visible(self):
        from tuning.expression_tuner import _fmt_pass

        assert "VISIBLE" in _fmt_pass(False, semantic=False, visible=True)

    def test_fail_returns_fail(self):
        from tuning.expression_tuner import _fmt_pass

        assert "FAIL" in _fmt_pass(False)


# ---------------------------------------------------------------------------
# _expression_labels
# ---------------------------------------------------------------------------


class TestExpressionLabels:
    def test_returns_expression_field(self):
        from tuning.expression_tuner import _expression_labels

        exprs = [{"id": "happiness", "expression": "Happiness"}, {"id": "sadness"}]
        labels = _expression_labels(exprs)
        assert labels[0] == "Happiness"
        assert labels[1] == "sadness"  # falls back to id


# ---------------------------------------------------------------------------
# _print_expression_summary
# ---------------------------------------------------------------------------


class TestPrintExpressionSummary:
    def test_100_pct_prints_green(self, capsys):
        from tuning.expression_tuner import _print_expression_summary

        _print_expression_summary("happiness", 5, 5)
        out = capsys.readouterr().out
        assert "happiness" in out
        assert "5/5" in out

    def test_zero_total_no_crash(self, capsys):
        from tuning.expression_tuner import _print_expression_summary

        _print_expression_summary("happiness", 0, 0)
        out = capsys.readouterr().out
        assert "happiness" in out

    def test_low_pct_red(self, capsys):
        from tuning.expression_tuner import _print_expression_summary

        _print_expression_summary("anger", 1, 10)
        out = capsys.readouterr().out
        assert "1/10" in out


# ---------------------------------------------------------------------------
# _print_overall_summary
# ---------------------------------------------------------------------------


class TestPrintOverallSummary:
    def test_empty_dict_no_output(self, capsys):
        from tuning.expression_tuner import _print_overall_summary

        _print_overall_summary({})
        assert capsys.readouterr().out == ""

    def test_normal_case(self, capsys):
        from tuning.expression_tuner import _print_overall_summary

        _print_overall_summary({"happiness": (8, 10), "sadness": (5, 10)})
        out = capsys.readouterr().out
        assert "13/20" in out


# ---------------------------------------------------------------------------
# _print_expression_run_result
# ---------------------------------------------------------------------------


class TestPrintExpressionRunResult:
    def test_pass_returns_true(self, capsys):
        from tuning.expression_tuner import _print_expression_run_result

        result = _pass_result("Happiness")
        ok = _print_expression_run_result("Happiness", result, "female", "photorealistic", 0, 0.35)
        assert ok is True

    def test_fail_returns_false(self, capsys):
        from tuning.expression_tuner import _print_expression_run_result

        result = _fail_result("Happiness")
        ok = _print_expression_run_result("Happiness", result, "male", "photorealistic", 0, 0.35)
        assert ok is False

    def test_semantic_pass(self, capsys):
        from tuning.expression_tuner import _print_expression_run_result

        result = _fail_result("Happiness")
        ok = _print_expression_run_result(
            "Happiness", result, "male", "photorealistic", 0, 0.35, semantic_score=0.80
        )
        assert ok is True

    def test_reasoning_printed(self, capsys):
        from tuning.expression_tuner import _print_expression_run_result

        result = _pass_result("Happiness")
        _print_expression_run_result("Happiness", result, "female", "photorealistic", 0, 0.35)
        out = capsys.readouterr().out
        assert "clear smile" in out


# ---------------------------------------------------------------------------
# _load_expressions_fresh / _load_styles_fresh
# ---------------------------------------------------------------------------


class TestLoadFresh:
    def test_load_expressions_returns_list(self):
        from tuning.expression_tuner import _load_expressions_fresh

        exprs = _load_expressions_fresh()
        assert isinstance(exprs, list)
        assert len(exprs) > 0
        assert all("id" in e for e in exprs)

    def test_load_styles_returns_list(self):
        from tuning.expression_tuner import _load_styles_fresh

        styles = _load_styles_fresh()
        assert isinstance(styles, list)
        assert len(styles) > 0


# ---------------------------------------------------------------------------
# _flush_litellm_pool — should never raise
# ---------------------------------------------------------------------------


class TestFlushLitellmPool:
    def test_no_raise(self):
        from tuning.expression_tuner import _flush_litellm_pool

        _flush_litellm_pool()  # OK if litellm not installed — swallows exceptions


# ---------------------------------------------------------------------------
# _run_tuning_pass — refine=False (generate only)
# ---------------------------------------------------------------------------


class TestRunTuningPassNoRefine:
    def test_counts_total_without_classification(self, tmp_path):
        from tuning.expression_tuner import _run_tuning_pass

        with patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                refine=False,
                runs=2,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        assert "happiness" in results
        _correct, total = results["happiness"]
        assert total == 2

    def test_random_style_picks_from_list(self, tmp_path):
        from tuning.expression_tuner import _run_tuning_pass

        styles = [
            {"id": "photorealistic", "system_prompt": "photo", "name": "Photo"},
            {"id": "clay", "system_prompt": "clay", "name": "Clay"},
        ]
        with patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=styles,
                random_style=True,
                gateway_url="http://gw",
                genders=["female"],
                refine=False,
                runs=1,
                seed=42,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        assert "happiness" in results

    def test_random_gender_picks_from_list(self, tmp_path):
        from tuning.expression_tuner import _run_tuning_pass

        with patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["male", "female"],
                random_gender=True,
                refine=False,
                runs=3,
                seed=7,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        assert "happiness" in results

    def test_random_expression_picks_from_list(self, tmp_path):
        from tuning.expression_tuner import _run_tuning_pass

        with patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                random_expression=True,
                refine=False,
                runs=1,
                seed=42,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        assert isinstance(results, dict)


# ---------------------------------------------------------------------------
# _run_tuning_pass — refine=True, classification paths
# ---------------------------------------------------------------------------


class TestRunTuningPassWithRefine:
    def test_pass_increments_correct(self, tmp_path, capsys):
        from tuning.expression_tuner import _run_tuning_pass

        with (
            patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen),
            patch("tuning.expression_tuner.classify_image_expression", return_value=_pass_result()),
        ):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                refine=True,
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        correct, total = results["happiness"]
        assert correct == 1
        assert total == 1

    def test_fail_with_semantic_fallback(self, tmp_path):
        from tuning.expression_tuner import _run_tuning_pass

        with (
            patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen),
            patch("tuning.expression_tuner.classify_image_expression", return_value=_fail_result()),
            patch("tuning.expression_tuner.semantic_effective_score", return_value=0.80),
        ):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                refine=True,
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        correct, total = results["happiness"]
        assert correct == 1  # semantic pass counts

    def test_synonym_score_passes(self, tmp_path):
        """Synonym matches bypass semantic_effective_score call."""
        from tuning.expression_tuner import _run_tuning_pass

        # "happy" is a synonym of Happiness; score >= threshold → synonym pass
        synonym_result = ExpressionClassificationResult(
            top_expression="neutral",
            scores={"neutral": 0.50, "happy": 0.45},
        )
        with (
            patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen),
            patch("tuning.expression_tuner.classify_image_expression", return_value=synonym_result),
        ):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                refine=True,
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        correct, total = results["happiness"]
        assert correct == 1

    def test_generation_failure_counts_as_total(self, tmp_path, capsys):
        from tuning.expression_tuner import _run_tuning_pass

        with patch(
            "tuning.expression_tuner._generate_for_expression",
            side_effect=RuntimeError("gpu down"),
        ):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                refine=True,
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["happiness"]
        assert total == 1
        err = capsys.readouterr().err
        assert "FAILED" in err

    def test_classification_failure_continues(self, tmp_path, capsys):
        from tuning.expression_tuner import _run_tuning_pass

        with (
            patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen),
            patch(
                "tuning.expression_tuner.classify_image_expression",
                side_effect=RuntimeError("vision down"),
            ),
        ):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                refine=True,
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["happiness"]
        assert total == 1
        err = capsys.readouterr().err
        assert "classification FAILED" in err

    def test_semantic_score_failure_continues(self, tmp_path):
        """semantic_effective_score raises → warning logged, run counted as fail."""
        from tuning.expression_tuner import _run_tuning_pass

        with (
            patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen),
            patch("tuning.expression_tuner.classify_image_expression", return_value=_fail_result()),
            patch(
                "tuning.expression_tuner.semantic_effective_score",
                side_effect=RuntimeError("llm down"),
            ),
        ):
            results = _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=[_FAKE_STYLE],
                gateway_url="http://gw",
                genders=["female"],
                refine=True,
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        _correct, total = results["happiness"]
        assert total == 1

    def test_multiple_styles_printed(self, tmp_path, capsys):
        """When len(styles) > 1, style header line is printed."""
        from tuning.expression_tuner import _run_tuning_pass

        styles = [
            {"id": "photorealistic", "system_prompt": "photo", "name": "Photo"},
            {"id": "clay", "system_prompt": "clay", "name": "Clay"},
        ]
        with (
            patch("tuning.expression_tuner._generate_for_expression", side_effect=_fake_gen),
            patch("tuning.expression_tuner.classify_image_expression", return_value=_pass_result()),
        ):
            _run_tuning_pass(
                [_FAKE_EXPR],
                ["Happiness"],
                styles=styles,
                gateway_url="http://gw",
                genders=["female"],
                refine=True,
                runs=1,
                seed=1,
                width=64,
                height=64,
                tmp_dir=tmp_path,
            )
        out = capsys.readouterr().out
        assert "photorealistic" in out or "clay" in out


# ---------------------------------------------------------------------------
# _generate_diverse_personas
# ---------------------------------------------------------------------------


class TestGenerateDiversePersonas:
    def _mock_pipeline(self):
        return [
            patch(
                "tuning.expression_tuner.pick_demographics",
                return_value={
                    "gender": "female",
                    "age": 30,
                    "name": "Alice",
                },
            ),
            patch(
                "tuning.expression_tuner.generate_advisor_profile",
                return_value={
                    "education": ["MBA"],
                    "experience": ["5 years"],
                    "traits": ["analytical"],
                },
            ),
            patch("tuning.expression_tuner.select_features", return_value={"HAIR_STYLE": "bob"}),
            patch("tuning.expression_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
        ]

    def test_returns_gender_keyed_map(self, tmp_path):
        from tuning.expression_tuner import _generate_diverse_personas

        patches = self._mock_pipeline()
        with patches[0], patches[1], patches[2], patches[3]:
            result = _generate_diverse_personas(
                ["female"], base_seed=42, gateway_url="http://gw", tmp_dir=tmp_path
            )
        assert "female" in result
        assert (tmp_path / "persona_female.yml").exists()

    def test_ac_failure_still_builds_persona(self, tmp_path, capsys):
        from tuning.expression_tuner import _generate_diverse_personas

        with (
            patch(
                "tuning.expression_tuner.pick_demographics",
                return_value={
                    "gender": "male",
                    "age": 28,
                    "name": "Bob",
                },
            ),
            patch(
                "tuning.expression_tuner.generate_advisor_profile",
                side_effect=RuntimeError("B down"),
            ),
            patch("tuning.expression_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
        ):
            result = _generate_diverse_personas(
                ["male"], base_seed=None, gateway_url="http://gw", tmp_dir=tmp_path
            )
        assert "male" in result
        err = capsys.readouterr().err
        assert "WARNING" in err

    def test_total_failure_excluded(self, tmp_path, capsys):
        from tuning.expression_tuner import _generate_diverse_personas

        with (
            patch("tuning.expression_tuner.pick_demographics", side_effect=RuntimeError("A down")),
        ):
            result = _generate_diverse_personas(
                ["female"], base_seed=1, gateway_url="http://gw", tmp_dir=tmp_path
            )
        assert "female" not in result
        err = capsys.readouterr().err
        assert "FAILED" in err

    def test_multiple_genders_different_seeds(self, tmp_path):
        from tuning.expression_tuner import _generate_diverse_personas

        seeds_used = []

        def _cap_demo(seed=None, hard_type_gender=False):
            seeds_used.append(seed)
            return {"gender": "female", "age": 30, "name": "Alice"}

        with (
            patch("tuning.expression_tuner.pick_demographics", side_effect=_cap_demo),
            patch("tuning.expression_tuner.generate_advisor_profile", side_effect=RuntimeError),
            patch("tuning.expression_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
        ):
            _generate_diverse_personas(
                ["male", "female"], base_seed=10, gateway_url="http://gw", tmp_dir=tmp_path
            )
        assert len(seeds_used) == 2
        assert seeds_used[0] != seeds_used[1]


# ---------------------------------------------------------------------------
# _generate_for_expression — image generation helper
# ---------------------------------------------------------------------------


class TestGenerateForExpression:
    def test_with_avatar_provided(self, tmp_path):
        """avatar is not None → skips demographics, writes persona.yml, returns bytes."""
        from tuning.expression_tuner import _generate_for_expression

        out_path = tmp_path / "out.png"
        out_path.write_bytes(b"fake_png")

        with patch("tuning.expression_tuner.generate_avatar_image"):
            img_bytes, avatar_used = _generate_for_expression(
                "happiness",
                _FAKE_STYLE,
                "female",
                seed=42,
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
        from tuning.expression_tuner import _generate_for_expression

        out_path = tmp_path / "out.png"
        out_path.write_bytes(b"fake_png")

        with (
            patch(
                "tuning.expression_tuner.pick_demographics",
                return_value={
                    "gender": "female",
                    "age": 30,
                    "name": "Alice",
                },
            ),
            patch("tuning.expression_tuner.build_avatar_charachter", return_value=_FAKE_AVATAR),
            patch("tuning.expression_tuner.generate_avatar_image"),
        ):
            img_bytes, avatar_used = _generate_for_expression(
                "happiness",
                _FAKE_STYLE,
                "female",
                seed=10,
                gateway_url="http://gw",
                width=64,
                height=64,
                out_path=out_path,
            )
        assert img_bytes == b"fake_png"

    def test_session_dir_none_uses_out_parent(self, tmp_path):
        """session_dir=None → artifact_dir = out_path.parent."""
        from tuning.expression_tuner import _generate_for_expression

        sub = tmp_path / "sub"
        sub.mkdir()
        out_path = sub / "out.png"
        out_path.write_bytes(b"fake_png")

        with patch("tuning.expression_tuner.generate_avatar_image"):
            _generate_for_expression(
                "happiness",
                _FAKE_STYLE,
                "female",
                seed=1,
                gateway_url="http://gw",
                width=64,
                height=64,
                out_path=out_path,
                session_dir=None,
                avatar=_FAKE_AVATAR,
            )
        assert (sub / "persona.yml").exists()


# ---------------------------------------------------------------------------
# _flush_litellm_pool — inner cache branch
# ---------------------------------------------------------------------------


class TestFlushLitellmPoolCache:
    def _make_litellm_modules(self, mock_litellm):
        """Build the sys.modules entries needed for the _flush_litellm_pool import chain."""
        import types

        # The function does:
        #   import httpx; import litellm
        #   from litellm.llms.custom_httpx.http_handler import HTTPHandler
        # We need to mock the submodule path so the import succeeds.
        mock_handler_mod = types.SimpleNamespace(HTTPHandler=lambda **kw: None)
        mock_custom_httpx = types.SimpleNamespace(http_handler=mock_handler_mod)
        mock_llms = types.SimpleNamespace(custom_httpx=mock_custom_httpx)
        return {
            "litellm": mock_litellm,
            "litellm.llms": mock_llms,
            "litellm.llms.custom_httpx": mock_custom_httpx,
            "litellm.llms.custom_httpx.http_handler": mock_handler_mod,
        }

    def test_cache_not_none_branch(self):
        """When litellm.in_memory_llm_clients_cache is not None, set_cache is called."""
        import types

        from tuning.expression_tuner import _flush_litellm_pool

        set_calls = []
        mock_cache = types.SimpleNamespace(set_cache=lambda *a: set_calls.append(a))
        mock_litellm = types.SimpleNamespace(
            module_level_client=None,
            in_memory_llm_clients_cache=mock_cache,
        )
        mods = self._make_litellm_modules(mock_litellm)
        with patch.dict("sys.modules", mods):
            _flush_litellm_pool()
        # set_cache should have been called for the two keys
        assert len(set_calls) >= 1

    def test_cache_set_cache_raises(self):
        """When set_cache raises, exception is swallowed."""
        import types

        from tuning.expression_tuner import _flush_litellm_pool

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
    """Test the expression_tuner main() CLI function."""

    def _common_patches(self, tmp_path):
        """Return patch context managers covering all side-effects of main()."""
        return [
            patch(
                "sys.argv",
                [
                    "avatar-expression-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--expression",
                    "happiness",
                    "--style",
                    "photorealistic",
                    "--gender",
                    "female",
                    "--refine",
                    "expression",
                ],
            ),
            patch(
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.expression_tuner._run_tuning_pass",
                return_value={
                    "happiness": (1, 1),
                },
            ),
        ]

    def test_main_runs_without_watch(self, tmp_path):
        """main() without --watch runs _run_once and returns."""
        patches = self._common_patches(tmp_path)
        with patches[0], patches[1], patches[2]:
            from tuning.expression_tuner import main

            main()  # should not raise

    def test_main_no_watch_generate_only(self, tmp_path):
        """main() with --refine none still completes."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-expression-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--refine",
                    "none",
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.expression_tuner._run_tuning_pass",
                return_value={
                    "happiness": (0, 1),
                },
            ),
        ):
            from tuning.expression_tuner import main

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
                    "avatar-expression-tuner",
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
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.expression_tuner._run_tuning_pass",
                return_value={
                    "happiness": (0, 1),
                },
            ),
            patch("time.sleep", side_effect=_mock_sleep),
        ):
            from tuning.expression_tuner import main

            main()  # KeyboardInterrupt is caught internally → should not propagate

    def test_main_watch_reruns_on_file_change(self, tmp_path):
        """--watch: detects mtime change and re-runs _run_once."""
        import types

        # Sequence: initial_stat=100, loop_stat_1=200 (change!), then interrupt on sleep
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
            # Interrupt after the change-triggered rerun has happened
            if len(sleep_calls) >= 2:
                raise KeyboardInterrupt

        mock_expressions = [{"id": "happiness", "expression": "Happiness", "synonyms": []}]
        mock_styles = [{"id": "photorealistic", "system_prompt": "photo", "name": "Photo"}]

        with (
            patch(
                "sys.argv",
                [
                    "avatar-expression-tuner",
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
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch("tuning.expression_tuner._load_expressions_fresh", return_value=mock_expressions),
            patch("tuning.expression_tuner._load_styles_fresh", return_value=mock_styles),
            patch(
                "tuning.expression_tuner._run_tuning_pass",
                side_effect=lambda *a, **kw: (run_once_calls.append(1), {"happiness": (0, 1)})[1],
            ),
            patch("time.sleep", side_effect=_mock_sleep),
            patch("tuning.expression_tuner.EXPRESSIONS_YML") as mock_yml,
        ):
            mock_yml.stat.side_effect = _mock_stat
            from tuning.expression_tuner import main

            main()
        # _run_once called at startup + once on mtime change
        assert len(run_once_calls) >= 2

    def test_main_if_name_main_guard(self):
        """Line 844: __name__ == '__main__' guard — covered by running main directly."""
        import runpy

        with (
            patch("sys.argv", ["expression_tuner", "--help"]),
        ):
            try:
                runpy.run_module("tuning.expression_tuner", run_name="__main__", alter_sys=True)
            except SystemExit:
                pass  # --help exits with 0

    def test_main_custom_model_prefix_added(self, tmp_path):
        """Lines 709, 712: models without ollama/ prefix get it added."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-expression-tuner",
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
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.expression_tuner._load_expressions_fresh",
                return_value=[
                    {"id": "happiness", "expression": "Happiness", "synonyms": []},
                ],
            ),
            patch(
                "tuning.expression_tuner._load_styles_fresh",
                return_value=[
                    {"id": "photorealistic", "system_prompt": "photo", "name": "Photo"},
                ],
            ),
            patch(
                "tuning.expression_tuner._run_tuning_pass",
                return_value={
                    "happiness": (0, 1),
                },
            ),
        ):
            from tuning.expression_tuner import main

            main()  # prefix-adding lines exercised, should not raise

    def test_main_no_matching_expressions_exits_early(self, tmp_path, capsys):
        """Lines 766-767: no matching expressions found → prints error and returns."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-expression-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--expression",
                    "nonexistent_xyz",
                    "--gender",
                    "female",
                ],
            ),
            patch(
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.expression_tuner._load_expressions_fresh",
                return_value=[
                    {"id": "happiness", "expression": "Happiness", "synonyms": []},
                ],
            ),
            patch(
                "tuning.expression_tuner._load_styles_fresh",
                return_value=[
                    {"id": "photorealistic", "system_prompt": "photo", "name": "Photo"},
                ],
            ),
        ):
            from tuning.expression_tuner import main

            main()
        err = capsys.readouterr().err
        assert "No matching expressions found" in err

    def test_main_style_fallback_to_first_available(self, tmp_path):
        """Lines 760-763: no style resolved → fallback to first style with system_prompt."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-expression-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--gender",
                    "female",
                    "--refine",
                    "none",
                    "--style",
                    "nonexistent_style_xyz",  # won't match → target_styles empty
                ],
            ),
            patch(
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.expression_tuner._load_expressions_fresh",
                return_value=[
                    {"id": "happiness", "expression": "Happiness", "synonyms": []},
                ],
            ),
            patch(
                "tuning.expression_tuner._load_styles_fresh",
                return_value=[
                    {"id": "photorealistic", "system_prompt": "photo", "name": "Photo"},
                ],
            ),
            patch(
                "tuning.expression_tuner._run_tuning_pass",
                return_value={
                    "happiness": (0, 1),
                },
            ),
        ):
            from tuning.expression_tuner import main

            main()  # should not raise — fallback style used

    def test_main_style_fallback_no_system_prompt(self, tmp_path):
        """Line 763: all styles lack system_prompt → fallback to all_styles[:1]."""
        with (
            patch(
                "sys.argv",
                [
                    "avatar-expression-tuner",
                    "--tmp-dir",
                    str(tmp_path),
                    "--runs",
                    "1",
                    "--gender",
                    "female",
                    "--refine",
                    "none",
                    "--style",
                    "nonexistent_style_xyz",
                ],
            ),
            patch(
                "tuning.expression_tuner._generate_diverse_personas",
                return_value={
                    "female": _FAKE_AVATAR,
                },
            ),
            patch(
                "tuning.expression_tuner._load_expressions_fresh",
                return_value=[
                    {"id": "happiness", "expression": "Happiness", "synonyms": []},
                ],
            ),
            patch(
                "tuning.expression_tuner._load_styles_fresh",
                return_value=[
                    # No system_prompt → first list comprehension returns empty → fallback to [:1]
                    {"id": "random", "name": "Random"},
                ],
            ),
            patch(
                "tuning.expression_tuner._run_tuning_pass",
                return_value={
                    "happiness": (0, 1),
                },
            ),
        ):
            from tuning.expression_tuner import main

            main()  # should not raise — all_styles[:1] fallback used
