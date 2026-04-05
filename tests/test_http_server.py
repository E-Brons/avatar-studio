"""Tests for api.http_server — pure helpers and endpoint functions.

Uses asyncio.run() to invoke async endpoints directly without httpx.
"""

from __future__ import annotations

import asyncio
import io
from unittest.mock import patch

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(w: int = 64, h: int = 64) -> bytes:
    img = Image.new("RGBA", (w, h), (100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_DEMO_BASE = {
    "gender": "female",
    "age": 30,
    "name": "Alice Smith",
    "style": "photorealistic",
    "bg_color": "#4A90D9",
    "fg_color": "#FFFFFF",
    "SKIN_TONE": "#D4A76A",
    "HAIR_COLOR": "#8B5E3C #5C3D1E",
    "EYE_COLOR": "#3D1C02 #1A0800",
    "BROWS_COLOR": "#5C3D1E",
    "EYE_SHAPE": "almond",
    "BROWS_STYLE": "arched thin",
    "NOSE_SHAPE": "button",
    "CHIN_SHAPE": "soft rounded",
    "CHEEKS_SHAPE": "full and high",
}


# ---------------------------------------------------------------------------
# _resolve_demographics — dict hair_color branch (lines 203-206)
# ---------------------------------------------------------------------------


class TestResolveDemographicsDict:
    def test_hair_color_dict_re_derives_brows(self):
        """Lines 203-206: HAIR_COLOR is dict with hex_base → BROWS_COLOR re-derived."""
        from api.http_server import AttributeSelection, _resolve_demographics

        hair_dict = {"hex_base": "#8B5E3C", "hex_shadow": "#5C3D1E"}
        with patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)):
            demo = _resolve_demographics(
                [AttributeSelection(id="hair_color", mode="select", value=hair_dict)]
            )
        assert "BROWS_COLOR" in demo
        # brows should be darkened from #8B5E3C
        assert demo["BROWS_COLOR"].startswith("#")

    def test_hair_color_dict_no_hex_base_keeps_original(self):
        """Line 206 branch: dict with no hex_base → brows unchanged."""
        from api.http_server import AttributeSelection, _resolve_demographics

        base = dict(_DEMO_BASE)
        original_brows = base["BROWS_COLOR"]
        with patch("api.http_server.pick_demographics", return_value=base):
            demo = _resolve_demographics(
                [AttributeSelection(id="hair_color", mode="select", value={})]
            )
        assert demo["BROWS_COLOR"] == original_brows


# ---------------------------------------------------------------------------
# Async endpoint helpers
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_returns_ok(self):
        from api.http_server import health

        result = asyncio.run(health())
        assert result == {"status": "ok"}


class TestGetConfigEndpoint:
    def test_returns_attributes(self):
        from api.http_server import get_config

        result = asyncio.run(get_config())
        assert "attributes" in result
        assert isinstance(result["attributes"], list)


class TestRandomizeEndpoint:
    def test_returns_values_dict(self):
        from api.http_server import RandomizeRequest, randomize_avatar

        with patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)):
            result = asyncio.run(randomize_avatar(RandomizeRequest()))
        assert "values" in result
        assert isinstance(result["values"], dict)

    def test_constraint_applied(self):
        from api.http_server import AttributeSelection, RandomizeRequest, randomize_avatar

        with patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)):
            req = RandomizeRequest(
                constraints=[AttributeSelection(id="gender", mode="select", value="male")]
            )
            result = asyncio.run(randomize_avatar(req))
        assert result["values"]["gender"] == "male"


# ---------------------------------------------------------------------------
# _run_pipeline_sync — full pipeline (lines 226-333)
# ---------------------------------------------------------------------------


def _make_avatar_dict():
    return {
        "avatar_persona": {
            "personal": {"gender": "female", "age": 30, "name": "Alice Smith"},
            "personality": {"traits": []},
            "style": {"bg_color": "#4A90D9", "fg_color": "#FFFFFF"},
            "appearance": {},
        }
    }


class TestRunPipelineSync:
    def _patch_all(self):
        """Context managers for all pipeline dependencies."""
        return [
            patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)),
            patch("api.http_server.select_features", return_value={"HAIR_STYLE": "bob"}),
            patch("api.http_server.build_avatar_charachter", return_value=_make_avatar_dict()),
            patch("api.http_server.generate_avatar_image", side_effect=self._mock_gen),
        ]

    @staticmethod
    def _mock_gen(persona_path, *, out_path, **kwargs):
        """Write a tiny PNG to out_path so the pipeline can read it back."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(_make_png())
        return out_path

    def test_returns_generate_result(self):
        from api.http_server import GenerateRequest, _run_pipeline_sync

        req = GenerateRequest(expressions=["neutral"], width=64, height=64)
        patches = self._patch_all()
        with patches[0], patches[1], patches[2], patches[3]:
            result = _run_pipeline_sync(req)
        assert result.image_b64
        assert isinstance(result.session_id, str)
        assert "neutral" in result.expressions

    def test_feature_selection_failure_continues(self):
        """Feature selection failure → features=None, pipeline still runs."""
        from api.http_server import GenerateRequest, _run_pipeline_sync

        req = GenerateRequest(expressions=["neutral"], width=64, height=64)
        with (
            patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)),
            patch("api.http_server.select_features", return_value={}),
            patch("api.http_server.build_avatar_charachter", return_value=_make_avatar_dict()),
            patch("api.http_server.generate_avatar_image", side_effect=self._mock_gen),
        ):
            result = _run_pipeline_sync(req)
        assert result.image_b64

    def test_select_features_failure_continues(self):
        """Feature selection failure → features=None, pipeline still runs."""
        from api.http_server import GenerateRequest, _run_pipeline_sync

        req = GenerateRequest(expressions=["neutral"], width=64, height=64)
        with (
            patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)),
            patch("api.http_server.select_features", side_effect=RuntimeError("C down")),
            patch("api.http_server.build_avatar_charachter", return_value=_make_avatar_dict()),
            patch("api.http_server.generate_avatar_image", side_effect=self._mock_gen),
        ):
            result = _run_pipeline_sync(req)
        assert result.image_b64

    def test_neutral_image_failure_raises_http_exception(self):
        """generate_avatar_image failure for neutral → HTTPException 500."""
        from fastapi import HTTPException

        from api.http_server import GenerateRequest, _run_pipeline_sync

        req = GenerateRequest(expressions=["neutral"], width=64, height=64)
        with (
            patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)),
            patch("api.http_server.select_features", return_value={}),
            patch("api.http_server.build_avatar_charachter", return_value=_make_avatar_dict()),
            patch("api.http_server.generate_avatar_image", side_effect=RuntimeError("gpu down")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                _run_pipeline_sync(req)
        assert exc_info.value.status_code == 500

    def test_expression_variant_failure_skipped(self):
        """Expression generation failure → that expression absent, neutral still returned."""
        neutral_calls = []

        def _selective_gen(persona_path, *, expression, out_path, **kwargs):
            if expression["name"] == "neutral":
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(_make_png())
                neutral_calls.append(1)
                return out_path
            raise RuntimeError("expr down")

        from api.http_server import GenerateRequest, _run_pipeline_sync

        req = GenerateRequest(expressions=["neutral", "happiness"], width=64, height=64)
        with (
            patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)),
            patch("api.http_server.select_features", return_value={}),
            patch("api.http_server.build_avatar_charachter", return_value=_make_avatar_dict()),
            patch("api.http_server.generate_avatar_image", side_effect=_selective_gen),
        ):
            result = _run_pipeline_sync(req)
        assert "neutral" in result.expressions
        assert "happiness" not in result.expressions

    def test_advisor_fields_from_selections(self):
        """traits from selections → used directly, no LLM call needed."""
        from api.http_server import AttributeSelection, GenerateRequest, _run_pipeline_sync

        req = GenerateRequest(
            selections=[
                AttributeSelection(id="traits", mode="predefined", value=["curious"]),
            ],
            expressions=["neutral"],
            width=64,
            height=64,
        )

        captured_advisor = {}

        def _capture_advisor(advisor, demo, features):
            captured_advisor.update(advisor)
            return _make_avatar_dict()

        with (
            patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)),
            patch("api.http_server.select_features", return_value={}),
            patch("api.http_server.build_avatar_charachter", side_effect=_capture_advisor),
            patch("api.http_server.generate_avatar_image", side_effect=self._mock_gen),
        ):
            _run_pipeline_sync(req)
        assert captured_advisor.get("traits") == ["curious"]


# ---------------------------------------------------------------------------
# generate_avatar endpoint — wires async executor (lines 366-370)
# ---------------------------------------------------------------------------


class TestGenerateAvatarEndpoint:
    def test_calls_run_pipeline_sync(self):
        from api.http_server import GenerateRequest, GenerateResult, generate_avatar

        fake_result = GenerateResult(
            image_b64="abc",
            avatar_persona={},
            expressions={"neutral": "abc"},
            session_id="sid-1",
        )
        with patch("api.http_server._run_pipeline_sync", return_value=fake_result):
            req = GenerateRequest(expressions=["neutral"])
            result = asyncio.run(generate_avatar(req))
        assert result.session_id == "sid-1"
        assert result.image_b64 == "abc"


# ---------------------------------------------------------------------------
# _run_pipeline_sync — expression variant success (line 326)
# ---------------------------------------------------------------------------


class TestExpressionVariantSuccess:
    @staticmethod
    def _gen_both(persona_path, *, expression, out_path, **kwargs):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(_make_png())
        return out_path

    def test_expression_variant_included_on_success(self):
        """Line 326: expression variant succeeds → b64 encoded in results."""
        from api.http_server import GenerateRequest, _run_pipeline_sync

        req = GenerateRequest(expressions=["neutral", "happiness"], width=64, height=64)
        with (
            patch("api.http_server.pick_demographics", return_value=dict(_DEMO_BASE)),
            patch("api.http_server.select_features", return_value={}),
            patch("api.http_server.build_avatar_charachter", return_value=_make_avatar_dict()),
            patch("api.http_server.generate_avatar_image", side_effect=self._gen_both),
        ):
            result = _run_pipeline_sync(req)
        assert "happiness" in result.expressions
        assert result.expressions["happiness"]  # non-empty b64


# ---------------------------------------------------------------------------
# _lifespan — BROWSER_SHUTDOWN task creation (replaces _start_shutdown_watcher)
# ---------------------------------------------------------------------------


class TestStartShutdownWatcher:
    def test_creates_task_when_browser_shutdown_enabled(self):
        """_lifespan creates a shutdown watcher task when _BROWSER_SHUTDOWN=True."""
        import api.http_server as mod

        task_created = []

        async def _run():
            with (
                patch.object(mod, "_BROWSER_SHUTDOWN", True),
                patch(
                    "asyncio.create_task",
                    side_effect=lambda coro: (task_created.append(1), coro.close(), None)[2],
                ),
            ):
                async with mod._lifespan(mod.app):
                    pass
            return task_created

        result = asyncio.run(_run())
        assert len(result) == 1

    def test_no_task_when_browser_shutdown_disabled(self):
        """_lifespan does not create a task when _BROWSER_SHUTDOWN=False."""
        import api.http_server as mod

        async def _run():
            with patch.object(mod, "_BROWSER_SHUTDOWN", False):
                with patch("asyncio.create_task") as mock_ct:
                    async with mod._lifespan(mod.app):
                        pass
                    return mock_ct.call_count

        count = asyncio.run(_run())
        assert count == 0


# ---------------------------------------------------------------------------
# _shutdown_watcher — background task (lines 72-83)
# ---------------------------------------------------------------------------


class TestShutdownWatcher:
    def test_exits_after_grace_period_when_no_sessions(self):
        """_shutdown_watcher exits when _had_connection=True and _active_sessions empty."""
        import signal

        import api.http_server as mod

        kill_calls = []

        async def _run():
            with (
                patch.object(mod, "_had_connection", True),
                patch.object(mod, "_active_sessions", set()),
                patch.object(mod, "_SHUTDOWN_GRACE", 0),
                patch("asyncio.sleep", side_effect=[None, None]),  # first sleep(1), then sleep(0)
                patch("os.kill", side_effect=lambda *a: kill_calls.append(a)),
            ):
                await mod._shutdown_watcher()

        asyncio.run(_run())
        assert any(call[1] == signal.SIGTERM for call in kill_calls)

    def test_no_shutdown_when_no_prior_connection(self):
        """_shutdown_watcher loops but does NOT kill when _had_connection=False."""
        import api.http_server as mod

        sleep_count = []

        async def _run():
            async def _fake_sleep(secs):
                sleep_count.append(secs)
                if len(sleep_count) >= 3:
                    raise asyncio.CancelledError

            with (
                patch.object(mod, "_had_connection", False),
                patch.object(mod, "_active_sessions", set()),
                patch("asyncio.sleep", side_effect=_fake_sleep),
                patch("os.kill") as mock_kill,
            ):
                try:
                    await mod._shutdown_watcher()
                except asyncio.CancelledError:
                    pass
                return mock_kill.call_count

        count = asyncio.run(_run())
        assert count == 0

    def test_no_shutdown_when_sessions_reconnect_during_grace(self):
        """If sessions reconnect during grace period, shutdown is aborted."""
        import api.http_server as mod

        sessions = set()
        sleep_calls = []

        async def _fake_sleep(secs):
            sleep_calls.append(secs)
            if len(sleep_calls) == 1:
                # After first sleep(1), sessions still empty → enter grace
                pass
            elif len(sleep_calls) == 2:
                # During grace period sleep, add a session back
                sessions.add("reconnected")
            else:
                raise asyncio.CancelledError

        with (
            patch.object(mod, "_had_connection", True),
            patch.object(mod, "_active_sessions", sessions),
            patch.object(mod, "_SHUTDOWN_GRACE", 0),
            patch("asyncio.sleep", side_effect=_fake_sleep),
            patch("os.kill") as mock_kill,
        ):
            try:
                asyncio.run(mod._shutdown_watcher())
            except asyncio.CancelledError:
                pass
        assert mock_kill.call_count == 0


# ---------------------------------------------------------------------------
# browser_keepalive — WebSocket handler (lines 101-115)
# ---------------------------------------------------------------------------


class TestBrowserKeepaliveWebSocket:
    def test_adds_and_removes_session(self):
        """WebSocket handler adds session on connect, removes on disconnect."""
        import api.http_server as mod

        sessions_snapshot = []

        class _FakeWS:
            async def accept(self):
                sessions_snapshot.append(len(mod._active_sessions))

            async def send_text(self, text):
                raise Exception("disconnect now")

        async def _run():
            ws = _FakeWS()
            # Reset global state
            mod._active_sessions.clear()
            mod._had_connection = False
            with patch("api.http_server.asyncio.sleep", return_value=None):
                await mod.browser_keepalive(ws)
            return len(mod._active_sessions)

        remaining = asyncio.run(_run())
        assert remaining == 0  # session cleaned up in finally
        assert mod._had_connection is True

    def test_session_removed_on_websocket_disconnect(self):
        """WebSocketDisconnect → session removed from _active_sessions."""
        from fastapi.websockets import WebSocketDisconnect

        import api.http_server as mod

        class _FakeWS:
            async def accept(self):
                pass

            async def send_text(self, text):
                raise WebSocketDisconnect()

        async def _run():
            mod._active_sessions.clear()
            mod._had_connection = False
            with patch("api.http_server.asyncio.sleep", return_value=None):
                await mod.browser_keepalive(_FakeWS())
            return len(mod._active_sessions)

        remaining = asyncio.run(_run())
        assert remaining == 0


# ---------------------------------------------------------------------------
# cli.py line 281 — __name__ == '__main__' guard
# ---------------------------------------------------------------------------


class TestCliMainGuard:
    def test_cli_main_guard_via_runpy(self):
        """Line 281: if __name__ == '__main__': main() — covered by runpy."""
        import runpy
        import sys

        sys.modules.pop("api.cli", None)
        with patch("sys.argv", ["cli", "--help"]):
            try:
                runpy.run_module("api.cli", run_name="__main__", alter_sys=True)
            except SystemExit:
                pass  # --help or no-subcommand exits


# ---------------------------------------------------------------------------
# expression_autotuner.py line 15 — __name__ == '__main__' guard
# ---------------------------------------------------------------------------


class TestExpressionAutotunerMainGuard:
    def test_autotuner_main_raises_not_implemented(self):
        """main() raises NotImplementedError."""
        import pytest

        from tuning.expression_autotuner import main

        with pytest.raises(NotImplementedError):
            main()

    def test_autotuner_main_guard_via_runpy(self):
        """Line 15: if __name__ == '__main__': main() — covered by runpy."""
        import runpy
        import sys

        sys.modules.pop("tuning.expression_autotuner", None)
        import pytest

        with pytest.raises(NotImplementedError):
            runpy.run_module("tuning.expression_autotuner", run_name="__main__", alter_sys=True)
