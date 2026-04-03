# Image Generation Prompt Improvement — Research Plan

**Status:** Active
**Date:** 2026-04-02
**Context:** `test_pipeline_categorizer_score` scores ~58–67 % against a 75 % threshold.

---

## Problem Statement

The categorizer tests generate a portrait via FLUX (through the LLM Gateway `/image_gen`)
and verify that the generated image matches the persona properties. The current prompt is a
raw YAML dump of `avatar_persona` plus the style directive. FLUX ignores or misreads many
of the specified properties.

Observed failure pattern across multiple runs:

| Property | Failure mode |
|---|---|
| `skin_tone` | FLUX renders medium-tan regardless of the specified hex |
| `hair_color` | Often darker than specified; near-black is frequent |
| `eye_color` | Wrong color family (blue vs brown, etc.) |
| `eye_shape` | Subtle shapes (downturned, wide-set) not reproduced |
| `brows_style` | Arch/thickness ignored; FLUX uses a default |
| `nose_shape` | Only very distinctive shapes (aquiline, broad) survive |
| `chin_shape` | Subtle variations (heart-tip, wide-flat) lost |
| `cheeks_shape` | Ignored unless extreme (hollow/sculpted) |

Properties that already pass reliably: `gender`, `hair_style`, `clothing`, `accessories`,
and (with YCbCr tolerance) `eye_color` when the distance is small.

---

## Root Causes

1. **YAML is not image-model language.** FLUX is trained on image captions, not structured
   YAML. A key like `skin_tone: "#A67C52"` carries no meaning to it. The model needs a
   natural-language portrait description.

2. **Hex codes are meaningless to FLUX.** `#A67C52` does not convey "warm medium-brown
   skin." Human-readable color names must be substituted before the prompt reaches the
   model.

3. **Structural feature terms are inconsistent.** "bulbous tip nose" or "soft rounded chin"
   are not FLUX's vocabulary. FLUX responds to photographic/artistic descriptors
   ("rounded nose tip", "gentle round chin").

4. **Style directive and persona are concatenated, not blended.** The style directive
   (e.g., "photorealistic portrait…") sets the rendering style, but the persona properties
   (features, colors) are in a separate block that FLUX may not associate with it.

5. **No explicit rendering instruction.** The prompt doesn't tell FLUX *how* to use the
   persona — it just dumps data. FLUX needs an explicit instruction like
   "render a portrait of this person."

---

## Approach

Improve the prompt-building function in `step_ef_generate_image.py` that constructs
`full_prompt` before calling the gateway. The goal is a natural-language portrait
description that FLUX can use directly.

### Investigation sequence

Work through failures one by one. For each property, measure improvement across 10 seeds
before moving on.

---

### Step 1 — Replace YAML dump with a natural-language portrait description

**Current:**
```
persona profile:
personal:
  name: Marcus Lee
  gender: male
  age: 42
appearance:
  skin_tone: '#A67C52'
  hair_style: side-parted short
  hair_color: {hex_base: '#3B2314', hex_shadow: '#261508'}
  ...
```

**Proposed:** Build a single coherent portrait paragraph using the appearance fields in
the order a portrait artist would use them.

```
Portrait of a 42-year-old male.
Skin: warm medium-brown.
Hair: short side-parted, dark brown.
Eyes: almond-shaped, amber/hazel.
Eyebrows: straight and full.
Nose: long and straight.
...
Wearing: navy blazer (#1A3A5C), white collared shirt (#E8E0D0).
Accessories: thin rectangular glasses; neat short beard.
```

---

### Step 2 — Convert hex colors to natural-language names in the prompt

The hex-to-label tables already exist in `classify_persona.py`
(`_SKIN_TONE_LABELS`, `_HAIR_BASE_LABELS`, `_EYE_IRIS_LABELS`). Use the same
`_hex_label` / nearest-color logic to translate hex values in the prompt.

Clothing hex codes: convert to color name (e.g., `#1A3A5C` → "dark navy").

---

### Step 3 — Normalise facial feature vocabulary to FLUX-friendly terms

Some values in the settings are ambiguous or anime-specific. Map them to
photographic portrait descriptors before including in the prompt.

Examples:
- `subtle vertical line` → `minimal nose, barely defined`
- `manga (large, exaggerated irises)` → `large expressive eyes`
- `bold unibrow` → `thick continuous brow`
- `wide-set` → `eyes placed wide apart on the face`

Maintain a vocabulary mapping in `step_ef_generate_image.py` (or a shared helper).

---

### Step 4 — Add an explicit rendering instruction

Prefix the portrait description with a clear instruction that tells FLUX what to do
with the data:

```
Generate a portrait photograph of the following person.
Reproduce all physical traits faithfully. [style directive]
[portrait description]
```

---

### Step 5 — Evaluate style-feature compatibility

Some feature values (manga eyes, anime nose) are inherently incompatible with the
`photorealistic` style. Two sub-approaches to investigate:

**5a — Filter:** In the prompt builder, silently skip features that conflict with the
selected style (e.g., skip `eye_shape: manga` when style is `photorealistic`).

**5b — Style auto-select:** Allow `pick_demographics` to bias the style selection
based on the feature set picked in Step A (cartoon features → cartoon/korean style).

Evaluate which produces better categorizer scores.

---

## Test Methodology

Each step must be validated before moving on:

1. Generate portraits for **10 seeds** chosen to cover a range of feature combinations
   (light/dark skin, male/female, varied eye/nose shapes).
2. Run the categorizer on all 10.
3. Compute **mean score** and **pass rate** (score ≥ 75 %).
4. A step is considered a win when pass rate ≥ 80 % across the 10 seeds.

Seeds to use for evaluation:
```
1, 2, 3, 4, 8, 21, 25, 138, 185, 204
```
(These cover male/female, light/dark skin, varied eye/nose/brow combinations —
identified by scanning the demographics picker for photorealistic-compatible features.)

The integration test `test_pipeline_categorizer_score` uses a fixed seed and must pass
reliably. The evaluation suite (10 seeds) is a separate research harness, not part of CI.

---

## Files to modify

| File | Change |
|---|---|
| `src/avatar_studio/pipeline/step_ef_generate_image.py` | Rewrite `_build_persona_prompt()` (new helper); replace YAML dump with natural-language description |
| `src/avatar_studio/config/config.py` | Optionally expose `_hex_label` for reuse |
| `assets/persona/phenotype_settings.json` | Optionally add `flux_vocab` mapping for feature normalisation |

---

## Success Criteria

- `test_pipeline_categorizer_score` passes at ≥ 75 % on seed=21
- `test_circle_frame_categorizer` passes at ≥ 65 % on seed=4
- Both tests pass consistently on 3 consecutive CI runs
- Mean categorizer score across 10 evaluation seeds ≥ 75 %
