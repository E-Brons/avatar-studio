#! .venv/bin/python3
"""Enrich celebrity persona.yml files with Wikipedia data and portrait analysis.

Scans assets/examples/*/persona.yml and fills any missing fields:
  - personal.religion, personal.zodiac  — from Wikipedia article (text LLM)
  - appearance.*                         — from original.jpg via image_inspector

Usage:
    python scripts/examples/enrich_persona.py [--dry-run] [--overwrite] [--gateway-url URL] [--workers N]

Options:
    --dry-run       Print planned changes but don't write files
    --overwrite     Re-enrich already-populated fields (default: skip existing values)
    --gateway-url   LLM Gateway base URL (default: http://127.0.0.1:4096)
    --workers       Concurrent workers for image inspection (default: 3)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import yaml
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from config.gateway import GatewayClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _appearance import extract_appearance, flat_to_persona_appearance  # noqa: E402
from _cv_scoring import compute_quality_score  # noqa: E402
from _example_utils import find_best_image  # noqa: E402
from _portrait_crop import crop_portrait_file  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXAMPLES_DIR = ROOT / "assets" / "examples"

# ── Wikipedia helpers ─────────────────────────────────────────────────────────

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKI_HEADERS = {"User-Agent": "AvatarStudioEnricher/1.0 (educational use)"}

_DDG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _wikipedia_intro(title: str) -> str | None:
    """Fetch the intro section of a Wikipedia article by exact title.

    Retries up to 4 times with exponential backoff on HTTP 429.
    """
    params = {
        "action": "query",
        "prop": "extracts",
        "exintro": "true",
        "explaintext": "true",
        "redirects": "1",
        "format": "json",
        "titles": title,
    }
    url = _WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_WIKI_HEADERS)

    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            pages = data.get("query", {}).get("pages", {})
            page = next(iter(pages.values()))
            if "missing" in page:
                return None
            return page.get("extract", "").strip() or None
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = int(exc.headers.get("Retry-After", 2 ** (attempt + 1)))
                logger.debug(
                    "Wikipedia 429 for %r — waiting %ds (attempt %d)",
                    title,
                    retry_after,
                    attempt + 1,
                )
                time.sleep(retry_after)
            else:
                logger.warning("Wikipedia fetch failed for %r: %s", title, exc)
                return None
        except Exception as exc:
            logger.warning("Wikipedia fetch failed for %r: %s", title, exc)
            return None

    logger.warning("Wikipedia fetch failed for %r after retries (429)", title)
    return None


def _ddg_find_wikipedia_title(name: str) -> str | None:
    """Search DuckDuckGo for '{name} wiki' and return the Wikipedia article title."""
    query = f"{name} wiki"
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers=_DDG_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("DDG search failed for %r: %s", name, exc)
        return None

    match = re.search(r'https?://en\.wikipedia\.org/wiki/([^"&\s<>]+)', html)
    if not match:
        return None
    raw_title = urllib.parse.unquote(match.group(1)).replace("_", " ")
    # Strip fragment and query string if any leaked through
    raw_title = re.split(r"[?#]", raw_title)[0].strip()
    return raw_title or None


def _fetch_wikipedia_text(name: str) -> str | None:
    """Return Wikipedia intro text for *name*, trying direct lookup then DDG fallback.

    Returns None only when no Wikipedia article can be found by either method.
    """
    text = _wikipedia_intro(name)
    if text:
        return text

    logger.info("  Wikipedia direct lookup failed for %r — trying DDG fallback", name)
    title = _ddg_find_wikipedia_title(name)
    if not title:
        logger.warning("  DDG found no Wikipedia URL for %r", name)
        return None

    logger.info("  DDG resolved %r → Wikipedia title %r", name, title)
    text = _wikipedia_intro(title)
    if not text:
        logger.warning("  Wikipedia fetch failed for DDG-resolved title %r", title)
    return text


# ── Zodiac from date ──────────────────────────────────────────────────────────

_ZODIAC_BOUNDS = [
    (date(1900, 3, 21), date(1900, 4, 19), "Aries"),
    (date(1900, 4, 20), date(1900, 5, 20), "Taurus"),
    (date(1900, 5, 21), date(1900, 6, 20), "Gemini"),
    (date(1900, 6, 21), date(1900, 7, 22), "Cancer"),
    (date(1900, 7, 23), date(1900, 8, 22), "Leo"),
    (date(1900, 8, 23), date(1900, 9, 22), "Virgo"),
    (date(1900, 9, 23), date(1900, 10, 22), "Libra"),
    (date(1900, 10, 23), date(1900, 11, 21), "Scorpio"),
    (date(1900, 11, 22), date(1900, 12, 21), "Sagittarius"),
    (date(1900, 12, 22), date(1900, 12, 31), "Capricorn"),
    (date(1900, 1, 1), date(1900, 1, 19), "Capricorn"),
    (date(1900, 1, 20), date(1900, 2, 18), "Aquarius"),
    (date(1900, 2, 19), date(1900, 3, 20), "Pisces"),
]


def _zodiac_from_date(month: int, day: int) -> str:
    probe = date(1900, month, day)
    for lo, hi, sign in _ZODIAC_BOUNDS:
        if lo <= probe <= hi:
            return sign
    return "unknown"


# ── LLM-based Wikipedia extraction ───────────────────────────────────────────

_PERSONAL_SCHEMA = {
    "type": "object",
    "properties": {
        "religion": {"type": "string"},
        "zodiac": {"type": "string"},
        "birth_month": {"type": "integer"},
        "birth_day": {"type": "integer"},
    },
    "required": ["religion", "zodiac"],
}

_PERSONAL_SYSTEM = (
    "You are a research assistant extracting factual details from Wikipedia text. "
    "Respond ONLY with valid JSON matching the requested schema."
)


def _extract_personal_from_wiki(
    gateway: GatewayClient, name: str, wiki_text: str, needs: set[str]
) -> dict:
    """Ask LLM to extract missing personal fields from Wikipedia intro text."""
    field_list = ", ".join(sorted(needs))
    prompt = (
        f"From the following Wikipedia article about {name}, extract these fields: {field_list}.\n\n"
        "Rules:\n"
        "- religion: the person's religion or faith (e.g. 'Christian', 'Muslim', 'Jewish', "
        "'atheist', 'Buddhist'). Use 'unknown' if not mentioned.\n"
        "- zodiac: their zodiac/star sign (e.g. 'Aries', 'Taurus'). "
        "Derive from birth date if given. Use 'unknown' if not determinable.\n"
        "- birth_month and birth_day: integers extracted from birth date, omit if not found.\n\n"
        f"Wikipedia text:\n{wiki_text[:4000]}\n\n"
        "Respond with JSON only."
    )
    output_config = {"format": {"schema": _PERSONAL_SCHEMA}}
    try:
        raw = gateway.text_gen(
            [{"role": "user", "content": prompt}],
            output_config=output_config,
        )
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("LLM personal extraction failed for %r: %s", name, exc)
        return {}


def _parse_json(text: str) -> dict:
    """Strip markdown fences and parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


# ── Missing-field detection ───────────────────────────────────────────────────

_PERSONAL_ENRICHABLE = {"religion", "zodiac"}
_APPEARANCE_FIELDS = {
    "skin_tone",
    "skin_texture",
    "hair_color",
    "eye_color",
    "brows_color",
    "face_shape",
    "eye_shape",
    "brows_style",
    "nose_shape",
    "chin_shape",
    "cheeks_shape",
    "hair_style",
    "hair_note",
}


def _missing_personal(personal: dict, overwrite: bool) -> set[str]:
    missing = set()
    for field in _PERSONAL_ENRICHABLE:
        val = personal.get(field)
        if overwrite or not val or val == "unknown":
            missing.add(field)
    return missing


def _missing_appearance(appearance: dict, overwrite: bool) -> set[str]:
    if overwrite:
        return set(_APPEARANCE_FIELDS)
    missing = set()
    for field in _APPEARANCE_FIELDS:
        val = appearance.get(field)
        if not val:
            missing.add(field)
    return missing


# ── Core enrichment per persona ───────────────────────────────────────────────


def _enrich_personal(
    gateway: GatewayClient, name: str, personal: dict, need_personal: set[str]
) -> dict:
    """Fetch Wikipedia + call LLM to fill personal fields. Returns {field: value} updates."""
    wiki_text = _fetch_wikipedia_text(name)
    if not wiki_text:
        logger.warning("  No Wikipedia article found for %r — skipping personal enrichment", name)
        return {}
    extracted = _extract_personal_from_wiki(gateway, name, wiki_text, need_personal)
    bm = extracted.pop("birth_month", None)
    bd = extracted.pop("birth_day", None)
    if bm and bd and "zodiac" in need_personal:
        extracted["zodiac"] = _zodiac_from_date(bm, bd)
    return {f: v for f, v in extracted.items() if v}


def _enrich_appearance(
    gateway: GatewayClient, persona_path: Path, name: str, need_appearance: set[str]
) -> dict:
    """Load portrait image + call shared extract_appearance, return persona.yml-ready dict."""
    img_path = find_best_image(persona_path.parent)
    if img_path is None:
        logger.warning("  No image found in %s", persona_path.parent)
        return {}
    flat = extract_appearance(gateway, img_path.read_bytes(), name)
    if not flat:
        return {}
    nested = flat_to_persona_appearance(flat)
    # Keep only fields that were actually requested
    return {k: v for k, v in nested.items() if k in need_appearance}


def _load_persona(persona_path: Path) -> tuple[dict, dict, dict, str]:
    """Load persona.yml and return (persona, personal, appearance, name)."""
    with open(persona_path) as f:
        persona = yaml.safe_load(f) or {}
    personal = persona.setdefault("personal", {})
    appearance = persona.setdefault("appearance", {})
    if appearance is None:
        appearance = {}
        persona["appearance"] = appearance
    name = personal.get("name") or persona_path.parent.name.replace("_", " ").title()
    return persona, personal, appearance, name


def _write_persona(persona_path: Path, persona: dict, *, dry_run: bool) -> None:
    if dry_run:
        logger.info("  [dry-run] Would write %s", persona_path)
    else:
        with open(persona_path, "w") as f:
            yaml.dump(persona, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.debug("  Saved %s", persona_path)


# ── Public API ────────────────────────────────────────────────────────────────


def run_enrich(
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    dry_run: bool = False,
    overwrite: bool = False,
    skip_personal: bool = False,
    crop_portraits: bool = True,
    workers: int = 3,
    examples_dir: Path | None = None,
) -> dict:
    """Enrich persona.yml files with Wikipedia data and portrait analysis.

    Returns {"enriched": N, "skipped": N, "empty_removed": N, "errors": N}.
    """
    examples_dir = examples_dir or EXAMPLES_DIR
    gateway = GatewayClient(gateway_url)

    persona_paths = sorted(examples_dir.glob("*/persona.yml"))
    if not persona_paths:
        logger.error("No persona.yml files found under %s", examples_dir)
        return {"enriched": 0, "skipped": 0, "empty_removed": 0, "errors": 1}

    logger.info("Found %d persona files under %s", len(persona_paths), examples_dir)

    # ── Portrait crop pass ────────────────────────────────────────────────────
    if crop_portraits:
        crop_counts: dict[str, int] = {
            "cropped_face": 0,
            "cropped_fallback": 0,
            "skipped": 0,
            "error": 0,
        }
        example_dirs = sorted({p.parent for p in persona_paths})
        with tqdm(example_dirs, unit="image", desc="Cropping portraits") as pbar:
            for folder in pbar:
                best = find_best_image(folder)
                if best is None:
                    continue
                # Always source from 001.jpg (original download) when available so that
                # re-running enrich after a prior crop always starts from full resolution.
                original = folder / "images" / "001.jpg"
                source = original if original.exists() and original != best else None
                dest = folder / "images" / "best.jpg"
                status = crop_portrait_file(
                    dest, source=source, dry_run=dry_run, overwrite=overwrite
                )
                crop_counts[status] = crop_counts.get(status, 0) + 1

                # Re-score the cropped best.jpg and store in metadata.json.
                # Scoring on the crop is more reliable: the face is larger and
                # properly framed, so quality/blur/resolution scores reflect the
                # image actually used by the pipeline.
                if status.startswith("cropped") and not dry_run and dest.exists():
                    meta_path = folder / "images" / "metadata.json"
                    if meta_path.exists():
                        try:
                            meta = json.loads(meta_path.read_text())
                            q = compute_quality_score(dest.read_bytes())
                            meta["best_score"] = round(q["composite_score"], 4)
                            meta_path.write_text(json.dumps(meta, indent=2))
                        except Exception as exc:
                            logger.debug("Could not re-score %s: %s", dest, exc)
        logger.info(
            "Portraits: cropped_face=%d  cropped_fallback=%d  skipped=%d  errors=%d",
            crop_counts["cropped_face"],
            crop_counts["cropped_fallback"],
            crop_counts["skipped"],
            crop_counts.get("error", 0),
        )
    PersonaWork = dict  # keys: path, persona, personal, appearance, name, futs

    work: list[PersonaWork] = []
    results = {"enriched": 0, "skipped": 0, "errors": 0}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for path in persona_paths:
            try:
                persona, personal, appearance, name = _load_persona(path)
            except Exception as exc:
                logger.error("Failed to load %s: %s", path, exc)
                results["errors"] += 1
                continue

            need_personal = set() if skip_personal else _missing_personal(personal, overwrite)
            need_appearance = _missing_appearance(appearance, overwrite)

            if not need_personal and not need_appearance:
                logger.debug("%-40s  already complete — skipping", name)
                results["skipped"] += 1
                continue

            logger.debug(
                "%-40s  needs personal=%s  appearance=%s",
                name,
                sorted(need_personal),
                sorted(need_appearance),
            )

            futs: dict = {}
            if need_personal:
                futs["personal"] = (
                    pool.submit(_enrich_personal, gateway, name, personal, need_personal),
                    need_personal,
                )
            if need_appearance:
                futs["appearance"] = (
                    pool.submit(_enrich_appearance, gateway, path, name, need_appearance),
                    need_appearance,
                )

            work.append(
                dict(
                    path=path,
                    persona=persona,
                    personal=personal,
                    appearance=appearance,
                    name=name,
                    futs=futs,
                )
            )

        # ── Collect results and write ─────────────────────────────────────────
        with tqdm(work, unit="persona", desc="Enriching") as pbar:
            for item in pbar:
                name = item["name"]
                pbar.set_postfix_str(name[:30])
                changed = False
                try:
                    if "personal" in item["futs"]:
                        fut, need = item["futs"]["personal"]
                        for field, val in fut.result().items():
                            if field in need:
                                item["personal"][field] = val
                                changed = True
                                logger.debug("  personal.%-12s = %r", field, val)

                    if "appearance" in item["futs"]:
                        fut, need = item["futs"]["appearance"]
                        for field, val in fut.result().items():
                            if val and field in need:
                                item["appearance"][field] = val
                                changed = True
                                logger.debug("  appearance.%-16s = %r", field, val)
                except Exception as exc:
                    logger.error("Error collecting results for %s: %s", name, exc, exc_info=True)
                    results["errors"] += 1
                    continue

                if not changed:
                    logger.debug("  No new data extracted for %s", name)
                    results["skipped"] += 1
                    continue

                try:
                    _write_persona(item["path"], item["persona"], dry_run=dry_run)
                    results["enriched"] += 1
                except Exception as exc:
                    logger.error("Failed to write %s: %s", item["path"], exc)
                    results["errors"] += 1

    # ── Remove empty folders ──────────────────────────────────────────────────
    empty_removed = 0
    for folder in sorted(examples_dir.iterdir()):
        if not folder.is_dir():
            continue
        files = [f for f in folder.iterdir() if f.is_file() and not f.name.startswith(".")]
        if not files:
            logger.info("Removing empty folder: %s", folder)
            if not dry_run:
                shutil.rmtree(folder)
            else:
                logger.info("  [dry-run] Would remove empty folder %s", folder)
            empty_removed += 1

    results["empty_removed"] = empty_removed
    logger.info(
        "\nDone. enriched=%d  skipped=%d  empty_removed=%d  errors=%d",
        results["enriched"],
        results["skipped"],
        empty_removed,
        results["errors"],
    )
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes, don't write")
    parser.add_argument(
        "--overwrite", action="store_true", help="Re-enrich already-populated fields"
    )
    parser.add_argument(
        "--gateway-url",
        default="http://127.0.0.1:4096",
        help="LLM Gateway base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Concurrent network workers (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-personal",
        action="store_true",
        help="Skip zodiac/religion enrichment (appearance only)",
    )
    crop_group = parser.add_mutually_exclusive_group()
    crop_group.add_argument(
        "--crop-portraits",
        dest="crop_portraits",
        action="store_true",
        default=True,
        help="Crop best.jpg to a square portrait (waist → top of head) before enriching (default: on)",
    )
    crop_group.add_argument(
        "--no-crop-portraits",
        dest="crop_portraits",
        action="store_false",
        help="Skip portrait cropping",
    )
    args = parser.parse_args()
    run_enrich(
        gateway_url=args.gateway_url,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        skip_personal=args.skip_personal,
        crop_portraits=args.crop_portraits,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
