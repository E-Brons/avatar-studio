# Background Removal — Studio 3D Style

**Date**: 2026-04-06 (Pass 1)
**Images tested**: 3 subjects — latest per subject (adam_levine, rihanna, sara_ramirez)
**Total studio_3d images in dataset**: 14
**Source images**: `assets/examples/<subject>/studio_3d_*.PNG`
**Experiment outputs**: `assets/examples/_bg_removal_experiments/studio_3d_pass1/`

---

## Style Characteristics

Studio_3d produces **Pixar/Disney-style 3D renders** with:

- **Dark gray/brown gradient background** (~R64–128, G64–112, B64–96) — much darker than clay
- **Very high background gradient** (border std ≈ 20–36 per channel) — significantly more variation than clay (std ≈ 2–8)
- **No outline strokes** — smooth 3D render, no black edge barriers
- **Dark subject elements** — hair, clothing, and shadows use colors in the same dark/gray/brown range as the background

---

## Background Color Variability

| Image | Estimated bg (R, G, B) | Border std |
|---|---|---|
| adam_levine/studio_3d_12_24_40 | 80, 80, 80 | ~19.9 |
| rihanna/studio_3d_12_28_46 | 112, 96, 96 | ~36.3 |
| sara_ramirez/studio_3d_12_32_51 | 64, 64, 64 | ~34.2 |
| adam_levine/studio_3d_11_28_20 | 64, 64, 64 | ~25.0 |
| rihanna/studio_3d_11_29_19 | 112, 112, 96 | ~32.6 |

Background is dark neutral gray/brown, varies noticeably per generation. Border std 20–36 is 5–15× higher than clay — the background is a strong gradient, not uniform.

---

## Results

| Method | adam opaque% | rihanna opaque% | sara opaque% | Speed | Verdict |
|---|---|---|---|---|---|
| `ff_dist20` | 86.1 | **99.9** | 69.5 | ~0.1s | ❌ False positive — bg not removed |
| `ff_dist30` | 79.0 | 94.3 | 58.5 | ~0.2s | ❌ Mostly false positive |
| `ff_dist40` | 72.0 | 91.2 | 56.4 | ~0.2s | ❌ BFS barely spreads from corners |
| `ff_dist50` | 57.8 | 90.0 | 50.4 | ~0.3s | ❌ Leaks into subject OR bg remains |
| `ff_dist65` | 36.2 | 67.2 | 37.9 | ~0.5s | ❌ Erodes subject (hair/clothing) |
| `ff_dist80` | 31.1 | 52.3 | 31.2 | ~0.5s | ❌ Heavy subject erosion |
| **`u2net_am`** | **48.2** | **80.4** | **58.2** | ~0.4–1.7s | ✅ **Best — clean portrait cutout** |

### Visual verification

Composite-on-green images reveal the true picture:

- **ff_dist20 on rihanna**: opaque=99.9% is a **false positive** — the high-variance gradient background
  blocks BFS from spreading beyond the image corners. Almost no background removed.

- **ff_dist50 on adam_levine**: Large green patches leak into beard and facial shadow regions —
  the dark background color (R=80,G=80,B=80) is indistinguishable from dark facial hair within
  dist=50. BFS escapes through shadows.

- **ff_dist50 on sara_ramirez**: Background mostly removed but visible leakage into dark hair
  and jacket along the left side.

- **u2net_am on all 3 subjects**: Clean, full portrait preserved, crisp background removal.
  Adam, rihanna, and sara all show professional-quality cutouts with no leakage.

---

## Why Flood-Fill Fails for Studio 3D

Two compounding problems:

### 1. High background gradient (std ≈ 20–36)

The background is a gradient, not a uniform solid. Pixels at the gradient extremes can be 50–80
units away from the estimated bg color. BFS seeds from corners but can't spread through the
gradient — at low dist thresholds (≤20), most of the gradient is unreachable → opaque% falsely
high (background not removed). At higher thresholds (≥50), the fill spreads but leaks.

This is distinct from clay (std ≈ 2–8), where the background is nearly uniform and the gradient
is very shallow.

### 2. Subject-background color overlap (no outline barriers)

Dark gray/brown background colors (R=64–128, G=64–112, B=64–96) overlap with:
- Dark hair (black/dark brown)
- Dark clothing (jackets, tops)
- Facial shadows and neck shadows

Without hard outline strokes to create BFS barriers (unlike Korean/lineart), the fill leaks
from the background directly through shadow gradients into the subject. There is no safe
threshold: low = background not removed, high = subject eroded.

---

## Comparison with Other Styles

| Property | Korean | Lineart | Clay | **Studio 3D** |
|---|---|---|---|---|
| Background | White | Orange | Warm gray | **Dark gray/brown** |
| Background gradient (std) | ~0–1 | ~2–5 | ~2–8 | **~20–36** |
| Outline strokes | Yes (barrier) | Yes (barrier) | No | **No** |
| Subject-bg color overlap | None | Moderate | Low | **High** |
| Flood-fill result | ✅ | ✅ | ✅ | ❌ |
| u2net_am result | Good (slower) | Dissolves clothing | Comparable | **✅ Best method** |

---

## Production Recommendation

**Use `remove_background()` (u2net + alpha_matting) for studio_3d** — not `remove_background_illustration()`.

The flood-fill approach is fundamentally incompatible with studio_3d due to:
1. High background gradient blocking BFS spread
2. Dark subject elements (hair, clothing) overlapping background color range with no outline barriers

u2net with alpha_matting correctly identifies the human subject using learned semantics rather
than color proximity, producing clean cutouts regardless of background–subject color overlap.

Call site should route based on image style:

```python
if style in ("korean", "lineart", "clay"):
    result = remove_background_illustration(image_bytes)
elif style in ("studio_3d", "photorealistic"):
    result = remove_background(image_bytes)  # u2net ML path
```

---

## Future Work

- Test on all 14 studio_3d images to confirm u2net robustness across generations
- Test `photorealistic` style — also needs ML path (real photo backgrounds)
- When proxy/network restored: test `birefnet-portrait` and `isnet-anime` — newer architectures
  may give sharper edges than u2net, especially for hair
- Investigate whether a two-pass approach (flood-fill to remove obvious bg, u2net for edges) could
  improve quality further
