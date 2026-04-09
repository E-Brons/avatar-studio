# Pipeline: Restyle Avatar from Image

**Input**: 1–N reference images of an existing avatar + target style + target expression
**Output**: Single best-candidate PNG — same identity, new style and expression

---

## 1. Input

| Parameter | Type | Description |
|---|---|---|
| `images_b64` | `list[str]` | 1–N reference images in base64; any style or origin |
| `style_id` | `str` | Target style — any `style_id` from `assets/styles/styles.yml` |
| `expression_id` | `str` | Target expression — any expression name from `assets/expressions/expressions.yml` |
| `candidates` | `int` (default 4) | Number of candidates to generate and score |
| `width` | `int` (default 512) | Output image width in pixels |
| `height` | `int` (default 512) | Output image height in pixels |

Multiple reference images are supported natively. When N > 1, attribute extraction and identity scoring run per image, then reconcile.

---

## 2. Output

A single PNG — the highest-scoring candidate — with embedded metadata. For the metadata schema see [common/structures.md](../common/structures.md#png-metadata).

---

## 3. Pipeline

```mermaid
flowchart TD
    INPUT[/"images_b64 (1–N)\nstyle_id, expression_id\ncandidates=4"/]:::kv --> EXTRACT

    subgraph extract["1 · Extract Attributes"]
        style extract fill:#EBC138,color:#333,stroke:#463A05
        INSPECT["image_inspector\n(per image)"]:::llm
        CATEGORIZE["categorize_avatar_image\n(per image)"]:::llm
        RECONCILE["reconcile attributes\nacross N images"]:::op
        INSPECT --> CATEGORIZE --> RECONCILE
    end

    RECONCILE --> SPEC[("extracted\npersona")]:::inter

    subgraph build["2 · Build Prompt"]
        style build fill:#D8DFF1,color:#333,stroke:#0A066F
        SANITIZE["sanitize_persona(extracted)"]:::op
        PROMPT["build_prompt\n(reference_mode=person_photo)"]:::op
        SANITIZE --> PROMPT
    end

    SPEC --> SANITIZE

    subgraph gen["3 · Generate N Candidates"]
        style gen fill:#ECC8CD,color:#333,stroke:#9B053C
        GEN["ipadapter_faceid\n(prompt, images_b64, seed=varied)"]:::llm
        CANDS[("candidates\n1…N")]:::inter
        GEN -->|N calls| CANDS
    end

    PROMPT --> GEN

    subgraph score["4 · Score Each Candidate"]
        style score fill:#CDEF8D,color:#333,stroke:#034A04
        SBS["compare_side_by_side\n(candidate vs source images)\n→ identity_score [primary]"]:::llm
        ATTR["categorize_avatar_image\n(candidate vs extracted spec)\n→ persona_score [tiebreaker]"]:::llm
    end

    CANDS --> SBS
    CANDS --> ATTR

    SELECT["5 · Select Best\nidentity_score primary\npersona_score tiebreaker"]:::op
    SBS --> SELECT
    ATTR --> SELECT

    OUTPUT[/"best candidate PNG\n+ metadata"/]:::kv
    SELECT --> OUTPUT

    classDef kv fill:#e6fffb,stroke:#006d77,stroke-width:2px,font-family:monospace;
    classDef inter fill:#FFF,color:#333,stroke:#111,stroke-width:2px,font-family:monospace;
    classDef llm fill:#F5C4E1,stroke:#A92656,stroke-width:2px;
    classDef op fill:#D8DFF1,stroke:#0A066F,stroke-width:2px;
```

### Step 1 — Extract Attributes

- Call `GatewayClient.image_inspector()` on each reference image
- Run `categorize_avatar_image()` to get a structured attributes dict per image (see [Persona Categorizer](../common/validation.md#persona-categorizer))
- Reconcile across N images: most consistent value per attribute wins

### Step 2 — Build Prompt

- `sanitize_persona(extracted)` strips text-heavy and compositing-only fields
- `build_prompt(reference_mode="person_photo")` — the `person_photo` mode instructs the model to anchor on the reference image appearance while applying the target style

### Step 3 — Generate N Candidates

- N calls to `GatewayClient.ipadapter_faceid(prompt, images_b64, seed=varied)`
- All reference images are passed together; IP-Adapter uses them collectively as the identity anchor
- Seeds are varied across calls to produce diverse candidates

### Step 4 — Score Each Candidate

| Signal | Method | Role |
|---|---|---|
| SBS identity | `compare_side_by_side(candidate, source)` | Primary — does the candidate look like the source? |
| Persona attribute match | `categorize_avatar_image(candidate)` vs extracted spec | Tiebreaker |

### Step 5 — Select Best

Rank candidates by `identity_score`; use `persona_score` as tiebreaker. Return the highest-ranked candidate.

---

## 4. Validation

For scorer specifications see [common/validation.md](../common/validation.md).

| Scorer | Signal | Weight |
|---|---|---|
| Side-by-Side Comparison (`identity_score`) | Likeness to source images | ●●●●● primary |
| Side-by-Side Comparison (`quality_score`) | Render quality | ●●●●○ |
| Style Classifier | Target style fidelity | ●●●●○ |
| Persona Categorizer | Attribute match vs extracted spec | ●○○○○ tiebreaker |
| Expression Classifier | Expression accuracy | ●●●○○ |

**Identity consistency is the primary quality gate.** Likeness across the style boundary is the defining success criterion for this flow.
