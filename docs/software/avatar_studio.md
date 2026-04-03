# Avatar Studio — Software Design

> Companion to the design spec: [avatars.md](../product/avatars.md).
> This document defines the **runtime architecture** — API services,
> concurrency, logging, file persistence, and error handling.

## Table of Contents

1. [Overview](#1-overview)
2. [API Services](#2-api-services)
3. [Artifact Dependency Flow](#3-artifact-dependency-flow)
4. [Logging & Observability](#4-logging--observability)
5. [Session File Structure](#5-session-file-structure)
6. [Error Handling](#6-error-handling)
7. [Dev Utilities (Classifiers)](#7-dev-utilities-classifiers)

---

## 1. Overview

Avatar Studio generates avatars through a multi-step pipeline that involves two LLM backends:

| Backend | Purpose | Typical latency |
|---------|---------|-----------------|
| **Text LLM** | Profile generation (Step B) + feature selection (Step C) — picks name, skin tone, hair, clothing, etc. | TBD (needs logging) |
| **Image LLM** | Portrait & expression generation (Steps E, F) — renders PNG images via the LLM Gateway | 10–60 s per image |

The API exposes stateless HTTP endpoints. Each endpoint performs a single, well-scoped operation and returns when done. There is no server-side session state for avatar generation — the caller owns the pipeline orchestration and artifact dependencies.

---

## 2. API Services

### 2.1 Endpoints

#### `GET /api/avatar/config`

Returns avatar studio capabilities and LLM configuration.

**Response:**
```json
{
  "max_concurrent_requests": 2,
  "text_model": "llama3.1:8b",
  "image_model": "stable-diffusion-xl",
  "expression_ids": ["neutral", "happy", "thoughtful", "..."]
}
```

> `max_concurrent_requests` — the maximum number of parallel image-generation
> requests the backend can handle. The caller MUST respect this limit when
> scheduling work.

---

#### `GET /api/ollama/models?ollama_url=...`

Returns available Ollama models, categorized by capability (text vs image).
This is a shared endpoint — not avatar-specific.

**Response:**
```json
{
  "text_models": ["llama3.1:8b", "..."],
  "image_models": ["sd-xl:latest", "..."],
  "default_text_model": "llama3.1:8b",
  "default_image_model": "sd-xl:latest"
}
```

---

#### `POST /api/avatar/rand`

Executes Step A (randomise demographics) + optional Step B (generate
profile when education/experience/traits are empty) + Step C (LLM feature
selection). Returns the full `avatar_persona` dict including the LLM-generated NAME.

**Request:**
```json
{
  "role": "Financial Analyst",
  "education": [],
  "experience": [],
  "traits": [],
  "text_model": "llama3.1:8b",
  "text_model_api_base": null
}
```

> When `education`, `experience`, and `traits` are all empty (or omitted),
> the backend generates them via LLM from the role. This supports the
> multi-candidate flow where the caller provides only a role.

**Response:**
```json
{
  "avatar_persona": { "personal": { "name": "Elena Vasquez", "...": "..." }, "...": "..." },
  "demographics": { "gender": "female", "age": 34, "frame_bg_color": "#4A90D9" },
  "model": "llama3.1:8b",
  "duration_ms": 1200
}
```

---

#### `POST /api/avatar/image`

Generates a single avatar image (portrait, abbreviation, or expression).

**Request:**
```json
{
  "type": "neutral | abbreviation | expression",
  "expression_id": "happy",
  "avatar_persona": { "...": "..." },
  "ollama_url": "http://localhost:11434",
  "ollama_model": "sd-xl:latest",
  "width": 512,
  "height": 512,
  "portrait_base64": null
}
```

- `type: "abbreviation"` — generates the circular initials PNG from `avatar_persona.personal.name`. No LLM call. Requires `avatar_persona`.
- `type: "neutral"` — generates the canonical portrait. Requires `avatar_persona`.
- `type: "expression"` — generates an expression variant. Requires `avatar_persona`, `expression_id`, and `portrait_base64` (the neutral image, used as reference).

**Response:**
```json
{
  "image": "<base64 PNG>",
  "prompt": "...",
  "model": "sd-xl:latest",
  "duration_ms": 25000
}
```

---

#### `GET /api/avatar/expressions`

Returns the list of available expression IDs.

**Response:**
```json
{
  "expressions": ["neutral", "happy", "thoughtful", "stressed", "..."]
}
```

---

### 2.2 Sequence Diagram

```mermaid
sequenceDiagram
    participant C as Caller
    participant BE as Backend
    participant TXT as Text LLM (Gateway)
    participant IMG as Image LLM (Gateway)

    C->>BE: GET /api/avatar/config
    BE-->>C: { max_concurrent_requests: N, ... }

    par up to 4 candidates in parallel
        loop Each candidate
            C->>BE: POST /api/avatar/rand { role }
            BE->>TXT: B: Generate profile (education, experience, traits)
            TXT-->>BE: profile YAML
            BE->>TXT: C: LLM feature selection (per-field)
            TXT-->>BE: features + NAME
            BE-->>C: { avatar_persona, demographics }

            par abbreviation ∥ neutral
                C->>BE: POST /api/avatar/image { type: "abbreviation" }
                BE-->>C: { image: "<abbr_b64>" }
            and
                C->>BE: POST /api/avatar/image { type: "neutral" }
                BE->>IMG: image_gen (prompt + style)
                IMG-->>BE: PNG bytes
                BE-->>C: { image: "<portrait_b64>" }
            end
        end
    end

    Note over C: Caller selects one candidate

    loop Each expression (up to N concurrent)
        C->>BE: POST /api/avatar/image { type: "expression", expression_id }
        BE->>IMG: image_gen (prompt + reference image)
        IMG-->>BE: PNG bytes
        BE-->>C: { image: "<expr_b64>", duration_ms }
    end
```

---

## 3. Artifact Dependency Flow

The pipeline produces five artifact types. The caller uses this dependency
graph to decide what can run, what must wait, and what requires a decision
before proceeding.

```mermaid
flowchart TD
    INPUT["<b>Persona Input</b><br/><i>role only</i>"]
    CANDIDATES["<b>N × rand</b><br/><i>Step A: randomise demographics</i><br/><i>Step B: LLM profile generation</i><br/><i>Step C: LLM feature selection</i><br/><br/>Produces: N avatar_personas"]
    CAND_IMAGES["<b>N × (abbreviation ∥ neutral)</b><br/><i>Abbreviation: code only</i><br/><i>Neutral: Image LLM × max N concurrent</i>"]
    SELECTION{{"<b>Caller Decision</b><br/><i>Pick 1 candidate / Re-run</i>"}}
    APPROVAL{{"<b>Caller Decision</b><br/><i>Proceed / Regenerate / Stop</i>"}}
    EXPR["<b>expressions</b><br/><i>Expression variants</i><br/><i>Image LLM × up to N concurrent</i>"]
    DONE["<b>Done</b>"]

    INPUT --> CANDIDATES
    CANDIDATES --> CAND_IMAGES
    CAND_IMAGES --> SELECTION
    SELECTION -->|Select| APPROVAL
    SELECTION -->|Re-run| CANDIDATES
    APPROVAL -->|Proceed| EXPR
    APPROVAL -->|Regenerate| CANDIDATES
    EXPR --> DONE
    DONE -->|Regenerate| CANDIDATES

    style CANDIDATES fill:#7B61FF,color:#fff,stroke:#5B41DF
    style CAND_IMAGES fill:#27AE60,color:#fff,stroke:#1E8C4E
    style EXPR fill:#E67E22,color:#fff,stroke:#C46A1A
    style SELECTION fill:#F5F0E8,color:#333,stroke:#999
    style APPROVAL fill:#F5F0E8,color:#333,stroke:#999
    style DONE fill:#F5F0E8,color:#333,stroke:#999
```

### Dependency Rules

| Artifact | Depends on | Can run in parallel with |
|----------|-----------|------------------------|
| **rand** (Steps A+B+C) × N | persona input (role) | each other (all N in parallel) |
| **abbreviation** (Step D) × N | rand (needs NAME) | neutral for same candidate |
| **neutral** portrait (Step E) × N | rand (needs avatar_persona) | abbreviation; other candidates (up to N) |
| **candidate selection** | all N candidates complete | — |
| **expressions** (Step F) | candidate selected + neutral portrait available | each other (up to N) |

### Concurrency

The backend publishes `max_concurrent_requests` via `GET /api/avatar/config`.
The caller is responsible for maintaining a request queue and never exceeding N
in-flight image requests. During the expression phase, up to N expressions are
generated concurrently; as one completes, the next is dequeued.

---

## 4. Logging & Observability

Every pipeline step is logged with structured fields. Logs go to stdout
(standard Python logging) and are also written as a `session.log` file inside
each image's folder (see §5).

### Log format

Logs use a timestamped `[Step X] START/DONE` format. The Python logging format
string is `"%(asctime)s.%(msecs)03d %(levelname)s %(message)s"` with
`datefmt="%Y-%m-%d %H:%M:%S"`.

**Example output:**
```
2026-03-25 14:32:01.123 INFO [Step A] START — randomise_person (seed=42)
2026-03-25 14:32:01.145 INFO [Step A] DONE  — gender=male, age=52, skin_tone=#5C3010
2026-03-25 14:32:01.150 INFO [Step B] START — generate_cv (model=ollama/qwen2.5:7b)
2026-03-25 14:32:03.890 INFO [Step B] DONE  — role=CEO, traits=3
2026-03-25 14:32:03.895 INFO [Step C] START — select_features (model=ollama/qwen2.5:7b)
2026-03-25 14:32:12.456 INFO [Step C] DONE  — 12 features selected, persona.yml written
2026-03-25 14:32:12.460 INFO [Step D] START — make_abbreviation (name=Marcus Washington)
2026-03-25 14:32:12.512 INFO [Step D] DONE  — /tmp/.../abbreviation.png
2026-03-25 14:32:12.515 INFO [Step E] START — generate_portrait neutral (model=x/flux2-klein:4b, style=clay)
2026-03-25 14:32:12.516 INFO [Step E] Writing session artifacts to /tmp/.../neutral/
2026-03-25 14:32:45.789 INFO [Step E] DONE  — /tmp/.../neutral/output.png
2026-03-25 14:32:45.800 INFO [Step F] START — generate_expression happy (ref=neutral/output.png)
2026-03-25 14:32:45.801 INFO [Step F] Writing session artifacts to /tmp/.../happy/
2026-03-25 14:33:18.234 INFO [Step F] DONE  — /tmp/.../happy/output.png
2026-03-25 14:33:18.240 INFO [Step G] START — postprocess circle_frame
2026-03-25 14:33:18.345 INFO [Step G] DONE  — /tmp/.../final.png
```

### Dual output

Each image generation writes logs to two destinations simultaneously:
- **Console** (`StreamHandler`) — standard stdout output
- **File** (`FileHandler`) — `session.log` inside the image's folder (e.g., `neutral/session.log`, `happy/session.log`)

### What gets logged

| Event | Log level | Details |
|-------|-----------|---------|
| Step START | INFO | step letter, function name, key parameters |
| Step DONE | INFO | step letter, key output values |
| Session artifacts written | INFO | folder path |
| Image saved to disk | INFO | file path, size bytes |
| Error | ERROR | full exception with traceback |

### Timing

The pipeline records wall-clock time for every step:
- **Profile generation**: text LLM call (Step B)
- **Feature selection**: text LLM call (Step C)
- **Image generation**: image LLM call per image (Steps E, F)
- **Abbreviation**: expected <100ms, no LLM (Step D)

Timing is returned in every response (`duration_ms`) and written to the session log file.

---

## 5. Session File Structure

Every avatar generation run writes artifacts and logs to a local directory
organised by persona name and run timestamp:

```
/tmp/avatar_studio/{persona_name}/{YYYYMMDD_HHMMSS}/
  persona.yml                       ← written by step C (shared for all expressions)
  neutral/
    style.yml
    expression.yml
    style_example_{gender}.png
    prompt.txt
    output.png
    session.log
  happy/
    style.yml
    expression.yml
    style_example_{gender}.png
    reference_person.png             ← step F only (copy of neutral/output.png)
    prompt.txt
    output.png
    session.log
  thinking/
    ...                              ← one subfolder per expression
```

### Files per image folder

| File | Written at | Content |
|------|-----------|---------|
| `persona.yml` | Before calling image model (step C output) | Full `avatar_persona` dict as YAML |
| `style.yml` | Before calling image model | Extracted style entry from `styles.yml` for the selected `style_id` |
| `expression.yml` | Before calling image model | Extracted expression entry from `expressions.yml` for the target expression |
| `style_example_{gender}.png` | Before calling image model | Copy of the style's example image from `assets/styles/` |
| `reference_person.png` | Before step F (expression variants only) | Copy of `neutral/output.png` used as identity anchor |
| `prompt.txt` | Before calling image model | The combined prompt sent to the image model |
| `output.png` | After image model returns | The generated image |
| `session.log` | Throughout the generation | Timestamped `[Step X] START/DONE` log for this image |

### Lifecycle

- A new timestamped folder is created on each generation run — no run ever overwrites another
- Files are written as they are produced (portrait first, then expressions)
- Directories are **not** auto-cleaned — the caller or a cron job removes old sessions

---

## 6. Error Handling

### Per-step error behavior

| Step | On failure | Caller handling |
|------|-----------|-----------------|
| **config** | Returns HTTP error | Caller retries or aborts |
| **rand** (features) | Returns HTTP error | Caller retries or aborts |
| **abbreviation** | Logs warning, may return partial result | Non-blocking — caller continues without abbreviation |
| **neutral** (portrait) | Returns HTTP error | Caller may retry with same `avatar_persona` |
| **expression** (one) | Returns HTTP error for that expression | Caller may retry individually; other expressions unaffected |
| **expression** (all fail) | Each returns HTTP error | Caller may retry all or accept portrait only |

### Retry semantics

- **Retry** re-runs only the failed step with the same `avatar_persona` — no need to regenerate features or portrait
- **Regenerate** means the caller discards all artifacts and starts from scratch (new rand, new persona, new images)
- Abbreviation failure is non-fatal — the caller proceeds without it

### Timeout

- Each image request has a configurable timeout (default: 120s)
- If the LLM Gateway doesn't respond within the timeout, the request returns an error
- The caller handles the timeout and decides whether to retry

### Cancellation

- The caller cancels in-flight requests by aborting the HTTP connection
- The backend has no cancel API — if a gateway call is in progress, it runs to completion server-side but the response is discarded

---

## 7. Dev Utilities (Classifiers)

The `src/avatar_studio/tuning/` package includes utilities for evaluating
and iterating on generated images. These are not part of the production pipeline
— they are used during style development and prompt tuning.

### `classify_style.py`

Answers: **"Which art style is this image?"**

Takes a generated PNG and scores it against the known style IDs (clay, emoji,
lineart, etc.). Returns a ranked list of style IDs with confidence scores, with
the best match first. Used to verify that a generated image actually matches the
intended `style_id`.

### `classify_persona.py`

Answers: **"Do the visual properties of this image match the persona?"**

Takes a generated PNG and an `avatar_persona` dict, then checks each visual
property (hair colour, skin tone, clothing colour, glasses, etc.) against the
persona spec. Returns a scored pass/fail result per property, making it easy to
identify which attributes the image model missed or misrendered.

### `classify_expression.py`

Answers: **"Does the expression in this image match the target?"**

Takes a generated PNG and a target expression ID (e.g., `happy`, `neutral`,
`thinking`). Verifies the facial expression by checking FACS action units
against the expected expression. Returns a pass/fail verdict with per-unit
detail, so prompt failures can be diagnosed precisely.

### `style_tuner.py`

Runs a **generate → classify → report** loop for iterating style prompts.

Given a style ID and a set of test personas, it generates images with the
current style prompt, runs all three classifiers (style, persona, expression),
and writes a structured report. Session artifacts are written to
`/tmp/avatar_studio/style_tuner/{YYYYMMDD_HHMMSS}/{style_id}_{persona_id}/`
following the same folder hierarchy as the main pipeline (§5), including
`persona.yml`, `style.yml`, `expression.yml`, `reference_person.png`,
`prompt.txt`, `output.png`, and `session.log`.
