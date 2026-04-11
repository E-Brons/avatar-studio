"""IPAdapter Prompt Generator — config-driven generation parameter builder.

Reads assets/prompt_gen/restyle.yml or reexpress.yml on every call so that
mid-run REASON patches are picked up immediately in the next iteration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from pipeline.render.llm.facs_resolver import resolve_unilateral

_ASSETS_DIR = Path(__file__).parents[4] / "assets" / "prompt_gen"
_RESTYLE_CONFIG = _ASSETS_DIR / "restyle.yml"
_REEXPRESS_CONFIG = _ASSETS_DIR / "reexpress.yml"


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
    """Load restyle.yml config and fill {style_description} from style_entry.

    Re-reads the YAML on every call so REASON patches take effect immediately.
    """
    cfg = yaml.safe_load(_RESTYLE_CONFIG.read_text())
    description = (style_entry.get("description") or "portrait").rstrip(".")
    prompt = cfg["prompt_template"].format(style_description=description)
    return IPAdapterGenParams(
        prompt=prompt,
        negative_prompt=cfg["negative_prompt"],
        width=int(cfg["width"]),
        height=int(cfg["height"]),
        num_inference_steps=int(cfg["num_inference_steps"]),
        cfg_scale=float(cfg["cfg_scale"]),
        ip_adapter_scale=float(cfg["ip_adapter_scale"]),
        lora=cfg.get("lora") or None,
        lora_weight=float(cfg.get("lora_weight", 1.0)),
    )


def build_reexpress_params(expr_entry: dict) -> IPAdapterGenParams:
    """Load reexpress.yml config and fill {expression_name} / {facs_au_codes}.

    Re-reads the YAML on every call so REASON patches take effect immediately.
    {facs_au_codes}: resolved via resolve_unilateral, intensity labels stripped.
    """
    cfg = yaml.safe_load(_REEXPRESS_CONFIG.read_text())
    expr_name = expr_entry.get("expression", expr_entry.get("id", "neutral"))
    facs_raw = resolve_unilateral(expr_entry.get("facs_action_units", ""))
    facs_clean = re.sub(r"\s*\([^)]+\)", "", facs_raw).strip(", ")
    prompt = cfg["prompt_template"].format(
        expression_name=expr_name,
        facs_au_codes=facs_clean,
    )
    return IPAdapterGenParams(
        prompt=prompt,
        negative_prompt=cfg["negative_prompt"],
        width=int(cfg["width"]),
        height=int(cfg["height"]),
        num_inference_steps=int(cfg["num_inference_steps"]),
        cfg_scale=float(cfg["cfg_scale"]),
        ip_adapter_scale=float(cfg["ip_adapter_scale"]),
        lora=cfg.get("lora") or None,
        lora_weight=float(cfg.get("lora_weight", 1.0)),
    )
