# Background Removal — Photorealistic Style

**Date**: 2026-04-06 (Pass 1)
**Images tested**: 3 subjects — latest per subject (adam_levine, rihanna, sara_ramirez)
**Total photorealistic images in dataset**: 6
**Source images**: `assets/examples/<subject>/photorealistic_*.PNG`
**Experiment outputs**: `assets/examples/_bg_removal_experiments/photorealistic_pass1/`

---

## Style Characteristics

Photorealistic portraits are **real-photograph-quality** AI renders with:

- **Neutral gray studio backdrop** (~R112–128, G112–128, B112–128)
- **Very high background gradient** (border std ≈ 24–42 per channel) — standard studio lighting
  vignette; background varies widely from centre to edges
- **No outline strokes** — photorealistic by definition
- **Gray background overlaps with subject** — facial shadows, neck, and lighter skin tones
  fall in the same gray range as the backdrop

---

## Background Color Variability

| Image | Estimated bg (R, G, B) | Border std |
|---|---|---|
| adam_levine/photorealistic_13_37_47 | 112, 128, 128 | ~23.9 |
| rihanna/photorealistic_13_38_37 | 128, 128, 128 | ~41.9 |
| sara_ramirez/photorealistic_13_39_29 | 112, 112, 112 | ~40.6 |

All three share similar neutral gray backgrounds — same regime as studio_3d (std 20–36) but
even higher gradient in some cases.

---

## Results

| Method | adam opaque% | rihanna opaque% | sara opaque% | Speed | Verdict |
|---|---|---|---|---|---|
| `ff_dist20` | 74.0 | 75.2 | **98.8** | ~0.01–0.2s | ❌ False positive / partial removal |
| `ff_dist30` | 56.2 | 71.9 | 61.9 | ~0.2–0.3s | ❌ Inconsistent — leaks or fails |
| `ff_dist50` | 50.8 | **70.7** | 49.6 | ~0.2–0.4s | ❌ Severe leakage on sara (face removed) |
| `ff_dist65` | 41.8 | 69.6 | 46.7 | ~0.4s | ❌ Further erosion |
| **`u2net_am`** | **45.3** | **68.6** | **51.2** | ~0.4–1.7s | ✅ **Best — clean portrait on all 3** |

### Visual quality summary (composite-on-green)

| Subject | ff_dist50 | u2net_am |
|---|---|---|
| adam_levine | Clean — background fully removed ✅ | Clean ✅ |
| rihanna | Clean — background fully removed ✅ | Clean ✅ |
| sara_ramirez | **Catastrophic leakage** — large patches of face/neck removed ❌ | Clean ✅ |

### The sara_ramirez failure

`ff_dist50` removes most of sara's face: gray studio background (~R112) is within dist=50 of
facial shadows, neck, and lighter skin tones. BFS escapes through the continuous shadow gradient
from background → neck shadow → face shadow → face, turning the head transparent.

**This failure is not detectable from opaque% alone** (49.6% looks reasonable). Visual inspection
is essential.

### The rihanna/adam apparent success

Rihanna and adam_levine flood-fill results happen to look clean at dist=50 — coincidental: their
specific lighting/skin tone produced enough gap from background gray. This is not reliable:
photorealistic images have no structural guarantee of subject-background separation by color.

---

## Why Flood-Fill Is Unreliable for Photorealistic

| Factor | Korean / Lineart | Clay | Studio 3D | **Photorealistic** |
|---|---|---|---|---|
| Outline barriers | ✅ Yes | ✗ No | ✗ No | **✗ No** |
| Background uniformity | High | High | Medium | **Low (std ≈ 24–42)** |
| Background-subject color gap | Large | Medium | Low | **Unreliable** |
| Flood-fill verdict | ✅ | ✅ | ❌ | **❌** |

Real photography has continuous tone gradients from background through ambient light into the
subject with no structural boundary. There is no threshold that reliably separates background
from subject across all subjects — it depends on lighting, skin tone, clothing, and hair color.

---

## Production Recommendation

**Use `remove_background()` (u2net + alpha_matting) for photorealistic** — identical to studio_3d.

u2net was trained on real portrait photos and understands semantic person/background separation
regardless of color similarity. All 3 subjects produce clean cutouts.

Routing rule (confirmed across all 5 styles):

```python
if style in ("korean", "lineart", "clay"):
    result = remove_background_illustration(image_bytes)   # flood-fill, ~0.1–0.4s
else:  # studio_3d, photorealistic
    result = remove_background(image_bytes)                # u2net + alpha-matting, ~0.4–1.7s
```

---

## Comparison: All Styles

| Style | Background | Outline barriers | Flood-fill | u2net | Recommended |
|---|---|---|---|---|---|
| Korean | White | ✅ Yes | ✅ Best | Good | `remove_background_illustration()` |
| Lineart | Orange/amber | ✅ Yes | ✅ Best | ⚠️ Dissolves matching clothing | `remove_background_illustration()` |
| Clay | Warm gray | ✗ No (but uniform) | ✅ Good | Comparable | `remove_background_illustration()` |
| Studio 3D | Dark gray (gradient) | ✗ No | ❌ Leaks/fails | ✅ Clean | `remove_background()` |
| **Photorealistic** | Neutral gray (gradient) | ✗ No | ❌ Unreliable | ✅ Clean | **`remove_background()`** |

---

## Pass 2 — Production Asset Observation (2026-04-06)

`assets/examples/<subject>/photorealistic.png` files are **already RGBA with transparent
backgrounds** (mode=RGBA, border alpha=0, 1024×1024). They are post-processed reference
assets from a previous pipeline run — not raw generations.

Running `remove_background_for_style()` on pre-extracted RGBA images produces degraded
results (u2net re-processes an already-transparent mask, causing partial alpha loss). The
pipeline should always apply background removal to raw generator output bytes, not to
previously-extracted RGBA files.

| Subject | Source already transparent | Re-processed opaque% | Notes |
|---|---|---|---|
| adam_levine | ✅ Yes | 31.7% | Quality loss — low opaque vs expected ~45% |
| rihanna | ✅ Yes | 76.3% | Acceptable — dense subject area |
| sara_ramirez | ✅ Yes | 55.2% | Acceptable |

**Conclusion**: Pass 1 research (on raw timestamped `.PNG` generations with gray studio
backgrounds) remains the definitive reference. Do not test on `photorealistic.png` assets.

---

## Future Work

- Test on raw generations (not pre-extracted) to confirm u2net robustness across more subjects
- When proxy/network restored: test `birefnet-portrait` — newer architecture designed for
  portrait cutout; expected to give sharper hair edges than u2net on photorealistic
- Investigate `isnet-anime` for illustration styles as u2net ML alternative
