# Plan: Learning Scripts Restructure

**Date:** 2026-04-09  
**Status:** Implemented

## Context

The `scripts/` folder had grown to include learning/benchmarking scripts alongside infrastructure scripts. `improvement_loop.py` only used `image_gen` and didn't leverage the new IP-Adapter FaceID endpoint. `original.jpg` example photos needed to be removed from git tracking for copyright/privacy reasons.

## Changes implemented

### 1. Git-removed original.jpg (copyright/privacy)

- Added `assets/examples/*/original.jpg` to `.gitignore`
- Ran `git rm --cached` on all tracked original.jpg files — files remain on disk but are no longer committed
- Added `logs/` to `.gitignore` (experiment logs never committed)

### 2. Reorganized scripts/

**scripts/ root** (infrastructure only):
- `install.sh`, `run.sh`, `stop.sh`, `test.sh`, `test-integration.sh`, `fullstack_run.sh`, `find_old_terminology.sh`

**scripts/learn/** (learning pipelines):
- `learn_create.py` — persona → avatar learning loop
- `learn_restyle.py` — restyle (IP-Adapter) learning loop  
- `learn_reexpress.py` — reexpress (IP-Adapter) learning loop
- `_cli.py` — common argparse
- `_logger.py` — LJSON logger
- `_sampler.py` — iterative sampling logic
- `_benchmark.py` — render + score engine (from example_benchmark.py)
- `_analyze.py` — analysis engine (from analyze_benchmark.py)
- `_example_utils.py` — persona loading, normalization utilities
- `_fixes.py` — LLM fix engine (from improvement_loop.py)

**scripts/examples/** (dataset management):
- `audit_examples.py`, `audit_example_coverage.py`
- `enrich_example_persona.py`, `normalize_example_personas.py`
- `download_examples.py`, `gen_style_previews.py`

### 3. Common CLI signature

All three learning scripts accept:
- `--range A B` / `--samples X` (mutually exclusive; default = full set with confirmation)
- `--workers N` (default: 3)
- `--stop-on-plateau` / `--no-stop-on-plateau` (default: on)
- `--max-iterations N` (default: 2)
- `--optimize OPT` (quality | normal | fast, default: normal)
- `--gateway URL`
- `--log-dir DIR` (default: logs/learn/)

### 4. Iterative sampling strategy

- Step 0: X random samples → render → score → LLM fixes
- Step N: bottom X/2 from step N-1 + fresh X/2 → render → score → LLM fixes
- Plateau guard: stop if score delta < 1% for 2 consecutive iterations

### 5. IP-Adapter integration

- `learn_create.py`: uses `image_gen` for neutral portraits (persona-anchored)
- `learn_restyle.py`: uses `ipadapter_faceid` with `reference_mode="style_transfer"`
- `learn_reexpress.py`: uses `ipadapter_faceid` with `reference_mode="avatar_portrait"`

### 6. LJSON logging

Each run appends to `logs/learn/<script>_<timestamp>.ljson` — one JSON record per line.
Records: config, render, score, fix, summary, plateau, done.

## Key files

| File | Purpose |
|---|---|
| `scripts/learn/learn_create.py` | Entry point — create pipeline learning |
| `scripts/learn/learn_restyle.py` | Entry point — restyle pipeline learning |
| `scripts/learn/learn_reexpress.py` | Entry point — reexpress pipeline learning |
| `scripts/learn/_fixes.py` | LLM reasoning → structured asset patches |
| `scripts/learn/_benchmark.py` | Render + score engine for create pipeline |
| `docs/software/learn/overview.md` | User-facing documentation |

## Verification

```bash
# Lint
.venv/bin/ruff check scripts/learn/ scripts/examples/
.venv/bin/ruff format --check scripts/learn/ scripts/examples/

# Quick smoke test (requires gateway running)
python scripts/learn/learn_create.py --samples 5 --max-iterations 1 --optimize fast
python scripts/learn/learn_restyle.py --samples 5 --max-iterations 1 --optimize fast
python scripts/learn/learn_reexpress.py --samples 5 --max-iterations 1 --optimize fast

# Verify logs written
ls logs/learn/
```
