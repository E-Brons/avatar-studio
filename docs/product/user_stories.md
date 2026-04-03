# Avatar Studio — User Stories

> **Who are the users?** The users of Avatar Studio are **packages and applications** that embed it as a library dependency or call it via its REST API. Stories are written from that perspective.

---

## US-1 · Generate Avatar

**As a** calling application,
**I want** to generate a full set of avatar images for a given persona description,
**so that** I can display a consistent visual identity for my character or agent across all emotional states.

### Inputs

| Input | Required | Description |
|-------|:--------:|-------------|
| Persona description / role | ✅ | Free-text description of the character (e.g. "senior financial analyst", "cheerful baby", "grumpy wizard") |
| Style | ❌ | One of the style IDs in `assets/styles/styles.yml`. Defaults to `random`. |
| Seed | ❌ | Integer seed for reproducible randomization in Step A |

### Outputs

| Output | Description |
|--------|-------------|
| `abbreviation.png` | Initials on a colored circle — available immediately (Step D, no LLM) |
| `neutral/output.png` | Canonical portrait (Step E) |
| `<expression>/output.png` | One portrait per expression in `expressions.yml` (Step F) |
| `persona.yml` | Full persona dict used for generation (useful for debugging and re-generation) |

### How to invoke

**Via Python package:**
```python
from avatar_studio.api.server import process_advisor

result = process_advisor(advisor_yaml_path="persona.yml")
```

**Via REST API:**
```http
POST /generate
Content-Type: application/json

{ "role": "cheerful baby", "style": "clay" }
```

**Via CLI:**
```bash
avatar-studio generate persona.yml
```

### Acceptance criteria

- All outputs are written before the call returns
- Abbreviation PNG is produced even if image generation fails
- The same seed produces the same persona across runs
- Style `random` produces a valid image (no system prompt constraint)

---

## US-2 · Add Expression

**As a** calling application or operator,
**I want** to add a new expression to the expression set,
**so that** all future avatar generations include that emotional state as a variant.

### How to

Add a new entry to `assets/expressions/expressions.yml`:

```yaml
- expression: Curiosity
  synonyms: [Interested, Intrigued, Curious]
  facs_action_units: "AU1 (slight), AU2 (slight), AU4 (trace)"
  description: >
    Asymmetric brow raise — one inner brow lifts slightly more than the
    other. Head tilts very slightly. Eyes widen marginally. Lips relaxed
    and slightly parted. An open, attentive, slightly questioning look.
```

**Fields:**

| Field | Description |
|-------|-------------|
| `expression` | Canonical name (used as folder name and classifier label) |
| `synonyms` | Alternative names the expression classifier accepts as a match |
| `facs_action_units` | FACS AUs and intensities — reference for prompt engineering and classifier scoring |
| `description` | Natural-language rendering instruction injected into the Step F prompt |

### What happens next

- Step F automatically generates a portrait for every expression in the file — no code change required
- Run `avatar-expression-tuner` to validate the new expression achieves acceptable classifier scores before deploying

### Acceptance criteria

- New expression variant PNG is produced alongside existing ones in every new generation run
- Expression classifier (`classify_expression.py`) returns the new expression ID in its top-1 result for at least N% of test seeds (target set by `--pass-threshold`)

---

## US-3 · Add Style

**As a** calling application or operator,
**I want** to add a new visual style,
**so that** avatars can be rendered in a new aesthetic without any code change.

### How to

Add a new entry to `assets/styles/styles.yml`:

```yaml
- id: watercolor
  name: Watercolor
  description: Soft watercolor illustration with visible brushwork and muted tones.
  key_technical_traits:
    - visible brushstroke texture on all surfaces
    - muted desaturated palette with soft color bleeds
    - no hard outlines — edges defined by color diffusion
    - paper texture visible in highlights
  closest_reference: editorial book illustration
  system_prompt: |
    Soft watercolor portrait illustration. Visible brushwork on skin,
    hair, and clothing. Muted desaturated palette. Edges defined by
    color diffusion, not outlines. Paper texture in highlight areas.
    No digital-looking sharpness anywhere.
  example_images:
    - assets/styles/avatar_style_watercolor_female.png
    - assets/styles/avatar_style_watercolor_male.png
    - assets/styles/avatar_style_watercolor_non_binary.png
```

**Key fields:**

| Field | Description |
|-------|-------------|
| `id` | Machine identifier used in API calls and file paths |
| `system_prompt` | Injected verbatim as the image model system prompt for Steps E and F. Cover rendering only — no background, no framing. `null` = model decides freely (`random`). |
| `key_technical_traits` | Rendering characteristics used by the style classifier and as prompt engineering reference |
| `example_images` | Optional reference PNGs for the tuner; generate them with `avatar-studio gen-examples` |

### What happens next

- The new style is immediately available in the API (`style: "watercolor"`)
- Run `avatar-style-tuner` to measure how reliably the image model produces output that matches the style's `key_technical_traits`
- Add reference PNGs to `assets/styles/` via `avatar-studio gen-examples` for use by the classifier

### Acceptance criteria

- `avatar-style-tuner` reports pass for the new style ID (classifier's `top_style_id` matches the style)
- No existing style scores regress after the addition

---

## US-4 · Configure Settings

**As a** calling application or operator,
**I want** to configure pipeline settings,
**so that** the pipeline fits my character types, infrastructure, and quality requirements.

### Configuration files

| File | Controls |
|------|----------|
| `assets/persona/phenotype_settings.json` | **Age groups** (ranges, including baby/toddler/kid/…/elder), gender options, name pools, skin tones, hair colors, eye colors, eye shapes, brow styles, nose shapes, chin shapes, cheeks shapes, background color palette |
| `assets/persona/cv_settings.json` | Step B LLM parameters (temperature, max_tokens) and CV schema (education, experience, traits) |
| `assets/persona/presentation_settings.json` | Step C LLM parameters (temperature, max_tokens), hair styles, clothing options, accessories options per gender |

### Common configurations

**Restrict age range** — limit generation to a specific age group (e.g. adults only):
```json
// phenotype_settings.json — remove or comment out unwanted age groups
"age_groups": {
  "adult":  [27, 36],
  "mature": [37, 46]
}
```

**Add a new age group** — already includes `baby` [0,1], `toddler` [2,5], etc. Add custom groups the same way:
```json
"age_groups": {
  "baby":    [0, 1],
  "toddler": [2, 5],
  "kid":     [6, 11]
}
```

**Change LLM model** — the gateway URL and default model keys are resolved from the settings passed to each pipeline step. Update the relevant key in `cv_settings.json` or `presentation_settings.json`.

**Add clothing options** — extend `clothing_options.neutral` in `presentation_settings.json`:
```json
"neutral": [
  "onesie", "romper", "tiny denim jacket over bodysuit", ...
]
```

### Acceptance criteria

- Pipeline runs without error after the change
- New age group appears in generated persona YAMLs with the expected age range
- New clothing options appear in Step C outputs

---

## US-5 · Tuning

**As a** calling application or operator,
**I want** to validate and improve the quality of generated avatars,
**so that** styles and expressions are reliably produced as intended.

### Tools

| Tool | Entry point | What it does |
|------|-------------|--------------|
| **Style Tuner** | `avatar-style-tuner` | Generates a portrait per style, runs the style classifier, reports pass/fail per style ID |
| **Expression Tuner** | `avatar-expression-tuner` | Generates a portrait per expression, runs the expression classifier, checks exact + synonym + semantic match |
| **Expression Autotuner** | `avatar-expression-autotuner` | Iterative loop: generate → classify → refine prompt → repeat up to `--max-iterations`. Stops when `--pass-threshold` is met. |

### Autotuner workflow

```bash
# Run autotuner for all expressions with default settings
avatar-expression-autotuner

# Run for a single expression, 10 iterations, 75% threshold
avatar-expression-autotuner \
  --expression Happiness \
  --max-iterations 10 \
  --pass-threshold 0.75
```

### CI integration

The autotuner is also available as a GitHub Actions workflow (`.github/workflows/tuner.yml`), triggered manually via `workflow_dispatch` with configurable expression, iterations, and threshold inputs.

### Acceptance criteria

- Style Tuner: `top_style_id` from the classifier matches the intended style ID for each style
- Expression Tuner: classifier top expression matches the expression label (exact or synonym match) with score ≥ threshold
- `test_pipeline_categorizer_score` CI test passes at ≥ 75% on the designated seed
