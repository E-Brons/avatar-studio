# Avatar Studio — Avatars Design

## Table of Contents

1. [Avatars Essence](#1-avatars-essence)
2. [Artistic Style](#2-artistic-style)
   - [2.1 LLM-Generated Styles](#21-llm-generated-styles)
   - [2.2 Programmatic Styles](#22-programmatic-styles)
   - [2.3 Style Comparison Matrix](#23-style-comparison-matrix)
3. [Phenotype](#3-phenotype)
4. [Expressions](#4-expressions)
   - [4.1 Expression Set](#41-expression-set)
   - [4.2 Style × Expression](#42-style--expression)
5. [Attire](#5-attire)
6. [Acceptance Gate](#6-acceptance-gate)
   - [6.1 Identity Consistency](#61-identity-consistency)
   - [6.2 Phenotype Fidelity](#62-phenotype-fidelity)
   - [6.3 Expression Clarity](#63-expression-clarity)
   - [6.4 Style Fidelity](#64-style-fidelity)
   - [6.5 Technical Quality](#65-technical-quality)

---

## 1. Avatars Essence

Avatar Studio generates avatars for any type of persona — from professional advisors to cartoon characters to babies.
The visual identity, personality, and style are fully configurable via the style and persona inputs; no particular character archetype is assumed.

Every avatar presents an **artistic style**, **phenotype**, **attire**, and **expression**.

---

## 2. Artistic Style

The artistic style defines how the avatar is rendered visually. It is independent of background, sizing, and file format — those are applied programmatically after generation and are not part of any style definition.

Avatar Studio supports two fundamentally different style families:

| Family | How rendered | Expression control | Output |
|---|---|---|---|
| **LLM-Generated** | Image model + style system prompt | Natural language prompt | Raster (PNG) |
| **Programmatic** | Deterministic code / component library | Component selection (eyes, mouth, …) | Vector (SVG) |

The style input also accepts **`random`** as a selector value — it resolves to one of the LLM-generated styles at runtime, chosen uniformly. `random` is not a style; it has no visual definition and cannot appear as a result in style classification.

---

### 2.1 LLM-Generated Styles

LLM styles are driven by a `system_prompt` injected into the image model call. The full set is defined in [`assets/styles/styles.yml`](../../assets/styles/styles.yml) — adding a style there makes it active automatically.

> **Background note:** no background is described in the style system prompt. The background is applied by the pipeline programmatically after image generation.

#### 3D Animation (`studio_3d`)
> *High-quality 3D animated feature film characters*

Fully 3D rendered with physically-based lighting, multi-point specular highlights, fine strand-level hair detail, and exaggerated cartoon expressions.

- Dramatic CG lighting — blue/cool-toned rim or back light on hair and shoulders
- Large rounded eyes with bright multi-point specular catchlights — clearly larger than realistic
- Volumetric hair in distinct curved clusters with AO and strand-level sheen
- Smooth glossy skin — soft specular on forehead and cheekbones
- Exaggerated 1.5:1 head-to-body ratio
- Rich tonal range: skin 5+ tones (base → shadow → AO crease → highlight → specular); hair 4+ tones
- Exaggerated expression — emotion amplified, reads from across the room

---

#### Korean Cartoon (`korean`)
> *2D digital illustration / light anime character design*

2D digital Korean-style illustration with anime influence, no silhouette outline, semi-realistic proportions, and full highlight-plus-shadow rendering.

- No outline on the silhouette — shapes defined by adjacent flat color areas
- Semi-realistic proportions — slim elongated face, almond-shaped eyes moderately large
- Fine details — individual eyelashes, layered overlapping hair strand shapes
- 3–4 tones per area: skin (base + shadow + 1–2 highlights); hair (base + tones + specular strip); eyes (base + 2 highlight dots)
- Pale or light-toned skin — faint delicate complexion
- Shiny glossy hair with specular strip; shiny wet-look eyes with bright catchlights
- Exaggerated expression — wide eyes, raised brows, open smile

---

#### Photo-Realistic (`photorealistic`)
> *Portrait photography / photorealistic rendering*

Full photographic realism — natural skin texture, accurate lighting with subsurface scattering, anatomically correct proportions, shallow depth of field.

- Natural skin texture with visible pores and subtle imperfections
- Physically accurate lighting — single-point catchlights, subsurface scattering
- Anatomically correct facial proportions
- Shallow depth of field — sharp focus on eyes, soft bokeh on background

---

#### Line Art Sticker (`lineart`)
> *Sticker pack illustration / web avatar icon*

Simple 2D web-illustration with outline strokes, simplified friendly proportions, flat fills with no highlights, and large-scale features only.

- Outline strokes present on silhouette and all facial features
- Large-scale features only — no eyelashes, no hair strands, no skin texture
- Max 3 flat tones per area (hair / clothing item / skin) — no highlights anywhere
- Simplified round friendly face proportions — not semi-realistic
- Rich multi-color palette (8+ distinct hues)
- Natural expression — face near resting state

---

#### 3D Clay (`clay`)
> *Commercial 3D plastic-clay character pack*

Smooth 3D render with a matte clay/plastic finish, simplified large-scale features, no fine detail, warm diffuse lighting, and understated expressions.

- Prominent warm pink/rosy blush circles on both cheeks
- Matte surface — zero specular highlights anywhere
- 2–3 flat tones per area (base + at most 1 soft shadow) — no highlights
- Warm flat diffuse lighting — no rim light, no dramatic shadows
- Hair as a simple smooth rounded solid mass — single tone, no strand detail
- Realistic head-to-body proportions
- Large-scale features only — no eyelashes, no skin pores
- Understated expression — face near rest, emotion soft and minimal

---

### 2.2 Programmatic Styles

Programmatic styles are generated entirely in code using component libraries (DiceBear or equivalent). They are **deterministic** — the same persona name always produces the same avatar. Expression is controlled by selecting specific facial component variants, not by prompting a model.

> **Background note:** as with LLM styles, no background is embedded in the avatar SVG. The background circle is composited programmatically after generation.

#### Toon Head (`toon-head`)
> *DiceBear @dicebear/toon-head — CC BY 4.0*

Friendly cartoon head with large round eyes, smooth shapes, and clear color fills. Good general-purpose avatar for professional and casual contexts.

#### Avataaars (`avataaars`)
> *DiceBear @dicebear/avataaars — CC BY 4.0*

Human-like cartoon avatar with customizable hair, clothing, skin tone, and facial features. The most expressive programmatic style for human personas.

#### Micah (`micah`)
> *DiceBear @dicebear/micah — CC BY 4.0*

Minimal geometric illustration style. Flat, modern, icon-like. Supports a broad range of skin tones and hair styles.

#### Opeeps (`opeeps`)
> *@opeepsfun/avatar-illustration-system*

Bold, colourful character illustrations. More artistic than the DiceBear styles; does not support seed-based determinism.

#### Bottts (`bottts`) — Robot avatars
> *DiceBear @dicebear/bottts — CC BY 4.0*

Robot / machine avatars. No human phenotype features (skin tone, hair, etc. are irrelevant). Lowest feature coverage for human persona expression — recommended only when a non-human character is intentional.

---

### 2.3 Style Comparison Matrix

| | **studio_3d** | **korean** | **photorealistic** | **lineart** | **clay** | **toon-head** | **avataaars** | **micah** | **opeeps** | **bottts** |
|---|---|---|---|---|---|---|---|---|---|---|
| **family** | LLM | LLM | LLM | LLM | LLM | Programmatic | Programmatic | Programmatic | Programmatic | Programmatic |
| **output** | PNG | PNG | PNG | PNG | PNG | SVG | SVG | SVG | SVG | SVG |
| **expression control** | prompt | prompt | prompt | prompt | prompt | components | components | components | components | components |
| **deterministic** | no | no | no | no | no | yes | yes | yes | no | yes |
| **human phenotype** | full | full | full | full | full | partial | partial | partial | partial | none |
| **finish** | glossy PBR | shiny | photographic | flat/matte | matte | flat | flat | flat | flat | flat |
| **detail level** | fine (strands, AO) | fine (lashes, strands) | full photographic | large-scale only | large-scale only | medium | medium | minimal | medium | minimal |
| **expression intensity** | exaggerated | exaggerated | natural | natural/resting | understated | component-dependent | component-dependent | component-dependent | component-dependent | limited |
| **proportions** | 1.5:1 head ratio | semi-realistic | anatomically correct | simplified/round | realistic | fixed by library | fixed by library | fixed by library | fixed by library | N/A |
| **outline** | none (3D volume) | none (color only) | none (photography) | silhouette + features | none (3D volume) | varies | varies | minimal | varies | varies |

> **Key confusion pairs (LLM styles):**
> - `lineart` vs `korean` — lineart has silhouette outlines + no highlights + natural expression; korean has no outline + shiny hair/eyes + exaggerated expression
> - `clay` vs `studio_3d` — clay is matte + simple + understated; studio_3d is glossy + fine detail + exaggerated expression

---

## 3. Phenotype

Phenotype is the set of **visible physical characteristics** that define what the avatar looks like as a person. These fields are randomized uniformly during demographics generation with no population-ratio bias — the goal is visual variety across generated personas, not demographic modelling.

Phenotype applies fully to **LLM-generated styles**. Programmatic styles derive appearance from the persona name seed and only consume a subset of phenotype fields (primarily `bg_color`).

### 3.1 Skin

| Field | Description |
|---|---|
| **SKIN_TONE** | Overall skin complexion (e.g. light, medium, dark, deep) |

### 3.2 Hair

| Field | Description |
|---|---|
| **HAIR_TYPE** | Texture and curl pattern (e.g. straight, wavy, curly, coily) |
| **HAIR_COLOR** | Natural or stylized color (e.g. black, auburn, blonde, silver) |

Hair **style** (cut, length, arrangement) is determined separately during feature selection (Presentation), not in phenotype.

### 3.3 Eyes

| Field | Description |
|---|---|
| **EYE_SHAPE** | Geometric shape of the eye opening (e.g. almond, round, hooded, upturned) |
| **EYE_COLOR** | Iris color (e.g. brown, hazel, blue, green, grey) |

### 3.4 Brows

| Field | Description |
|---|---|
| **BROWS_STYLE** | Thickness, arch, and definition (e.g. straight thick, arched thin, bushy) |
| **BROWS_COLOR** | Color — usually matched to hair color but may differ |

### 3.5 Facial Structure

| Field | Description |
|---|---|
| **NOSE_SHAPE** | Bridge width and tip shape (e.g. narrow straight, wide rounded, button) |
| **CHIN_SHAPE** | Chin form (e.g. pointed, rounded, square, cleft) |
| **CHEEKS_SHAPE** | Cheekbone prominence and fullness (e.g. high pronounced, soft rounded, flat) |

### 3.6 Diversity Principle

One rule applies to all phenotype generation:

> **Absolute diversity neutrality** — no phenotype trait is stereotypically associated with any demographic, role, nationality, or personality trait. All picks are statistically uniform across available options.

---

## 4. Expressions

An expression is a distinct **emotional state** rendered on the avatar's face. Avatars are generated in a full set of expressions so the product can select the appropriate one at display time.

Every expression carries a subtle baseline warmth — a faint cheek lift and soft lip set — that prevents the face from reading as cold or blank even in neutral or negative states.

### 4.1 Expression Set

| Expression | Core signal | Mouth | Eyes | Brows | Cheek wrinkles | Forehead wrinkles | Eye wrinkles |
|---|---|---|---|---|---|---|---|
| **Neutral** | Resting, composed | Lightly closed, no tension | Open, soft gaze | Level, relaxed | None | None | None |
| **Happiness** | Genuine Duchenne smile | Corners pulled up and out, upper teeth visible | Narrowed from below by lifted cheeks, bright | Slightly raised, relaxed | Strong bunching under eyes, deep nasolabial folds | None | Crow's feet at outer corners |
| **Surprise** | Open, unguarded | Jaw dropped, mouth open (oval), no tension | Wide open, whites visible above iris | Both fully raised, high arch | Minimal | Horizontal lines across forehead | None (lids stretched open) |
| **Anger** | Focused aggression | Pressed firmly together, thinned and compressed | Narrowed, lids tight, fixed stare | Pulled hard down and together, deep V-furrow | Jaw set, masseter visible | Deep vertical furrow between brows | Lower lid tension |
| **Sadness** | Heavy stillness | Corners gently downward, chin slightly puckered | Heavy drooping lids, downcast gaze | Inner corners raised obliquely, faint overall furrow | Minimal, slight nasolabial depth | Faint inner-brow crease | Slight lower lid sag |
| **Contempt** | Unilateral superiority | One side only: corner slightly lifted with a dimple; opposite flat | Slightly narrowed, asymmetric gaze | Asymmetric — one slightly raised, opposite flat | Single dimple on active side only | None | Minimal, one-sided at most |

### 4.2 Style × Expression

Expression rendering intensity varies by style:

| Style | Expression register |
|---|---|
| `studio_3d` | Exaggerated — amplified, reads from a distance |
| `korean` | Exaggerated — wide eyes, raised brows, open smile |
| `photorealistic` | Natural — anatomically plausible |
| `lineart` | Natural / resting — near rest state |
| `clay` | Understated — soft and minimal |
| `toon-head` | Component-limited; basic happy/sad/angry variants available |
| `avataaars` | Component-limited; widest programmatic expression range |
| `micah` | Component-limited; minimal expression differentiation |
| `opeeps` | Component-limited; expression support varies by illustration |
| `bottts` | Very limited — robot components have minimal emotion signal |

The canonical expression definitions are the single source of truth in [`assets/expressions/expressions.yml`](../../assets/expressions/expressions.yml).

---

## 5. Attire

> **Status: Secondary Priority — not gating in current phase**

Attire covers the avatar's clothing, accessories, and overall presentation style. In the current phase the image model selects clothing appropriate to the persona's CV and style; no explicit attire attributes are defined or verified.

Attire is intentionally excluded from the acceptance gate for now — enforcing clothing fidelity would require a dedicated asset catalog (per style × clothing category × accessory), which is out of scope at this stage. The model's output is accepted as-is on this dimension.

A dedicated Attire system is planned for a future phase:
- Explicit clothing categories and options
- Accessory inventory (glasses, jewellery, headwear, etc.)
- Cultural and professional attire presets
- User-controllable overrides

---

## 6. Acceptance Gate

The acceptance gate defines the quality criteria an avatar output is scored against. Each criterion produces a score included in the output metadata; what callers do with failing scores (retry, surface warning, reject) is their responsibility.

### 6.1 Identity Consistency

All expression variants of an avatar must depict **the same person** as the neutral portrait.

- Skin tone, hair color, eye color, and facial structure must be visually consistent across all expressions
- The style (finish, tonal range, detail level) must be consistent across expressions

### 6.2 Phenotype Fidelity

Phenotype attributes are provided as generation inputs. Their fidelity in the output is gated as follows:

| Attribute | Gate | Notes |
|---|---|---|
| **SKIN_TONE** | Mandatory | Observable; significant visual impact |
| **HAIR_COLOR** | Mandatory | Observable |
| **HAIR_TYPE** | Best effort | Texture compliance varies by model and style |
| **EYE_COLOR** | Best effort | Hard to verify reliably at typical output sizes |
| **EYE_SHAPE** | Best effort | Model interpretation is loose |
| **BROWS_STYLE** | Best effort | Subtle; model compliance unreliable |
| **BROWS_COLOR** | Best effort | Usually inferred from hair color by the model |
| **NOSE_SHAPE** | Best effort | Hard to verify and control precisely |
| **CHIN_SHAPE** | Best effort | Hard to verify and control precisely |
| **CHEEKS_SHAPE** | Best effort | Hard to verify and control precisely |


### 6.3 Expression Clarity

The target expression must be **recognisable** to a viewer unfamiliar with the generation process.

- The primary facial signal must be present and legible (e.g. lifted cheeks for happiness, V-furrow for anger)
- The expression must not be confused with a different expression in the set
- Subtle expressions (contempt, sadness) are held to a lower intensity bar than primary emotions (happiness, anger)

### 6.4 Style Fidelity

The image must match the selected style's visual contract.

- Finish, detail level, proportions, and expression intensity must fall within the style's defined range (see §2.3 matrix)
- No backgrounds should be present in the raw avatar image — background is applied programmatically

### 6.5 Technical Quality

- No visible generation artefacts (blurring, malformed features, double-face, floating limbs)
- Face must be front-facing or slight ¾ turn (≤ 15°), centred and complete in the frame
- Bust-up composition: head, shoulders, and upper chest visible
