# avatar_render_llm_facs_resolver

**Parent**: `avatar_render_llm_prompt_builder` | **Type**: pure function | **Testable**: unit

## Purpose
Resolves unilateral FACS action unit placeholders in an expression's FACS string, randomly assigning a left or right side to each.

## Inputs
- `facs_string`: e.g. `"AU14x (moderate), AU12x (trace)"`

## Outputs
- Resolved FACS string: e.g. `"AU14R (moderate), AU12L (trace)"`

## Behavior
1. Find all `AUNNx` patterns (where `NN` is a digit sequence).
2. For each match: randomly replace `x` with `R` or `L` (independent per AU).
3. Return the resolved string.

## Notes
- Re-rolled independently per image call — contempt's active side may differ between expressions and between runs.
- Used for expressions with unilateral muscle actions (primarily contempt: AU14, AU12 unilateral).
