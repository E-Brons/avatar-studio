"""Persona sanitizer for the image model — strip text-heavy fields and enrich
structural property labels into detailed visual descriptions so the image model
renders them accurately rather than guessing from a terse keyword.
"""

from __future__ import annotations

from pipeline.persona.marshal import visual_only_persona

# ---------------------------------------------------------------------------
# Skin tone labels (hex → human-readable + hex preserved for model)
# ---------------------------------------------------------------------------

_SKIN_TONE_LABELS: dict[str, str] = {
    "#F5E0C9": "warm ivory, very fair (#F5E0C9)",
    "#FBCCB3": "light peach, fair (#FBCCB3)",
    "#E8C49A": "golden beige, light (#E8C49A)",
    "#E0CEBC": "cool beige, light (#E0CEBC)",
    "#F2D3C4": "rosy fair, light (#F2D3C4)",
    "#F7E8D8": "soft cream, fair (#F7E8D8)",
    "#FDE8D5": "pale sand, fair (#FDE8D5)",
    "#F0D5C0": "warm sand, light (#F0D5C0)",
    "#EDD5B3": "golden sand, light (#EDD5B3)",
    "#F5CBA7": "peachy tan, light-medium (#F5CBA7)",
    "#D4A76A": "honey tan, medium (#D4A76A)",
    "#C9A96E": "warm olive, medium (#C9A96E)",
    "#D9B896": "warm sand, medium (#D9B896)",
    "#CEAC7A": "caramel, medium (#CEAC7A)",
    "#C8A882": "warm beige, medium (#C8A882)",
    "#A67C52": "light brown, medium-dark (#A67C52)",
    "#8B5E3C": "medium brown, dark (#8B5E3C)",
    "#B8864E": "warm sienna, medium-dark (#B8864E)",
    "#9E6B3A": "deep tan, medium-dark (#9E6B3A)",
    "#AA7B4C": "tawny, medium-dark (#AA7B4C)",
    "#6B3F23": "deep brown, very dark (#6B3F23)",
    "#4A2912": "rich espresso, darkest (#4A2912)",
    "#7A4530": "deep mahogany (#7A4530)",
    "#5C3318": "dark chocolate (#5C3318)",
    "#6E3D25": "warm dark brown (#6E3D25)",
    "#3B1F0D": "near-black brown (#3B1F0D)",
    "#2C1608": "deepest ebony (#2C1608)",
    "#4F2B14": "very deep brown (#4F2B14)",
}

# ---------------------------------------------------------------------------
# Eye shape expansions
# ---------------------------------------------------------------------------

_EYE_SHAPE: dict[str, str] = {
    "almond": (
        "almond-shaped eyes: slightly pointed at both inner and outer corners, "
        "a visible upper lid crease, elegant and mildly upward-tilted"
    ),
    "round": (
        "large round eyes: wide open with a circular visible iris, "
        "prominent and expressive with a full rounded lid shape"
    ),
    "hooded": (
        "hooded eyes: heavy overhanging brow bone drooping over the upper eyelid, "
        "eyelid crease hidden, short brow-to-lash distance"
    ),
    "monolid": (
        "monolid eyes: single eyelid with no visible upper lid crease, "
        "flat lid surface, common in East Asian features"
    ),
    "deep-set": (
        "deep-set eyes: recessed deep into the eye socket beneath a prominent "
        "overhanging brow ridge, creating strong shadows above the eye"
    ),
    "upturned": (
        "upturned eyes: outer corners lifted noticeably higher than inner corners, "
        "cat-eye or fox-eye appearance, giving an alert and feline look"
    ),
    "downturned": (
        "downturned eyes: outer corners angled gently downward below the inner "
        "corners, giving a soft melancholic or gentle expression"
    ),
    "wide-set": (
        "wide-set eyes: eyes positioned farther apart than average, with substantial "
        "space between them relative to nose width"
    ),
    "manga": (
        "large stylized eyes in anime/manga aesthetic: exaggerated round irises, "
        "wide expressive pupils, dramatic highlights, oversized and luminous"
    ),
    "protruding": (
        "protruding eyes: eyeballs appear to bulge forward from the face, "
        "prominent and wide, with visible white above the iris"
    ),
    "close-set": (
        "close-set eyes: positioned very close together near the nose bridge, "
        "narrow space between the inner corners"
    ),
    "heavy-lidded": (
        "heavy-lidded eyes: thick drooping upper eyelids that partially cover the "
        "iris, giving a sleepy, sultry or intense expression"
    ),
    "cat-eye": (
        "cat-eye shaped eyes: elongated horizontally with dramatically upswept and "
        "pointed outer corners, sharp and feline"
    ),
    "small and sharp": (
        "small sharp eyes: narrow compact lids, intense focused gaze, "
        "precise and piercing despite the small size"
    ),
    "large and soft": (
        "large soft eyes: generous lid height, wide iris, warm and open expression, "
        "inviting and expressive"
    ),
    "asymmetric": (
        "subtly asymmetric eyes: one eye is slightly larger, higher, or differently "
        "shaped than the other, giving a natural distinctive character"
    ),
}

# ---------------------------------------------------------------------------
# Nose shape expansions
# ---------------------------------------------------------------------------

_NOSE_SHAPE: dict[str, str] = {
    "small rounded shadow": (
        "small soft nose with a rounded tip, minimal bridge definition, "
        "gentle shadow suggesting a delicate compact nose"
    ),
    "subtle vertical line": (
        "narrow slim nose indicated by a subtle vertical shadow line, "
        "minimal width, elegant and refined"
    ),
    "soft L-curve": (
        "nose with a soft L-shaped profile: a slight bump at the bridge "
        "then a gentle downward curve to a soft tip"
    ),
    "gentle button": (
        "classic button nose: small rounded tip curving gently upward, "
        "short bridge, narrow delicate nostrils"
    ),
    "narrow bridge shadow": (
        "nose with a narrow elongated bridge, a slim shadow line running "
        "down the center, refined and straight"
    ),
    "wide bridge shadow": (
        "nose with a wide flat bridge casting a broad shadow across the "
        "middle of the face, prominent width"
    ),
    "broad flat": (
        "broad flat nose: wide nostrils spreading across the lower face, "
        "flat low bridge with minimal projection"
    ),
    "long straight": (
        "long straight nose with an uninterrupted smooth bridge line from "
        "brow bone to tip, classic proportions"
    ),
    "concave ski slope": (
        "concave ski-slope nose: the bridge dips inward creating a concave "
        "curve before the tip tilts slightly upward"
    ),
    "bulbous tip": (
        "nose with a large rounded bulbous tip that dominates the lower nose, "
        "wide and fleshy at the end"
    ),
    "hawk curved": (
        "hawk nose: a dramatic downward-curving bridge with a sharp refined tip "
        "that hooks slightly toward the upper lip"
    ),
    "wide nostrils": (
        "nose with noticeably wide flared nostrils, a full broad nasal base spreading outward"
    ),
    "narrow nostrils": (
        "nose with narrow pinched nostrils, a slim compact nasal base "
        "close together beneath the tip"
    ),
    "snubbed upturned": (
        "short snubbed upturned nose: a lifted tip that reveals the nostrils "
        "when viewed from the front, perky and small"
    ),
    "strong aquiline": (
        "strong aquiline Roman nose: high prominent bridge with a bold downward "
        "curve, angular and refined, narrow at the tip"
    ),
    "soft undefined": (
        "soft undefined nose with subtle indistinct features, smooth and blending "
        "gently into the face without sharp definition"
    ),
}

# ---------------------------------------------------------------------------
# Brow style expansions
# ---------------------------------------------------------------------------

_BROWS_STYLE: dict[str, str] = {
    "straight thick": "thick straight eyebrows running horizontally with no arch, dense dark hairs",
    "bushy natural": "bushy unkempt natural eyebrows with dense full ungroomed hairs",
    "bold unibrow": "bold heavy eyebrows nearly meeting at the center, near-unibrow effect",
    "strong horizontal": "strong bold horizontal eyebrows, no arch, flat and commanding",
    "arched dramatic": "dramatically high-arched eyebrows with a sharp sweeping upward curve",
    "pencil thin": "extremely thin pencil-line eyebrows, very narrow and precisely groomed",
    "straight thin": "thin straight eyebrows with no arch, minimal and horizontal",
    "soft arch thick": "thick full eyebrows with a soft gentle arch, natural and well-groomed",
    "soft arch thin": "thin eyebrows with a soft gentle arch, delicate and refined",
    "flat natural": "flat natural eyebrows with minimal arch, relaxed and barely groomed",
    "angular defined": "angular sharply defined eyebrows with a strong peaked arch and crisp edges",
    "tapered": "eyebrows thick at the inner head, tapering sharply to a thin pointed tail",
    "rounded soft": "rounded eyebrows with a soft circular gentle arch, friendly and open",
    "feathered": "feathered eyebrows with natural soft individual hair strokes, textured",
    "high arch thick": "thick eyebrows with a very high dramatic arch",
    "curved wide": "wide-spaced broadly curved eyebrows with a generous rounded arc",
    "sparse natural": "sparse thin eyebrows with visible gaps between individual hairs",
    "short and defined": "short neat eyebrows not extending far past the outer eye corner",
    "long and full": "long full eyebrows extending well past the outer eye corner",
}

# ---------------------------------------------------------------------------
# Chin shape expansions
# ---------------------------------------------------------------------------

_CHIN_SHAPE: dict[str, str] = {
    "squared-off": "squared-off jaw with a wide flat chin and angular corner edges",
    "strong prominent": "strong prominent chin projecting forward from the lower jaw, assertive",
    "wide and flat": "wide flat chin spanning broadly across the bottom of the face",
    "deep cleft": "chin with a deep pronounced vertical cleft dimple at its center",
    "small and delicate": "small delicate pointed chin, narrow and refined, feminine",
    "heart-shaped tip": "chin with a soft heart-shaped point, widening gently above",
    "soft rounded": "soft smoothly rounded chin with a gentle outward curve",
    "gently pointed": "chin narrowing to a gentle soft point",
    "narrow oval": "narrow oval chin with a slightly elongated vertical shape",
    "broad rounded": "broad rounded chin with substantial width and a smooth curve",
    "subtle cleft": "chin with a subtle barely-visible vertical cleft dimple",
    "receding soft": "receding chin that slopes backward softly from the lower lip",
}

# ---------------------------------------------------------------------------
# Cheeks shape expansions
# ---------------------------------------------------------------------------

_CHEEKS_SHAPE: dict[str, str] = {
    "hollow and sculpted": (
        "hollow sunken cheeks with dramatic shadows beneath sharp prominent cheekbones"
    ),
    "wide and broad": "wide broad cheeks giving the face a generous mid-face width",
    "narrow and lean": "narrow lean cheeks with little soft tissue, angular bone visible",
    "sharp prominent": "sharp prominent cheekbones creating strong angular planes in the mid-face",
    "full and warm": "full warm rounded cheeks with generous soft volume in the mid-face",
    "rounded apple": "round apple cheeks that become prominently full and rounded",
    "soft with dimples": "soft full cheeks with visible dimples in the cheek surface",
    "flat and smooth": "flat smooth cheeks with minimal projection, even surface",
    "soft rounded": "softly rounded cheeks with gentle volume and no sharp angles",
    "subtly angular": "mildly angular cheeks with light definition without sharpness",
    "high and defined": "high defined cheekbones creating elegant angular upper-face structure",
}

# ---------------------------------------------------------------------------
# Hair style expansions (terse labels → visual rendering descriptions)
# ---------------------------------------------------------------------------

_HAIR_STYLE: dict[str, str] = {
    "short cropped": "very short cropped hair, close to the scalp, minimal length",
    "side-parted short": "short hair with a clean side part, neatly combed to one side",
    "swept back": "hair swept back away from the face, slicked or pushed rearward",
    "medium layered": "medium-length hair with layered cuts adding movement and texture",
    "medium tousled": "medium-length loosely tousled hair with natural casual waves, deliberately disheveled and unkempt in appearance, not neatly styled or combed",
    "medium side-swept": "medium hair swept to one side with a gentle diagonal flow",
    "shoulder-length straight": "straight hair falling evenly to shoulder level",
    "shoulder-length wavy": "wavy hair with gentle S-curves falling to shoulder level",
    "shoulder-length curtained": "hair parted in the middle, curtained symmetrically to shoulders",
    "long straight": "long straight hair falling below the shoulders, sleek and smooth",
    "long wavy": "long hair with flowing natural waves, loose and full",
    "long layered": "long hair with multiple layered cuts, movement and varied lengths",
    "long curly": "long hair with large loose curls cascading down",
    "tight curls": "tight densely coiled spring-like curls, high-volume",
    "loose curls": "loose relaxed curls with wide open spiral shapes",
    "coily natural": "tight coily natural texture, dense springy coils",
    "afro": "large natural afro, full round symmetrical shape radiating outward",
    "afro puff": "hair pulled up into a large round afro puff on top",
    "twist-out": "defined twist-out pattern: elongated coils from two-strand twists",
    "low bun": "hair gathered into a neat low bun at the nape of the neck",
    "high bun": "hair pulled up into a tight high bun on top of the head",
    "top knot": "hair gathered into a messy or neat knot at the very top of the head",
    "half-up half-down": "top half of hair visibly pulled back and secured away from the face (pinned or tied), bottom half falling loose — the upper section is clearly up, NOT fully down",
    "pixie cut": "short pixie cut: very short sides and back, slightly longer on top",
    "textured pixie": "short textured pixie cut with deliberately disheveled top",
    "bob straight": "chin-length blunt-cut bob, straight and smooth, even all around",
    "bob wavy": "chin-length bob with soft waves",
    "inverted bob": "bob that is shorter at the back and longer at the front",
    "blunt bob": "blunt-edge bob with a sharp even cut, no layers",
    "braided": "hair gathered into one or several braids",
    "cornrows": "tight cornrow braids running in parallel rows flat against the scalp",
    "locs": "natural dreadlocks: rope-like matted strands hanging down",
    "locs updo": "dreadlocks gathered and pinned up in an updo style",
    "slicked back": "hair slicked straight back away from the forehead with product",
    "undercut": "shaved or very short sides with longer hair on top",
    "ponytail sleek": "smooth sleek hair gathered into a ponytail",
    "ponytail curly": "curly hair gathered into a high or low ponytail",
    "turban wrapped": "hair wrapped in a turban-style cloth wrap",
    "traditional head wrap": "hair covered in a traditional fabric head wrap",
    "gele head wrap": "hair in a gele-style formal Nigerian head wrap",
    "hijab draped": "hair covered with a draped hijab headscarf",
    "wrapped crown updo": "hair wrapped and pinned into a crown-style updo",
    "bald": "completely bald head, no hair visible",
    "bald on top with close-cropped sides": "bald on top with short closely cropped hair on sides",
    "buzz cut": "uniformly very short buzz-cut hair all over the head",
    "fade cut": "hair with a fade: very short at the sides gradually longer toward top",
    "tapered sides": "hair with tapered sides that gradually blend into longer top",
    "textured quiff": "hair styled into a voluminous quiff at the front with texture",
    "pompadour": "hair styled into a classic high pompadour swept upward at the front",
    "coiled updo": "hair coiled and pinned into an elegant updo",
    "french twist": "hair twisted upward and pinned into a vertical french twist",
    "chignon": "hair gathered into a low smooth chignon at the nape",
    "space buns": "hair divided into two buns positioned high on either side of the head",
    "two braids": "hair divided into two braids, one on each side",
    "bantu knots": "Bantu knots hairstyle: hair divided into sections, each section tightly coiled into a small compact round spiral bun sitting flat directly ON TOP of the scalp — the entire head is covered with multiple small round spiral bun mounds close to the scalp; STRICTLY NOT dreadlocks, NOT locs, NOT rope-like hanging strands — the knots are flat coiled round buns against the head, with soft loose curly tendrils framing the face and hairline",
}

# ---------------------------------------------------------------------------
# Accessory expansions — enrich terse names with rendering detail
# ---------------------------------------------------------------------------

_ACCESSORY: dict[str, str] = {
    "tie": "formal necktie knotted at the collar",
    "bow tie": "formal bow tie at the collar",
    "corporate beard": "neatly trimmed short corporate beard, professional and well-groomed",
    "chevron mustache": "thick chevron mustache with straight-cut ends spanning above the lip",
    "french beard": "pointed French goatee beard: chin strip and thin connecting mustache",
    "wristwatch": "a wristwatch clearly strapped on the wrist",
    "analog wristwatch": "classic analog wristwatch with a round face on the wrist",
    "sport watch": "sport watch with chunky case on the wrist",
    "dress watch": "slim elegant dress watch on the wrist",
    "minimalist wristwatch": "slim wristwatch with a clean round face strapped on the wrist, clearly visible",
    "prominent wristwatch on wrist": "a large prominent wristwatch strapped on the left wrist, clearly visible",
    "thin-framed rectangular glasses": "thin metal rectangular-framed glasses sitting on the nose bridge",
    "round wire-rimmed glasses": "delicate round wire-rimmed glasses on the nose bridge",
    "simple pendant necklace over collar": "a simple pendant necklace draped over the collar, visible at the neckline",
    "braided leather bracelet on wrist": "a braided leather bracelet wrapped around the wrist, clearly visible",
    "visible ear cuff on upper ear": "a decorative ear cuff clipped to the upper ear cartilage, clearly visible",
    "chunky sport watch on wrist": "chunky bold sport watch on the wrist",
    "pair of earrings": "a matching pair of earrings in both ears",
    "stud earrings": "small stud earrings in both earlobes",
    "hoop earrings": "circular hoop earrings in both ears",
    "drop earrings": "hanging drop earrings dangling below the earlobes",
    "statement earrings": "large bold statement earrings",
    "ear cuff": "decorative ear cuff on the upper ear cartilage",
    "necklace": "necklace worn around the neck",
    "pendant necklace": "a pendant necklace with a charm hanging at the chest",
    "choker": "close-fitting choker necklace around the neck",
    "eyeglasses": "eyeglasses with frames sitting on the nose",
    "thick-framed glasses": "thick bold-framed eyeglasses",
    "thin metal glasses": "thin minimalist metal-framed glasses",
    "round glasses": "round circular-framed glasses",
    "rectangular glasses": "rectangular-framed glasses",
    "sunglasses": "sunglasses with tinted lenses",
    "headband": "a headband across the top of the head",
    "hair clip": "a decorative hair clip holding part of the hair",
    "scarf": "a scarf loosely draped around the neck",
    "pocket square": "a pocket square tucked into a jacket breast pocket",
    "lapel pin": "a small lapel pin on the jacket lapel",
    "nose ring": "a small nose ring or stud piercing",
    "glasses": "eyeglasses with clearly visible frames on the nose bridge",
    "tinted glasses": "glasses with lightly tinted semi-transparent lenses in a frame on the nose",
    "tinted rimless glasses": "rimless glasses with subtly tinted lenses clipped to the nose bridge",
    "patterned scarf": "a scarf with a visible decorative pattern draped loosely around the neck",
    "silk scarf": "a smooth shiny silk scarf loosely knotted or draped at the neck",
    "discreet lapel pin": "a small pin clearly attached to the lapel of a jacket, visible against the fabric",
    "enamel pin": "a small colorful enamel pin clipped to the lapel or collar",
    "hair decoration": "a decorative ornamental hair accessory visible in the hair",
    "hearing aid": "a clearly visible hearing aid device worn on the ear",
    "subtle face jewel": "a small glittering rhinestone gem placed on the cheekbone, catching light",
    "traditional head wrap accessory": "a large decorative brooch pinned prominently to a fabric head wrap",
    "woven bracelet": "a colorful handwoven fabric bracelet wrapped around the wrist",
    "cuff bracelet": "a wide rigid metal cuff bracelet clasped around the wrist",
    "watch": "a wristwatch on the wrist",
    "geometric earrings": "bold geometric-shaped earrings with angular abstract forms hanging from the ears",
    "bold geometric earrings": "large bold geometric-shaped earrings with strong angular or abstract forms, clearly visible hanging from the earlobes",
    "choker necklace": "a tight close-fitting choker necklace sitting high on the neck",
    "classic dress watch on wrist": "a slim elegant classic dress watch clearly visible on the wrist",
    "tie clip": "a polished metal tie clip bar clasped horizontally across the tie at mid-chest, clearly visible",
    "layered necklaces": "multiple necklaces of varying lengths layered together at the chest",
    "statement necklace": "a large bold statement necklace as a focal point at the neckline",
}

# ---------------------------------------------------------------------------
# Enrichment engine
# ---------------------------------------------------------------------------

_FACE_PROPERTY_MAPS: dict[str, dict[str, str]] = {
    "eye_shape": _EYE_SHAPE,
    "nose_shape": _NOSE_SHAPE,
    "brows_style": _BROWS_STYLE,
    "chin_shape": _CHIN_SHAPE,
    "cheeks_shape": _CHEEKS_SHAPE,
}

_STYLE_PROPERTY_MAPS: dict[str, dict[str, str]] = {
    "hair_style": _HAIR_STYLE,
}

_PROPERTY_MAPS: dict[str, dict[str, str]] = {
    **_FACE_PROPERTY_MAPS,
    **_STYLE_PROPERTY_MAPS,
}


def _enrich_skin_tone(hex_val: str) -> str:
    """Return 'label (HEX)' — adds human-readable label to skin tone hex."""
    label = _SKIN_TONE_LABELS.get(hex_val.upper())
    if label:
        return f"exact skin tone — {label}"
    return hex_val


def _enrich_accessories(accessories: dict | str) -> dict | str:
    """Expand terse accessory names to richer visual descriptions."""
    if isinstance(accessories, dict):
        return {
            _ACCESSORY.get(name.lower(), name): desc if desc and desc != name else ""
            for name, desc in accessories.items()
        }
    return accessories


def _enrich_appearance(appearance: dict) -> dict:
    """Apply visual expansions to structural properties in appearance dict."""
    enriched = dict(appearance)

    # Structural property label → rich description
    for prop, lookup in _PROPERTY_MAPS.items():
        val = enriched.get(prop)
        if isinstance(val, str) and val:
            enriched[prop] = lookup.get(val.lower(), val)

    # Skin tone: hex → label (hex)
    skin = enriched.get("skin_tone")
    if isinstance(skin, str) and skin.startswith("#"):
        enriched["skin_tone"] = _enrich_skin_tone(skin)

    # Accessories: terse name → visual description
    accessories = enriched.get("accessories")
    if accessories:
        enriched["accessories"] = _enrich_accessories(accessories)

    return enriched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_persona(persona: dict) -> dict:
    """Return a visual-only persona dict suitable for the image prompt.

    Strips text-heavy fields, then enriches structural property labels with
    detailed visual descriptions so the image model renders them accurately.
    """
    visual = visual_only_persona(persona)
    visual["appearance"] = _enrich_appearance(visual.get("appearance", {}))
    # Non-binary: explicitly enforce androgynous gender-neutral rendering
    if visual.get("gender") == "non-binary":
        visual["gender"] = (
            "non-binary — strictly androgynous, gender-neutral presentation: "
            "absolutely NO beard, NO stubble, NO mustache, NO prominent Adam's apple, NO strong masculine jawline, NO heavy brow ridge, NO broad masculine shoulders; "
            "absolutely NO feminine makeup, NO mascara, NO eyeshadow, NO lipstick, NO blush, NO gendered styling or adornment; "
            "soft symmetrical neutral facial bone structure with intermediate subtle features — "
            "face MUST read as completely androgynous, neither male nor female, deliberately ambiguous to any observer; "
            "photorealistic rendering MUST use soft intermediate bone structure — no angular masculine jaw, no prominent brow ridge, no feminine softness or makeup; "
            "naturally smooth skin, neutral medium-weight brows, purely androgynous facial geometry that reads as neither male nor female in a realistic photograph"
        )
    return visual
