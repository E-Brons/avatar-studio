# Background Removal — Korean Style

**Last updated**: 2026-04-06 (Pass 8 — full dataset validation)
**Images tested**: 3 subjects × 7 images = **21 images** (entire dataset)
**Source images**: `assets/examples/<subject>/korean_*.PNG`
**Experiment outputs**: `assets/examples/_bg_removal_experiments/korean_pass*/`
**Script**: `scripts/remove_bg_korean.py`

---

## The Challenge

Korean-style illustration (webtoon / manhwa) presents a tricky background-removal problem:

- Background is near-white (`#FFFFFF` or very close)
- **Skin highlights are also near-white** — specular highlights on cheeks, nose bridge, and eye whites are indistinguishable from background by simple luminance methods
- Thin outline strokes define the figure boundary; hair flyaways create complex alpha edges
- The style is flat/2D — no depth gradients to help a subject-detection model

**Key structural insight**: The strong black outline strokes that define Korean illustration style are actually an asset — they create hard connectivity barriers that prevent a flood-fill seeded from corners from ever reaching skin highlights or interior white areas.

---

## Pass 7 — Production Code Gap (Critical Finding)

`src/pipeline/render/postprocess/background_remover.py` was using plain `u2net` with no
alpha-matting — the worst-performing approach from Pass 1.

| Subject | Old production opaque% | New production opaque% | Speedup |
|---|---|---|---|
| adam_levine | 5.3% | **51.3%** | 11.6× |
| rihanna | 1.8% | **70.7%** | 5.3× |
| sara_ramirez | 5.0% | **52.2%** | 3.7× |

The old implementation produced ghostly/washed-out results on Korean style — the red background
bled through the entire face on rihanna. **`background_remover.py` has been updated** with:
- `remove_background_illustration()` — flood-fill (new primary method for illustration styles)
- `remove_background()` — u2net + alpha_matting + morph_close (upgraded ML fallback)

---

## Final Results — All Methods

| Method | Speed | rihanna opaque% | semi% | Verdict |
|---|---|---|---|---|
| **Flood-fill + RGB pre-close (r=1)** | **~0.1s** | **70.8%** | **0%** | ✅ **Best overall** |
| Flood-fill (threshold=230, 4-conn) | ~0.1s | 70.2% | 0% | ✅ Excellent |
| Flood-fill + soft edge (r=0.8) | ~0.1s | 69.1% | 2.0% | ✅ Natural-looking edges |
| Flood-fill (8-connectivity) | ~0.2s | 70.2% | 0% | ✅ Same as 4-conn for this style |
| Flood-fill (edge-seeded) | ~0.1s | 70.2% | 0% | ✅ Same as corner-seeded |
| Auto threshold (5th-percentile) | ~0.1s | 70.1% | 0% | ✅ Robust no-hardcode variant |
| `u2net` + alpha_matting + morph_close | ~0.7–1.1s | 64.5% | 7.1% | ✅ Best ML method (use as fallback) |
| `u2net` + alpha_matting | ~0.6–1.0s | 62.2% | 8.4% | ✅ Good |
| `u2net` plain | ~0.5s | ~2% | ~70% | ⚠️ Soft edges only |
| Alpha sigmoid contrast boost | ~0.6s | 0% | 100% | ❌ Broken — all semi |
| `isnet-general-use` | ~0.9s | 0.2% | 52% | ❌ Skin dissolves |
| `threshold_240` (PIL, global) | ~0.003s | ~50% | 0% | ❌ Face highlights destroyed |
| `isnet-anime` | N/A | — | — | ⏳ Proxy-blocked — test when network available |
| `birefnet-portrait` | N/A | — | — | ⏳ Proxy-blocked |
| `u2net_human_seg` | N/A | — | — | ⏳ Proxy-blocked |

---

## Why Flood-Fill Wins for Korean Style

```
              FAILS (global threshold)    WINS (flood-fill)
near-white BG pixel:   → transparent       → transparent ✓
near-white skin highlight: → transparent ❌  → opaque ✓ (enclosed by outline)
```

**Global threshold** (`threshold_240`): removes every pixel above a luminance value, regardless of where it is. Face highlights and eye whites are near-white → they get erased.

**Flood-fill from corners**: removes only pixels that are (a) near-white AND (b) *connected* to a corner via a path of near-white pixels. The strong black outline creates an impenetrable barrier — face highlights inside the outline are unreachable from the background.

This is why flood-fill achieves the same 0% semi as threshold but without destroying the face.

---

## Detailed Pass-by-Pass Findings

### Pass 1 — Baseline (u2net, isnet, threshold)
- `u2net` works; `isnet-general-use` fails (skin dissolves); `threshold` fails (face highlights erased)
- Red-composite visual test used throughout to reveal transparency

### Pass 2 — u2net + alpha_matting
- `alpha_matting=True` converts soft u2net mask into crisp matte: opaque jumps 5% → 48–62%
- semi drops from 47–70% to 4–8%

### Pass 3 — alpha_matting parameter sweep
- `erode_size=5`: best for simple backgrounds; `erode_size=10`: best for complex hair
- Morphological closing (MaxFilter+MinFilter r=3) adds +1–2pp opaque by filling interior holes
- `foreground_threshold` and `background_threshold` have negligible effect — keep defaults

### Pass 4 — Flood-fill discovery
- **Flood-fill from corners beats all ML approaches**: 70.2% vs 64.5% opaque for rihanna
- 10× faster (0.1s vs 1.1s), no model required, 0% semi
- All 3 subjects: full portrait preserved, face highlights intact

### Pass 5 — Flood-fill refinement
- **Threshold sweep 200–240**: all give identical results (±0.1pp) — Korean bg is uniformly white
- `soft_0.8` (Gaussian blur r=0.8 on alpha): 2% semi, natural-looking edges for compositing
- `hybrid AND` (flood-fill ∩ u2net): loses 5pp opaque on rihanna — u2net limits flood-fill, no benefit
- `hybrid OR` (flood-fill ∪ u2net): identical to flood-fill — flood-fill already covers u2net

### Pass 6 — Advanced variants
- **8-connectivity**: identical to 4-connectivity — Korean outlines are thick enough that diagonals don't change result
- **Edge-seeded** (all border pixels): identical to corner-seeded — background is so uniform all border pixels reach the same region
- **Pre-close r=1**: MinFilter(3) on RGB before fill closes sub-pixel outline gaps → +0.6pp opaque across all subjects — marginal but consistent
- **Auto threshold** (5th-percentile of corner samples): detects threshold=200 automatically, consistent with manual results — eliminates hardcoded parameter

---

## Production Code

### Option A — Flood-fill (recommended for Korean style and any solid-bg illustration)

Fast (0.1s), no ML needed, perfect subject preservation. Relies on strong outline strokes.

```python
from collections import deque
from PIL import Image, ImageFilter
import numpy as np


def remove_bg_korean(img: Image.Image, feather: bool = False) -> Image.Image:
    """
    Remove white background from Korean-style illustration.
    Uses BFS flood-fill from corners — preserves face highlights enclosed by outlines.

    Args:
        img:     Source PIL Image (any mode)
        feather: If True, applies 0.8px Gaussian blur to alpha for softer compositing edges
    Returns:
        RGBA PIL Image with background removed
    """
    img = img.convert("RGBA")
    # Pre-close: seal any sub-pixel outline gaps to prevent potential fill leakage
    rgb_closed = np.array(img.convert("RGB").filter(ImageFilter.MinFilter(3)))
    threshold = _estimate_bg_threshold(rgb_closed)

    h, w = rgb_closed.shape[:2]
    keep = np.ones((h, w), dtype=bool)
    visited = np.zeros((h, w), dtype=bool)
    queue = deque()

    for sy, sx in [(0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)]:
        r, g, b = int(rgb_closed[sy, sx, 0]), int(rgb_closed[sy, sx, 1]), int(rgb_closed[sy, sx, 2])
        if r >= threshold and g >= threshold and b >= threshold and not visited[sy, sx]:
            queue.append((sy, sx))
            visited[sy, sx] = True

    while queue:
        y, x = queue.popleft()
        keep[y, x] = False
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                r, g, b = int(rgb_closed[ny, nx, 0]), int(rgb_closed[ny, nx, 1]), int(rgb_closed[ny, nx, 2])
                if r >= threshold and g >= threshold and b >= threshold:
                    visited[ny, nx] = True
                    queue.append((ny, nx))

    result = img.copy()
    alpha = Image.fromarray((keep * 255).astype(np.uint8))
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=0.8))
    result.putalpha(alpha)
    return result


def _estimate_bg_threshold(rgb: np.ndarray, sample: int = 20) -> int:
    """Auto-detect background threshold from corner pixel samples."""
    h, w = rgb.shape[:2]
    s = sample
    corners = np.concatenate([
        rgb[:s, :s].reshape(-1, 3), rgb[:s, w-s:].reshape(-1, 3),
        rgb[h-s:, :s].reshape(-1, 3), rgb[h-s:, w-s:].reshape(-1, 3),
    ])
    thr = int(np.min(np.percentile(corners, 5, axis=0))) - 15
    return max(200, min(250, thr))
```

### Option B — u2net + alpha_matting + morph_close (ML fallback)

Use when background is not solid white, or when flood-fill might leak (open compositions,
backgrounds that wrap around the subject through gaps between arms and body).

```python
import io
from PIL import Image, ImageFilter
from rembg import new_session, remove

_u2net_session = new_session("u2net")  # load once at module import


def remove_bg_ml(img_bytes: bytes) -> Image.Image:
    """ML-based removal. Robust to complex/non-white backgrounds."""
    result_bytes = remove(
        img_bytes,
        session=_u2net_session,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
    )
    img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
    r, g, b, a = img.split()
    a = a.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(7))
    img.putalpha(a)
    return img
```

---

## When to Use Which

| Condition | Use |
|---|---|
| Korean / lineart / clay / studio_3d (solid white bg) | Flood-fill (Option A) |
| Compositing onto bright/white background | `feather=True` for 1–2px soft edge |
| Compositing onto dark/coloured background | `feather=False` for crisp comic-style edge |
| Complex scene, non-white background | u2net ML fallback (Option B) |
| Batch processing (no GPU, speed critical) | Flood-fill only — 10× faster, no model load |

---

## Pass 8 — Full Dataset Validation (2026-04-06)

Ran production `remove_background_illustration()` on all 21 Korean images (3 subjects × 7 images).

| Metric | Value |
|---|---|
| Total images | 21 |
| Failures (opaque% < 35%) | **0** |
| opaque% range | 50.0 – 72.7 |
| opaque% mean | 58.2 |
| semi% | **0.0% on every image** |
| bg color (all images) | R=240 G=240 B=240 — perfectly consistent |

**Background color is invariant** across all 21 Korean generations — always quantizes to R=240 G=240 B=240. No generation-to-generation bg variance to worry about (unlike lineart which varies significantly).

Border std is high (44–94) because the subject fills much of the frame — doesn't affect results since the dominant-mode estimator correctly identifies bg=240,240,240 in every case.

Visual spot-checks (earliest and latest batches per subject): all clean, full portrait preserved, face highlights intact.

**Korean flood-fill is fully validated across the entire dataset. No edge cases found.**

---

## Known Limitations & Future Work

**Flood-fill limitations**:
- Leakage risk: if background connects through a gap in the outline (e.g. between arm and body, or at image bottom where subject doesn't fill the frame). For Korean portrait busts this doesn't occur.
- Fails on non-white backgrounds — auto threshold handles slight off-white but not coloured backgrounds

**Models to test when proxy/network is restored** (in priority order):
1. `isnet-anime` — trained specifically on anime/illustration; likely outperforms u2net for ML path
2. `birefnet-portrait` — newer BiRefNet architecture, portrait-optimised
3. `u2net_human_seg` — human body segmentation
4. `silueta` — lighter weight, portrait-tuned
5. `bria-rmbg` — newer commercial-grade model

**Other styles**: All 5 styles now have Pass 1 docs. See `remove_bg_lineart.md`, `remove_bg_clay.md`, `remove_bg_studio_3d.md`, `remove_bg_photorealistic.md`.
