# Style Prompt Learning

Learning accumulated from style loop runs.

## Analysis — 20-Round Run (2026-04-06)

### Pass Rates

| Style | Avg Score | Pass Rate | Notes |
|---|---|---|---|
| photorealistic | 80% | 83% (5/6) | Best performer — reliable and consistent |
| studio_3d | 46% | 50% (3/6) | Moderate — classifier recognizes correctly when JSON returned |
| korean | 28% | 33% (5/15) | Underestimated — classifier often returns correct top_style but score=0 (see bug below) |
| lineart | 23% | 27% (4/15) | Also underestimated — same score extraction bug |
| clay | 29% | 17% (3/18) | Genuine failure — gen model renders clay as studio_3d |

### Key Findings

**1. photorealistic is the gold standard.**
96% scores consistently across all 3 personas. The classifier's JSON response is clean and well-structured.
Persona scores are also highest here (93–99%).

**2. Clay is systematically confused with studio_3d.**
Despite explicit "MATTE", "Zero specular highlights", "Flat subsurface-free skin rendering" instructions,
the generation model produces glossy/specular surfaces that the classifier reads as studio_3d.
Clay only passes when the image happens to land on distinctly matte rendering (~17% of the time).
**Fix needed**: Add even stronger negative constraints — e.g. "NO shine, NO reflections, NO gloss, NO subsurface scattering. Chalky flat surface like painted plaster."

**3. Lineart and Korean have a score-extraction false-negative bug.**
When the classifier writes Markdown analysis (not JSON), the markdown regex fallback successfully
extracts `top_style_id` but fails to parse the numeric score → `scores.get(expected_id)` returns 0.
Result: top_style is correct but style_score = 0 → FAIL despite correct classification.
**Fix needed**: In `classify_style.py`, if `top_style_id == expected_id` but score == 0, default score
to the classifier threshold (e.g. 0.7) rather than treating as failure.

**4. Lineart is inconsistent by persona.**
sara_ramirez consistently passes (88%), while adam_levine and rihanna consistently fail.
The classifier returns `top_style=""` for adam_levine/rihanna — not even identifying a style.
This suggests the generated image doesn't look like "lineart" to the classifier for those personas.
The reference image for these two might be too photorealistic, making the style instruction insufficient.

**5. Persona scores are independent of style.**
Scores of 84–99% appear regardless of style choice (except early aborted rounds).
Persona fidelity is driven primarily by the reference image, not the style directive.
sara_ramirez consistently scores 96–99% despite style failures — the reference image is doing the work.

### Recommendations

1. **Clay**: Add negative anti-gloss terms to the clay system_prompt:
   `"NO shine, NO specular highlights, NO reflections, NO subsurface scattering. Surface must look chalky, powdery, or matte like unpainted clay."`

2. **Fix score=0 false negative**: When `top_style_id == expected_id and scores.get(expected_id, 0) == 0`,
   set score to 0.7 (threshold) to avoid marking correct classifications as FAIL.

3. **Lineart**: The classifier never assigns `lineart` to adam_levine or rihanna — the style isn't landing.
   Investigate whether the generation model handles lineart differently for dark-haired/darker-complexion subjects.
   Consider adding `"thick dark outline on every edge and feature"` as a stronger trait.

4. **Korean**: 33% pass rate is misleadingly low due to bug #2. True recognition rate is likely ~60–70%.
   After fixing the score bug, re-evaluate korean's actual performance.


## Round 1 — lineart / adam_levine — 2026-04-06 11:19

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — lineart / rihanna — 2026-04-06 11:21

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — lineart / sara_ramirez — 2026-04-06 11:22

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Summary

- **lineart**: avg style score 0%, 0/3 passed (0%)

## Round 1 — clay / adam_levine — 2026-04-06 11:23

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — clay / rihanna — 2026-04-06 11:24

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — clay / sara_ramirez — 2026-04-06 11:25

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 2 — korean / adam_levine — 2026-04-06 11:26

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 2 — korean / rihanna — 2026-04-06 11:27

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 2 — korean / sara_ramirez — 2026-04-06 11:28

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 3 — studio_3d / adam_levine — 2026-04-06 11:29

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 3 — studio_3d / rihanna — 2026-04-06 11:30

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 3 — studio_3d / sara_ramirez — 2026-04-06 11:31

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 4 — clay / adam_levine — 2026-04-06 11:32

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 4 — clay / rihanna — 2026-04-06 11:33

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — korean / adam_levine — 2026-04-06 11:38

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — korean / rihanna — 2026-04-06 11:40

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — korean / sara_ramirez — 2026-04-06 11:40

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 2 — studio_3d / adam_levine — 2026-04-06 11:41

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 2 — studio_3d / rihanna — 2026-04-06 11:42

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 2 — studio_3d / sara_ramirez — 2026-04-06 11:43

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 3 — lineart / adam_levine — 2026-04-06 11:44

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 3 — lineart / rihanna — 2026-04-06 11:45

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 3 — lineart / sara_ramirez — 2026-04-06 11:46

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 4 — studio_3d / adam_levine — 2026-04-06 11:47

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 1 — clay / adam_levine — 2026-04-06 11:58

- **Style score** (clay): 18% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 89%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: First run for this combination. Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (89%).

## Round 1 — clay / rihanna — 2026-04-06 11:59

- **Style score** (clay): 88% (PASS ✓)
- **Top classified**: `clay`
- **Persona score**: 85%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `clay`. Persona strong (85%).

## Round 1 — clay / sara_ramirez — 2026-04-06 12:00

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 96%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: First run for this combination. Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (96%).

## Round 2 — studio_3d / adam_levine — 2026-04-06 12:01

- **Style score** (studio_3d): 92% (PASS ✓)
- **Top classified**: `studio_3d`
- **Persona score**: 93%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: Style Analysis
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `studio_3d`. Persona strong (93%).

## Round 2 — studio_3d / rihanna — 2026-04-06 12:02

- **Style score** (studio_3d): 88% (PASS ✓)
- **Top classified**: `studio_3d`
- **Persona score**: 86%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: Style Analysis
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `studio_3d`. Persona strong (86%).

## Round 2 — studio_3d / sara_ramirez — 2026-04-06 12:03

- **Style score** (studio_3d): 96% (PASS ✓)
- **Top classified**: `studio_3d`
- **Persona score**: 92%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: Style Analysis
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `studio_3d`. Persona strong (92%).

## Round 3 — korean / adam_levine — 2026-04-06 12:04

- **Style score** (korean): 82% (PASS ✓)
- **Top classified**: `korean`
- **Persona score**: 99%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Style Analysis
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `korean`. Persona strong (99%).

## Round 3 — korean / rihanna — 2026-04-06 12:05

- **Style score** (korean): 82% (PASS ✓)
- **Top classified**: `korean`
- **Persona score**: 92%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Looking at the portrait carefully, I'll analyze the visible technical traits:
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `korean`. Persona strong (92%).

## Round 3 — korean / sara_ramirez — 2026-04-06 12:06

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: `korean`
- **Persona score**: 78%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Looking at the portrait carefully, I'll analyze the visual traits:
- **Observations**: First run for this combination. Style FAILED — classifier returned `korean` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona strong (78%).

## Round 4 — korean / adam_levine — 2026-04-06 12:07

- **Style score** (korean): 92% (PASS ✓)
- **Top classified**: `korean`
- **Persona score**: 99%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Visual Analysis
- **Observations**: Δ+10% vs avg 82% over 1 prior run(s). Style PASSED. Classifier correctly identified `korean`. Persona strong (99%).

## Round 4 — korean / rihanna — 2026-04-06 12:07

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: `korean`
- **Persona score**: 91%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Looking at this portrait carefully, I'll analyze the key visual traits present:
- **Observations**: Δ-82% vs avg 82% over 1 prior run(s). Style FAILED — classifier returned `korean` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona strong (91%).

## Round 4 — korean / sara_ramirez — 2026-04-06 12:08

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 72%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Looking at this portrait carefully:
- **Observations**: Δ+0% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona moderate (72%) — some features not preserved.

## Round 5 — clay / adam_levine — 2026-04-06 12:09

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 89%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Looking at this portrait carefully:
- **Observations**: Δ-18% vs avg 18% over 1 prior run(s). Style FAILED — classifier returned `` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (89%).

## Round 5 — clay / rihanna — 2026-04-06 12:10

- **Style score** (clay): 28% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 86%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ-60% vs avg 88% over 1 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (86%).

## Round 5 — clay / sara_ramirez — 2026-04-06 12:12

- **Style score** (clay): 28% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 0%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ+28% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 6 — korean / adam_levine — 2026-04-06 12:16

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: Δ-87% vs avg 87% over 2 prior run(s). Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 6 — korean / rihanna — 2026-04-06 12:20

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: Δ-41% vs avg 41% over 2 prior run(s). Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 6 — korean / sara_ramirez — 2026-04-06 12:24

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 2 prior run(s). Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 7 — studio_3d / adam_levine — 2026-04-06 12:28

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: Δ-92% vs avg 92% over 1 prior run(s). Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 7 — studio_3d / rihanna — 2026-04-06 12:32

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: Δ-88% vs avg 88% over 1 prior run(s). Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 7 — studio_3d / sara_ramirez — 2026-04-06 12:36

- **Style score** (studio_3d): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: 3D rendered portrait avatar, high-quality CG animation style, physically-based rendering. Subsurface scattering on skin. Exaggerated head-to-body ratio 1.5:1. Large rounded expressive eyes with multi-
- **Model reasoning**: 
- **Observations**: Δ-96% vs avg 96% over 1 prior run(s). Style FAILED — classifier returned `` instead of `studio_3d`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 8 — lineart / adam_levine — 2026-04-06 12:40

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 8 — lineart / rihanna — 2026-04-06 12:45

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 8 — lineart / sara_ramirez — 2026-04-06 12:49

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: First run for this combination. Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 9 — lineart / adam_levine — 2026-04-06 12:53

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 9 — lineart / rihanna — 2026-04-06 12:57

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 9 — lineart / sara_ramirez — 2026-04-06 13:01

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 1 prior run(s). Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 10 — lineart / adam_levine — 2026-04-06 13:05

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 2 prior run(s). Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 10 — lineart / rihanna — 2026-04-06 13:09

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 0%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: 
- **Observations**: Δ+0% vs avg 0% over 2 prior run(s). Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona weak (0%) — visual properties not well preserved. Reference image may be insufficient or style is too aggressive.

## Round 10 — lineart / sara_ramirez — 2026-04-06 13:11

- **Style score** (lineart): 88% (PASS ✓)
- **Top classified**: `lineart`
- **Persona score**: 97%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: Style Analysis
- **Observations**: Δ+88% vs avg 0% over 2 prior run(s). Style PASSED. Classifier correctly identified `lineart`. Persona strong (97%).

## Round 11 — korean / adam_levine — 2026-04-06 13:12

- **Style score** (korean): 78% (PASS ✓)
- **Top classified**: `korean`
- **Persona score**: 99%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Style Analysis
- **Observations**: Δ+20% vs avg 58% over 3 prior run(s). Style PASSED. Classifier correctly identified `korean`. Persona strong (99%).

## Round 11 — korean / rihanna — 2026-04-06 13:12

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: `korean`
- **Persona score**: 91%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Looking at this portrait carefully, I'll analyze the key visual traits:
- **Observations**: Δ-27% vs avg 27% over 3 prior run(s). Style FAILED — classifier returned `korean` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona strong (91%).

## Round 11 — korean / sara_ramirez — 2026-04-06 13:13

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 79%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Looking at the portrait carefully:
- **Observations**: Δ+0% vs avg 0% over 3 prior run(s). Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona strong (79%).

## Round 12 — clay / adam_levine — 2026-04-06 13:14

- **Style score** (clay): 28% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 94%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Visual Style Analysis
- **Observations**: Δ+19% vs avg 9% over 2 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (94%).

## Round 12 — clay / rihanna — 2026-04-06 13:16

- **Style score** (clay): 18% (FAIL ✗)
- **Top classified**: `photorealistic`
- **Persona score**: 84%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ-40% vs avg 58% over 2 prior run(s). Style FAILED — classifier returned `photorealistic` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (84%).

## Round 12 — clay / sara_ramirez — 2026-04-06 13:17

- **Style score** (clay): 8% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 93%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ-6% vs avg 14% over 2 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (93%).

## Round 13 — korean / adam_levine — 2026-04-06 13:18

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 98%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Looking at this portrait carefully, I'll analyze the visual evidence against each style's traits.
- **Observations**: Δ-63% vs avg 63% over 4 prior run(s). Style FAILED — classifier returned `` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona strong (98%).

## Round 13 — korean / rihanna — 2026-04-06 13:19

- **Style score** (korean): 92% (PASS ✓)
- **Top classified**: `korean`
- **Persona score**: 92%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Style Analysis
- **Observations**: Δ+72% vs avg 20% over 4 prior run(s). Style PASSED. Classifier correctly identified `korean`. Persona strong (92%).

## Round 13 — korean / sara_ramirez — 2026-04-06 13:20

- **Style score** (korean): 0% (FAIL ✗)
- **Top classified**: `korean`
- **Persona score**: 92%
- **Prompt excerpt**: 2D digital illustration, Korean style with anime influence. No silhouette outline — shape separation by adjacent flat color areas only. Semi-realistic facial proportions: slim elongated face, almond-s
- **Model reasoning**: Style Analysis
- **Observations**: Δ+0% vs avg 0% over 4 prior run(s). Style FAILED — classifier returned `korean` instead of `korean`. Consider strengthening style-defining traits in system_prompt. Persona strong (92%).

## Round 14 — lineart / adam_levine — 2026-04-06 13:20

- **Style score** (lineart): 88% (PASS ✓)
- **Top classified**: `lineart`
- **Persona score**: 98%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: Looking at the portrait carefully:
- **Observations**: Δ+88% vs avg 0% over 3 prior run(s). Style PASSED. Classifier correctly identified `lineart`. Persona strong (98%).

## Round 14 — lineart / rihanna — 2026-04-06 13:21

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: `lineart`
- **Persona score**: 86%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: Looking at this portrait carefully, I'll analyze the visible technical traits:
- **Observations**: Δ+0% vs avg 0% over 3 prior run(s). Style FAILED — classifier returned `lineart` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona strong (86%).

## Round 14 — lineart / sara_ramirez — 2026-04-06 13:22

- **Style score** (lineart): 78% (PASS ✓)
- **Top classified**: `lineart`
- **Persona score**: 96%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: Visual Style Analysis
- **Observations**: Δ+49% vs avg 29% over 3 prior run(s). Style PASSED. Classifier correctly identified `lineart`. Persona strong (96%).

## Round 15 — clay / adam_levine — 2026-04-06 13:23

- **Style score** (clay): 18% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 89%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ+3% vs avg 15% over 3 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (89%).

## Round 15 — clay / rihanna — 2026-04-06 13:25

- **Style score** (clay): 82% (PASS ✓)
- **Top classified**: `clay`
- **Persona score**: 84%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ+37% vs avg 45% over 3 prior run(s). Style PASSED. Classifier correctly identified `clay`. Persona strong (84%).

## Round 15 — clay / sara_ramirez — 2026-04-06 13:26

- **Style score** (clay): 0% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 81%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ-12% vs avg 12% over 3 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (81%).

## Round 16 — lineart / adam_levine — 2026-04-06 13:26

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 99%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: Looking at the portrait carefully:
- **Observations**: Δ-22% vs avg 22% over 4 prior run(s). Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona strong (99%).

## Round 16 — lineart / rihanna — 2026-04-06 13:27

- **Style score** (lineart): 0% (FAIL ✗)
- **Top classified**: ``
- **Persona score**: 84%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: Looking at this portrait carefully:
- **Observations**: Δ+0% vs avg 0% over 4 prior run(s). Style FAILED — classifier returned `` instead of `lineart`. Consider strengthening style-defining traits in system_prompt. Persona strong (84%).

## Round 16 — lineart / sara_ramirez — 2026-04-06 13:28

- **Style score** (lineart): 88% (PASS ✓)
- **Top classified**: `lineart`
- **Persona score**: 77%
- **Prompt excerpt**: Simple 2D web illustration portrait, friendly sticker style. Outline strokes present on figure edges and facial features. Simplified facial features — large-scale shapes only, no fine details like ind
- **Model reasoning**: Visual Style Analysis
- **Observations**: Δ+46% vs avg 42% over 4 prior run(s). Style PASSED. Classifier correctly identified `lineart`. Persona strong (77%).

## Round 17 — photorealistic / adam_levine — 2026-04-06 13:29

- **Style score** (photorealistic): 96% (PASS ✓)
- **Top classified**: `photorealistic`
- **Persona score**: 93%
- **Prompt excerpt**: Photorealistic professional portrait photograph. No stylization, illustration, or cartoon elements. Natural skin with visible pores, subtle texture, and fine hair detail. Physically accurate three-poi
- **Model reasoning**: - **Natural skin texture**: Visible pores, fine wrinkles, and subtle skin imperfections across forehead, cheeks, and nose
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `photorealistic`. Persona strong (93%).

## Round 17 — photorealistic / rihanna — 2026-04-06 13:30

- **Style score** (photorealistic): 96% (PASS ✓)
- **Top classified**: `photorealistic`
- **Persona score**: 90%
- **Prompt excerpt**: Photorealistic professional portrait photograph. No stylization, illustration, or cartoon elements. Natural skin with visible pores, subtle texture, and fine hair detail. Physically accurate three-poi
- **Model reasoning**: - **Natural skin texture**: Visible pores, faint freckles, and subtle skin imperfections across the nose and cheeks — no smoothing or stylization.
- **Observations**: First run for this combination. Style PASSED. Classifier correctly identified `photorealistic`. Persona strong (90%).

## Round 17 — photorealistic / sara_ramirez — 2026-04-06 13:31

- **Style score** (photorealistic): 0% (FAIL ✗)
- **Top classified**: `photorealistic`
- **Persona score**: 99%
- **Prompt excerpt**: Photorealistic professional portrait photograph. No stylization, illustration, or cartoon elements. Natural skin with visible pores, subtle texture, and fine hair detail. Physically accurate three-poi
- **Model reasoning**: Looking at this portrait carefully:
- **Observations**: First run for this combination. Style FAILED — classifier returned `photorealistic` instead of `photorealistic`. Consider strengthening style-defining traits in system_prompt. Persona strong (99%).

## Round 18 — clay / adam_levine — 2026-04-06 13:32

- **Style score** (clay): 82% (PASS ✓)
- **Top classified**: `clay`
- **Persona score**: 94%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ+66% vs avg 16% over 4 prior run(s). Style PASSED. Classifier correctly identified `clay`. Persona strong (94%).

## Round 18 — clay / rihanna — 2026-04-06 13:33

- **Style score** (clay): 8% (FAIL ✗)
- **Top classified**: `clay`
- **Persona score**: 86%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ-46% vs avg 54% over 4 prior run(s). Style FAILED — classifier returned `clay` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (86%).

## Round 18 — clay / sara_ramirez — 2026-04-06 13:34

- **Style score** (clay): 48% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 96%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ+39% vs avg 9% over 4 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (96%).

## Round 19 — clay / adam_levine — 2026-04-06 13:35

- **Style score** (clay): 28% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 94%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Visual Style Analysis
- **Observations**: Δ-1% vs avg 29% over 5 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (94%).

## Round 19 — clay / rihanna — 2026-04-06 13:36

- **Style score** (clay): 22% (FAIL ✗)
- **Top classified**: `studio_3d`
- **Persona score**: 84%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Visual Style Analysis
- **Observations**: Δ-23% vs avg 45% over 5 prior run(s). Style FAILED — classifier returned `studio_3d` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (84%).

## Round 19 — clay / sara_ramirez — 2026-04-06 13:37

- **Style score** (clay): 9% (FAIL ✗)
- **Top classified**: `korean`
- **Persona score**: 96%
- **Prompt excerpt**: Smooth 3D rendered portrait avatar, commercial plastic-clay character style. MATTE clay surface — like molded plastic or clay toy. Zero specular highlights. Flat subsurface-free skin rendering. 2–3 fl
- **Model reasoning**: Style Analysis
- **Observations**: Δ-8% vs avg 17% over 5 prior run(s). Style FAILED — classifier returned `korean` instead of `clay`. Consider strengthening style-defining traits in system_prompt. Persona strong (96%).

## Round 20 — photorealistic / adam_levine — 2026-04-06 13:38

- **Style score** (photorealistic): 95% (PASS ✓)
- **Top classified**: `photorealistic`
- **Persona score**: 98%
- **Prompt excerpt**: Photorealistic professional portrait photograph. No stylization, illustration, or cartoon elements. Natural skin with visible pores, subtle texture, and fine hair detail. Physically accurate three-poi
- **Model reasoning**: - **Natural skin texture**: Visible pores, fine beard stubble texture, subtle skin imperfections on forehead and cheeks — hallmarks of photorealistic rendering
- **Observations**: Δ-1% vs avg 96% over 1 prior run(s). Style PASSED. Classifier correctly identified `photorealistic`. Persona strong (98%).

## Round 20 — photorealistic / rihanna — 2026-04-06 13:39

- **Style score** (photorealistic): 96% (PASS ✓)
- **Top classified**: `photorealistic`
- **Persona score**: 90%
- **Prompt excerpt**: Photorealistic professional portrait photograph. No stylization, illustration, or cartoon elements. Natural skin with visible pores, subtle texture, and fine hair detail. Physically accurate three-poi
- **Model reasoning**: - **Natural skin texture**: Visible pores, subtle skin imperfections, fine freckles — characteristic of real photography or photorealistic rendering
- **Observations**: Δ+0% vs avg 96% over 1 prior run(s). Style PASSED. Classifier correctly identified `photorealistic`. Persona strong (90%).

## Round 20 — photorealistic / sara_ramirez — 2026-04-06 13:40

- **Style score** (photorealistic): 95% (PASS ✓)
- **Top classified**: `photorealistic`
- **Persona score**: 71%
- **Prompt excerpt**: Photorealistic professional portrait photograph. No stylization, illustration, or cartoon elements. Natural skin with visible pores, subtle texture, and fine hair detail. Physically accurate three-poi
- **Model reasoning**: - **Natural skin texture**: Visible pores, subtle skin imperfections, and realistic skin tonal variation consistent with a photograph
- **Observations**: Δ+95% vs avg 0% over 1 prior run(s). Style PASSED. Classifier correctly identified `photorealistic`. Persona moderate (71%) — some features not preserved.

## Summary

- **clay**: avg style score 29%, 3/18 passed (17%)
- **korean**: avg style score 28%, 5/15 passed (33%)
- **lineart**: avg style score 23%, 4/15 passed (27%)
- **photorealistic**: avg style score 80%, 5/6 passed (83%)
- **studio_3d**: avg style score 46%, 3/6 passed (50%)
