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
| **REST API** | `avatar-studio` (uvicorn) | FastAPI service; integrates with parent apps via HTTP |
| **`stage-b`** | `avatar-studio stage-b` | Run Step B only — print persona YAML |
| **`generate`** | `avatar-studio generate` | Full A→G pipeline for one or more advisor YAML files |
| **`gen-examples`** | `avatar-studio gen-examples` | Generate reference portraits for all styles × genders |
