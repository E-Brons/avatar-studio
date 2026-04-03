---
name: run-tuner
description: >
  Run avatar studio tuner CLI commands (expression tuner, style tuner, expression autotuner).
  Use this skill whenever the user asks to run a tuner, tune expressions or styles, generate
  tuning images, or run avatar-expression-tuner / avatar-style-tuner / avatar-expression-autotuner.
  Also use when the user says things like "tune happiness", "run the tuner", "start a tuning pass",
  or "generate expressions for all styles/genders".
---

# Avatar Studio — Run Tuner

## Critical: install venv

```bash
source scripts/install.sh
```

## Available tuners

| Command | Purpose |
|---|---|
| `src/tuning/expression_tuner.py` | Generate + classify expression variants |
| `src/tuning/style_tuner.py` | Generate + classify style variants |

## Always run in background

Tuning runs are long (many images). Always use `run_in_background=true` on the Bash tool.

## Key flags

### avatar-expression-tuner / avatar-style-tuner

| Flag | Default | Notes |
|---|---|---|
| `--expression` | all | Expression ID(s) or `all` / `random` |
| `--style` | first available | Style ID(s) or `all` / `random` |
| `--gender` | all | `male female non-binary` or `all` / `random` |
| `--runs` | 1 | Iterations per (expression × style × gender) |
| `--hard-type-gender` | off | Restrict to strict gender feature pools |
| `--refine` | expression | `expression` = classify after gen; `none` = generate only |
| `--threshold` | 0.35 | Min probability to count as PASS |
| `--seed` | random | Base seed for reproducibility |
| `--ollama-url` | http://127.0.0.1:4096 | LLM Gateway URL |
| `--log-level` | DEBUG | DEBUG / INFO / WARNING / ERROR |
| `--tmp-dir` | /tmp/avatar_studio | Output base directory |

### avatar-expression-autotuner (additional flags)

| Flag | Default | Notes |
|---|---|---|
| `--max-iterations` | 5 | Max self-refining iterations |
| `--pass-threshold` | 0.60 | Target pass rate to stop early |
| `--apply-label-changes` | off | Write label improvements back to expressions.yml |
| `--apply-facs-changes` | off | Write FACS improvements back to expressions.yml |

## Available styles

`studio_3d`, `korean`, `photorealistic`, `lineart`, `clay`
(`random` = no system prompt, not useful for tuning)

## Available expressions

`happiness`, `surprise`, `anger`, `sadness`, `contempt`

## Image count formula

`expressions × styles × genders × runs`

Example: 1 expression × 5 styles × 3 genders × 5 runs = **75 images**

## Example commands

```bash
# Tune Happiness across all styles/genders, hard-typed, ~75 images
src/tuning/expression_tuner.py \
  --expression happiness \
  --style all \
  --gender all \
  --hard-type-gender \
  --runs 5 \
  --log-level INFO

# Generate only (no classification), single style
src/tuning/expression_tuner.py \
  --expression anger \
  --style studio_3d \
  --gender male female \
  --runs 1 \
  --refine none

