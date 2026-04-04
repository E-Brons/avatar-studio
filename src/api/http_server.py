"""FastAPI HTTP server — wraps the Avatar Studio pipeline.

Run with:
    uvicorn api.http_server:app --host 127.0.0.1 --port 8080 --app-dir <project>/src

Set AVATAR_BROWSER_SHUTDOWN=1 to automatically stop the server when all
browser sessions disconnect (used by start_http_server.sh).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import signal
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.config_loader import ConfigLoader
from config.config import SETTINGS, _darken_hex
from pipeline.step_a_randomise_person import pick_demographics
from pipeline.step_b_generate_cv import generate_advisor_profile
from pipeline.step_c_select_features import build_avatar_charachter, select_features
from pipeline.step_ef_generate_image import EXPRESSIONS_YML, STYLES_YML, generate_avatar_image

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_GATEWAY_URL: str = SETTINGS.get("gateway_url", "http://127.0.0.1:4096")
_DEFAULT_SIZE: int = SETTINGS.get("default_image_size", 512)
_BROWSER_SHUTDOWN: bool = os.environ.get("AVATAR_BROWSER_SHUTDOWN", "") == "1"
# Grace period (seconds) between last disconnect and shutdown — tolerates reloads.
_SHUTDOWN_GRACE: int = int(os.environ.get("AVATAR_SHUTDOWN_GRACE", "8"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Avatar Studio API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets (avatar style example images etc.)
_assets_dir = _PROJECT_ROOT / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

_executor = ThreadPoolExecutor(max_workers=4)

# ─── Browser session tracking (for auto-shutdown) ────────────────────────────

_active_sessions: set[str] = set()
_had_connection: bool = False  # True once first browser has connected


async def _shutdown_watcher() -> None:
    """Background task: shut down the server when all browsers disconnect."""
    global _had_connection
    while True:
        await asyncio.sleep(1)
        if _had_connection and not _active_sessions:
            logger.info(
                "All browser sessions disconnected — waiting %ss grace period before shutdown.",
                _SHUTDOWN_GRACE,
            )
            await asyncio.sleep(_SHUTDOWN_GRACE)
            if not _active_sessions:
                logger.info("Shutting down server (browser window closed).")
                os.kill(os.getpid(), signal.SIGTERM)
                return


@app.on_event("startup")
async def _start_shutdown_watcher() -> None:
    if _BROWSER_SHUTDOWN:
        asyncio.create_task(_shutdown_watcher())


@app.websocket("/api/ws/keepalive")
async def browser_keepalive(ws: WebSocket) -> None:
    """Browser connects here on startup and holds the connection open.

    When the browser tab/window closes, the WebSocket disconnects and — if
    AVATAR_BROWSER_SHUTDOWN=1 — the server will shut itself down after a
    short grace period.
    """
    global _had_connection
    await ws.accept()
    session_id = str(uuid.uuid4())
    _active_sessions.add(session_id)
    _had_connection = True
    logger.info("Browser session connected: %s (total=%d)", session_id, len(_active_sessions))
    try:
        while True:
            # Send a ping every 15 s; client echoes it back.
            await asyncio.sleep(15)
            await ws.send_text("ping")
    except WebSocketDisconnect, Exception:
        pass
    finally:
        _active_sessions.discard(session_id)
        logger.info(
            "Browser session disconnected: %s (remaining=%d)", session_id, len(_active_sessions)
        )


# ─── Pydantic models ─────────────────────────────────────────────────────────


class AttributeSelection(BaseModel):
    id: str
    mode: str
    value: Any = None


class RandomizeRequest(BaseModel):
    constraints: list[AttributeSelection] = []
    seed: int | None = None


class GenerateRequest(BaseModel):
    selections: list[AttributeSelection] = []
    expressions: list[str] = ["neutral"]
    width: int = 256
    height: int = 256
    seed: int | None = None


class GenerateResult(BaseModel):
    image_b64: str
    avatar_persona: dict
    expressions: dict[str, str]
    session_id: str


# ─── Attribute ID ↔ demographics key mapping ─────────────────────────────────

# Maps UI attribute IDs (snake_case) to the pipeline dict keys (UPPER_CASE)
_ATTR_TO_DEMO_KEY: dict[str, str] = {
    "gender": "gender",
    "age": "age",
    "style": "style",
    "skin_tone": "SKIN_TONE",
    "hair_color": "HAIR_COLOR",
    "eye_color": "EYE_COLOR",
    "brows_color": "BROWS_COLOR",
    "eye_shape": "EYE_SHAPE",
    "brows_style": "BROWS_STYLE",
    "nose_shape": "NOSE_SHAPE",
    "chin_shape": "CHIN_SHAPE",
    "cheeks_shape": "CHEEKS_SHAPE",
    "hair_style": "HAIR_STYLE",
    "clothing": "CLOTHING",
    "accessories": "ACCESSORIES",
    "role": "role",
}


def _demo_key(attr_id: str) -> str | None:
    return _ATTR_TO_DEMO_KEY.get(attr_id)


# ─── Demographics resolution ─────────────────────────────────────────────────


def _resolve_demographics(
    constraints: list[AttributeSelection],
    seed: int | None = None,
) -> dict:
    """Merge pick_demographics() random base with user constraints."""
    demo = pick_demographics(seed)

    # Apply select / predefined overrides
    hair_color_overridden = False
    for sel in constraints:
        if sel.mode not in ("select", "predefined"):
            continue
        key = _demo_key(sel.id)
        if key is None or sel.value is None:
            continue
        demo[key] = sel.value
        if sel.id == "hair_color":
            hair_color_overridden = True

    # Re-derive BROWS_COLOR from hair_color base hex if hair_color changed
    if hair_color_overridden:
        hair_color_raw = demo.get("HAIR_COLOR", "")
        if isinstance(hair_color_raw, str) and hair_color_raw:
            base_hex = hair_color_raw.split()[0]
            demo["BROWS_COLOR"] = _darken_hex(base_hex, factor=0.7)
        elif isinstance(hair_color_raw, dict):
            base_hex = hair_color_raw.get("hex_base", "")
            if base_hex:
                demo["BROWS_COLOR"] = _darken_hex(base_hex, factor=0.7)

    return demo


def _demo_to_response(demo: dict) -> dict:
    """Convert the demographics dict to a JSON-friendly attribute values map."""
    inverse = {v: k for k, v in _ATTR_TO_DEMO_KEY.items()}
    result: dict[str, Any] = {}
    for demo_key, value in demo.items():
        attr_id = inverse.get(demo_key) or demo_key.lower()
        result[attr_id] = value
    return result


# ─── Pipeline runner ─────────────────────────────────────────────────────────


def _run_pipeline_sync(request: GenerateRequest) -> GenerateResult:
    """Blocking pipeline execution — run inside the thread executor."""
    session_id = str(uuid.uuid4())

    # ── Step A — demographics ─────────────────────────────────────────────
    demo = _resolve_demographics(request.selections, request.seed)
    gender = demo.get("gender", "male")

    # ── Extract advisor fields from selections ────────────────────────────
    advisor: dict[str, Any] = {"role": "Professional"}
    for sel in request.selections:
        if sel.id == "role" and sel.mode in ("select", "predefined") and sel.value:
            advisor["role"] = sel.value
        elif sel.id in ("education", "experience", "traits") and sel.mode == "predefined":
            advisor[sel.id] = sel.value or []

    # ── Step B — advisor profile (LLM) ───────────────────────────────────
    if not all(k in advisor for k in ("education", "experience", "traits")):
        try:
            profile = generate_advisor_profile(
                advisor["role"],
                {"gender": gender, "age": demo.get("age", 30)},
                gateway_url=_GATEWAY_URL,
            )
            advisor.update(profile)
        except Exception as exc:
            logger.warning("[Step B] advisor profile failed: %s", exc)
            advisor.setdefault("education", [])
            advisor.setdefault("experience", [])
            advisor.setdefault("traits", [])

    # ── Step C — feature selection (LLM) ─────────────────────────────────
    features = None
    with tempfile.TemporaryDirectory(prefix="avatar_studio_") as tmpdir:
        session_dir = Path(tmpdir)
        try:
            features = select_features(
                demo,
                advisor,
                gateway_url=_GATEWAY_URL,
                session_dir=session_dir,
            )
        except Exception as exc:
            logger.warning("[Step C] feature selection failed: %s", exc)

        # ── Build avatar_persona & write persona.yml ──────────────────────
        avatar = build_avatar_charachter(advisor, demo, features)
        persona_path = session_dir / "persona.yml"
        with open(persona_path, "w") as f:
            yaml.dump(
                avatar["avatar_persona"],
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        style_arg = {
            "name": demo.get("style", "random"),
            "bg_color": demo.get("bg_color", "#F5F0E8"),
            "styles_yml": STYLES_YML,
        }

        # ── Step E — neutral portrait ─────────────────────────────────────
        expr_results: dict[str, str] = {}
        neutral_path = session_dir / "neutral.png"

        expressions_to_generate = request.expressions or ["neutral"]

        try:
            generate_avatar_image(
                persona_path,
                style=style_arg,
                expression={"name": "neutral", "expressions_yml": EXPRESSIONS_YML},
                gateway_url=_GATEWAY_URL,
                width=request.width,
                height=request.height,
                seed=request.seed,
                out_path=neutral_path,
                session_dir=session_dir / "neutral",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Image generation failed: {exc}") from exc

        expr_results["neutral"] = base64.b64encode(neutral_path.read_bytes()).decode()

        # ── Step F — expression variants (if requested) ───────────────────
        for expr_id in [e for e in expressions_to_generate if e != "neutral"]:
            expr_path = session_dir / f"{expr_id}.png"
            try:
                generate_avatar_image(
                    persona_path,
                    style=style_arg,
                    expression={"name": expr_id, "expressions_yml": EXPRESSIONS_YML},
                    reference_image=neutral_path,
                    gateway_url=_GATEWAY_URL,
                    width=request.width,
                    height=request.height,
                    seed=request.seed,
                    out_path=expr_path,
                    session_dir=session_dir / expr_id,
                )
                expr_results[expr_id] = base64.b64encode(expr_path.read_bytes()).decode()
            except Exception as exc:
                logger.warning("[Step F] %s failed: %s", expr_id, exc)

        # Primary image for the response (neutral)
        primary_b64 = expr_results.get("neutral", "")

        return GenerateResult(
            image_b64=primary_b64,
            avatar_persona=avatar["avatar_persona"],
            expressions=expr_results,
            session_id=session_id,
        )


# ─── Endpoints ───────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
async def get_config() -> dict:
    """Return all attribute definitions with resolved options."""
    loader = ConfigLoader()
    return loader.load()


@app.post("/api/avatar/randomize")
async def randomize_avatar(body: RandomizeRequest) -> dict:
    """Return randomized attribute values, respecting any fixed constraints."""
    demo = _resolve_demographics(body.constraints, body.seed)
    return {"values": _demo_to_response(demo)}


@app.post("/api/avatar/generate")
async def generate_avatar(body: GenerateRequest) -> GenerateResult:
    """Run the full pipeline and return the generated avatar image (base64 PNG)."""
    import asyncio

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _run_pipeline_sync, body)
    return result


# ─── Flutter web frontend (must be mounted LAST — catch-all) ─────────────────

_flutter_web_dir = _PROJECT_ROOT / "frontend" / "build" / "web"
if _flutter_web_dir.exists():
    app.mount("/", StaticFiles(directory=str(_flutter_web_dir), html=True), name="flutter_web")
else:
    logger.warning(
        "Flutter web build not found at %s — run 'flutter build web' inside frontend/",
        _flutter_web_dir,
    )
