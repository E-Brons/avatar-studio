# avatar_postprocessor_metadata

**Parent**: `avatar_postprocessor_compositor` | **Type**: pure function | **Testable**: unit

## Purpose
Embeds the output metadata into the final PNG as text chunks, including the persona attributes, expression ID, acceptance scores, and generation provenance.

## Inputs
- Final composite PNG bytes
- Avatar Persona (attributes)
- Expression name
- Acceptance scores dict (from §4 Validation scorers)
- Generation provenance: render path (`llm` or `programmatic`), model info or credits, generation time

## Outputs
- PNG bytes with metadata chunks embedded

## Metadata written (see Appendix A.3)
- `avatar-studio`: date, version
- `attributes`: all persona attributes
- `expression-id`
- `llm` block (LLM path): model name/version, full prompt
- `programmatic` block (Programmatic path): attribution/credits
- `acceptance-scores`: per-scorer float scores
- `generation-time-ms`

## Notes
- Uses `PIL.PngImagePlugin.PngInfo` text chunks — readable by any PNG-aware tool.
- Acceptance scores are written even if validation was not run — missing scorers write `null`.
