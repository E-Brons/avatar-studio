"""IPAdapter Prompt Generator — config-driven generation parameter builder.

Reads the restyle or reexpress config from styles.yml / expressions.yml on every call so
that mid-run REASON patches are picked up immediately in the next iteration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from pipeline.render.llm.facs_resolver import resolve_unilateral

_STYLES_YML = Path(__file__).parents[4] / "assets" / "styles" / "styles.yml"
_EXPRESSIONS_YML = Path(__file__).parents[4] / "assets" / "expressions" / "expressions.yml"


@dataclass
class IPAdapterGenParams:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    num_inference_steps: int
    cfg_scale: float
    ip_adapter_scale: float
    lora: str | None
    lora_weight: float

    def log_lines(self) -> list[str]:
        """Return human-readable lines for iteration-opening log output."""
        lines = [
            f"  prompt            : {self.prompt}",
            f"  negative_prompt   : {self.negative_prompt}",
            f"  size              : {self.width}x{self.height}",
            f"  num_inference_steps: {self.num_inference_steps}",
            f"  cfg_scale         : {self.cfg_scale}",
            f"  ip_adapter_scale  : {self.ip_adapter_scale}",
            f"  lora              : {self.lora or 'null'}  weight={self.lora_weight}",
        ]
        return lines


def build_restyle_params(style_entry: dict) -> IPAdapterGenParams:
    """Read restyle config from styles.yml for the given style and build generation params.

    Re-reads the YAML on every call so REASON patches take effect immediately.
    """
    style_id = style_entry.get("id")
    styles_data = yaml.safe_load(_STYLES_YML.read_text())
    live_entry = next(
        (s for s in styles_data.get("styles", []) if s.get("id") == style_id),
        style_entry,
    )
    llm_params = (live_entry.get("restyle") or {}).get("llm_params") or {}
    description = (style_entry.get("description") or "portrait").rstrip(".")
    prompt = llm_params["prompt_template"].format(style_description=description)
    return IPAdapterGenParams(
        prompt=prompt,
        negative_prompt=llm_params["negative_prompt"],
        width=int(llm_params["width"]),
        height=int(llm_params["height"]),
        num_inference_steps=int(llm_params["num_inference_steps"]),
        cfg_scale=float(llm_params["cfg_scale"]),
        ip_adapter_scale=float(llm_params["ip_adapter_scale"]),
        lora=llm_params.get("lora") or None,
        lora_weight=float(llm_params.get("lora_weight", 1.0)),
    )


def build_reexpress_params(expr_entry: dict) -> IPAdapterGenParams:
    """Read reexpress config from expressions.yml for the given expression and build generation params.

    Re-reads the YAML on every call so REASON patches take effect immediately.
    {facs_au_codes}: resolved via resolve_unilateral, intensity labels stripped.
    """
    expr_name = expr_entry.get("expression", expr_entry.get("id", "neutral"))
    exprs_data = yaml.safe_load(_EXPRESSIONS_YML.read_text())
    live_entry = next(
        (e for e in exprs_data.get("expressions", []) if e.get("expression") == expr_name),
        expr_entry,
    )
    llm_params = (live_entry.get("reexpress") or {}).get("llm_params") or {}
    facs_raw = resolve_unilateral(expr_entry.get("facs_action_units", ""))
    facs_clean = re.sub(r"\s*\([^)]+\)", "", facs_raw).strip(", ")
    prompt = llm_params["prompt_template"].format(
        expression_name=expr_name,
        facs_au_codes=facs_clean,
    )
    return IPAdapterGenParams(
        prompt=prompt,
        negative_prompt=llm_params["negative_prompt"],
        width=int(llm_params["width"]),
        height=int(llm_params["height"]),
        num_inference_steps=int(llm_params["num_inference_steps"]),
        cfg_scale=float(llm_params["cfg_scale"]),
        ip_adapter_scale=float(llm_params["ip_adapter_scale"]),
        lora=llm_params.get("lora") or None,
        lora_weight=float(llm_params.get("lora_weight", 1.0)),
    )
