# Prompt-Generation Learning Scripts

Learning scripts measure and improve pipeline quality through iterative benchmarking and LLM-driven fixes.

## Folder structure

```
scripts/learn/          — learning scripts + shared libraries
scripts/examples/       — example dataset management
scripts/              — infrastructure only (install, run, test, stop)
logs/learn/           — experiment logs (.ljson, never deleted, untracked)
reports/              — benchmark JSON outputs (untracked)
```

## Three pipelines, three scripts

| Script | Pipeline | Renders via | Scores |
|---|---|---|---|
| `learn_create.py` | Persona → avatar | `image_gen` | persona + style + SBS |
| `learn_restyle.py` | Avatar → new style | `ipadapter_faceid` | style + identity (SBS) |
| `learn_reexpress.py` | Avatar → new expression | `ipadapter_faceid` | expression + identity (SBS) |

## Common CLI signature

All three scripts share the same flags:

```
--range A B               inclusive index range into sorted example list
--samples X               random sample count (mutually exclusive with --range)
--workers N               parallel render workers (default: 3)
--stop-on-plateau         stop when score delta < 1% for 2 consecutive iterations
--no-stop-on-plateau      disable plateau guard
--max-iterations N        maximum number of learning iterations (if platue not reached or disabled)
--optimize OPT            rendering optimisation: quality | normal | fast  
--improve-threshold F     min score delta (0.0–1.0) between iterations to be
                          considered meaningful progress; below this triggers
                          the plateau exit-ramp
--component-threshold S   min score (0.0–1.0) for each individual score component
--compound-threshold S    min score (0.0–1.0) for compound/aggregate scores
--gateway URL             LLM gateway base URL
--log-dir DIR             experiment log directory
--from-source PATH        source file, relative to each example's folder
```

### parameter defaults per script

| Parameter | Script | Default | Notes |
|---|---|---| --- |
|`--samples`| Any | Entire set | prompt confiramtion if samples > 100 |
|`--workers`| Any | 3 | |
|`--max-iterations`| Any | 2 | | 
|`--stop-on-plateau`| Any | true | |
|`--optimize` | Any | `normal` | |
|`--improve-threshold` | Any | `0.03` | 3% delta minimum |
|`--component-threshold` | Any | `0.75` | |
|`--compound-threshold` | Any | `0.90` | |
|`--gateway`| Any | `localhost:4096` ||
|`--log-dir`| Any | `logs/learn/` ||
|`--from-source`| `learn_create.py` | `persona.yml` | Persona YAML used as generation input |
| | `learn_restyle.py`[^source_img] | `images/photorealistic.png` | Must resolve to an image |
| | `learn_reexpress.py`[^source_img] | `images/photorealistic.png` | Must resolve to an image |

> All scores are in the range 0.0–1.0. Threshold flags use the same scale (e.g. `0.75`, not `75`).

**Example — use the real downloaded portrait as the IPAdapter identity source:**

```bash
python scripts/learn/learn_create.py    --samples 20 --from-source persona.yml
python scripts/learn/learn_reexpress.py --samples 32 --max-iterations 6 --from-source images/best.jpg
python scripts/learn/learn_restyle.py   --samples 20 --from-source images/best.jpg
```

## Iterative Sampling Strategy


```mermaid
flowchart TD

    START(("<b>Start:</b><br/>CLI command")):::ss

    subgraph RENDER_BLK ["<b>Render Iteration</b> (i)"]
        PROMPT[\Generate Prompt\]:::render
        RENDER(["Render N samples"]):::render
        SCORE(["Score the N images"]):::render
        LOG_RESULTS(["Log the results"]):::render
        PROMPT ==> RENDER ==> SCORE ==> LOG_RESULTS
    end

    subgraph ITER_BLK ["<b>Next Iteration?</b>"]
        IS_MAX_ITER{"i ≥ max<br/>iterations?"}:::iter
        IS_BELOW_THRESHOLD{"improvement <<br/> improve_threshold"}:::iter
        IS_PLATEAU{"improvement > 0<br/><b>and</b><br/>--stop_on_plateau"}:::iter
        INCREMENT(["<b>Increment N samples</b><br/><i>N = min(max_samples, N×2)</i>"]):::iter
    end

    REASON[["<b>LLM-reason:</b><br/>Improve Prompt-Gen"]]:::llm
    STOP_PLATEAU(["<b>Stop:</b><br/>Plateau Reached"]):::stop
    STOP_MAX_ITERATIONS(["<b>Stop:</b><br/>Max Iterations Reached"]):::stop
    FINAL[["<b>LLM-select:</b><br/>Final Prompt-Gen"]]:::llm
    STOP(("<b>End</b><br/>User: commit?")):::ss

    START --> |"i=0, N=samples"| PROMPT
    RENDER_BLK --> IS_MAX_ITER
    IS_MAX_ITER --> |Yes| STOP_MAX_ITERATIONS --> FINAL
    IS_MAX_ITER --> |No| IS_BELOW_THRESHOLD
    IS_BELOW_THRESHOLD --> |No| INCREMENT --> REASON
    IS_BELOW_THRESHOLD --> |"Yes (regression)"| IS_PLATEAU
    IS_PLATEAU --> |"Yes (plateau)"| STOP_PLATEAU --> FINAL
    IS_PLATEAU --> |No| REASON
    REASON --> |"i = i+1"| RENDER_BLK
    FINAL --> STOP

    %% Class Definitions - styles
    classDef ss fill:#F5F3FF,stroke:#534AB7,color:#3C3489,stroke-width:2px;
    classDef render fill:#E6F1FB,stroke:#185FA5,color:#0C447C,stroke-width:2px;
    classDef iter fill:#FAEEDA,stroke:#BA7517,color:#633806,stroke-width:1px;
    classDef stop fill:#F3DBD9,stroke:#993C1D,color:#712B13,stroke-width:2px;
    classDef llm fill:#EAF3DE,stroke:#3B6D11,color:#27500A,stroke-width:2px;

    style RENDER_BLK fill:#F0F7FF,stroke:#185FA5,color:#0C447C,stroke-width:2px;
    style ITER_BLK   fill:#F6F5D0,stroke:#86764F,color:#3C3C26,stroke-width:2px;
```

**Step 0**: Choose N samples (`--samples`, `--range` or default); i=0

**Render Iteration (i)**: Use Prompt-gen to: `Prompt`, `Render`, `Score`, `Log` the N samples.

**Iteration Decision tree**:
(1) Good improvement → grow (up to double) N samples → reason → reiterate
(2) Negative improvement → keep N samples → reason → reiterate
(3) Tiny improvement → Plateau exit-ramp, or:→ keep N samples → reason → reiterate

Stop conditions:
1. reached max_n_iterations (normal)
2. reached plateau (and `--stop_on_plateau` is `true`)

**Step N** (N ≥ 1): Keep ALL examples from step N-1 (regression testing) + add up to N fresh examples.
Render with modified pipeline. Score and compare.

### Reason - LLM Prompt-Gen Improvement

> **Improve LLM Reason**: explores new solutions — higher temperature, generative. The LLM proposes changes to the Prompt-Generator given the current failure patterns.
> **Final LLM Selection**: selects the best solution from those already produced — lower temperature, deterministic. Does not generate new candidates; consolidates into the final Prompt-Generator.

The Portrait-Prompt-Generators are script with known inputs and outputs (see below script)
The Reasoning-LLM task is to create the $\color{#e65100}{\text{Prompt-Generator}}$ code.

### Create Portrait Flow

Create Portrait Flow is based on $\color{#01579b}{\textsf{style}}$, $\color{#01579b}{\textsf{expression}}$ and $\color{#01579b}{\textsf{persona}}$ literals and renders via LLM-Gateway's $\color{#440B72}{\textsf{OllamaImageGenLLM}}$

The scores it is trying to maximize [are](../pipeline/create_from_persona.md#4-validation):

| Scorer | Signal | Weight | Role in this flow |
|---|---|---|---|
| Persona Categorizer | Phenotype fidelity | 🌕🌕🌕 |Verifies the output reflects the persona attributes that were used to generate it |
| Style Classifier | Style fidelity | 🌕🌗🌚| Verifies the output matches the requested `style_id` |
| Expression Classifier | Expression accuracy | 🌕🌚🌚| Verifies the rendered expression matches the requested `expression_id` |

```mermaid
flowchart LR

    subgraph INPUT ["<b>Inputs</b>"]
        PERSONA_FILE[(persona.yml)]:::input
        STYLE_FILE[(style.yml)]:::input
        STYLE_ID>style_id]:::input
        EXPRESS_FILE[(expression.yml)]:::input
        EXPRESS_ID>expression_id]:::input
    end

    subgraph PROPMT_GEN["<b>Portrait Creation - Prompt Generator</b>"]
        STYLE["Style Attribute(s)"]:::gen
        EXPRESS["Expression Attribute(s)"]:::gen
        PERSONA["Person Attribute(s)"]:::gen
        STYLE_ID .-> STYLE
        STYLE_FILE .-> STYLE
        EXPRESS_ID .-> EXPRESS
        EXPRESS_FILE .-> EXPRESS
        PERSONA_FILE .-> PERSONA
    end

    subgraph OUTPUT ["<b>Outputs</b>"]
        direction TD
        PERSONA .-> PROMPT_OUT[/prompt/]:::output
        SIZE_OUT>width, height]:::output
        STEPS_OUT>num_inference_steps]:::output
        TEMP_OUT>temperature]:::output
        TOKENS_OUT>max_tokens]:::output
    end

    IMAGE_GEN[["LLM Gateway<br/>OllamaImageGen"]]
    IMAGE[("<b>final.png")]:::final

    subgraph SCORING["<b>Scoring</b>"]
        direction TD
        PERSONA_CLASS([Persona Classifier]):::score
        EXPRESS_CLASS([Expression Classifier]):::score
        STYLE_CLASS([Style Classifier]):::score
    end

    INPUT --> PROPMT_GEN --> OUTPUT --> IMAGE_GEN --> IMAGE --> SCORING
    IMAGE .-> PERSONA_CLASS

    %% Class Definitions - styles
    classDef input fill:#e1f5fe,stroke:#01579b,stroke-width:2px,color:#01579b
    style INPUT fill:#DBF4FA,stroke:#7EAED3,color:#01579b,stroke-width:2px
    classDef gen fill:#fff3e0,stroke:#e65100,stroke-width:1px,color:#e65100,stroke-dasharray: 5 5
    style PROPMT_GEN fill:#fff8e1,stroke:#ffc107,stroke-width:2px,color:#e65100
    classDef output fill:#f1f8e9,stroke:#33691e,stroke-width:2px,color:#33691e
    style OUTPUT fill:#f9fbe7,stroke:#8bc34a,stroke-width:2px,color:#33691e
    classDef final fill:#F3DDFA,stroke:#330651,stroke-width:2px,color:#2C0849
    style SCORING fill:#F9D6F0,stroke:#B14B81,stroke-width:2px,color:#B53F80
    classDef score fill:#F6C3E2,stroke:#8C1856,stroke-width:2px,color:#6B0C40

```

### ReStyle / ReExpress Portrait Flows

ReStyle / ReExpress Portrait Flows are based on $\color{#01579b}{\textsf{reference image(s)}}$, $\color{#01579b}{\textsf{style}}$ and $\color{#01579b}{\textsf{expression}}$ literals and renders via LLM-Gateway's $\color{#440B72}{\textsf{DiffusionServerIPAdapterLLM}}$

The scores it is trying to maximize are [restyle](../pipeline/create_from_persona.md#4-validation) / [ReExpress](../pipeline/expressions_from_image.md#4-validation):

| Scorer | Signal | **ReStyle** Weights | **ReExpress** Weights |
|---|---|---|---|
| Side-by-Side Comparison (`identity_score`) | Likeness to source images | 🌕🌕🌕 primary | 🌕🌕🌕 primary |
| Final product (`quality_score`) | Render quality | 🌕🌕🌚 important| 🌕🌕🌚 important|
| Style Classifier | Target style fidelity | 🌕🌕🌗 target| 🌕🌚🌚 secondary|
| Expression Classifier | Expression accuracy | 🌕🌚🌚 secondary| 🌕🌕🌗 target|
| Persona Categorizer | Attribute match vs extracted spec | 🌗🌚🌚 tiebreaker | 🌗🌚🌚 tiebreaker |

```mermaid
flowchart LR

    subgraph INPUT ["<b>Inputs</b>"]
        REFERENCE_FILES[("reference(s).png")]:::input
        STYLE_FILE[(style.yml)]:::input
        STYLE_ID>style_id]:::input
        EXPRESS_FILE[(expression.yml)]:::input
        EXPRESS_ID>expression_id]:::input
    end

    subgraph PROPMT_RESTYLE["<b>Portrait Restyle - Prompt Generator</b>"]
        STYLE["Style Attribute(s)"]:::gen
        STYLE_ID .-> STYLE
        STYLE_FILE .-> STYLE
    end

    subgraph PROPMT_REEXPRESS["<b>Portrait ReExpress - Prompt Generator</b>"]
        EXPRESS["Expression Attribute(s)"]:::gen
        EXPRESS_ID .-> EXPRESS
        EXPRESS_FILE .-> EXPRESS
    end

    subgraph OUTPUT ["<b>Outputs</b>"]
        direction TD
        REFERENCE_FILES .-> OUTPUT_FILES[("reference_image(s)")]:::output
        PROMPT_OUT[/prompt/]:::output
        NEG_PROMPT_OUT[/negative_prompt/]:::output
        SIZE_OUT>width, height]:::output
        STEPS_OUT>num_inference_steps]:::output
        ADPT_SCALE>"cfg_scale,<br/>ip_adapter_scale"]:::output
        TEMP_OUT>"lora,<br/>lora_weight"]:::output
    end

    IMAGE_GEN[["LLM Gateway<br/>DiffusionServerIPAdapter"]]
    IMAGE[("<b>final.png")]:::final

    subgraph SCORING["<b>Scoring</b>"]
        direction TD
        IDENTITY_CLASS([Identity <br/> The Same Person?]):::score
        QUALITY_CLASS([Image Quality]):::score
        STYLE_CLASS([Style Classifier]):::score
        EXPRESS_CLASS([Expression Classifier]):::score
    end

    INPUT --> PROPMT_RESTYLE --> OUTPUT --> IMAGE_GEN --> IMAGE --> SCORING
    INPUT --> PROPMT_REEXPRESS --> OUTPUT
    REFERENCE_FILES .-> IDENTITY_CLASS

    %% Class Definitions - styles
    classDef input fill:#e1f5fe,stroke:#01579b,stroke-width:2px,color:#01579b
    style INPUT fill:#DBF4FA,stroke:#7EAED3,color:#01579b,stroke-width:2px
    classDef gen fill:#fff3e0,stroke:#e65100,stroke-width:1px,color:#e65100,stroke-dasharray: 5 5
    style PROPMT_RESTYLE fill:#fff8e1,stroke:#ffc107,stroke-width:2px,color:#e65100
    style PROPMT_REEXPRESS fill:#fff8e1,stroke:#ffc107,stroke-width:2px,color:#e65100
    classDef output fill:#f1f8e9,stroke:#33691e,stroke-width:2px,color:#33691e
    style OUTPUT fill:#f9fbe7,stroke:#8bc34a,stroke-width:2px,color:#33691e
    classDef final fill:#F3DDFA,stroke:#330651,stroke-width:2px,color:#2C0849
    style SCORING fill:#F9D6F0,stroke:#B14B81,stroke-width:2px,color:#B53F80
    classDef score fill:#F6C3E2,stroke:#8C1856,stroke-width:2px,color:#6B0C40
```


## Experiment logs (.ljson)

Each run writes one JSON object per line to `logs/learn/<script>_<timestamp>.ljson`:

```json
{"ts": "...", "type": "config", "script": "learn_create", "samples": 20}
{"ts": "...", "type": "render", "iteration": 0, "example": "adele", "style": "photorealistic"}
{"ts": "...", "type": "score", "iteration": 0, "example": "adele", "persona_score": 0.85}
{"ts": "...", "type": "fix", "iteration": 0, "description": "phenotype.skin_tone: +2 values"}
{"ts": "...", "type": "summary", "iteration": 0, "avg_persona": 0.82}
{"ts": "...", "type": "done", "reason": "plateau"}
```

Logs are append-only and never deleted. Use them for debugging and historical tracking.

## When to run each script

| Situation | Script |
|---|---|
| Persona accuracy regressed / improving prompts | `learn_create.py` |
| Styles look wrong after model update | `learn_restyle.py` |
| Expressions not rendering correctly | `learn_reexpress.py` |

## Quick start

```bash
# Quick test (5 examples, 1 iteration, fast mode)
python scripts/learn/learn_create.py --samples 5 --max-iterations 1 --optimize fast
python scripts/learn/learn_restyle.py --samples 5 --max-iterations 1 --optimize fast
python scripts/learn/learn_reexpress.py --samples 5 --max-iterations 1 --optimize fast

# Standard improvement run
python scripts/learn/learn_create.py --samples 30 --style photorealistic
python scripts/learn/learn_restyle.py --samples 32 --max-iterations 6 --optimize quality --style photorealistic
python scripts/learn/learn_reexpress.py --range 0 127 --style studio_3d --from_source=images/photorealistic.png

```

[^source_img]: > **Notes**: 
**Format conversion**: `learn_restyle.py` and `learn_reexpress.py` pass the source image directly to
`ipadapter_faceid`, which requires PNG bytes. If `--from-source` resolves to a non-PNG file (e.g.
`images/best.jpg`), the image is decoded and re-encoded as PNG in memory before being sent — no file
is written to disk.
**Exclusion rule**: if `<example_dir>/<from-source>` does not exist, that example is silently dropped
from the candidate pool before sampling. This keeps the effective pool consistent with the actual
available data, rather than producing runtime errors mid-run.