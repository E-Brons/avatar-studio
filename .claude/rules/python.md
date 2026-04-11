# Python Code Rules

Every Python change must pass the project's ruff configuration before committing.

## Linting

Run after every Python edit:
```
.venv/bin/ruff check src/ tests/ scripts/
```

Fix all reported errors before committing. The active rule sets (from `pyproject.toml`):
- `E` — pycodestyle errors
- `F` — pyflakes
- `W` — pycodestyle warnings
- `I` — isort (import ordering)
- `E501` is ignored (line length enforced at 100 via `line-length = 100`)

## Formatting

Run after every Python edit:
```
.venv/bin/ruff format src/ tests/ scripts/
```

Never commit code that fails `ruff format --check`. When writing new code, match the existing style so format passes without changes.

## Key style points

- Line length: 100 characters max
- Imports: sorted (isort rules via ruff `I`); stdlib → third-party → local, each group separated by a blank line
- No unused imports or variables
- No lazy imports — all imports must be at module top level, never inside functions or methods
- Target: Python 3.14+
