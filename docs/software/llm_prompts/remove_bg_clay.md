# Background Removal — Clay Style

**Date**: 2026-04-06 (Pass 1)
**Images tested**: 3 subjects — latest per subject (adam_levine, rihanna, sara_ramirez)
**Total clay images in dataset**: 24
**Source images**: `assets/examples/<subject>/clay_*.PNG`
**Experiment outputs**: `assets/examples/_bg_removal_experiments/clay_pass1/`

---

## Style Characteristics

Clay-style 3D renders have a **warm gray/beige background** (~R185–192, G177–188, B168–180) with:

- **Gradient background** (slight vignette): std ≈ 2–8 per channel across border — not perfectly uniform but low variation
- **No hard outline strokes** — unlike Korean and lineart, the 3D figure blends smoothly with soft shadows into the background
- **Soft edge transitions** — shadow areas at the figure boundary may be within distance 20–35 of bg color

Despite having no outline barriers, flood-fill still works because the background color is uniform enough and the subject's skin/clothing has sufficient color contrast (~dist 66+ from bg).

---

## Background Color Variability

| Image | R | G | B | Border std |
|---|---|---|---|---|
| adam_levine/clay_13_34_30 | 192 | 176 | 176 | ~5 |
| rihanna/clay_13_35_43 | 176 | 176 | 160 | ~2 |
| sara_ramirez/clay_13_36_45 | 176 | 176 | 176 | ~2 |
| adam_levine/clay_11_22_19 | 185 | 177 | 168 | ~6 |

Dominant-border-mode auto-detection works well — threshold=50 comfortably separates bg from subject.

---

## Results

| Method | adam opaque% | rihanna opaque% | sara opaque% | Speed | Verdict |
|---|---|---|---|---|---|
| `ff_dist20` | 49.6 | **81.2** | **61.9** | ~0.3s | ❌ Incomplete — bg patches remain |
| **`ff_dist30`** | **46.8** | 59.4 | 48.8 | ~0.35s | ✅ **Best — full clean removal** |
| `ff_dist40` | 45.8 | 59.3 | 48.8 | ~0.35s | ✅ Good |
| `ff_dist50` | 45.1 | 58.5 | 48.7 | ~0.35s | ✅ Good (production default) |
| `ff_dist65` | 44.9 | 47.6 | 39.3 | ~0.4s | ❌ Erodes subject (hair, shoulders) |
| `u2net_am` | 44.6 | 57.0 | 45.8 | ~0.7–1.7s | ✅ Good, slightly softer edges |

### dist=20 false positive

`ff_dist20` shows **spuriously high opaque%** (81.2% for rihanna). This is because the background gradient has many pixels with dist > 20 from the estimated bg color — the fill seeds from corners but can't spread through the gradient, leaving large background patches opaque. The number is misleading: it means *more background remained*, not more subject preserved.

Always verify visually with a colored composite — opaque% alone can indicate either "subject preserved" or "background not removed."

### dist=65 erosion

Without hard outlines, dist=65 bleeds into the subject through the soft shadow transition zone. Hair tips and shoulder edges get cut at this threshold.

### Optimal threshold: 30

The production default of `dist=50` also produces visually clean results for clay (nearly identical to dist=30 numerically). Threshold sensitivity is low in the 30–50 range — use 50 as the universal default.

---

## Comparison: No Outlines vs Outlined Styles

| Property | Korean | Lineart | Clay |
|---|---|---|---|
| Background | White | Orange | Warm gray/beige |
| Outline strokes | Yes (hard barrier) | Yes (hard barrier) | **No** |
| Optimal dist_threshold | 50 | 50 | 30–50 |
| Threshold sensitivity | Low (30–75 identical) | Low (30–75 identical) | **Medium (30 ok, 65 erodes)** |
| Flood-fill result | ✅ | ✅ | ✅ |
| u2net alternative | Slower, comparable | Destroys same-hue clothing | Comparable, softer edges |

Flood-fill works on clay despite missing outlines because the **background is still a distinct, uniform color** — the 3D render provides enough subject/bg color contrast even without explicit boundary strokes.

---

## Production Recommendation

The current `dist_threshold=50` in `remove_background_illustration()` works well for clay. No change needed. The dominant-border-mode bg estimation correctly identifies the warm-gray background.

---

## Future Work

- Test on all 24 clay images to confirm bg color consistency and threshold robustness
- Test remaining styles: studio_3d, photorealistic
- `studio_3d` likely has similar characteristics to clay (3D render, possible gradient background)
- `photorealistic` will require the ML path (`remove_background()`) — real photo backgrounds are complex
