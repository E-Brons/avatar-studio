"""Tests for api.cli — argument parsing and subcommand dispatch."""

from __future__ import annotations

from unittest.mock import patch

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEMO = {
    "gender": "female", "age": 30, "name": "Alice Smith",
    "bg_color": "#4A90D9", "fg_color": "#FFFFFF", "style": "photorealistic",
}

_ADVISOR_YAML = {
    "name": "Alice Smith",
    "role": "Advisor",
    "traits": ["analytical"],
    "education": ["MBA"],
    "experience": ["5 years"],
}

_PERSONA = {
    "personal": {"name": "Alice Smith", "gender": "female", "age": 30},
    "advisor": {"role": "Advisor"},
    "appearance": {"hair_style": "bob"},
    "style": {"bg_color": "#4A90D9"},
}

_FEATURES = {
    "NAME": "Alice Smith",
    "HAIR_STYLE": "bob cut",
    "CLOTHING": {"blazer": "#333"},
    "ACCESSORIES": {},
}


def _run_main(argv: list[str]) -> int:
    """Call cli.main() with given argv, return exit code (0 if no SystemExit)."""
    with patch("sys.argv", ["avatar-studio", *argv]):
        try:
            from api.cli import main
            main()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0


# ---------------------------------------------------------------------------
# _load_styles
# ---------------------------------------------------------------------------

class TestLoadStyles:
    def test_returns_list(self):
        from api.cli import _load_styles
        result = _load_styles()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_styles_have_id(self):
        from api.cli import _load_styles
        for s in _load_styles():
            assert "id" in s


# ---------------------------------------------------------------------------
# main — no subcommand → help + exit 1
# ---------------------------------------------------------------------------

class TestMainNoSubcommand:
    def test_no_args_exits_1(self, capsys):
        code = _run_main([])
        assert code == 1


# ---------------------------------------------------------------------------
# stage-b subcommand
# ---------------------------------------------------------------------------

class TestRunStageB:
    def _patch_stage_b(self):
        return [
            patch("api.cli.pick_demographics", return_value=dict(_DEMO)),
            patch("api.cli.select_features", return_value=_FEATURES),
            patch("api.cli.marshal_avatar_persona", return_value=_PERSONA),
        ]

    def test_stage_b_prints_ok(self, capsys):
        patches = self._patch_stage_b()
        with patches[0], patches[1], patches[2]:
            code = _run_main(["stage-b", "--role", "Engineer"])
        assert code == 0
        out = capsys.readouterr().out
        assert "Stage B OK" in out

    def test_stage_b_uses_role(self, capsys):
        captured = {}

        def _cap_select(demo, advisor, **kwargs):
            captured["role"] = advisor["role"]
            return _FEATURES

        patches = [
            patch("api.cli.pick_demographics", return_value=dict(_DEMO)),
            patch("api.cli.select_features", side_effect=_cap_select),
            patch("api.cli.marshal_avatar_persona", return_value=_PERSONA),
        ]
        with patches[0], patches[1], patches[2]:
            _run_main(["stage-b", "--role", "Data Scientist"])
        assert captured["role"] == "Data Scientist"

    def test_stage_b_exits_1_when_no_name(self, capsys):
        """Missing name in persona → sys.exit(1)."""
        bad_persona = {"personal": {}, "appearance": {"hair": "bob"}, "advisor": {}, "style": {}}
        patches = [
            patch("api.cli.pick_demographics", return_value=dict(_DEMO)),
            patch("api.cli.select_features", return_value=_FEATURES),
            patch("api.cli.marshal_avatar_persona", return_value=bad_persona),
        ]
        with patches[0], patches[1], patches[2]:
            code = _run_main(["stage-b"])
        assert code == 1

    def test_stage_b_exits_1_when_no_appearance(self, capsys):
        """Empty appearance in persona → sys.exit(1)."""
        bad_persona = {
            "personal": {"name": "Alice Smith"},
            "appearance": {},
            "advisor": {},
            "style": {},
        }
        patches = [
            patch("api.cli.pick_demographics", return_value=dict(_DEMO)),
            patch("api.cli.select_features", return_value=_FEATURES),
            patch("api.cli.marshal_avatar_persona", return_value=bad_persona),
        ]
        with patches[0], patches[1], patches[2]:
            code = _run_main(["stage-b"])
        assert code == 1


# ---------------------------------------------------------------------------
# generate subcommand
# ---------------------------------------------------------------------------

class TestRunGenerate:
    def test_single_advisor(self, tmp_path, capsys):
        advisor_path = tmp_path / "alice.yml"
        advisor_path.write_text(yaml.dump(_ADVISOR_YAML))

        with patch("api.cli.process_advisor") as mock_pa:
            code = _run_main([
                "generate",
                "--advisor", str(advisor_path),
                "--out-dir", str(tmp_path),
            ])
        assert code == 0
        mock_pa.assert_called_once()

    def test_advisors_dir(self, tmp_path, capsys):
        for i in range(2):
            (tmp_path / f"advisor_{i}.yml").write_text(yaml.dump(_ADVISOR_YAML))

        with patch("api.cli.process_advisor") as mock_pa:
            code = _run_main([
                "generate",
                "--advisors-dir", str(tmp_path),
                "--out-dir", str(tmp_path / "out"),
            ])
        assert code == 0
        assert mock_pa.call_count == 2

    def test_advisors_dir_empty_exits_1(self, tmp_path, capsys):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        code = _run_main([
            "generate",
            "--advisors-dir", str(empty_dir),
            "--out-dir", str(tmp_path / "out"),
        ])
        assert code == 1

    def test_gateway_url_forwarded(self, tmp_path):
        advisor_path = tmp_path / "alice.yml"
        advisor_path.write_text(yaml.dump(_ADVISOR_YAML))
        captured = {}

        def _cap(path, out, **kwargs):
            captured["url"] = kwargs.get("gateway_url")

        with patch("api.cli.process_advisor", side_effect=_cap):
            _run_main([
                "generate",
                "--advisor", str(advisor_path),
                "--out-dir", str(tmp_path),
                "--gateway-url", "http://custom:9999",
            ])
        assert captured["url"] == "http://custom:9999"


# ---------------------------------------------------------------------------
# gen-examples subcommand
# ---------------------------------------------------------------------------

class TestRunGenExamples:
    def _styles(self):
        return [
            {"id": "photorealistic", "name": "Photo", "system_prompt": "photo portrait"},
            {"id": "clay", "name": "Clay", "system_prompt": "clay style"},
        ]

    def test_generates_for_all_genders(self, tmp_path):
        import io as _io

        captured_paths = []

        def _mock_gen(persona_path, *, out_path, **kwargs):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            from PIL import Image as PILImage
            img = PILImage.new("RGBA", (64, 64), (0, 0, 0, 255))
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            out_path.write_bytes(buf.getvalue())
            captured_paths.append(out_path.name)

        with (
            patch("api.cli._load_styles", return_value=self._styles()),
            patch("api.cli.pick_demographics", return_value=dict(_DEMO)),
            patch("api.cli._build_demographics_for_gender", return_value=dict(_DEMO)),
            patch("api.cli.build_avatar_charachter", return_value={"avatar_persona": _PERSONA}),
            patch("pipeline.render.llm.orchestrator.generate_avatar_image", side_effect=_mock_gen),
            patch("api.server._PROJECT_ROOT", tmp_path),
            patch("api.cli._PROJECT_ROOT", tmp_path),
        ):
            code = _run_main(["gen-examples", "--style", "photorealistic", "--gender", "female"])
        assert code == 0

    def test_no_matching_styles_exits_1(self, tmp_path, capsys):
        with patch("api.cli._load_styles", return_value=[]):
            code = _run_main(["gen-examples", "--style", "nonexistent"])
        assert code == 1

    def test_existing_file_skipped_without_overwrite(self, tmp_path):

        gen_calls = []

        def _mock_gen(*args, **kwargs):
            gen_calls.append(1)

        styles = [{"id": "photorealistic", "system_prompt": "photo", "name": "Photo"}]

        with (
            patch("api.cli._load_styles", return_value=styles),
            patch("api.cli._build_demographics_for_gender", return_value=dict(_DEMO)),
            patch("api.cli.build_avatar_charachter", return_value={"avatar_persona": _PERSONA}),
            patch("pipeline.render.llm.orchestrator.generate_avatar_image", side_effect=_mock_gen),
            patch("api.cli._PROJECT_ROOT", tmp_path),
        ):
            # Pre-create the output file so it already "exists"
            expected = tmp_path / "tmp" / "avatar_style_photorealistic_female.png"
            expected.parent.mkdir(parents=True, exist_ok=True)
            expected.write_bytes(b"fake")

            code = _run_main([
                "gen-examples",
                "--style", "photorealistic",
                "--gender", "female",
            ])
        assert code == 0
        assert len(gen_calls) == 0  # skipped

    def test_image_gen_failure_continues(self, tmp_path, capsys):
        """generate_avatar_image raises → error printed, loop continues."""
        styles = [
            {"id": "photorealistic", "system_prompt": "photo", "name": "Photo"},
        ]
        with (
            patch("api.cli._load_styles", return_value=styles),
            patch("api.cli._build_demographics_for_gender", return_value=dict(_DEMO)),
            patch("api.cli.build_avatar_charachter", return_value={"avatar_persona": _PERSONA}),
            patch("pipeline.render.llm.orchestrator.generate_avatar_image", side_effect=RuntimeError("gpu down")),
            patch("api.cli._PROJECT_ROOT", tmp_path),
        ):
            code = _run_main(["gen-examples", "--style", "photorealistic", "--gender", "female"])
        assert code == 0
        out = capsys.readouterr().err
        assert "gpu down" in out

    def test_no_style_flag_uses_all_prompt_styles(self, tmp_path, capsys):
        """Line 132: no --style flag → filter all styles with system_prompt."""
        import io as _io

        from PIL import Image as PILImage

        gen_calls = []

        def _mock_gen(persona_path, *, out_path, **kwargs):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img = PILImage.new("RGBA", (64, 64), (0, 0, 0))
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            out_path.write_bytes(buf.getvalue())
            gen_calls.append(out_path.name)

        styles = [
            {"id": "photorealistic", "system_prompt": "photo portrait", "name": "Photo"},
            {"id": "random", "system_prompt": None, "name": "Random"},  # excluded
        ]
        with (
            patch("api.cli._load_styles", return_value=styles),
            patch("api.cli._build_demographics_for_gender", return_value=dict(_DEMO)),
            patch("api.cli.build_avatar_charachter", return_value={"avatar_persona": _PERSONA}),
            patch("pipeline.render.llm.orchestrator.generate_avatar_image", side_effect=_mock_gen),
            patch("api.cli._PROJECT_ROOT", tmp_path),
        ):
            code = _run_main(["gen-examples", "--gender", "female"])
        assert code == 0
        # Only photorealistic generated (random excluded as no system_prompt)
        assert any("photorealistic" in n for n in gen_calls)
        assert not any("random" in n for n in gen_calls)


class TestStageBNoneFeatures:
    def test_select_features_returns_none_exits_1(self, capsys):
        """Lines 70-71: _select_features returns None → sys.exit(1)."""
        patches = [
            patch("api.cli.pick_demographics", return_value=dict(_DEMO)),
            patch("api.cli.select_features", return_value=None),
        ]
        with patches[0], patches[1]:
            code = _run_main(["stage-b", "--role", "Advisor"])
        assert code == 1
        err = capsys.readouterr().err
        assert "None" in err
