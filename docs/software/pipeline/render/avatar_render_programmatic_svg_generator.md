# avatar_render_programmatic_svg_generator

**Parent**: `avatar_render_programmatic` | **Type**: subprocess call | **Testable**: integration (mock subprocess or fixture SVG)

## Purpose
Generates a DiceBear SVG by calling the vendored Node.js script as a subprocess, passing the persona name as the seed and the expression component options as JSON.

## Inputs
- `name`: persona name (used as DiceBear seed)
- `style`: DiceBear style ID
- `size`: canvas size in pixels
- `options`: component override dict (from `avatar_render_programmatic_expression_mapper`) plus `backgroundColor`
- `out_path`: destination `.svg` file

## Outputs
- SVG file written to `out_path`

## Behavior
1. Build command: `node generate.js --seed <name> --style <style> --size <size> --out <out_path> [--options <json>]`
2. Run in `vendor/programmatic-avatar/` working directory (so Node can resolve `node_modules`).
3. `subprocess.run(cmd, check=True, cwd=vendor_dir)`.

## Error handling
- `FileNotFoundError` if Node.js not in PATH or vendor dir missing → propagates; caller (non-fatal at `avatar_renderer` level).
- `CalledProcessError` on non-zero exit → propagates similarly.

## Notes
- `opeeps` style does not use `name` as a seed — produces a random avatar each call.
- Vendor setup: `npm ci` inside `vendor/programmatic-avatar/`.
