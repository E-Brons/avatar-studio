# Avatar Studio — Data Structures

Shared data structures referenced by all pipeline flow documents.

---

## Avatar Request

The Avatar Request is a key-value dictionary. Each key is an attribute name; each value is either a concrete value or a selector that resolves to one.

**Selector types**:

| Selector | Description |
|---|---|
| **Single value** | Explicit concrete value — passed through unchanged |
| **List** | Uniform random pick from the provided list of values |
| **Range** | Uniform random sample from `[min, max]` |
| **Probability dict** | Weighted random pick; dict of `{value: probability}` (probabilities must sum to 1) |
| **Inherit** | Derives value from another attribute: `{parent_attribute: {parent_value: derived_value, ...}}` |
| **🤖 LLM Selector** | Value is chosen by an LLM call given the attribute context and the partially-resolved persona |

Attributes absent from the request fall back to the schema default selector defined in `Persona_Schema.yml`.

---

## Avatar Persona

`avatar_persona.yml` is the fully resolved persona produced by the persona generation phase. Every attribute has exactly one concrete value — no selectors remain.

```yaml
personal:
  name: <str>
  gender: <str>           # male | female | non-binary
  age-group: <str>        # baby | toddler | adult | senior | etc.
  age: <int>
  nationality: <str>
  religion: <str>
  zodiac: <str>

appearance:
  skin_tone: <hex>
  hair_color:
    hex_base: <hex>
    hex_shadow: <hex>
  eye_color:
    hex_iris: <hex>
    hex_pupil: <hex>
  brows_color: <hex>
  hair_style: <str>
  eye_shape: <str>
  brows_style: <str>
  nose_shape: <str>
  chin_shape: <str>
  cheeks_shape: <str>
  clothing:
    <garment>: <hex>       # 1–3 items
    ...
  accessories:
    <accessory>: <desc>    # 0–2 items
    ...

personality:
  traits:
    <str>                  # 1–4 items
    ...

post-process:              # ⚠️ NOT passed to the image model — compositing metadata only
  pp_style_name: <str>     # factory to post-process: `transparent`, `color-fill`, `round-fill`
  bg_color: <hex>          # background circle color
  fg_color: <hex>          # foreground/text color
```

When injected into the image model prompt, the `post-process` block is stripped and `eye_shape` is excluded.[^persona-img-strip]

[^persona-img-strip]: `post-process` holds compositing metadata (bg/fg colors), not visual identity. `eye_shape` is excluded because rendering is owned by the style system prompt — injecting a persona-level eye shape would conflict with the style's defined rendering contract.

---

## PNG Metadata

Every output PNG carries the following embedded text chunks:

```yaml
avatar-studio:
  date: <ISO date>
  version: <package version>

attributes:
  artistic-style: <style_id>
  gender: <str>
  age: <int>
  name: <str>
  # ... all appearance attributes

expression-id: <str>

# LLM-generated avatars only:
llm:
  model: <model name and version>
  prompt: <full prompt sent to image model>

# Programmatically-generated avatars only:
programmatic:
  credits: <attribution per package usage>

acceptance-scores:
  expression-clarity: <float 0.0–1.0>
  style-fidelity: <float 0.0–1.0>
  phenotype-fidelity: <float 0.0–1.0>

generation-time-ms: <int>   # includes all acceptance scorer passes
```
