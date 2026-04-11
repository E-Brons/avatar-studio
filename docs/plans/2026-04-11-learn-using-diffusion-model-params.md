# Plan: Learn Using Diffusion Model Parameters

**Date:** 2026-04-11
**Status:** Implemented

---

## Problem

The learning scripts (`learn_restyle.py`, `learn_reexpress.py`) implement the REASON step as
text-only patching: `styles.yml` system_prompt strings for restyle, FACS codes and synonyms in
`expressions.yml` for reexpress. All diffusion model parameters (`ip_adapter_scale`, `cfg_scale`,
`negative_prompt`, `num_inference_steps`, `lora`, `lora_weight`) are hardcoded in `_process_one`
and invisible to the REASON LLM.

The doc specifies that the Prompt Generator for IPAdapter pipelines must output the full set of
diffusion parameters:

| Output | ReStyle | ReExpress | Currently |
|---|---|---|---|
| `prompt` | style attributes → CLIP text | expression attributes → CLIP text | ✓ (hardcoded template) |
| `negative_prompt` | ✓ | ✓ | ✗ |
| `width`, `height` | ✓ | ✓ | ✓ (hardcoded 512×512) |
| `num_inference_steps` | ✓ | ✓ | ✗ (only `optimize` abstraction) |
| `cfg_scale` | ✓ | ✓ | ✗ |
| `ip_adapter_scale` | ✓ | ✓ | ✗ (`weight` param removed as unsupported) |
| `lora`, `lora_weight` | ✓ | ✓ | ✗ |

---

## Create vs IPAdapter — parameter surfaces are different

The doc defines two distinct Prompt Generator surfaces:

**Create (`image_gen`)** — controls an LLM generating an image from text:
```
prompt, width, height, num_inference_steps, temperature, max_tokens
```

**ReStyle / ReExpress (`ipadapter_faceid`)** — controls a diffusion model conditioned on a
reference image:
```
prompt, negative_prompt, width, height, num_inference_steps,
cfg_scale, ip_adapter_scale, lora, lora_weight
```

`temperature` and `max_tokens` are LLM knobs; `cfg_scale`, `ip_adapter_scale`, `lora*` are
diffusion knobs. These sets do not overlap. This plan covers only the IPAdapter surface.
The Create pipeline is out of scope.

---

## Design: config-driven Prompt Generator

All IPAdapter generation parameters live in two YAML config files under `assets/prompt_gen/`.
The REASON LLM modifies these files. The Prompt Generator module reads them at call time.
No code injection; all changes are data.

### New config files

#### `assets/prompt_gen/restyle.yml`

```yaml
# Template variable: {style_description} — filled from style entry at call time
prompt_template: >-
  {style_description}. Same person, preserve face and appearance.
  Professional portrait, chest-up, soft lighting.
  Confident neutral expression, flat medium-contrast background.
negative_prompt: "deformed, blurry, low quality, overexposed, watermark, text, signature"
width: 512
height: 512
num_inference_steps: 20
cfg_scale: 7.0
ip_adapter_scale: 0.7
lora: null
lora_weight: 1.0
```

#### `assets/prompt_gen/reexpress.yml`

```yaml
# Template variables: {expression_name}, {facs_au_codes}
prompt_template: "Same person, preserve face and appearance. {expression_name}, {facs_au_codes}."
negative_prompt: "deformed, blurry, low quality, wrong expression, distorted face, unnatural mouth"
width: 512
height: 512
num_inference_steps: 20
cfg_scale: 7.0
ip_adapter_scale: 0.6
lora: null
lora_weight: 1.0
```

---

## New module: `src/pipeline/render/ipadapter/prompt_gen.py`

New package `src/pipeline/render/ipadapter/` with `__init__.py` and `prompt_gen.py`.

```python
@dataclass
class IPAdapterGenParams:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    num_inference_steps: int
    cfg_scale: float
    ip_adapter_scale: float
    lora: str | None
    lora_weight: float

def build_restyle_params(style_entry: dict) -> IPAdapterGenParams:
    """Load restyle.yml config, fill {style_description} from style_entry."""
    ...

def build_reexpress_params(expr_entry: dict) -> IPAdapterGenParams:
    """Load reexpress.yml config, fill {expression_name} and {facs_au_codes} from expr_entry."""
    # {facs_au_codes}: pass through resolve_unilateral, strip intensity labels
    ...
```

Both functions re-load the YAML on each call so that mid-run config patches are picked up
immediately in the next iteration without restarting.

`build_clip_prompt_restyle` and `build_clip_prompt_reexpress` in `prompt_builder.py` are
**superseded** by this module for the learning scripts and should not be called from them.
The pipeline production code (`restyle.py`, `reexpress.py`) can be migrated separately.

---

## Gateway client: `src/config/gateway.py`

Extend `ipadapter_faceid` with the full parameter surface. All new params are optional and
sent in the payload only when not `None`:

```python
def ipadapter_faceid(
    self,
    prompt: str,
    face_images_b64: list[str],
    *,
    negative_prompt: str | None = None,
    width: int = 256,
    height: int = 256,
    num_inference_steps: int | None = None,
    cfg_scale: float | None = None,
    ip_adapter_scale: float | None = None,
    lora: str | None = None,
    lora_weight: float | None = None,
    seed: int | None = None,
    optimize: str = "normal",
    max_retries: int = 3,
    timeout: int = 300,
) -> bytes:
```

`optimize` is kept as a coarse compute-budget override (the CLI `--optimize` flag still
controls generation speed). `num_inference_steps` is the fine-grained config value; when both
are provided, `optimize` adjusts the step count as a multiplier on top of whatever the gateway
server applies — exact interaction is server-defined.

The old `weight` parameter (default 0.7, removed from the payload after the 500 error) is
**deleted from the signature** entirely in this pass.

---

## `optimize` vs `num_inference_steps` — quality feedback loop

The gateway server almost certainly maps `optimize` to a fixed step count internally:
`fast` → N₁ steps, `normal` → N₂ steps, `quality` → N₃ steps. We do not know those values.

The problem: the REASON LLM can tune `num_inference_steps` in the config, but if `--optimize fast`
is in effect and the server uses it to override or cap the step count, the config value has no
effect — and the quality_score will silently degrade without the LLM knowing why.

### Signal available

`quality_score` comes from `compare_side_by_side` and is already collected per-entry in
`_process_one`. It is included in the SBS compound score and surfaced in the per-iteration
summary. This is exactly the signal needed to detect step-count starvation.

### Proposed approach: `optimize` as a named step preset, `num_inference_steps` as override

The config stores `num_inference_steps` as the **desired** base step count for full-quality
learning runs. The gateway client sends it in the payload when set. The gateway server must
treat it as authoritative and ignore its internal `optimize→steps` mapping when
`num_inference_steps` is explicitly provided.

At the same time, the CLI `--optimize` flag remains useful as a **scale factor** for quick
smoke runs where the user intentionally accepts lower quality:

```
--optimize fast    →  multiply config num_inference_steps by 0.5 (floor 10)
--optimize normal  →  use config num_inference_steps as-is
--optimize quality →  multiply config num_inference_steps by 1.5
```

This scaling is applied in the learning scripts before the gateway call, not inside the gateway.
The gateway always receives the resolved integer `num_inference_steps` and is never sent
`optimize` for IPAdapter calls (unlike `image_gen`, which keeps `optimize` as its only speed
knob because it does not expose `num_inference_steps`).

### REASON LLM responsibility

The REASON prompt must include:
- Per-iteration `quality_score` summary (avg + worst examples)
- The current `num_inference_steps` value from the config
- An explanation that low quality_score is a likely indicator of insufficient steps

If quality_score is consistently low (< compound_threshold) while identity and style/expression
scores are acceptable, the LLM should increase `num_inference_steps`. If quality_score is
consistently high across all step counts tested, it may safely reduce steps to speed up future
runs (and implicitly free compute budget for more samples).

### Learning artefact: `optimize_step_map`

Over multiple learning runs, the scripts accumulate evidence of what step count is
"good enough" for each style. This is surfaced in the iteration history and FINAL summary.
No automated mapping is built yet, but the LJSON logs provide the data for a future
calibration pass.

---



### Shared `prompt_gen_patches` sub-object (both scripts)

Fields are all optional (null = no change to that field):

```json
{
  "prompt_template": null,
  "negative_prompt": null,
  "num_inference_steps": null,
  "cfg_scale": null,
  "ip_adapter_scale": null,
  "lora": null,
  "lora_weight": null
}
```

`prompt_template` is a full string replacement (not a find/replace patch). The LLM writes the
entire new template; the old one is overwritten. Find/replace is insufficient here because the
template is short and structural.

### Restyle REASON schema

```json
{
  "prompt_gen_patches": { ... },
  "style_prompt_patches": [{"style_id": str, "find": str, "replace": str}],
  "rationale": str
}
```

`style_prompt_patches` is retained: the style `system_prompt` in `styles.yml` (used by the
Create pipeline and style classification) is still worth tuning separately from the CLIP
`prompt_template` in `restyle.yml`.

### Reexpress REASON schema

```json
{
  "prompt_gen_patches": { ... },
  "expression_synonym_additions": { "ExprName": ["synonym1", ...] },
  "facs_patches": [{"expression": str, "find": str, "replace": str}],
  "rationale": str
}
```

`expression_synonym_additions` and `facs_patches` are retained: the classifier uses them,
and FACS codes feed directly into the `{facs_au_codes}` template variable.

### FINAL schema

Same JSON structure as the corresponding REASON schema. The prompt instructs the LLM to
consolidate (select from existing solutions, do not propose new values).

---

## Patch application helper

New function in each script (or shared `_prompt_gen_fixes.py`):

```python
def _apply_prompt_gen_patches(patches: dict, config_path: Path) -> list[str]:
    """Apply prompt_gen_patches dict to a YAML config file. Returns list of applied changes."""
    # Load YAML
    # For each non-null field in patches: update the config dict
    # Atomic write back to YAML
    # Return ["restyle.yml: ip_adapter_scale 0.7 → 0.8", ...]
```

---

## Changes to learning scripts

### `_process_one` in `learn_restyle.py`

```python
from pipeline.render.ipadapter.prompt_gen import build_restyle_params

pg = build_restyle_params(style_entry)

candidate_bytes = client.ipadapter_faceid(
    pg.prompt,
    [source_b64],
    negative_prompt=pg.negative_prompt,
    width=pg.width,
    height=pg.height,
    num_inference_steps=pg.num_inference_steps,
    cfg_scale=pg.cfg_scale,
    ip_adapter_scale=pg.ip_adapter_scale,
    lora=pg.lora,
    lora_weight=pg.lora_weight,
    optimize=optimize,
)
```

The `style_entry` parameter already flows into `_process_one`; no signature change needed.

### `_process_one` in `learn_reexpress.py`

```python
from pipeline.render.ipadapter.prompt_gen import build_reexpress_params

pg = build_reexpress_params(expr_entry)

candidate_bytes = client.ipadapter_faceid(
    pg.prompt,
    [source_b64],
    negative_prompt=pg.negative_prompt,
    width=pg.width,
    height=pg.height,
    num_inference_steps=pg.num_inference_steps,
    cfg_scale=pg.cfg_scale,
    ip_adapter_scale=pg.ip_adapter_scale,
    lora=pg.lora,
    lora_weight=pg.lora_weight,
    optimize=optimize,
)
```

The `expr_entry` already flows in via `resolve_expression(expression_id)`.

### REASON prompt update

The reasoning prompt sent to `client.reasoning()` must include the full current
`restyle.yml` / `reexpress.yml` config and explain each parameter's effect on generation
quality, identity preservation, and expression fidelity. The LLM needs to know:

- `ip_adapter_scale`: higher = stronger reference image adherence (identity), lower = more
  style freedom. Typical range 0.4–0.9.
- `cfg_scale`: classifier-free guidance strength. Higher = more prompt-adherent but less
  natural. Typical range 5–12.
- `num_inference_steps`: more steps = higher quality but slower. Typical range 15–50.
- `negative_prompt`: what to suppress. Directly affects artifact rate.
- `prompt_template`: the CLIP conditioning text (≤77 tokens; template variables are filled
  at call time and do not count toward this limit).
- `lora` / `lora_weight`: optional fine-tuned style adapter. `null` = disabled.

### FINAL prompt update

Consolidation prompt includes:
- Full iteration history (scores, improvement deltas, what was applied each iteration)
- Current state of the config YAML
- Instruction: do not propose values not already tested in the history

---

## File summary

| File | Action |
|---|---|
| `assets/prompt_gen/restyle.yml` | **Create** — restyle Prompt Generator config |
| `assets/prompt_gen/reexpress.yml` | **Create** — reexpress Prompt Generator config |
| `src/pipeline/render/ipadapter/__init__.py` | **Create** — empty package |
| `src/pipeline/render/ipadapter/prompt_gen.py` | **Create** — `IPAdapterGenParams`, `build_restyle_params`, `build_reexpress_params` |
| `src/config/gateway.py` | **Modify** — extend `ipadapter_faceid` with full param surface; delete `weight` |
| `scripts/learn/learn_restyle.py` | **Modify** — use `build_restyle_params`; updated REASON/FINAL schemas; `_apply_prompt_gen_patches` |
| `scripts/learn/learn_reexpress.py` | **Modify** — use `build_reexpress_params`; updated REASON/FINAL schemas; `_apply_prompt_gen_patches` |

---

## Out of scope

- **Create pipeline** (`learn_create.py`, `image_gen`): different parameter surface
  (`temperature`, `max_tokens`). Address in a separate plan.
- **Production pipeline** (`src/pipeline/restyle.py`, `src/pipeline/reexpress.py`): migration
  to use `build_restyle_params` / `build_reexpress_params` instead of the old CLIP builders
  is a follow-on task once the learning loop validates the config approach.
- **LoRA discovery**: whether specific LoRA adapters are available on the gateway server is
  runtime-dependent. The config supports `lora: null` as default; the LLM can only suggest
  LoRA names it has seen in the failure/success history.
- **Server-side `num_inference_steps` support**: if the LLM gateway server does not accept
  this param, it will be silently ignored at the server level. The client sends it
  unconditionally when set.

---

## Verification

```bash
# Lint
.venv/bin/ruff check src/pipeline/render/ipadapter/ src/config/gateway.py scripts/learn/
.venv/bin/ruff format --check src/pipeline/render/ipadapter/ src/config/gateway.py scripts/learn/

# Unit tests
.venv/bin/pytest tests/test_render_ipadapter_prompt_gen.py -v  # 66 tests

# Integration tests (gateway must be running)
scripts/test-integration.sh

# Smoke test (gateway must be running)
python scripts/learn/learn_restyle.py --samples 3 --max-iterations 1 --optimize fast
python scripts/learn/learn_reexpress.py --samples 3 --max-iterations 1 --optimize fast
```

---

## Implementation deviations

The following deviations from the plan were applied during implementation:

### `face_image_b64` renamed to singular string

The gateway server renamed `face_images_b64: list[str]` to `face_image_b64: str` (single
base64 string, not a list). The gateway client and all callers were updated to match.
The plan's signature showing `face_images_b64: list[str]` is superseded:

```python
def ipadapter_faceid(self, prompt: str, face_image_b64: str, *, ...) -> bytes:
```

### `optimize` retained in signature

The plan proposed removing `optimize` from IPAdapter calls and resolving
`num_inference_steps` in the scripts. The gateway server **requires** the `optimize` field
in the payload (422 without it), so it was kept. Both `optimize` and `num_inference_steps`
are sent; the server treats `num_inference_steps` as authoritative when provided.

### `_apply_prompt_gen_patches` implemented inline

The plan proposed a shared helper or `_prompt_gen_fixes.py`. Each script defines its own
`_apply_prompt_gen_patches(patches, config_path)` inline. Deduplication deferred to a
follow-on refactor once the pattern is proven stable.

### `weight_suggestion` removed (replaced by `prompt_gen_patches`)

The old `weight_suggestion` field in the REASON schema was dead code (collected but never
applied). It is fully removed. The `prompt_gen_patches` sub-object now covers all tunable
diffusion params.

### Iteration diff logging added

Each iteration logs all `IPAdapterGenParams` fields on the first pass. Subsequent iterations
show only the fields that changed vs the previous iteration as `prompt_gen CHANGED: key: old → new`.

### YAML corruption guard added

Before writing any YAML patch (both `styles.yml` and `restyle.yml`/`reexpress.yml`),
`yaml.safe_load(candidate_text)` is called. Invalid YAML is skipped with a warning; the
file is never touched. This was added after a real-run corruption event.

### Reasoning scope via `style_filter`

`_apply_restyle_fixes` now accepts a `style_filter` argument. The `styles.yml` snippet
shown to the LLM is filtered to only the target style. A `SCOPE` note in the prompt
explicitly forbids patching other styles.

### Tests added

| File | Tests | Coverage |
|---|---|---|
| `tests/test_render_ipadapter_prompt_gen.py` | 66 | `IPAdapterGenParams`, `build_restyle_params`, `build_reexpress_params`, `_apply_prompt_gen_patches` |
| `tests/test_gateway_integration.py` | expanded | Gateway schema contract (circuit-breaker), all new IPAdapter params |
