# Avatar Studio

Standalone avatar generation system — A→G LLM pipeline, style/expression classification, and self-refining tuning tools.

## Overview

Avatar Studio generates professional advisor avatars through a 7-stage pipeline:

| Stage | What it does |
|---|---|
| A — Randomise Person | Random demographics, name, colors |
| B — Generate CV | LLM generates education, experience, traits |
| C — Select Features | LLM selects hair style, clothing, accessories |
| D — Abbreviation | Initials avatar (PIL) |
| E — Canonical Portrait | LLM image model, neutral expression |
| F — Expression Variants | LLM image from portrait reference |
| G — Postprocess | Circle frame sticker (PIL) |

## Installation

```bash
pip install .
# or for development:
pip install -e ".[dev]"
```

## LLM Gateway

By default all LLM calls are routed through the LLM Gateway at `http://127.0.0.1:4096`.

Override with `--ollama-url <url>` on any CLI command.

## CLI

```bash
# Full avatar generation pipeline
avatar-studio generate --advisor path/to/advisor.yml --out-dir out/

# Generate style example portraits
avatar-studio gen-examples --ollama-image-model flux:latest

# Run Stage B only (LLM feature selection)
avatar-studio stage-b --role "Financial Advisor"
```

## Tuning Tools

```bash
# Style tuner: generate → classify → report
avatar-style-tuner --style studio_3d --runs 3 --watch

# Expression tuner: generate → classify → report
avatar-expression-tuner --expression all --runs 2

# Self-refining expression autotuner (Phase 4)
avatar-expression-autotuner \
    --expression all \
    --max-iterations 5 \
    --pass-threshold 0.60 \
    --apply-label-changes \
    --apply-facs-changes
```

## Tests

```bash
# Unit tests (no LLM required)
pytest -m "avatar and not integration"

# Integration tests (requires LLM Gateway)
pytest -m "avatar and integration"
```

## Project Structure

```
avatar_studio/
├── config/         # Settings loader, WCAG utils, color helpers
├── pipeline/       # Stages A–G
├── api/            # FastAPI server, REST routes, CLI
└── tuning/         # Style/expression classification and tuning tools
data/
├── expressions.yml # Expression definitions (FACS, labels, synonyms)
└── styles.yml      # Visual style definitions
assets/
└── avatar_styles/  # Reference images per style × gender
tests/              # Test suite
```
