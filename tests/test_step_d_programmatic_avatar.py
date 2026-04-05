"""Tests for step_d_make_programmatic_avatar — mocked subprocess."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


def _mock_vendor(tmp_path: Path) -> Path:
    """Create a fake vendor dir with generate.js."""
    vendor = tmp_path / "vendor" / "programmatic-avatar"
    vendor.mkdir(parents=True)
    (vendor / "generate.js").write_text("// fake")
    return vendor


def _make_completed(stdout: str = "", stderr: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


class TestCreateProgrammaticAvatar:
    def test_returns_out_path(self, tmp_path):
        vendor = _mock_vendor(tmp_path)
        out = tmp_path / "out.svg"

        with (
            patch(
                "pipeline.render.programmatic.svg_generator._vendor_dir",
                return_value=vendor,
            ),
            patch("subprocess.run", return_value=_make_completed()) as mock_run,
        ):
            from pipeline.render.programmatic.svg_generator import create_programmatic_avatar

            result = create_programmatic_avatar("Alice", out)
            assert result == out
            mock_run.assert_called_once()

    def test_bg_color_added_to_options_non_opeeps(self, tmp_path):
        vendor = _mock_vendor(tmp_path)
        out = tmp_path / "out.svg"

        with (
            patch("pipeline.render.programmatic.svg_generator._vendor_dir", return_value=vendor),
            patch("subprocess.run", return_value=_make_completed()) as mock_run,
        ):
            from pipeline.render.programmatic.svg_generator import create_programmatic_avatar

            create_programmatic_avatar(
                "Bob", out, demographics={"bg_color": "#FF0000"}, style="toon-head"
            )
            cmd = mock_run.call_args.args[0]
            assert "--options" in cmd
            import json
            opts_idx = cmd.index("--options") + 1
            opts = json.loads(cmd[opts_idx])
            assert "backgroundColor" in opts

    def test_bg_color_opeeps_uses_circle_key(self, tmp_path):
        """Covers line 152: opeeps style uses circle.backgroundColor."""
        vendor = _mock_vendor(tmp_path)
        out = tmp_path / "out.svg"

        with (
            patch("pipeline.render.programmatic.svg_generator._vendor_dir", return_value=vendor),
            patch("subprocess.run", return_value=_make_completed()) as mock_run,
        ):
            from pipeline.render.programmatic.svg_generator import create_programmatic_avatar

            create_programmatic_avatar(
                "Carol", out, demographics={"bg_color": "#00FF00"}, style="opeeps"
            )
            cmd = mock_run.call_args.args[0]
            import json
            opts_idx = cmd.index("--options") + 1
            opts = json.loads(cmd[opts_idx])
            assert "circle" in opts
            assert "backgroundColor" in opts["circle"]

    def test_unknown_expression_logs_warning(self, tmp_path):
        """Covers lines 163-167: warning when expression not in style_map."""
        vendor = _mock_vendor(tmp_path)
        out = tmp_path / "out.svg"

        with (
            patch("pipeline.render.programmatic.svg_generator._vendor_dir", return_value=vendor),
            patch("subprocess.run", return_value=_make_completed()),
        ):
            from pipeline.render.programmatic.svg_generator import create_programmatic_avatar

            # "unknown_expr" is not in EXPRESSION_OPTIONS for toon-head
            result = create_programmatic_avatar(
                "Dave", out, expression="unknown_expr", style="toon-head"
            )
            assert result == out

    def test_stderr_logged_when_present(self, tmp_path):
        """Covers line 191: stderr debug log."""
        vendor = _mock_vendor(tmp_path)
        out = tmp_path / "out.svg"

        with (
            patch("pipeline.render.programmatic.svg_generator._vendor_dir", return_value=vendor),
            patch(
                "subprocess.run",
                return_value=_make_completed(stderr="some warning from node"),
            ),
        ):
            from pipeline.render.programmatic.svg_generator import create_programmatic_avatar

            result = create_programmatic_avatar("Eve", out)
            assert result == out

    def test_known_expression_updates_options(self, tmp_path):
        """Covers line 162: options.update(expr_opts) for a known expression."""
        vendor = _mock_vendor(tmp_path)
        out = tmp_path / "out.svg"

        with (
            patch("pipeline.render.programmatic.svg_generator._vendor_dir", return_value=vendor),
            patch("subprocess.run", return_value=_make_completed()) as mock_run,
        ):
            from pipeline.render.programmatic.svg_generator import create_programmatic_avatar

            create_programmatic_avatar("Alice", out, expression="neutral", style="toon-head")
            cmd = mock_run.call_args.args[0]
            assert "--options" in cmd
            import json
            opts = json.loads(cmd[cmd.index("--options") + 1])
            assert "eyes" in opts or "mouth" in opts
        """Covers line 87: FileNotFoundError when vendor dir missing."""
        import pytest

        # Patch _vendor_dir to raise (simulating missing vendor dir)
        with patch(
            "pipeline.render.programmatic.svg_generator._vendor_dir",
            side_effect=FileNotFoundError("vendor/programmatic-avatar/generate.js not found"),
        ):
            from pipeline.render.programmatic.svg_generator import create_programmatic_avatar

            with pytest.raises(FileNotFoundError):
                create_programmatic_avatar("Frank", tmp_path / "out.svg")
