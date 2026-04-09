# Avatar Studio — Validation Schemas

Shared validation scorer specifications referenced by all pipeline flow documents. Each scorer operates independently on a rendered image; results are combined by the calling flow according to its own weighting.

---

## Expression Classifier

**Module**: `tuning/classify_expression.py`
**Entry point**: `classify_image_expression(image_bytes, expression_labels, *, gateway_url, timeout)`
**[Full SRS →](../pipeline/scoring_expression_classifier.md)**

Asks a vision LLM to identify which facial expressions are visible in the image. The classifier operates **blind** — it receives only plain label names as soft hints, never FACS specs or generation instructions.

**Output — `ExpressionClassificationResult`**:

| Field | Type | Description |
|---|---|---|
| `top_expression` | `str` | Label with the highest score |
| `scores` | `dict[str, float]` | 5–10 expression labels → probability (sum ≈ 1.0) |
| `reasoning` | `str` | One-sentence visual observation |
| `raw_response` | `str` | Raw LLM YAML for debugging |

**Score formula**:

- **Direct match**: `top_expression` matches expected label (case-insensitive) AND `top_score ≥ 0.50`
  → `Expression Score` = 1.0  # amplify success
- **Semantic fallback** (`semantic_effective_score()`): sums probabilities of all output labels that a text-LLM judges semantically equivalent to the expected label (separate yes/no call per label; allows synonyms — e.g. `"joyful"` counts toward `"happiness"`):
  - If `sum_score ≥ 0.50` → `Expression Score` = `sum_score`
  - Else → `Expression Score` = `sum_score`²   # amplify failure

Threshold 0.50 filters diffused scores (0.15–0.20) caused by ambiguous renderings while accepting clearly rendered expressions.

---

## Style Classifier

**Module**: `tuning/classify_style.py`
**Entry point**: `classify_image_style(image_bytes, styles, *, gateway_url, timeout)`
**[Full SRS →](../pipeline/scoring_style_classifier.md)**

Asks a vision LLM to identify which style from `styles.yml` the image best represents. Each style's `key_technical_traits` list is provided as discriminating criteria. Styles without `key_technical_traits` and the `random` selector are automatically excluded.[^style-filter]

**Output — `StyleClassificationResult`**:

| Field | Type | Description |
|---|---|---|
| `top_style_id` | `str` | Style ID with the highest score |
| `scores` | `dict[str, float]` | style_id → score for all checkable styles |
| `reasoning` | `str` | One-sentence visual evidence |
| `raw_response` | `str` | Raw LLM YAML for debugging |

**Score formula**:
- `top_style_id == expected_style_id` → `Style Score` = `√style_score` # amplify success
- Otherwise → `Style Score` = `style_score`

[^style-filter]: `random` has no visual definition and cannot be classified. Styles without `key_technical_traits` are excluded because the classifier has no discriminating criteria to apply.

---

## Persona Categorizer

**Module**: `tuning/classify_persona.py`
**Entry point**: `categorize_avatar_image(image_bytes, persona, *, gateway_url, timeout)`
**[Full SRS →](../pipeline/scoring_persona_categorizer.md)**

Verifies which visual properties from an Avatar Persona (see [structures](structures.md#avatar-persona)) are present in the image.

**Color properties** — `skin_tone`, `hair_color`, `eye_color`, `clothing`:
1. VLM reports `observed_hex` (`#RRGGBB`) and color name for the dominant color of each property
2. `distance` computed programmatically by YCbCr Euclidean distance between observed and expected hex[^ycbcr]
3. `distance ≤ 0.70` → `Color Score` = `distance`; else → `Color Score` = `distance`²

**Structural properties**: VLM binary `visible: true/false` → `Property Exist` score 1 or 0.

**Property weights**:

| Property | Weight |
|---|---|
| `gender` | 30 |
| `skin_tone` | 25 |
| `eye_color` | 15 |
| `hair_color` | 10 |
| `hair_style` | 15 |
| `accessories` | 10 each |
| `brows_style` | 8 |
| `chin_shape` | 8 |
| `cheeks_shape` | 7 |
| `nose_shape` | 6 |
| `clothing` | 5 each |
| `clothing color` | 5 each |
| `eye_shape` | 4 |

**Score formula**: `Persona Score` = Σ(weight × [`Property Exist` or `Color Score`]) / Σ(weights)

[^ycbcr]: YCbCr separates luminance from chrominance, tolerating lighting variation typical of diffusion model outputs while still catching genuine color-family mismatches.

---

## Side-by-Side Comparison

**Module**: `tuning/compare_side_by_side.py`
**Entry point**: `compare_side_by_side(reference_bytes, generated_bytes, goal, *, reference_label, generated_label, gateway_url, timeout)`

Verifies visually whether the generated image depicts the same person as a reference image and that the requested goal was achieved.

**Procedure**:

1. Programmatically stitch reference and generated images side by side with labels:

```
+-----------------------+   +-----------------------+
|                       |   |                       |
|       512 x 512       |   |       512 x 512       |
|        PICTURE        |   |        PICTURE        |
|          (A)          |   |          (B)          |
|                       |   |                       |
+-----------------------+   +-----------------------+
       REFERENCE                   GENERATED
```

2. A vision-capable LLM receives the stitched image, a text description of the `{goal}`, and scores three dimensions:
   - **A.** The persons in both pictures are the same person
   - **B.** The generated render achieved the `{goal}` well
   - **C.** The generated render is high quality

For all the above:
```python
if (LLM_Score > .60):
  score = sqrt(LLM_Score) # amplify success
else:
  score = LLM_Score/2     # amplify failure
```

3. **Compound score**:

```python
compound_score = sqrt(.50 * score_same_person + .30 * score_goal_achieved + .20 * score_quality)   # amplify success
```

**Output — `ComparisonResult`**:

| Field | Type | Description |
|---|---|---|
| `identity_score` | `float` (0–1) | Score A: same-person consistency |
| `goal_score` | `float` (0–1) | Score B: goal achievement |
| `quality_score` | `float` (0–1) | Score C: render quality |
| `compound_score` | `float` (0–1) | sqrt(50% A + 30% B + 20% C) |
| `reasoning` | `str` | One-sentence visual evidence |
| `raw_response` | `str` | Raw LLM JSON for debugging |
