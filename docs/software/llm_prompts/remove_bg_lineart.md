# Background Removal — Lineart Style

**Date**: 2026-04-06 (Pass 1)
**Images tested**: 3 subjects × latest image each (adam_levine, rihanna, sara_ramirez)
**Total lineart images in dataset**: 21
**Source images**: `assets/examples/<subject>/lineart_*.PNG`
**Experiment outputs**: `assets/examples/_bg_removal_experiments/lineart_pass1/`
**Script**: `scripts/remove_bg_korean.py`

---

## The Challenge

Lineart style has a **solid orange/amber background** (~R=220–235, G=148–171, B=68–86) — not white. This breaks the Korean luminance-threshold flood-fill entirely:

- `remove_background_illustration()` (Korean approach): **opaque=100%, 0% background removed** — luminance threshold ≥200 never matches orange pixels
- Global luminance threshold: same total failure
- **Subject clothing can be the same hue as the background** — rihanna's orange top sits within the background color family, causing u2net to dissolve it

**Key structural insight**: Lineart style has the same strong black outlines as Korean — outlines are perfect BFS barriers. The approach transfers, but needs **Euclidean RGB color-distance** instead of per-channel luminance comparison.

---

## Background Estimation Bug (Critical Fix)

The initial `_estimate_bg_color` implementation sampled a 15×15 patch at each corner.
For Korean-style images where the subject fills the frame to the bottom, the bottom two
corners contained subject pixels (clothing) — skewing the median toward skin tone and
causing the flood-fill to never seed.

**Fix**: Sample all pixels on the entire outermost 1-pixel border ring, quantize to bins
of 16, and return the modal (most frequent) colour. The background is always the
dominant colour at the image boundary; subject pixels are a minority.

```python
border = np.concatenate([top_row, bottom_row, left_col, right_col])
quantized = border // 16 * 16
keys, counts = np.unique(quantized, axis=0, return_counts=True)
bg_color = keys[np.argmax(counts)]
```

Tested on Korean (white bg, subject bleeds into bottom corners) and lineart (orange bg,
all borders are background) — both seed correctly with this approach.

---

## Background Estimation Bug (Critical Fix)

Background varies noticeably across generations (not a fixed constant):

| Image | R | G | B |
|---|---|---|---|
| adam_levine/lineart_11_19_02 | 228 | 152 | 68 |
| adam_levine/lineart_12_36_57 | 213 | 143 | 62 |
| adam_levine/lineart_13_20_25 | 184 | 126 | 50 |
| adam_levine/lineart_13_26_17 | 233 | 161 | 73 |
| rihanna/lineart_13_27_00 | 220 | 171 | 86 |
| sara_ramirez/lineart_13_27_45 | 221 | 148 | 71 |

**Conclusion**: Must estimate bg color per-image from corner samples. Cannot hardcode.

---

## Color Distance Analysis

Why threshold 30–75 all give identical results (distance well separates subject from background):

| Pixel type | Example RGB | Distance to bg (~R=225 G=158 B=72) |
|---|---|---|
| Orange bg | R=225 G=158 B=72 | 0 |
| Skin tone | R=240 G=195 B=155 | ~98 |
| Black outline | R=50 G=30 B=20 | ~221 |
| Brown hair | R=120 G=80 B=50 | ~130 |

Gap between background (0) and nearest subject color (skin ≈98) is large — any threshold 30–80 cleanly separates them.

---

## Results

| Method | adam opaque% | rihanna opaque% | sara opaque% | Speed | Verdict |
|---|---|---|---|---|---|
| `color_dist_flood_fill(dist=50)` | 47.5% | 62.3% | 51.9% | ~0.35s | ✅ **Best** |
| `color_dist_flood_fill` + soft (r=0.8) | 46.3% | 61.3% | 50.7% | ~0.35s | ✅ Natural edges |
| `u2net` + alpha_matting + morph_close | 46.9% | 48.4% | 51.3% | ~0.7–1.7s | ⚠️ Destroys orange clothing |
| `luminance_ff` (Korean approach) | 100% | 100% | 100% | ~0.05s | ❌ Total failure — bg not removed |

### Critical u2net failure on rihanna

u2net alpha_matting removes rihanna's **orange top** — it treats it as background because the clothing hue matches the background. On a dark composite the top turns black.

**Flood-fill correctly preserves orange clothing** because connectivity from image corners can never reach clothing pixels enclosed within outline strokes — regardless of color.

### Distance threshold robustness

| dist_threshold | adam opaque% | rihanna opaque% | sara opaque% |
|---|---|---|---|
| 30 | 47.6 | 62.3 | 51.9 |
| 40 | 47.5 | 62.3 | 51.9 |
| 50 | 47.5 | 62.3 | 51.9 |
| 60 | 47.5 | 62.3 | 51.9 |
| 75 | 47.5 | 62.3 | 51.9 |

Effectively insensitive to threshold in range 30–75. Use **50** as default (midpoint of safe range).

---

## Visual Quality

All 3 subjects: full portrait preserved, crisp edges, clothing intact.
Green-composite visual test shows clean separation with no artifacts.

Compared to Korean: lineart produces slightly smaller body crops (subject doesn't fill frame as fully),
but edge quality is equivalent.

---

## Production Code

Update `remove_background_illustration()` to use **color-distance flood-fill** as the primary method,
falling back to luminance threshold only for confirmed near-white backgrounds.

```python
def remove_background_illustration(image_bytes: bytes, feather: bool = False) -> bytes:
    """
    Handles both white-background (korean, clay, studio_3d) and
    coloured-background (lineart) illustration styles automatically.
    Uses BFS flood-fill seeded from corners with per-image bg colour estimation.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    rgb_closed = np.array(img.convert("RGB").filter(ImageFilter.MinFilter(3)))
    bg_color = _estimate_bg_color(rgb_closed)

    # Color-distance flood-fill — works for any solid background colour
    keep = _color_dist_flood_fill(rgb_closed, bg_color, dist_threshold=50)
    ...
```

See `src/pipeline/render/postprocess/background_remover.py` for full implementation.

---

## Comparison with Korean Style

| | Korean | Lineart |
|---|---|---|
| Background | White (~R255 G255 B255) | Orange (~R220 G155 B72) |
| Approach | Luminance threshold ≥200 | RGB color-distance ≤50 |
| Subject-bg distance | N/A (not needed — monotone) | ~98 (skin) — well separated |
| u2net failure mode | Dissolves near-white skin tones | Dissolves same-hue clothing |
| Flood-fill robustness | Threshold 200–240 all equivalent | Distance 30–75 all equivalent |
| Production verdict | Flood-fill ✅ | Color-distance flood-fill ✅ |

Both share the same structural advantage: **strong outline strokes act as BFS barriers**.

---

## Future Work

- Test on earlier lineart batches to confirm bg color variance handled by auto-estimation
- Test if lineart style ever produces non-orange backgrounds (check all 21 images)
- Update `remove_background_illustration()` to use color-distance as primary method
- Test remaining styles: clay, studio_3d, photorealistic
