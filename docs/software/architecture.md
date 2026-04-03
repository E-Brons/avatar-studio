# Avatar Studio — Architecture

**Project**: avatar-studio — standalone avatar generation package
**Date**: 2026-04-02
**Version**: 0.1.0

---

## Table of Contents

1. [Overview](#1-overview)
2. [Pipeline Stages (A→G)](#2-pipeline-stages-ag)
3. [Package Structure](#3-package-structure)
4. [Data Flow](#4-data-flow)
5. [LLM Usage](#5-llm-usage)
6. [Tuning System](#6-tuning-system)
7. [HTTP Server](#7-http-server-aphttp_serverpy)
8. [Flutter Web UI](#8-flutter-web-ui)

---

## 1. Overview

Avatar Studio generates avatars through a 7-stage pipeline. Each stage is independently testable; the pipeline can be run end-to-end or stage-by-stage.

All LLM calls are routed through the LLM Gateway at `http://127.0.0.1:4096`.

```mermaid
graph LR
    classDef code     fill:#27AE60,color:#fff,stroke:#1E8C4E
    classDef llmText  fill:#7B61FF,color:#fff,stroke:#5B41DF
    classDef llmImage fill:#E67E22,color:#fff,stroke:#C46A1A
    classDef pil      fill:#1A6A9A,color:#fff,stroke:#0D4F7A

    A["A · Randomise Person"]:::code
    B["B · Generate CV"]:::llmText
    C["C · Select Features"]:::llmText
    D["D · Abbreviation + ToonHead"]:::pil
    E["E · Canonical Portrait"]:::llmImage
    F["F · Expression Variants"]:::llmImage
    G["G · Postprocess"]:::pil

    A --> B --> C --> D
    C --> E --> F --> G
```

---

## 2. Pipeline Stages (A→G)

| Stage | Module | What it does | LLM? |
|-------|--------|--------------|:----:|
| **A** | `pipeline/step_a_randomise_person.py` | Random demographics, name, phenotype colors | ❌ |
| **B** | `pipeline/step_b_generate_cv.py` | Education, experience, traits from role | ✅ text |
| **C** | `pipeline/step_c_select_features.py` | Hair style, clothing, accessories per-field | ✅ text |
| **D** | `pipeline/step_d_make_abbreviation.py` + `pipeline/step_d_make_toon_head.py` | Initials PNG (PIL) + ToonHead SVG (DiceBear, Node) | ❌ |
| **E** | `pipeline/step_ef_generate_image.py` | Neutral portrait from full persona | ✅ image |
| **F** | `pipeline/step_ef_generate_image.py` | Expression variants from neutral reference | ✅ image |
| **G** | `pipeline/step_g_postprocess.py` | Circle frame sticker composite (PIL + rembg) | ❌ |

### Stage A — Randomise Person

Produces a `demographics` dict with:
- Identity: `gender`, `age`, `name`
- Style: `style`, `bg_color`, `fg_color`
- Phenotype colors: `SKIN_TONE`, `HAIR_COLOR`, `EYE_COLOR`, `BROWS_COLOR`
- Shape fields: `EYE_SHAPE`, `BROWS_STYLE`, `NOSE_SHAPE`, `CHIN_SHAPE`, `CHEEKS_SHAPE`

All values drawn uniformly from the palettes in `assets/persona/phenotype_settings.json`. No LLM involved.

### Stage B — Generate CV

Calls a text LLM once to produce `education`, `experience`, `traits`. Retries up to `max_retries` on empty or malformed responses.

### Stage C — Select Features

One LLM call per field: `HAIR_STYLE`, `CLOTHING` (dict), `ACCESSORIES` (dict). Phenotype fields are pre-seeded from Stage A demographics — no LLM needed for them. Context accumulates across fields so each pick is consistent with the emerging persona.

### Stage D — Abbreviation + ToonHead Avatars

Two fast, code-only avatars are generated in parallel before any LLM call:

1. **Abbreviation** — PIL renders initials on a WCAG-AA-compliant colored circle. Deterministic; no network calls. Output: `<slug>-abbreviation.png`.
2. **ToonHead** — DiceBear `big-smile` style SVG, generated via `vendor/toon-head/generate.js` (Node.js subprocess). Seed = person name → same name always produces the same avatar. Output: `<slug>-toon-head.svg`. ToonHead failure is non-fatal; the pipeline continues without it.

### Stage E — Canonical Portrait

Single Ollama image model call. Input: `persona.yml` + style directive + `neutral` expression. Output: PNG.

### Stage F — Expression Variants

One Ollama image model call per expression. Sends the Stage E portrait as a reference image so the model preserves identity across expressions.

### Stage G — Postprocess

`rembg` removes the portrait background; PIL composites it over a colored circle with a white sticker border.

---

## 3. Package Structure

```
src/
├── config/
│   ├── config.py           # Settings, WCAG utils, color helpers
│   └── gateway.py          # LLM Gateway client
├── pipeline/
│   ├── step_a_randomise_person.py
│   ├── step_b_generate_cv.py
│   ├── step_c_select_features.py
│   ├── step_d_make_abbreviation.py
│   ├── step_d_make_toon_head.py
│   ├── step_ef_generate_image.py
│   └── step_g_postprocess.py
├── api/
│   ├── config_loader.py     # Loads attributes.yml; resolves source: refs → option lists
│   ├── http_server.py       # FastAPI HTTP server (port 8080); browser-shutdown WS
│   ├── server.py            # process_advisor, model resolution helpers (CLI backend)
│   └── cli.py               # CLI entry point (avatar-studio command)
└── tuning/
    ├── classify_expression.py
    ├── classify_style.py
    ├── classify_persona.py
    ├── expression_tuner.py  # avatar-expression-tuner CLI
    └── style_tuner.py       # avatar-style-tuner CLI
assets/
├── expressions/
│   └── expressions.yml               # Expression definitions: FACS, synonyms, descriptions
├── persona/
│   ├── attributes.yml                # Master UI attribute definitions (19 attrs)
│   ├── cv_settings.json              # Step B: LLM params + CV schema
│   ├── phenotype_settings.json       # Step A: age groups, names, phenotype options, palette
│   └── presentation_settings.json   # Step C: LLM params + hair/clothing/accessories options
└── styles/
    ├── styles.yml                    # Style definitions: system prompts, technical traits
    └── avatar_style_<style>_<gender>.png  # 15 reference PNGs (5 styles × 3 genders)
frontend/                             # Flutter web app
├── lib/
│   ├── main.dart / app.dart          # Entry point + ProviderScope + KeepaliveService
│   ├── core/api/                     # API client (Dio), models, keepalive WebSocket
│   ├── core/config/                  # Server URL constant
│   ├── core/theme/                   # Material theme
│   ├── features/
│   │   ├── config/providers/         # configProvider → GET /api/config
│   │   └── avatar/                   # selectionsNotifier, generateNotifier, main screen
│   └── widgets/
│       ├── attribute_panel/          # AttributePanel, ModeSelector, content widgets
│       └── avatar_preview/           # AvatarPreviewPane, GenerationProgress
└── web/                              # Web-only platform assets (index.html, manifest)
tests/
├── conftest.py
├── test_api.py                   # ConfigLoader + http_server helpers (no services)
├── test_avatar_features.py       # Step B/C: LLM mocks, feature selection
├── test_avatar_integration.py    # Integration tests (require OLLAMA_URL)
└── test_avatar_stages.py         # Step A/D/E/F: randomise, PIL, create_face_avatar
```

---

## 4. Data Flow

```mermaid
sequenceDiagram
    participant Client
    participant StepA as Step A<br>(randomise)
    participant StepBC as Steps B+C<br>(text LLM)
    participant StepD as Step D<br>(PIL + Node)
    participant StepEF as Steps E+F<br>(image LLM)
    participant StepG as Step G<br>(PIL + rembg)

    Client->>StepA: role, optional seed
    StepA-->>StepBC: demographics dict
    StepBC-->>StepEF: avatar_persona.yml
    StepA-->>StepD: bg_color, name
    StepD-->>Client: abbreviation.png + toon-head.svg
    StepEF-->>StepG: neutral.png, expression_N.png
    StepG-->>Client: framed PNGs
```

---

## 5. LLM Usage

All LLM calls go through the **LLM Gateway** (`config/gateway.py`, default `http://127.0.0.1:4096`). The pipeline never calls model endpoints directly. The gateway exposes three endpoints used by avatar-studio:

| Gateway endpoint | Protocol | Used by |
|-----------------|----------|---------|
| `POST /text_gen` | `{messages, max_retries}` → `{content}` | Steps B, C |
| `POST /image_gen` | `{prompt, width, height, seed?, reference_images_b64?}` → `{image_b64}` | Steps E, F |
| `POST /image_inspector` | `{image_b64, system, prompt, max_retries}` → `{content}` | Classifiers |
| `GET /api/tags` | — → `{models: [{name}]}` | Model discovery (startup) |

### Per-stage breakdown

| Step | Gateway endpoint | Key inputs | Output |
|------|-----------------|------------|--------|
| B | `POST /text_gen` | Role + demographics as messages | YAML: education / experience / traits |
| C | `POST /text_gen` | Profile + selected-so-far as messages (one call per field) | One field value per call |
| E | `POST /image_gen` | Prompt from `persona.yml` + style directive; no reference image | PNG portrait (neutral) |
| F | `POST /image_gen` | Same prompt + `reference_images_b64` = Step E portrait | PNG expression variant |
| Classifiers | `POST /image_inspector` | Generated PNG + system prompt with label hints | YAML scores |

Model selection and gateway URL are resolved at runtime from `assets/persona/cv_settings.json` and `assets/persona/presentation_settings.json`.

---

## 6. Tuning System

Two CLI tuners iteratively validate that generated avatars match their intended style or expression.

### Style Tuner (`avatar-style-tuner`)

```
for each style:
    generate portrait → classify style → report pass/fail
```

Pass: classifier's `top_style_id` matches the intended style.

### Expression Tuner (`avatar-expression-tuner`)

```
for each expression:
    generate portrait → classify expression → check exact match or synonym match
    → semantic fallback via LLM per-phrase check
```

Pass: classifier top expression matches label (exact or semantic), probability ≥ threshold.

---

## 7. HTTP Server (`api/http_server.py`)

`api/http_server.py` is a **FastAPI application** (port 8080) that wraps the pipeline for use by the Flutter web UI and any HTTP client.

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness check → `{"status": "ok"}` |
| `GET` | `/api/config` | Returns all 19 attribute definitions with resolved options (fast, no LLM) |
| `POST` | `/api/avatar/randomize` | Runs Step A + applies constraint overrides → resolved attribute values |
| `POST` | `/api/avatar/generate` | Full A→E pipeline in thread executor → base64 PNG + `avatar_persona` |
| `WS` | `/api/ws/keepalive` | Browser presence channel; drives auto-shutdown |

### Configuration loading (`api/config_loader.py`)

`ConfigLoader.load()` reads `assets/persona/attributes.yml` (19 attribute definitions) and resolves each attribute's `source:` field into a typed option list:

| Source type | Resolution |
|-------------|-----------|
| `phenotype_settings.json:skin_tones` | Flat list → `[{id, label}]` color options |
| `phenotype_settings.json:hair_colors` | `"#BASE #SHADOW"` pairs → dual_color options with `extra.hex_base / hex_shadow` |
| `phenotype_settings.json:brows_styles` | Gender-bucketed dict → all items tagged `extra.gender_bucket` |
| `phenotype_settings.json:age_groups` | Named ranges → `[{id, label, extra:{min,max}}]` |
| `styles.yml:styles` | Style entries → `[{id, label, extra:{description, example_images}}]` |
| `presentation_settings.json:hair_styles` | Gender-bucketed dict → items tagged `extra.gender_bucket` |

### Browser auto-shutdown

When launched with `AVATAR_BROWSER_SHUTDOWN=1` (set by `scripts/start_http_server.sh`), the server terminates itself when all browser sessions disconnect:

1. Each browser tab connects to `WS /api/ws/keepalive` on app start
2. A background task (`_shutdown_watcher`) watches `_active_sessions`
3. When the set empties, it waits `AVATAR_SHUTDOWN_GRACE` seconds (default 8 s) to tolerate page reloads
4. If still empty → `os.kill(os.getpid(), signal.SIGTERM)` → uvicorn exits cleanly

### Attribute ID mapping

Pipeline functions use `UPPER_CASE` keys (`SKIN_TONE`, `HAIR_COLOR`, …). The HTTP layer maps to/from `snake_case` attribute IDs via `_ATTR_TO_DEMO_KEY`. `BROWS_COLOR` is always re-derived from the `hair_color` base hex when `hair_color` is overridden.

### Starting the server

```bash
bash scripts/start_http_server.sh   # starts + opens browser + shuts down on close
# or manually:
AVATAR_BROWSER_SHUTDOWN=1 .venv/bin/uvicorn api.http_server:app \
    --host 127.0.0.1 --port 8080 --app-dir src
```

### Old CLI API layer

`api/server.py` provides `process_advisor()` — used by the CLI and earlier integrations.

`api/cli.py` exposes three sub-commands via the `avatar-studio` entry point:

| Sub-command | What it does |
|-------------|--------------|
| `stage-b` | Run Step B only (LLM feature selection), print YAML |
| `generate` | Full A→G pipeline for one or more advisor YAML files |
| `gen-examples` | Generate style reference portraits (all styles × genders) |

---

## 8. Flutter Web UI

The Flutter web app (`frontend/`) provides an interactive browser UI for avatar creation. It talks exclusively to the FastAPI server on `http://127.0.0.1:8080`.

### State flow

```
App start
  └─ configProvider → GET /api/config
        └─ Renders all 19 AttributePanel widgets grouped by category

User adjusts attributes (ModeSelector: 🎲 random | 🤖 llm | ✏️ select | 🔗 inherited)
  └─ selectionsNotifier.setSelection(id, mode, value)
        └─ if gender changed → reset all depends_on:gender attrs to random

🎲 Randomize button (AppBar)
  └─ POST /api/avatar/randomize { constraints }
        └─ selectionsNotifier.applyRandomizeResult(values)
              └─ fills random-mode attrs with grayed preview values

✨ Generate FAB
  └─ generateNotifier.generate()
        └─ POST /api/avatar/generate { selections, expressions:["neutral"] }
              └─ AvatarPreviewPane shows shimmer → decoded PNG + PersonaSummary
```

### Key files

| File | Role |
|------|------|
| `core/config/app_config.dart` | `kApiBaseUrl` constant |
| `core/api/api_models.dart` | Plain Dart classes mirroring Pydantic models |
| `core/api/avatar_api_client.dart` | Dio HTTP client wrapper |
| `core/api/keepalive_service.dart` | WS connection to `/api/ws/keepalive`; holds connection open for browser-shutdown detection |
| `features/config/providers/config_provider.dart` | `FutureProvider` → `GET /api/config` |
| `features/avatar/providers/selections_provider.dart` | `StateNotifier` — all current selections + gender-dep reset |
| `features/avatar/providers/generate_provider.dart` | `AsyncNotifier` — wraps `POST /api/avatar/generate` |
| `features/avatar/screens/avatar_studio_screen.dart` | Root screen: split-pane layout |
| `widgets/attribute_panel/attribute_panel.dart` | Per-attribute card + mode selector + content widget |
| `widgets/attribute_panel/mode_selector.dart` | Segmented button (🎲 🤖 ✏️ 🔗) |
| `widgets/attribute_panel/content/*.dart` | Choice / color / dual_color / integer / text / list widgets |
| `widgets/avatar_preview/avatar_preview_pane.dart` | Base64 image display + PersonaSummary collapsible |
| `widgets/avatar_preview/generation_progress.dart` | Shimmer placeholder during generation |
