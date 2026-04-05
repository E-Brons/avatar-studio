# avatar_expression_autotuner

**Type**: CLI agent | **Testable**: integration

## Purpose
Automated expression tuning: runs multiple tuning passes with diverse demographics and
aggregates results to identify which FACS configurations reliably produce recognisable
expressions across all genders and styles.

## Inputs
- `--expression` — expression ID(s) to tune
- `--style` — style ID(s) (default: all non-random)
- `--passes` — number of tuning passes (default: 3)
- `--seed` — base seed (per-pass seeds derived from it)

## Outputs
- Per-pass pass-rate tables (same format as `avatar_expression_tuner`)
- Aggregated multi-pass summary with confidence intervals

## Coordinates
1. Invoke `avatar_expression_tuner` logic repeatedly with varied seeds.
2. Aggregate per-expression, per-style, per-gender pass rates.
3. Flag expressions with < 60% pass rate as needing FACS revision.

## Parent
- [`avatar_expression_tuner`](avatar_expression_tuner.md)
