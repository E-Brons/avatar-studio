# Avatar Studio — Test Strategy

## Architecture

Unit tests mock the LLM Gateway client so the pipeline logic can be verified offline. Integration tests call the live LLM Gateway and validate real LLM output — including image quality scored by the classifier.

---

## Test Levels

### 1. Unit Tests

```sh
pytest tests/ -m "avatar and not integration" -v
```

The LLM Gateway client (`GatewayClient`) is patched at the module boundary. No running services required. All image generation calls, feature selection calls, and CV generation calls are mocked — but the full parsing, retry, marshalling, and error-handling logic runs against those mocks.

| File | Covers |
|------|--------|
| `test_api.py` | `ConfigLoader.load()` (attribute count, option shapes, dual-color extras, gender-bucket tags, formula/depends_on fields, style options), `_demo_key` (all 15 ID mappings + unknown returns None), `_demo_to_response` (key casing, value preservation), `_resolve_demographics` (no constraints, single overrides, hair_color → brows re-derive, random mode ignored, None value skipped, multiple constraints) |
| `test_avatar_features.py` | Demographics randomization (`_pick_diverse_demographics`, `_pool_by_gender`), CV generation (`_generate_advisor_profile`: YAML parsing, code-fence stripping, list truncation, retry on empty/missing fields, exhaustion raises), feature selection (`_select_features`, `_select_feature_field`, `_marshal_avatar_persona`, `_build_feature_prompt`, warmup failure non-fatal, context accumulates, hard-type-gender pool filtering), pipeline wiring (features → persona) |
| `test_avatar_stages.py` | `config` (WCAG utils, hex helpers, palette filtering), demographics (`_pick_colors`, `_pick_name`, `_pick_demographics`: required keys, gender valid, age in range, seeded determinism, bg_color WCAG pass), abbreviation (valid PNG, correct size, RGBA, transparent corners, opaque center, white border ring), toon-head (`create_toon_head_avatar`: creates file, returns path, SVG content, parent dirs, seed forwarded, bg_color option, no-options without demographics, Node error raises), portrait generation (`create_face_avatar`: neutral failure returns null map, success returns filenames, partial expression failure, feature failure non-fatal, demographics returned) |

### Mocking Strategy

| External dependency | Patched at |
|--------------------|------------|
| `pick_demographics` (http_server) | `api.http_server.pick_demographics` |
| Text LLM (feature selection) | `pipeline.persona.aggregator_llm.GatewayClient` |
| Image generation | `pipeline.render.llm.orchestrator.generate_avatar_image` |
| Demographics | `pipeline.render.llm.orchestrator.pick_demographics` |
| Feature selection | `pipeline.render.renderer.select_features` |
| Node.js programmatic avatar | `pipeline.render.programmatic.svg_generator.subprocess.run` |

---

### 2. Integration Tests

```sh
pytest tests/ -m "avatar and integration" -v
# or with explicit gateway URL:
OLLAMA_URL=http://127.0.0.1:4096 pytest tests/ -m "avatar and integration" -v
```

These call the live LLM Gateway and run real LLM calls through the full pipeline. They auto-skip if the gateway is unreachable (via the `gateway` fixture in `conftest.py`).

| File | Covers |
|------|--------|
| `conftest.py` | `gateway` session fixture: connects to `OLLAMA_URL` (default `http://127.0.0.1:4096`), auto-skips all integration tests if unreachable |
| `test_avatar_integration.py` | Gateway health check, CV generation live (profile has education/experience/traits), feature selection live (features non-empty, HAIR_STYLE and CLOTHING present), full pipeline (valid PNG output, persona has all required sections), `test_pipeline_categorizer_score` (categorizer ≥ 75% on seed=21), `test_circle_frame_categorizer` (framed portrait ≥ 65% on seed=4) |

**The categorizer tests are the primary quality gate.** They generate a real portrait via the LLM Gateway and score it against the persona using `classify_persona`. These tests fail when prompt quality degrades — see `docs/plans/2026-04-02-image-prompt-improvement.md`.

---

## Running Tests

```sh
# Unit tests (no services required)
pytest tests/ -m "avatar and not integration" -v

# API layer only (fastest — no pipeline imports needed beyond config + demographics)
pytest tests/test_api.py -v

# With coverage
pytest tests/ -m "avatar and not integration" --cov=src --cov-report=term-missing

# Single file
pytest tests/test_avatar_stages.py -v

# Integration (requires gateway)
pytest tests/ -m "avatar and integration" -v
```

---

## Test Naming Convention

- Files: `test_avatar_<scope>.py` — one file per pipeline area
- Functions: `test_<function>_<scenario>` — e.g. `test_create_face_avatar_neutral_failure_returns_null_map`
- Mocking: gateway client patched at the module where it is imported — e.g. `pipeline.persona.aggregator_llm.GatewayClient`

---

## CI

See `docs/test/ci_cd_plan.md` for the full CI pipeline description.

Unit tests run on every push and PR. Integration tests run automatically when `OLLAMA_URL` is set as a repository variable.

---

## Flutter Web UI Tests

Flutter widget tests live in `frontend/test/`. Run with:

```sh
cd frontend && flutter test
```

The generated `frontend/test/widget_test.dart` (smoke test that the app renders) serves as a placeholder until widget-level tests are added.
