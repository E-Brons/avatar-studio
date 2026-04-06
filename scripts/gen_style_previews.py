"""Generate programmatic style preview PNGs for the Flutter style picker."""
import re
import subprocess
import sys
from pathlib import Path

import cairosvg

vendor = Path("vendor/programmatic-avatar").resolve()
generate_js = vendor / "generate.js"
out_dir = Path("frontend/assets/styles").resolve()

styles = ["toon-head", "avataaars", "bottts", "micah", "opeeps"]
seeds = {
    "male": "Alex Thompson",
    "female": "Sarah Chen",
    "non_binary": "Jordan Kim",
}


def svg_to_png(svg_bytes: bytes, png_path: Path) -> None:
    """Render SVG to PNG, working around cairosvg's viewBox scaling bug.

    cairosvg ignores the viewBox→viewport transform, rendering 1 SVG coordinate
    unit = 1 pixel.  We patch the SVG's width/height to match its viewBox so the
    output is always the correct native size.
    """
    text = svg_bytes.decode()
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
    if m:
        vw, vh = m.group(1), m.group(2)
        # Replace only the first occurrence (on the <svg> opening tag)
        text = re.sub(r'\bwidth="\d+"', f'width="{vw}"', text, count=1)
        text = re.sub(r'\bheight="\d+"', f'height="{vh}"', text, count=1)
        svg_bytes = text.encode()
    cairosvg.svg2png(bytestring=svg_bytes, write_to=str(png_path))


for style in styles:
    style_slug = style.replace("-", "_")
    for gender, name in seeds.items():
        svg_path = out_dir / f"avatar_style_{style_slug}_{gender}.svg"
        png_path = out_dir / f"avatar_style_{style_slug}_{gender}.png"

        result = subprocess.run(
            ["node", str(generate_js), "--seed", name, "--style", style, "--out", str(svg_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR {style}/{gender}: {result.stderr[:200]}", file=sys.stderr)
            continue

        svg_to_png(svg_path.read_bytes(), png_path)
        svg_path.unlink()
        print(f"  {png_path.name}")

print("Done")
