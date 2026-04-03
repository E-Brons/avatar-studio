# Docs Catalog

## product/

| File | Title | State |
|------|-------|-------|
| `product/avatars.md` | Avatar Studio — Avatars Design | Native. Avatar pipeline design, style specs, expression system, prompt pipeline. Current. |
| `product/product_features.md` | Avatar Studio — Product Features | Native. Pipeline steps, styles, expressions, tuning tools, API/CLI. Current. |
| `product/product_vision.md` | Avatar Studio — Product Vision | Native. Package purpose, target use case, core capabilities, design principles. Current. |
| `product/user_stories.md` | Avatar Studio — User Stories | Native. Five stories: generate avatar, add expression, add style, configure settings, tuning. Current. |

## software/

| File | Title | State |
|------|-------|-------|
| `software/architecture.md` | Avatar Studio — Architecture | Native. avatar-studio standalone package architecture, v0.1.0 (2026-04-02). Current. |
| `software/avatar_studio.md` | Avatar Studio — Software Design | Native. Runtime architecture: backend services, frontend behavior, concurrency, logging. Current. |
| `software/implementation_plan.md` | Avatar Studio — Implementation Plan | Native. Current state, active image prompt improvement work, and backlog. Current. |
| `software/integration_plan.md` | Avatar Studio — Integration Plan | Native. LLM Gateway routing, FastAPI integration, CI integration. Current. |
| `software/llm-interfaces.md` | LLM Interfaces — Abstraction Design | Native. 6 interface types (Text-gen, Image-gen, Image Inspector used by avatar-studio). Updated for avatar-studio context. Current. |

## test/

| File | Title | State |
|------|-------|-------|
| `test/ci_cd_plan.md` | Avatar Studio — CI/CD Plan | Native. `.github/workflows/ci.yml` implemented and active. Current. |
| `test/test_strategy.md` | Avatar Studio — Test Strategy | Native. Pure Python, offline mocked test suite. Current. |

## plans/

| File | Title | State |
|------|-------|-------|
| `plans/2026-04-02-image-prompt-improvement.md` | Image Generation Prompt Improvement — Research Plan | Native. Active plan. `test_pipeline_categorizer_score` scoring ~58–67% against 75% threshold. |

## reference/

| File | Title | State |
|------|-------|-------|
| `reference/claude-code.md` | CLI Reference — Claude Code | Reference copy of Claude Code CLI docs. Not project-specific. |

## Root (docs/)

| File | Title | State |
|------|-------|-------|
| `git_workflow.md` | Git Workflow — avatar-studio | Native. v1.0 (2026-04-02). Current. |

---

## .github/workflows/

| File | Purpose | State |
|------|---------|-------|
| `ci.yml` | CI pipeline | Native. Runs on push/PR to main. Three jobs: **Lint** (ruff), **Backend · Avatar Studio** (unit tests, `avatar and not integration`), **Integration · Avatar Studio** (conditional on `OLLAMA_URL` var). Current. |
| `tuner.yml` | Expression Autotuner | Native. `workflow_dispatch` only. Runs `avatar-expression-autotuner` with configurable expression, iterations, and pass threshold. Requires `OLLAMA_URL`. Current. |

## .github/rulesets/

| File | Purpose | State |
|------|---------|-------|
| `Main Branch Protection.json` | Branch protection for `main` | Native. Enforces deletion protection, no force-push, and required status checks (`Lint`, `Backend · Avatar Studio`). Current. |

---

## Root (repo)

| File | Purpose | State |
|------|---------|-------|
| `pyproject.toml` | Package definition | Native. `avatar-studio` v0.1.0, Python ≥3.14. Dependencies: FastAPI, uvicorn, PyYAML, Pillow, requests, rembg, litellm, python-multipart. Four entry points: `avatar-studio`, `avatar-style-tuner`, `avatar-expression-tuner`, `avatar-expression-autotuner`. Dev extras: pytest, ruff. Current. |
