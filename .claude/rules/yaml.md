# YAML File Rules

All YAML files in this project use:
- 2-space indentation for mapping keys
- 2-space indented list items (`-` at +2 from parent, content at +4)
- Block scalars (`|`) for all multi-line strings
- No trailing whitespace inside block scalars

**Why:** These files are "data as code" — `styles.yml` and `expressions.yml` are tuned by the
REASON LLM. Consistent formatting means `git diff` shows only real value changes, not phantom
reformatting noise that obscures what was actually tuned.

## ruamel.yaml round-trip config

All code that reads and writes back a YAML file must use:

```python
from ruamel.yaml import YAML

def _yaml_rt() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 2**16
    y.Representer.add_representer(
        type(None), lambda self, _: self.represent_scalar("tag:yaml.org,2002:null", "null")
    )
    return y
```

Never use `yaml.dump` / `yaml.safe_dump` to write back files — PyYAML loses all formatting.

## Format check

Run `scripts/check_yaml_format.py` to verify that `styles.yml` and `expressions.yml`
round-trip identically through ruamel. This is analogous to `ruff format --check` for Python.
The pre-commit hook runs this automatically.
