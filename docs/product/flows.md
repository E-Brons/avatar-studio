# Avatar Studio — User Flows

## Overview

Avatar Studio supports three distinct user flows. They share a rendering engine and expression system but differ fundamentally in what the user provides, what serves as the identity anchor, and what can go wrong.

- **Flow 1** starts from a written spec. The user defines who the avatar should be; the system generates an image that matches.
- **Flow 2** starts from existing images. The user wants a different style; the system preserves the identity while crossing a style boundary.
- **Flow 3** also starts from existing images, but the user wants only the expression to change — everything else must stay the same.

Understanding which flow applies determines which pipeline path runs, which signals are used for scoring, and what constitutes a failure.

---

## Flow 1 — Generate from Persona Spec

**User brings:** A fully specified persona — demographics, phenotype, presentation style, `style_id`, `expression_id`.

**What happens:** The pipeline constructs a detailed text prompt from the attributes and calls the image model. The output should look like a faithful visual rendering of the written spec.

**Key characteristic:** Attributes are the source of truth. The image is generated *from* the spec, not compared against a prior image. There is no reference photo.

**Failure mode:** The image ignores or misrepresents the attributes — wrong age, wrong ethnicity presentation, wrong style. This is the primary risk, not likeness drift (there is no prior image to drift from).

**Validation weights:**

| Signal | Weight |
|---|---|
| Persona attribute fidelity | ●●●●● |
| Style accuracy | ●●●●○ |
| Expression accuracy | ●●●○○ |
| SBS identity | — (no reference image) |

---

## Flow 2 — Re-render in a New Style

**User brings:** 1–N reference images (any style or origin), a target `style_id`, and a target `expression_id`.

**What happens:**
1. The pipeline extracts persona attributes from the reference images via vision LLM.
2. It generates 4 candidates using the extracted attributes as prompt and the reference images as identity anchors (IP-Adapter).
3. Each candidate is scored on SBS identity (vs source images) and persona attribute match.
4. The best-scoring candidate is returned.

**Key characteristic:** The source images define identity. Extracted attributes serve two roles: they anchor the prompt and act as a scoring oracle. The SBS identity check is the primary quality gate — likeness across the style boundary is what this flow is optimizing for.

**Failure mode:** The output loses recognizable likeness to the source images after the style transfer. The face, coloring, or proportions drift enough that the avatar no longer reads as the same person.

**Validation weights:**

| Signal | Weight |
|---|---|
| SBS identity (vs source images) | ●●●●● |
| SBS quality | ●●●●○ |
| Style accuracy | ●●●●○ |
| Persona attribute match | ●○○○○ |

---

## Flow 3 — Re-render with a Different Expression

**User brings:** 1–N images of the same avatar (any expression), and a target `expression_id`.

**What happens:**
1. The pipeline infers the style from the source images.
2. It generates N candidates using only the expression directive as the free variable — the source images anchor everything else (face, style, colors, proportions) via IP-Adapter.
3. Each candidate is scored on expression accuracy and SBS consistency vs source.
4. The best-scoring candidate is returned.

**Key characteristic:** The source images are the complete spec. No persona extraction is needed — the images already encode identity, style, and presentation. Only the expression is changing.

**Failure mode:** The output drifts from the source on any axis other than expression — different hair color, different style rendering, different face shape. The expression may be correct but the avatar no longer matches its previous self.

**Validation weights:**

| Signal | Weight |
|---|---|
| Expression accuracy | ●●●●● |
| SBS consistency (vs source images) | ●●●●● |
| SBS identity | ●●●●○ |
| Style accuracy | ●●●○○ |
| Persona attributes | — (not extracted) |

---

## Comparison

| | Flow 1 | Flow 2 | Flow 3 |
|---|---|---|---|
| **User inputs** | Persona spec + style + expression | Images + style + expression | Images + expression |
| **Identity anchor** | Written attributes | Source images (IP-Adapter + SBS) | Source images (IP-Adapter + SBS) |
| **Style anchor** | `style_id` (explicit) | `style_id` (explicit target) | Inferred from source images |
| **Expression** | `expression_id` (explicit) | `expression_id` (explicit) | `expression_id` (explicit) |
| **Persona extraction** | No — user provides spec | Yes — vision LLM extracts from images | No — images are the full spec |
| **Best-of-N selection** | No | Yes (4 candidates) | Yes (N candidates) |
| **Primary failure mode** | Attributes ignored in output | Lost likeness across style boundary | Drift from source (non-expression axes) |
| **SBS role** | Not used | Primary quality gate | Primary quality gate |
