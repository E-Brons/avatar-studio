# Avatar Studio — Product Features

## Feature Overview

---

## Pipeline

| Feature | Description |
|---|---|
| **User** | *May* select (or confine) every feature of the avatar (e.g. age, style) |
| **Step A — Randomize Person** | Uniform random pick of *missing* demographics (name, gender, age), phenotype (skin tone, hair color, eye shape, etc.), and other features. No LLM call. |
| **Step B — Generate CV** | Text LLM generates *missing* education, experience, and personality traits from a role description and age. |
| **Step C — Select Features** | Text LLM picks *missing* apearnace: hair style, clothing, and accessories consistent with the persona. One call per field; context accumulates. |
| **Step D — Abbreviation Avatar** | Pillow renders initials on a WCAG-AA-compliant colored circle. Synchronous, no network call. |
| **Step E — Canonical Portrait** | Image LLM produces the neutral bust portrait that anchors all expression variants. |
| **Step F — Expression Variants** | Image LLM generates one portrait per expression, using the Step E output as a reference image to preserve identity. |
| **Step G — Postprocess** | `rembg` removes the generated background; Pillow composites the portrait over a colored circle with a white sticker border. |

---

## Styles

Visual styles are defined in `assets/styles/styles.yml` (single source of truth). Each style specifies a `system_prompt` injected into the image model call.

| Style ID | Name | Character |
|---|---|---|
| `random` | Random | No fixed style — model decides freely |
| `studio_3d` | 3D Animation | Physically-based CG rendering, exaggerated features, dramatic lighting |
| `korean` | Korean Cartoon | 2D digital illustration, anime-influenced, shiny hair and eyes |
| `photorealistic` | Photo-Realistic | Portrait photography fidelity, natural skin texture, shallow depth of field |
| `lineart` | Line Art Sticker | Flat fills, outline strokes, simplified friendly proportions |
| `clay` | 3D Clay | Matte plastic-clay finish, warm diffuse lighting, understated expression |

[Full style specifications](assets/styles/styles.yml)

---

## Expressions

FACS-grounded expressions are defined in `assets/expressions/expressions.yml`. Each expression includes FACS Action Unit specifications, synonyms, and rendering guidance.

| Expression | FACS Signal |
|---|---|
| Happiness | AU6 (marked), AU12 (marked) — Duchenne smile |
| Surprise | AU1, AU2 (marked), AU5, AU26 (moderate) |


[Full expressions specifications](assets/expressions/expressions.yml)

---

## Tuning System

| Tool | Entry Point | What It Does |
|---|---|---|
| **Style Tuner** | `avatar-style-tuner` | Generates portraits per style and classifies them; reports pass/fail per style |
| **Expression Tuner** | `avatar-expression-tuner` | Generates portraits per expression; checks exact, synonym, and semantic match |
| **Expression Autotuner** | `avatar-expression-autotuner` | Iterative loop: generate → classify → refine prompt → repeat up to N iterations |

The autotuner is also available as a GitHub Actions workflow (`.github/workflows/tuner.yml`) for CI-driven prompt improvement.

---

## API and CLI

| Interface | Entry Point | Description |
|---|---|---|
| **HTTP server** | `scripts/start_http_server.sh` | FastAPI service on port 8080; drives the Flutter web UI |
| **REST API** | `avatar-studio` (uvicorn) | FastAPI service; integrates with parent apps via HTTP |
| **`stage-b`** | `avatar-studio stage-b` | Run Step B only — print persona YAML |
| **`generate`** | `avatar-studio generate` | Full A→G pipeline for one or more advisor YAML files |
| **`gen-examples`** | `avatar-studio gen-examples` | Generate reference portraits for all styles × genders |

---

## Web UI

A Flutter web app (`frontend/`) provides an interactive browser UI for avatar creation.

### How it works

1. On load, the app fetches `GET /api/config` and builds all panels dynamically from the 19 attribute definitions — no hardcoded UI.
2. Every attribute shows a **mode selector** (segmented button):
   - 🎲 **Random** — pipeline picks a value at random (no LLM)
   - 🤖 **Bot** — LLM generates the value (fields marked `llm_generated`)
   - ✏️ **Select** — user picks a specific value (dropdown or free text)
   - 🔗 **Inherited** — value derived from another attribute (e.g. brows color ← hair color)
3. The **Randomize** button (`POST /api/avatar/randomize`) fills all random-mode fields with a grayed preview value, respecting any fixed (select/predefined) constraints.
4. The **Generate Avatar** FAB (`POST /api/avatar/generate`) runs the full A→E pipeline and displays the resulting portrait plus a collapsible `PersonaSummary`.

### Attribute panels (grouped by category)

| Category | Attributes |
|----------|-----------|
| Demographics | Gender, Age |
| Phenotype | Skin Tone, Hair Color, Eye Color, Brows Color, Eye Shape, Brow Style, Nose Shape, Chin Shape, Cheeks Shape |
| Appearance | Art Style, Hair Style, Clothing, Accessories |
| Advisor | Role, Education, Experience, Personality Traits |

### Gender dependency

Changing **Gender** automatically resets all `depends_on: gender` attributes (Brow Style, Chin Shape, Cheeks Shape, Hair Style, Clothing, Accessories) back to random mode, so gender-inappropriate options are never locked in.

### Starting the UI

```bash
# Install Python deps (once)
bash scripts/install.sh

# Start server + open browser (stops when you close the browser window)
bash scripts/start_http_server.sh

# Or run the Flutter app directly against a running server
cd frontend && flutter run -d chrome
```
