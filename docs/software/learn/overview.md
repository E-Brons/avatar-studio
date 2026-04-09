# Learning Scripts Overview

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
                          default: entire set — prompts for confirmation if > 100
--workers N               parallel render workers (default: 3)
--stop-on-plateau         stop when score delta < 1% for 2 consecutive iterations (default: on)
--no-stop-on-plateau      disable plateau guard
--max-iterations N        safety cap (default: 2)
--optimize OPT            quality | normal | fast  (default: normal)
--component-threshold N   min score (0–100) for each individual score component (default: 75)
--compound-threshold N    min score (0–100) for compound/aggregate scores (default: 90)
--gateway URL             LLM gateway base URL
--log-dir DIR             experiment log directory (default: logs/learn/)
```

## Iterative sampling strategy

**Step 0**: Choose X samples (random or range). Render. Score. Reason. Apply fixes.

**Step N** (N ≥ 1): Keep ALL examples from step N-1 (regression testing) + add up to X/2 fresh examples not seen in previous iterations. Render with modified pipeline. Score and compare.

**Why keep all previous examples?** Retaining the full prior set prevents regressions — a fix that improves new examples but breaks old ones is detected immediately. Each step is progressively more robust: step 0 has X examples, step 1 has up to 3X/2, step 2 up to 2X, and so on.

**Plateau**: Stop early if score improves by less than 1% for 2 consecutive iterations.

**Full set**: Only use when `--samples` is omitted and user confirms. Reserved for nightly/CI runs.

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
| Nightly full-set audit | All three with `--optimize fast` |

## Quick start

```bash
# Quick test (5 examples, 1 iteration, fast mode)
python scripts/learn/learn_create.py --samples 5 --max-iterations 1 --optimize fast
python scripts/learn/learn_restyle.py --samples 5 --max-iterations 1 --optimize fast
python scripts/learn/learn_reexpress.py --samples 5 --max-iterations 1 --optimize fast

# Standard improvement run
python scripts/learn/learn_create.py --samples 30 --style photorealistic

# Range run
python scripts/learn/learn_create.py --range 0 49 --max-iterations 5
```
