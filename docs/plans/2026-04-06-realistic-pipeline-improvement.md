# Plan: Realistic Pipeline Improvement

## Context

We have ~200 example personas (`assets/examples/{name}/`) with `original.jpg` + `persona.yml` describing their appearance. These serve as ground truth for evaluating whether our attribute pools and image generation pipeline can accurately represent diverse real-world faces.

**Problem**: The pipeline's attribute pools (28 skin tones, 36 hair styles, etc.) were designed without ground-truth validation. We don't know if they cover real-world diversity, or which attributes, demographics, shapes, accessories fail systematically during generation.

**Goal**: Use example data to (1) audit attribute pool coverage, (2) benchmark generation quality, (3) identify systematic failures, and (4) produce actionable recommendations for pool expansion and prompt improvement.

**Principle**: Every run is expensive (~80s/image for generation + classification). Every run must produce documented, queryable results. No experiment should be run without its inputs, parameters, outputs, and learnings being permanently recorded.

---

## Canonical Persona Schema

The pipeline expects a specific format for clothing and accessories. The normalization step must produce this exact schema — validated by vision LLM against the actual photo.

### Clothing
```yaml
clothing:
  sweater:
    style: fitted grey crew-neck sweater
    color: '#808080'
  top:
    style: color-block bateau neck top with black and white panels
    color: '#1A1A1A'
```
Each garment has `style` (descriptive text including fit, material, details) and `color` (single dominant hex).

### Accessories
```yaml
accessories:
  stubble beard:
    style: short dark stubble beard
    color: '#3B2314'
  necklace:
    style: chunky gold chain necklace
    color: '#C8A840'
  earrings:
    style: ornate silver starburst cluster stud earrings
    color: '#C0C0C0'
```
Each accessory has `style` (descriptive text) and `color` (single dominant hex). For items without a meaningful color (e.g. clear glasses), use the most visible color or omit the `color` field.

### Why this matters
The enrichment script (`enrich_celebrity_persona.py`) produced inconsistent formats — some have `{garment: "#hex"}` (losing style info), some have deeply nested structures with `material`, `pattern`, `secondary_color` etc. The YAML alone cannot be trusted as source of truth — it was LLM-generated and may contain hallucinations or errors. The normalization step validates each field against `original.jpg` using a vision LLM call, then writes back the canonical form.

---

## Experiment Documentation Strategy

All scripts write structured JSON to `reports/`. Every output file is self-describing — it includes the full run configuration so results can be reproduced or compared across runs.

### Run metadata (included in every output file)
```json
{
  "run_id": "20260406_143022",
  "started_at": "2026-04-06T14:30:22",
  "finished_at": "2026-04-06T16:45:10",
  "duration_s": 8088,
  "parameters": {
    "style": "photorealistic",
    "sample": 20,
    "seed": 42,
    "gateway_url": "http://127.0.0.1:4096",
    "image_size": "512x512",
    "optimize": "normal"
  },
  "versions": {
    "script": "example_benchmark.py",
    "git_sha": "cb01538",
    "settings_sha": "a3f2b1c"
  },
  "summary": { ... }
}
```

### Learning log (`reports/learnings.jsonl`)
Append-only JSONL file. Every script appends findings as structured entries:
```json
{"timestamp": "2026-04-06T16:45:10", "source": "example_benchmark", "run_id": "20260406_143022", "type": "finding", "category": "pool_gap", "detail": "skin_tone #C68642 has no pool match within 85% proximity (best: #A67C52 at 78%)", "action": "consider adding #C68642 or nearby tone to skin_tones pool", "severity": "medium", "affected_examples": ["beyonc"]}
{"timestamp": "2026-04-06T16:45:10", "source": "example_benchmark", "run_id": "20260406_143022", "type": "finding", "category": "systematic_failure", "detail": "accessories fail 72% for female x clay (15 images)", "action": "investigate clay style prompt — may suppress accessory rendering", "severity": "high", "affected_examples": ["beyonc", "billie_eilish", "selena_gomez"]}
```

Entry types:
- `finding` — an observation worth acting on (pool gap, systematic failure, quality issue)
- `metric` — a key aggregate number (overall pass rate, avg score by style)
- `anomaly` — unexpected result worth investigating (score=0 when expected high, classifier disagreement)

Severity levels:
- `high` — blocks diversity goals or causes >50% failure in a category
- `medium` — coverage gap or >25% failure rate
- `low` — minor quality issue or single-example problem

### Per-example results preservation
The benchmark saves each generated image with embedded metadata (prompt, style directive, timestamp) in the PNG. This means every image is self-documenting — you can inspect any output image and see exactly what prompt produced it.

Additionally, every `PropertyResult` from the classifier is preserved in the benchmark JSON — not just pass/fail, but the classifier's `note` field (its one-sentence observation) and `observed_hex` for color properties. This captures *why* the classifier judged something as pass/fail, not just the binary result.

---

## Deliverables

### 1. `scripts/_example_utils.py` — Shared utilities

Common functions for loading, normalizing, and validating example personas.

#### Functions

**`load_all_personas(examples_dir) -> Iterator[(str, dict)]`**
- Walk `examples_dir`, yield `(folder_name, persona_dict)` for dirs containing `persona.yml`
- Skip dirs with empty `appearance: {}` (no visual data to work with)
- Sort alphabetically for deterministic ordering

**`normalize_clothing(raw) -> dict[str, dict]`**
Restructures clothing to canonical `{garment: {style: "...", color: "#hex"}}` from any input format:
1. **Already canonical** `{garment: {style: ..., color: "#hex"}}` — pass through
2. **Flat hex** `{garment: "#hex"}` — keeps hex as color, `style` left empty (to be filled by vision LLM)
3. **Nested dict** `{garment: {style: ..., color: "#hex", colors: [...], material: ..., ...}}` — extract `style` + first hex as `color`, drop `material`, `pattern`, `color_labels`, `secondary_color`
4. **List of items** `[{item: ..., description: ..., primary_color: "#hex", ...}]` — convert to `{item: {style: description, color: primary_color}}`
- Returns empty dict for `None`, empty string, or empty collections

**`normalize_accessories(raw) -> dict[str, dict]`**
Restructures accessories to canonical `{name: {style: "...", color: "#hex"}}`:
1. **Already canonical** `{name: {style: ..., color: "#hex"}}` — pass through
2. **Flat string** `{name: "description"}` — becomes `{name: {style: "description"}}`, `color` omitted (to be filled by vision LLM)
3. **Nested dict** `{name: {type: ..., material: ..., color: "#hex"}}` — `style` = `type`, keep `color`, drop `material`
- Returns empty dict for `None` / empty / `"none"`

**`normalize_hair_color(raw) -> dict[str, str]`**
Handles 2 observed formats:
1. **Dict** `{hex_base: "#hex", hex_shadow: "#hex"}` — pass through (canonical)
2. **Plain hex string** `"#1A1A1A"` — wrap as `{hex_base: raw, hex_shadow: darken(raw)}` using a simple darkening function (shift RGB channels toward 0 by 50%)

**`normalize_eye_color(raw) -> dict[str, str]`**
Same logic as `normalize_hair_color` but with `hex_iris` / `hex_pupil` field names.

**`normalize_persona(persona) -> dict`**
- Deep-copies persona
- Normalizes `appearance.clothing` via `normalize_clothing()`
- Normalizes `appearance.accessories` via `normalize_accessories()`
- Normalizes `appearance.hair_color` via `normalize_hair_color()`
- Normalizes `appearance.eye_color` via `normalize_eye_color()`
- Returns modified copy (never mutates input)

**`append_learning(entry) -> None`**
- Appends a structured learning entry to `reports/learnings.jsonl`
- Auto-adds `timestamp` field
- Creates file if it doesn't exist

**`make_run_metadata(script_name, parameters) -> dict`**
- Captures run_id (timestamp-based), git SHA, start time, parameters
- Returns metadata dict to embed in output files

#### Implementation notes
- No external deps beyond PyYAML and stdlib
- Import path: `from _example_utils import ...` (scripts-local, not in `src/`)
- All functions pure (except `append_learning` which appends to JSONL)

---

### 2. `scripts/normalize_example_personas.py` — Vision-validated normalization

Normalizes each `persona.yml` to canonical schema, **validated against `original.jpg`** using the vision LLM. This is not just a schema reshuffling — the vision model verifies and corrects the YAML against what's actually visible in the photo.

#### Why vision validation is needed
The persona YAMLs were generated by `enrich_celebrity_persona.py` using a vision LLM, but:
- The LLM may have hallucinated details (wrong garment type, wrong accessory color)
- Some fields lost descriptive info during earlier manual edits (e.g. `{sweater: '#808080'}` lost the style)
- Color hex values may be inaccurate
- The vision call is cheap (~5s per image) compared to image generation (~80s). Don't spare these.

#### CLI interface
```
python scripts/normalize_example_personas.py [--dry-run | --write] [--examples-dir PATH] [--gateway URL]
```
- `--dry-run` (default): print per-file diff showing what would change, with validation notes
- `--write`: rewrite `persona.yml` files in place
- `--gateway`: LLM gateway URL (default `http://127.0.0.1:4096`)
- `--examples-dir`: defaults to `assets/examples/`

#### Per-file logic
1. Load persona YAML
2. Skip if `appearance` is empty dict or `original.jpg` doesn't exist
3. Call `normalize_persona(persona)` for structural normalization
4. **Vision validation step**: send `original.jpg` to vision LLM with the normalized persona, ask it to verify and correct:
   - For clothing items missing `style`: "Describe the garment visible in this image"
   - For clothing/accessory items: "Verify the color hex matches what you see. Report the actual dominant color hex."
   - For clothing items with `style`: "Verify this description matches: '{style}'. Correct if wrong."
   - For accessories missing `color`: "What is the dominant color of this accessory?"
5. Apply vision LLM corrections to the normalized persona
6. Compare original vs final:
   - If identical → skip (print "no changes")
   - If different → show unified diff (dry-run) or write (write mode)
7. Log all changes: structural normalization, vision corrections, dropped fields

#### Vision LLM prompt design
Single call per example — send the full normalized clothing + accessories and ask for corrections in structured JSON:

```
System: You are a visual property verifier. Given a photo and a list of clothing/accessory
descriptions, verify each item against what you see. Return corrections in JSON.

User: Examine this photo. For each item below, verify the description and color match
what's visible. Return a JSON object with corrections only for items that need fixing.

Clothing:
  sweater: {style: "", color: "#808080"}
  top: {style: "color-block bateau neck top", color: "#1A1A1A"}

Accessories:
  stubble beard: {style: "short dark stubble beard", color: ""}
  earrings: {style: "stud earrings", color: "#E8E8E8"}

For each item, return:
  - "style": corrected description (or same if accurate)
  - "color": corrected hex (or same if accurate)
  - "note": what you changed and why (empty string if no change)
Only include items that need corrections.
```

#### Output format (dry-run)
```
--- beyonc/persona.yml
+++ beyonc/persona.yml (validated)

  clothing:
-   top: '#1A1A1A'                              # was flat hex, no style
+   top:
+     style: color-block bateau neck top         # VISION: described from photo
+     color: '#1A1A1A'                           # VISION: confirmed

  accessories:
-   earrings:                                    # was nested {type:..., material:...}
-     type: stud/small drop
-     material: crystal/diamond
-     color: '#E8E8E8'
+   earrings:
+     style: crystal drop stud earrings          # VISION: corrected from "stud/small drop"
+     color: '#D4D4D4'                           # VISION: adjusted from #E8E8E8

  eye_color:
-   '#6B3A2A'                                    # was plain hex string
+   hex_iris: '#6B3A2A'
+   hex_pupil: '#351D15'
```

#### Documentation output
When `--write` is used, writes `reports/normalization_YYYYMMDD.json`:
```json
{
  "run_metadata": { ... },
  "total_processed": 200,
  "modified": 80,
  "skipped_empty": 50,
  "skipped_no_image": 5,
  "skipped_no_change": 65,
  "vision_calls": 145,
  "changes": [
    {
      "example": "beyonc",
      "structural_changes": ["clothing format: nested->canonical", "eye_color format: string->dict"],
      "vision_corrections": [
        {"field": "clothing.top.style", "action": "added", "value": "color-block bateau neck top"},
        {"field": "accessories.earrings.color", "action": "corrected", "old": "#E8E8E8", "new": "#D4D4D4", "note": "crystal appears slightly darker in photo"}
      ],
      "fields_dropped": [
        {"path": "accessories.earrings.material", "value": "crystal/diamond"}
      ]
    }
  ]
}
```

#### Edge cases
- Personas with no appearance data → skip entirely
- Personas without `original.jpg` → structural normalize only, log warning (no vision validation)
- Personas already in canonical form with complete style+color → still validate via vision LLM (verify accuracy)
- Vision LLM returns empty corrections → no changes needed, log as verified
- Vision LLM fails → fall back to structural normalization only, log error
- Multiple hex colors in clothing item → vision LLM picks the dominant one
- Clothing items with no hex at all → vision LLM provides the color from the photo

#### Time estimate
~200 examples x ~5s per vision call = ~17 minutes total. Cheap compared to benchmark runs.

---

### 3. `scripts/audit_example_coverage.py` — Pool coverage audit

Compares example attribute values against pipeline pools. No LLM calls.

#### CLI interface
```
python scripts/audit_example_coverage.py [--examples-dir PATH] [--output PATH]
```
- `--output`: defaults to `reports/coverage_audit.json`

#### Pool loading
Load pools from JSON files:
- `phenotype_settings.json`: `skin_tones[]`, `hair_colors[]`, `eye_colors[]`, `eye_shapes[]`, `brows_styles{gender->[]}`, `nose_shapes[]`, `chin_shapes{gender->[]}`, `cheeks_shapes{gender->[]}`
- `presentation_settings.json`: `hair_styles{gender->[]}`, `clothing_options{gender->[]}`, `accessories_options{gender->[]}`

Note: `hair_colors` and `eye_colors` in phenotype_settings are space-separated hex pairs like `"#1A0E07 #0A0603"` — need to parse first hex as `hex_base` equivalent.

#### Matching strategies

**Color attributes** (`skin_tone`, `hair_color`, `eye_color`):
- Reuse `_ycbcr_distance()` from `classify_persona.py` (copy the 3 functions: `_hex_to_rgb`, `_rgb_to_ycbcr`, `_ycbcr_distance` — they're pure math, no imports)
- Compute proximity = `1 - distance / 325.0`
- Threshold: proximity >= 0.85 for "matched" (tighter than the 0.70 validation threshold — here we want near-exact pool match)
- Report best match and proximity score for each example value

**Text attributes** (`hair_style`, `eye_shape`, `brows_style`, `nose_shape`, `chin_shape`, `cheeks_shape`):
- Tokenize both example value and pool value: lowercase, split on spaces/hyphens
- Token overlap ratio = `|intersection| / |example_tokens|`
- Threshold: overlap >= 0.5 for "matched"
- Gender-aware: check example's gender pool + neutral pool (where applicable)

**Clothing & accessories**: report raw values without pool matching (pools are too generic for meaningful comparison)

#### Output schema (`reports/coverage_audit.json`)
```json
{
  "run_metadata": { ... },
  "total_examples": 150,
  "skipped_empty": 50,
  "attributes": {
    "skin_tone": {
      "coverage_pct": 0.82,
      "total_with_value": 120,
      "matched_count": 98,
      "unmatched_count": 22,
      "matched": [
        {"example": "adam_levine", "value": "#F2D3C4", "best_pool_match": "#F2D3C4", "proximity": 1.0}
      ],
      "unmatched": [
        {"example": "beyonc", "value": "#C68642", "best_pool_match": "#A67C52", "proximity": 0.78}
      ],
      "unused_pool": ["#3B1F0D", "#2C1608"],
      "unused_pool_count": 2
    },
    "hair_style": {
      "coverage_pct": 0.65,
      "total_with_value": 110,
      "matched_count": 72,
      "unmatched_count": 38,
      "matched": [
        {"example": "lebron_james", "value": "short buzz cut", "best_pool_match": "buzz cut", "overlap": 0.67}
      ],
      "unmatched": [
        {"example": "adam_levine", "value": "short textured spiky top with faded sides", "best_pool_match": "textured pixie", "overlap": 0.14}
      ],
      "unused_pool": ["space buns", "french twist"],
      "unused_pool_count": 2
    }
  },
  "summary": {
    "best_covered": "hair_color (91%)",
    "worst_covered": "hair_style (65%)",
    "total_pool_gaps": 15,
    "total_unused_pool_entries": 22
  }
}
```

#### Learnings output
After writing the audit JSON, appends structured findings to `reports/learnings.jsonl`:
- One `finding` entry per unmatched attribute with proximity < 0.70 (severe gap)
- One `metric` entry per attribute with its coverage_pct
- One `finding` entry summarizing unused pool entries (dead weight in the pool)

#### Implementation steps
1. Load all example personas via `load_all_personas()`, normalize via `normalize_persona()`
2. Load pool JSONs
3. For each attribute type, iterate examples and compute matches
4. Track which pool values were matched (for unused_pool)
5. Compute coverage_pct = matched / (matched + unmatched)
6. Write JSON output, append learnings, print summary table to stdout

#### Stdout summary
```
=== Pool Coverage Audit ===
skin_tone:    82% covered  (98/120) — 2 unused pool entries
hair_color:   91% covered (109/120) — 1 unused pool entries
hair_style:   65% covered  (72/110) — 8 unused pool entries
eye_shape:    78% covered  (86/110) — 4 unused pool entries
...

Top unmatched gaps:
  skin_tone #C68642 (beyonc) — closest: #A67C52 @ 78%
  hair_style "short textured spiky top with faded sides" (adam_levine) — closest: "textured pixie" @ 14%
  ...
```

---

### 4. `scripts/example_benchmark.py` — Generation + scoring benchmark

#### CLI interface
```
python scripts/example_benchmark.py \
  --gateway http://127.0.0.1:4096 \
  --style photorealistic \
  --sample 20 \
  --runs 1 \
  --resume \
  --output reports/benchmark_YYYYMMDD.json
```

Flags:
- `--gateway`: LLM gateway URL (default `http://127.0.0.1:4096`)
- `--style`: specific style ID or `all` (default `photorealistic`)
- `--sample N`: random sample of N examples (default: all)
- `--runs N`: repeat each (example, style) pair N times (default 1)
- `--resume`: skip entries already in the output file (match on example+style+run)
- `--output`: results file path (default `reports/benchmark_YYYYMMDD.json`)
- `--seed`: random seed for sampling reproducibility

#### Architecture

```
main()
  |-- parse args, load styles from styles.yml (LLM engine only)
  |-- load example list, filter to those with original.jpg + non-empty appearance
  |-- optionally sample N examples (with seed)
  |-- build work queue: [(example, style, run_idx), ...]
  |-- if --resume, load existing results and remove completed entries from queue
  |-- for each (example, style, run_idx):
  |     |-- generate_one(client, example_dir, persona, style_entry, run_idx)
  |     |     |-- normalize persona
  |     |     |-- sanitize_persona() -> build_prompt() with NEUTRAL_EXPR
  |     |     |-- load original.jpg as reference
  |     |     |-- time the generation: client.image_gen(512x512, optimize="normal")
  |     |     |-- embed_metadata() (reuse from style_loop.py)
  |     |     +-- return (image_bytes, generation_time_s, prompt)
  |     |-- score_one(client, image_bytes, persona, styles, style_id)
  |     |     |-- classify_image_style() -> style_score
  |     |     |-- categorize_avatar_image() -> CategoryReport
  |     |     |-- extract failures(), color_scores, classifier notes from report.results
  |     |     +-- return BenchmarkEntry dataclass
  |     |-- save image to example_dir/{style_id}_benchmark_{run_idx}.png
  |     |-- append entry to results JSON (atomic write after each entry)
  |     +-- log progress: "[42/200] beyonc x photorealistic: style=85% persona=72%"
  +-- write final summary + append learnings
```

#### BenchmarkEntry dataclass
```python
@dataclass
class BenchmarkEntry:
    example: str
    style_id: str
    run_idx: int
    gender: str
    style_score: float
    persona_score: float
    persona_failures: list[str]
    persona_passes: list[str]
    color_scores: dict[str, float]       # {skin_tone: 0.91, hair_color: 0.68, ...}
    property_notes: dict[str, str]       # classifier's observation per property
    observed_colors: dict[str, str]      # {skin_tone: "#C47A3B", ...} — what the classifier saw
    generation_time_s: float
    image_path: str
    prompt_excerpt: str                  # first 300 chars of the generation prompt
    error: str | None                    # null on success, error message on failure
```

Key fields for experiment documentation:
- **`property_notes`**: The classifier's one-sentence observation per property (e.g. `"hair_style": "Image shows short wavy hair, not the expected spiky texture"`). This is the most valuable diagnostic — it tells us *why* something failed.
- **`observed_colors`**: The hex values the classifier reported seeing. Combined with expected hex from the persona, this lets us compute exact color drift without re-running classification.
- **`prompt_excerpt`**: So we can trace generation quality back to prompt construction without re-building.
- **`error`**: Captures generation/classification failures inline rather than silently skipping.

#### Output schema (`reports/benchmark_YYYYMMDD.json`)
```json
{
  "run_metadata": {
    "run_id": "20260406_143022",
    "started_at": "2026-04-06T14:30:22",
    "finished_at": "2026-04-06T16:45:10",
    "duration_s": 8088,
    "parameters": {
      "style": "photorealistic",
      "sample": 20,
      "seed": 42,
      "runs": 1,
      "gateway_url": "http://127.0.0.1:4096",
      "image_size": "512x512",
      "optimize": "normal"
    },
    "versions": {
      "script": "example_benchmark.py",
      "git_sha": "cb01538"
    }
  },
  "summary": {
    "total_entries": 20,
    "successful": 18,
    "failed": 2,
    "avg_style_score": 0.82,
    "avg_persona_score": 0.71,
    "avg_generation_time_s": 12.3,
    "style_pass_rate": 0.89,
    "persona_pass_rate": 0.67,
    "by_gender": {
      "female": {"count": 8, "avg_persona_score": 0.74},
      "male": {"count": 10, "avg_persona_score": 0.69},
      "non-binary": {"count": 2, "avg_persona_score": 0.65}
    },
    "most_failed_properties": [
      {"property": "accessories", "failure_rate": 0.44, "count": 8},
      {"property": "hair_style", "failure_rate": 0.33, "count": 6}
    ]
  },
  "entries": [ ... ]
}
```

The summary is computed at the end of the run and included in the same file. This means you can read just the top of any benchmark file to understand what happened without parsing all entries.

#### Learnings output
After all entries are processed, the benchmark script:
1. Computes summary statistics
2. Identifies systematic patterns (properties failing >40%, gender/style combos with disproportionate failures)
3. Appends structured findings to `reports/learnings.jsonl`:
   - `metric` entries for overall pass rates and avg scores
   - `finding` entries for each systematic failure pattern
   - `anomaly` entries for unexpected results (e.g. persona_score=0 on an example with complete appearance data)

#### Concurrency model
Sequential loop (matching style_loop.py pattern). The gateway already queues. Classification is the bottleneck and serializes on GPU anyway.

#### Resume logic
- On start, load existing JSON if `--resume` and file exists
- Build set of `(example, style_id, run_idx)` tuples already completed
- Skip matching work items
- Append new entries to the existing list
- Atomic write: write to `.tmp` then rename

#### Error handling
- Generation failure → log warning, record entry with `error` field set, `style_score=0.0`, `persona_score=0.0`
- Classification failure → log warning, record entry with `error` field set, partial scores where available
- Gateway timeout → log, record with error, continue (don't retry — the gateway handles retries internally)
- **Never silently skip** — every work item produces an entry, even on failure. This ensures the results file is a complete record of what was attempted.

---

### 5. `scripts/analyze_benchmark.py` — Post-hoc analysis

#### CLI interface
```
python scripts/analyze_benchmark.py \
  --input reports/benchmark_YYYYMMDD.json \
  --coverage reports/coverage_audit.json \
  --output reports/analysis_YYYYMMDD.json \
  --bottom N
```

Flags:
- `--input`: benchmark results JSON (required)
- `--coverage`: coverage audit JSON (optional — enables combined recommendations)
- `--output`: analysis output path
- `--bottom N`: number of worst performers to highlight (default 10)

#### Analysis dimensions

**1. By style**
```json
{
  "photorealistic": {
    "count": 150,
    "avg_style_score": 0.82,
    "avg_persona_score": 0.71,
    "style_pass_rate": 0.91,
    "persona_pass_rate": 0.65
  }
}
```
- `style_pass_rate`: % with style_score >= 0.66 (reuse STYLE_PASS_THRESHOLD from style_loop.py)
- `persona_pass_rate`: % with persona_score >= 0.50

**2. By gender**
```json
{
  "female": {"count": 65, "avg_persona_score": 0.73, "avg_style_score": 0.84},
  "male": {"count": 70, "avg_persona_score": 0.69, "avg_style_score": 0.81},
  "non-binary": {"count": 15, "avg_persona_score": 0.62, "avg_style_score": 0.79}
}
```

**3. By property** — failure rate, avg color score, and top classifier notes
```json
{
  "hair_style": {
    "failure_rate": 0.35,
    "total": 130,
    "top_failure_notes": [
      {"note": "Image shows short wavy hair, not the expected spiky texture", "count": 10},
      {"note": "Hair appears straight rather than curly as described", "count": 6}
    ]
  },
  "skin_tone": {
    "failure_rate": 0.12,
    "avg_color_score": 0.88,
    "total": 140,
    "avg_color_drift": {"expected_avg": "#B08050", "observed_avg": "#C09060", "direction": "lighter"}
  },
  "accessories": {"failure_rate": 0.48, "total": 110}
}
```

The `top_failure_notes` field aggregates the classifier's observations from `property_notes` across all failures for that property. This surfaces *why* a property fails — not just how often — so we can target prompt changes or pool adjustments precisely.

**4. Systematic failures** — properties failing >50% for specific (gender, style) combos
```json
[
  {"property": "accessories", "gender": "female", "style": "clay", "failure_rate": 0.72, "count": 25,
   "top_notes": ["Accessories not visible in clay style rendering"]},
  {"property": "hair_style", "gender": "non-binary", "style": "studio_3d", "failure_rate": 0.60, "count": 8,
   "top_notes": ["Hair rendered as generic short style, losing the distinctive described texture"]}
]
```

**5. Worst performers** — bottom N by persona score
```json
[
  {
    "example": "billie_eilish",
    "style": "clay",
    "persona_score": 0.23,
    "failures": ["hair_color", "clothing", "accessories"],
    "failure_notes": {
      "hair_color": "Hair appears dark brown (#3A2010) vs expected burgundy (#8B2020)",
      "clothing": "Turtleneck not distinguishable in clay style",
      "accessories": "Necklaces not rendered"
    }
  }
]
```

**6. Color drift analysis**
For each color property, compute aggregate drift patterns:
```json
{
  "skin_tone": {
    "avg_proximity": 0.84,
    "drift_direction": "lighter by avg 12 YCbCr units",
    "worst_drifts": [
      {"example": "beyonc", "expected": "#C68642", "observed": "#D4A870", "proximity": 0.71, "direction": "lighter+warmer"}
    ]
  }
}
```
This reveals whether the image model systematically shifts certain colors (e.g. always makes dark skin tones lighter, always desaturates hair color).

**7. Recommendations** (when `--coverage` is provided)
Combine benchmark failures with coverage gaps:
- For each unmatched attribute in coverage audit that also has high failure rate in benchmark → recommend pool expansion
- For color attributes with avg_color_score < 0.80 → recommend new pool entries near the unmatched example hex values
- For properties with consistent classifier notes → recommend prompt wording changes
- Each recommendation includes: severity, affected count, specific suggested action

```json
{
  "recommendations": [
    {
      "severity": "high",
      "category": "pool_gap",
      "property": "skin_tone",
      "detail": "skin_tone #C68642 has no pool match within 85% proximity",
      "action": "Add #C68642 (honey-brown) to skin_tones pool",
      "affected_count": 3,
      "affected_examples": ["beyonc", "priyanka_chopra", "lupita_nyongo"]
    },
    {
      "severity": "medium",
      "category": "prompt_failure",
      "property": "hair_style",
      "detail": "35% failure rate — classifier notes: 'texture not rendered' in 12/19 failures",
      "action": "Consider adding texture descriptors (spiky, coily, tousled) as first word in hair_style pool entries",
      "affected_count": 19
    },
    {
      "severity": "high",
      "category": "systematic_bias",
      "property": "skin_tone",
      "detail": "Dark skin tones (#4A2912, #6B3F23) drift lighter by avg 18 YCbCr units",
      "action": "Investigate image model bias — may need prompt reinforcement for darker tones",
      "affected_count": 8
    }
  ]
}
```

#### Learnings output
Appends all recommendations as `finding` entries to `reports/learnings.jsonl`, plus `metric` entries for cross-run comparison.

#### Stdout summary
```
=== Benchmark Analysis (150 entries, 3 styles) ===
Run: 20260406_143022 | Duration: 3h 20m | 145/150 successful

By Style:
  photorealistic  style=82% persona=71% (150 images)
  studio_3d       style=79% persona=65% (150 images)
  clay            style=74% persona=58% (150 images)

By Gender:
  female      persona=73% (65 images)
  male        persona=69% (70 images)
  non-binary  persona=62% (15 images)

Most Failed Properties (with top classifier reasons):
  accessories   48% fail — "not visible in clay rendering" (20x), "wrong type rendered" (8x)
  hair_style    35% fail — "texture not rendered" (16x), "length wrong" (7x)
  clothing      28% fail — "color mismatch" (12x), "garment type wrong" (9x)

Color Drift:
  skin_tone   avg proximity=0.84 — drifts lighter by 12 YCbCr units on dark tones
  hair_color  avg proximity=0.91 — stable
  eye_color   avg proximity=0.79 — drifts toward brown on light eyes

Systematic Failures (>50% fail for gender x style):
  accessories x female x clay     72% fail (25 images)
  hair_style x non-binary x all   60% fail  (8 images)

Bottom 5 Performers:
  billie_eilish x clay       persona=23%  failures: hair_color ("brown vs burgundy"), clothing, accessories
  ...

Recommendations (7 total — 2 high, 3 medium, 2 low):
  [HIGH] Add skin_tone #C68642 to pool (3 examples affected)
  [HIGH] Investigate skin_tone lightening bias on dark tones (8 examples)
  [MED]  Add texture descriptors to hair_style pool entries (19 failures)
  ...

Learnings appended to reports/learnings.jsonl (7 entries)
```

---

## File Layout

```
scripts/
  _example_utils.py                  # Shared normalization + loading + learning log
  normalize_example_personas.py      # Vision-validated normalization
  audit_example_coverage.py          # Pool coverage audit (offline)
  example_benchmark.py               # Generation + scoring
  analyze_benchmark.py               # Analysis + recommendations
reports/                             # .gitignore'd output directory
  learnings.jsonl                    # Append-only structured learning log (all scripts write here)
  normalization_YYYYMMDD.json        # Normalization run record (with vision corrections)
  coverage_audit.json                # Latest coverage audit
  benchmark_YYYYMMDD.json            # Benchmark results (one per run)
  analysis_YYYYMMDD.json             # Analysis results (one per run)
```

## Prerequisites

- Add `reports/` to `.gitignore`
- Ensure `reports/` directory exists (scripts should `mkdir -p`)

## Execution Order

1. `normalize_example_personas.py --dry-run` → review vision corrections → `--write`
2. `audit_example_coverage.py` → instant coverage report
3. `example_benchmark.py --sample 20 --style photorealistic` → quick sanity check
4. `analyze_benchmark.py` → first insights
5. Expand benchmark as needed, iterate on attribute pools

## Key Files to Reuse

| File | What to reuse |
|------|---------------|
| `scripts/style_loop.py` | `generate_image()`, `embed_metadata()`, `load_styles()`, `NEUTRAL_EXPR`, overall loop pattern |
| `src/tuning/classify_persona.py` | `categorize_avatar_image()`, `CategoryReport`, `PropertyResult`, `_ycbcr_distance()`, `_hex_to_rgb()`, `_rgb_to_ycbcr()` |
| `src/tuning/classify_style.py` | `classify_image_style()`, `StyleClassificationResult` |
| `src/pipeline/render/llm/prompt_builder.py` | `build_prompt()` |
| `src/pipeline/render/llm/style_directive.py` | `build_style_directive()` |
| `src/pipeline/render/llm/persona_sanitizer.py` | `sanitize_persona()` |
| `src/config/gateway.py` | `GatewayClient` — `image_inspector()` for vision validation, `image_gen()` for benchmark |
| `src/pipeline/persona/marshal.py` | `visual_only_persona()` (called by sanitize_persona) |
| `assets/persona/phenotype_settings.json` | Attribute pools: `skin_tones`, `hair_colors`, `eye_colors`, `eye_shapes`, `brows_styles`, `nose_shapes`, `chin_shapes`, `cheeks_shapes` |
| `assets/persona/presentation_settings.json` | Feature pools: `hair_styles`, `clothing_options`, `accessories_options` |

## Observed Persona Format Variations (pre-normalization)

| Field | Format 1 | Format 2 | Format 3 |
|-------|----------|----------|----------|
| `clothing` | `{garment: "#hex"}` — flat, no style (adam_levine) | `{garment: {style:..., color:"#hex", material:...}}` — nested with extras (beyonce, billie_eilish) | `[{item:..., primary_color:"#hex", description:...}]` — list (lebron_james) |
| `accessories` | `{name: "description"}` — flat string (adam_levine, sara_ramirez) | `{name: {type:..., material:..., color:"#hex"}}` — nested with extras (billie_eilish, beyonce) | — |
| `hair_color` | `{hex_base: "#hex", hex_shadow: "#hex"}` — canonical (adam_levine) | `"#hex"` — plain string (lebron_james) | — |
| `eye_color` | `{hex_iris: "#hex", hex_pupil: "#hex"}` — canonical (adam_levine) | `"#hex"` — plain string (beyonce) | — |

**Post-normalization canonical form** (target):

| Field | Canonical Form |
|-------|---------------|
| `clothing` | `{garment: {style: "descriptive text", color: "#hex"}}` |
| `accessories` | `{name: {style: "descriptive text", color: "#hex"}}` |
| `hair_color` | `{hex_base: "#hex", hex_shadow: "#hex"}` |
| `eye_color` | `{hex_iris: "#hex", hex_pupil: "#hex"}` |

## Verification

1. `normalize_example_personas.py --dry-run` on beyonce (nested clothing), lebron_james (list clothing), billie_eilish (nested accessories) shows correct normalization with vision-validated style descriptions and colors
2. `normalize_example_personas.py --dry-run` on adam_levine (flat `{sweater: '#808080'}`) recovers garment style description from vision LLM
3. `audit_example_coverage.py` runs in <10s, produces valid JSON with all attributes, coverage_pct between 0 and 1; appends learnings to JSONL
4. `example_benchmark.py --sample 3 --style photorealistic` completes end-to-end, produces valid JSON with scores, property_notes, observed_colors; no entries silently skipped
5. `analyze_benchmark.py` reads benchmark output, produces summary with color drift analysis and recommendations; appends learnings
6. `reports/learnings.jsonl` accumulates entries from all scripts with consistent schema
7. All scripts pass `ruff check scripts/` and `ruff format --check scripts/`
