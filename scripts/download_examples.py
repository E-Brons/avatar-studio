"""Download celebrity example folders: persona.yml + portrait image.

Uses DuckDuckGo Images to find a portrait photo for each celebrity.
Creates assets/examples/{folder_name}/ with:
  - persona.yml  (basic personal info; appearance left empty for pipeline)
  - original.jpg (downloaded from DuckDuckGo image search)

Usage:
    python scripts/download_celebrity_examples.py [--dry-run] [--overwrite]

The celebrity list is embedded below.  Edit CELEBRITIES to add/remove entries.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from config.gateway import GatewayClient

    _GATEWAY_AVAILABLE = True
except ImportError:
    _GATEWAY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXAMPLES_DIR = ROOT / "assets" / "examples"

# ── Celebrity list (merged + deduplicated from both provided lists) ───────────

CELEBRITIES: list[dict] = [
    {"name": "Adele", "age": 37, "nationality": "British", "gender": "female"},
    {"name": "Chimamanda Ngozi Adichie", "age": 48, "nationality": "Nigerian", "gender": "female"},
    {"name": "Shaheen Afridi", "age": 26, "nationality": "Pakistani", "gender": "male"},
    {"name": "Malik Al-Ali'e", "age": 22, "nationality": "Yemeni", "gender": "male"},
    {"name": "Arwa Al-Hujaili", "age": 38, "nationality": "Saudi Arabian", "gender": "female"},
    {"name": "Najla Al-Midfa", "age": 46, "nationality": "Emirati", "gender": "female"},
    {"name": "Grand Ayatollah Ali al-Sistani", "age": 95, "nationality": "Iraqi", "gender": "male"},
    {"name": "Travis Alabanza", "age": 30, "nationality": "British", "gender": "non-binary"},
    {"name": "Carlos Alcaraz", "age": 22, "nationality": "Spanish", "gender": "male"},
    {"name": "Sam Altman", "age": 40, "nationality": "American", "gender": "male"},
    {"name": "Tobi Amusan", "age": 29, "nationality": "Nigerian", "gender": "female"},
    {"name": "Ana de Armas", "age": 37, "nationality": "Cuban", "gender": "female"},
    {"name": "Dina Asher-Smith", "age": 30, "nationality": "British", "gender": "female"},
    {"name": "David Attenborough", "age": 99, "nationality": "British", "gender": "male"},
    {"name": "Soufiane El Bakkali", "age": 30, "nationality": "Moroccan", "gender": "male"},
    {"name": "Janani Balasubramanian", "age": 35, "nationality": "Indian", "gender": "non-binary"},
    {"name": "Xiye Bastida", "age": 24, "nationality": "Mexican", "gender": "female"},
    {"name": "Nathalie Becquart", "age": 57, "nationality": "French", "gender": "female"},
    {"name": "Beyoncé", "age": 44, "nationality": "American", "gender": "female"},
    {"name": "Jeff Bezos", "age": 62, "nationality": "American", "gender": "male"},
    {"name": "Joe Biden", "age": 83, "nationality": "American", "gender": "male"},
    {"name": "Justin Bieber", "age": 32, "nationality": "Canadian", "gender": "male"},
    {"name": "Simone Biles", "age": 29, "nationality": "American", "gender": "female"},
    {"name": "Bimini Bon-Boulash", "age": 32, "nationality": "British", "gender": "non-binary"},
    {"name": "Gabriel Boric", "age": 40, "nationality": "Chilean", "gender": "male"},
    {"name": "Sky Brown", "age": 17, "nationality": "British-Japanese", "gender": "female"},
    {"name": "Nayib Bukele", "age": 44, "nationality": "Salvadoran", "gender": "male"},
    {"name": "Bad Bunny", "age": 32, "nationality": "Puerto Rican", "gender": "male"},
    {"name": "Vitalik Buterin", "age": 32, "nationality": "Russian-Canadian", "gender": "male"},
    {"name": "Linda Caicedo", "age": 21, "nationality": "Colombian", "gender": "female"},
    {"name": "Zuzana Čaputová", "age": 52, "nationality": "Slovak", "gender": "female"},
    {"name": "Ino Casablanca", "age": 29, "nationality": "Moroccan", "gender": "male"},
    {"name": "Timothée Chalamet", "age": 30, "nationality": "French", "gender": "male"},
    {"name": "Giga Chicadze", "age": 37, "nationality": "Georgian", "gender": "male"},
    {"name": "Tony Leung Chiu-wai", "age": 63, "nationality": "Hong Kong", "gender": "male"},
    {"name": "Neeraj Chopra", "age": 28, "nationality": "Indian", "gender": "male"},
    {"name": "Priyanka Chopra", "age": 43, "nationality": "Indian", "gender": "female"},
    {"name": "Jay Chou", "age": 47, "nationality": "Taiwanese", "gender": "male"},
    {"name": "Caitlin Clark", "age": 24, "nationality": "American", "gender": "female"},
    {"name": "Jacob Collier", "age": 31, "nationality": "British", "gender": "male"},
    {"name": "Tim Cook", "age": 65, "nationality": "American", "gender": "male"},
    {"name": "Shea Couleé", "age": 37, "nationality": "American", "gender": "non-binary"},
    {"name": "Tyler, the Creator", "age": 35, "nationality": "American", "gender": "male"},
    {"name": "Tom Cruise", "age": 63, "nationality": "American", "gender": "male"},
    {"name": "Emma D'Arcy", "age": 33, "nationality": "British", "gender": "non-binary"},
    {"name": "Dandapani", "age": 48, "nationality": "Australian-Indian", "gender": "female"},
    {"name": "Tsitsi Dangarembga", "age": 50, "nationality": "Zimbabwean", "gender": "female"},
    {"name": "Alphonso Davies", "age": 25, "nationality": "Canadian-Liberian", "gender": "male"},
    {"name": "Viola Davis", "age": 60, "nationality": "American", "gender": "female"},
    {"name": "Olivia Dean", "age": 27, "nationality": "British", "gender": "female"},
    {"name": "Glennon Doyle", "age": 50, "nationality": "American", "gender": "female"},
    {"name": "Drake", "age": 39, "nationality": "Canadian", "gender": "male"},
    {"name": "Billie Eilish", "age": 24, "nationality": "American", "gender": "female"},
    {"name": "Idris Elba", "age": 53, "nationality": "British", "gender": "male"},
    {"name": "Dorian Electra", "age": 33, "nationality": "American", "gender": "non-binary"},
    {"name": "Eminem", "age": 53, "nationality": "American", "gender": "male"},
    {"name": "Recep Tayyip Erdoğan", "age": 72, "nationality": "Turkish", "gender": "male"},
    {"name": "Tobi Eriksen", "age": 22, "nationality": "Danish", "gender": "male"},
    {"name": "Remco Evenepoel", "age": 26, "nationality": "Belgian", "gender": "male"},
    {"name": "Golshifteh Farahani", "age": 42, "nationality": "Iranian-French", "gender": "female"},
    {"name": "Pope Francis", "age": 89, "nationality": "Argentine", "gender": "male"},
    {"name": "Shelly-Ann Fraser-Pryce", "age": 39, "nationality": "Jamaican", "gender": "female"},
    {"name": "Mette Frederiksen", "age": 48, "nationality": "Danish", "gender": "female"},
    {"name": "Bill Gates", "age": 70, "nationality": "American", "gender": "male"},
    {"name": "Coco Gauff", "age": 22, "nationality": "American", "gender": "female"},
    {"name": "Greta Gerwig", "age": 42, "nationality": "American", "gender": "female"},
    {"name": "Selena Gomez", "age": 33, "nationality": "American", "gender": "female"},
    {"name": "Peggy Gou", "age": 34, "nationality": "South Korean", "gender": "female"},
    {"name": "Eileen Gu", "age": 22, "nationality": "Chinese-American", "gender": "female"},
    {"name": "Arda Güler", "age": 21, "nationality": "Turkish", "gender": "male"},
    {"name": "Erling Haaland", "age": 25, "nationality": "Norwegian", "gender": "male"},
    {"name": "Ahmed Hafnaoui", "age": 23, "nationality": "Tunisian", "gender": "male"},
    {"name": "Lewis Hamilton", "age": 41, "nationality": "British", "gender": "male"},
    {"name": "Yuzuru Hanyu", "age": 31, "nationality": "Japanese", "gender": "male"},
    {"name": "Yuval Noah Harari", "age": 50, "nationality": "Israeli", "gender": "male"},
    {"name": "Kamala Harris", "age": 61, "nationality": "American", "gender": "female"},
    {"name": "Shakib Al Hasan", "age": 39, "nationality": "Bangladeshi", "gender": "male"},
    {"name": "Samia Suluhu Hassan", "age": 66, "nationality": "Tanzanian", "gender": "female"},
    {"name": "Sifan Hassan", "age": 33, "nationality": "Ethiopian-Dutch", "gender": "female"},
    {"name": "Angel Haze", "age": 34, "nationality": "American", "gender": "non-binary"},
    {"name": "Son Heung-min", "age": 33, "nationality": "South Korean", "gender": "male"},
    {"name": "Hozier", "age": 36, "nationality": "Irish", "gender": "male"},
    {"name": "Jensen Huang", "age": 63, "nationality": "Taiwanese-American", "gender": "male"},
    {"name": "Fares Ibrahim", "age": 27, "nationality": "Qatari", "gender": "male"},
    {"name": "Hindou Oumarou Ibrahim", "age": 42, "nationality": "Chadian", "gender": "female"},
    {"name": "King Charles III", "age": 77, "nationality": "British", "gender": "male"},
    {"name": "Mahesh Itadi", "age": 29, "nationality": "Indian", "gender": "non-binary"},
    {"name": "Shreyas Iyer", "age": 31, "nationality": "Indian", "gender": "male"},
    {"name": "Ons Jabeur", "age": 31, "nationality": "Tunisian", "gender": "female"},
    {"name": "Bishop T.D. Jakes", "age": 68, "nationality": "American", "gender": "male"},
    {"name": "Katrín Jakobsdóttir", "age": 50, "nationality": "Icelander", "gender": "female"},
    {"name": "LeBron James", "age": 41, "nationality": "American", "gender": "male"},
    {"name": "Xi Jinping", "age": 72, "nationality": "Chinese", "gender": "male"},
    {"name": "Dwayne Johnson", "age": 53, "nationality": "American-Samoan", "gender": "male"},
    {"name": "Bong Joon-ho", "age": 56, "nationality": "South Korean", "gender": "male"},
    {"name": "HoYeon Jung", "age": 31, "nationality": "South Korean", "gender": "female"},
    {"name": "Vinícius Júnior", "age": 25, "nationality": "Brazilian", "gender": "male"},
    {"name": "Kaja Kallas", "age": 48, "nationality": "Estonian", "gender": "female"},
    {"name": "Han Kang", "age": 55, "nationality": "South Korean", "gender": "female"},
    {"name": "Rashid Khan", "age": 27, "nationality": "Afghan", "gender": "male"},
    {"name": "Shah Rukh Khan", "age": 60, "nationality": "Indian", "gender": "male"},
    {"name": "Sherin Khankan", "age": 51, "nationality": "Danish", "gender": "female"},
    {"name": "Hina Rabbani Khar", "age": 48, "nationality": "Pakistani", "gender": "female"},
    {"name": "Angelique Kidjo", "age": 65, "nationality": "Beninese", "gender": "female"},
    {"name": "Chloe Kim", "age": 26, "nationality": "Korean-American", "gender": "female"},
    {"name": "Mina Kimes", "age": 40, "nationality": "American", "gender": "female"},
    {"name": "Patriarch Kirill", "age": 79, "nationality": "Russian", "gender": "male"},
    {"name": "Lydia Ko", "age": 29, "nationality": "New Zealander", "gender": "female"},
    {"name": "Christina Koch", "age": 47, "nationality": "American", "gender": "female"},
    {"name": "Virat Kohli", "age": 37, "nationality": "Indian", "gender": "male"},
    {"name": "Yayoi Kusama", "age": 97, "nationality": "Japanese", "gender": "female"},
    {"name": "Mon Laferte", "age": 42, "nationality": "Latin-American", "gender": "female"},
    {"name": "Dalai Lama", "age": 90, "nationality": "Tibetan", "gender": "male"},
    {"name": "Khaby Lame", "age": 26, "nationality": "Senegalese-Italian", "gender": "male"},
    {"name": "Zara Larsson", "age": 28, "nationality": "Swedish", "gender": "female"},
    {"name": "Rayssa Leal", "age": 18, "nationality": "Brazilian", "gender": "female"},
    {"name": "Charles Leclerc", "age": 28, "nationality": "Monegasque", "gender": "male"},
    {"name": "Ursula von der Leyen", "age": 67, "nationality": "German", "gender": "female"},
    {"name": "Dua Lipa", "age": 30, "nationality": "Albanian", "gender": "female"},
    {"name": "Emmanuel Macron", "age": 48, "nationality": "French", "gender": "male"},
    {"name": "Post Malone", "age": 30, "nationality": "American", "gender": "male"},
    {"name": "Chella Man", "age": 27, "nationality": "American-Chinese", "gender": "non-binary"},
    {"name": "Sanna Marin", "age": 40, "nationality": "Finnish", "gender": "female"},
    {"name": "Kylian Mbappé", "age": 27, "nationality": "French", "gender": "male"},
    {"name": "Thuso Mbedu", "age": 34, "nationality": "South African", "gender": "female"},
    {"name": "Summer McIntosh", "age": 19, "nationality": "Canadian", "gender": "female"},
    {"name": "Kaylee McKeown", "age": 24, "nationality": "Australian", "gender": "female"},
    {"name": "Giorgia Meloni", "age": 49, "nationality": "Italian", "gender": "female"},
    {"name": "Lionel Messi", "age": 38, "nationality": "Argentine", "gender": "male"},
    {"name": "Mads Mikkelsen", "age": 60, "nationality": "Danish", "gender": "male"},
    {"name": "Javier Milei", "age": 55, "nationality": "Argentine", "gender": "male"},
    {"name": "Lin-Manuel Miranda", "age": 46, "nationality": "American", "gender": "male"},
    {"name": "Narendra Modi", "age": 75, "nationality": "Indian", "gender": "male"},
    {"name": "Janelle Monáe", "age": 40, "nationality": "American", "gender": "non-binary"},
    {"name": "Indya Moore", "age": 31, "nationality": "American", "gender": "non-binary"},
    {"name": "Mia Mottley", "age": 60, "nationality": "Barbadian", "gender": "female"},
    {"name": "Wagner Moura", "age": 49, "nationality": "Brazilian", "gender": "male"},
    {"name": "Cillian Murphy", "age": 49, "nationality": "Irish", "gender": "male"},
    {"name": "Sudha Murty", "age": 75, "nationality": "Indian", "gender": "female"},
    {"name": "Elon Musk", "age": 54, "nationality": "South African-American", "gender": "male"},
    {"name": "Satya Nadella", "age": 58, "nationality": "Indian-American", "gender": "male"},
    {"name": "Vanessa Nakate", "age": 29, "nationality": "Ugandan", "gender": "female"},
    {"name": "Nemonte Nenquimo", "age": 39, "nationality": "Ecuadorian", "gender": "female"},
    {"name": "Lando Norris", "age": 26, "nationality": "British", "gender": "male"},
    {"name": "Lupita Nyong'o", "age": 43, "nationality": "Kenyan-Mexican", "gender": "female"},
    {"name": "Michelle Obama", "age": 62, "nationality": "American", "gender": "female"},
    {"name": "Shohei Ohtani", "age": 31, "nationality": "Japanese", "gender": "male"},
    {"name": "Jenna Ortega", "age": 23, "nationality": "American", "gender": "female"},
    {"name": "Naomi Osaka", "age": 28, "nationality": "Japanese", "gender": "female"},
    {"name": "Asisat Oshoala", "age": 31, "nationality": "Nigerian", "gender": "female"},
    {"name": "Deepika Padukone", "age": 40, "nationality": "Indian", "gender": "female"},
    {"name": "Rishabh Pant", "age": 28, "nationality": "Indian", "gender": "male"},
    {"name": "Pedro Pascal", "age": 51, "nationality": "Chilean", "gender": "male"},
    {"name": "Autumn Peltier", "age": 21, "nationality": "Canadian", "gender": "female"},
    {"name": "Oscar Piastri", "age": 25, "nationality": "Australian", "gender": "male"},
    {"name": "Sundar Pichai", "age": 53, "nationality": "Indian-American", "gender": "male"},
    {"name": "Diamond Platnumz", "age": 36, "nationality": "Tanzanian", "gender": "male"},
    {"name": "Florence Pugh", "age": 30, "nationality": "British", "gender": "female"},
    {"name": "Vladimir Putin", "age": 73, "nationality": "Russian", "gender": "male"},
    {"name": "Ke Huy Quan", "age": 54, "nationality": "Vietnamese", "gender": "male"},
    {"name": "Cyril Ramaphosa", "age": 73, "nationality": "South African", "gender": "male"},
    {"name": "Bella Ramsey", "age": 22, "nationality": "British", "gender": "non-binary"},
    {"name": "Maria Ressa", "age": 62, "nationality": "Filipino", "gender": "female"},
    {"name": "Sha'Carri Richardson", "age": 26, "nationality": "American", "gender": "female"},
    {"name": "Rihanna", "age": 38, "nationality": "Barbadian", "gender": "female"},
    {"name": "Margot Robbie", "age": 35, "nationality": "Australian", "gender": "female"},
    {"name": "Cristiano Ronaldo", "age": 41, "nationality": "Portuguese", "gender": "male"},
    {"name": "Arundhati Roy", "age": 64, "nationality": "Indian", "gender": "female"},
    {"name": "Holger Rune", "age": 23, "nationality": "Danish", "gender": "male"},
    {"name": "William Ruto", "age": 59, "nationality": "Kenyan", "gender": "male"},
    {"name": "Aryna Sabalenka", "age": 27, "nationality": "Belarusian", "gender": "female"},
    {"name": "Dua Saleh", "age": 31, "nationality": "Sudanese", "gender": "non-binary"},
    {"name": "Mohammed bin Salman", "age": 40, "nationality": "Saudi", "gender": "male"},
    {"name": "Tiwa Savage", "age": 46, "nationality": "Nigerian", "gender": "female"},
    {"name": "Travis Scott", "age": 34, "nationality": "American", "gender": "male"},
    {"name": "Yara Shahidi", "age": 26, "nationality": "American", "gender": "female"},
    {"name": "Anoushka Shankar", "age": 44, "nationality": "Indian", "gender": "female"},
    {"name": "Sri Sri Ravi Shankar", "age": 69, "nationality": "Indian", "gender": "male"},
    {"name": "Ed Sheeran", "age": 35, "nationality": "British", "gender": "male"},
    {"name": "Claudia Sheinbaum", "age": 63, "nationality": "Mexican", "gender": "female"},
    {"name": "Jay Shetty", "age": 38, "nationality": "British", "gender": "male"},
    {"name": "Mikaela Shiffrin", "age": 31, "nationality": "American", "gender": "female"},
    {"name": "Vandana Shiva", "age": 73, "nationality": "Indian", "gender": "female"},
    {"name": "Lula da Silva", "age": 80, "nationality": "Brazilian", "gender": "male"},
    {"name": "Ranveer Singh", "age": 40, "nationality": "Indian", "gender": "male"},
    {"name": "Hamed Sinno", "age": 37, "nationality": "Lebanese", "gender": "non-binary"},
    {"name": "Alexander Skarsgård", "age": 49, "nationality": "Swedish", "gender": "male"},
    {"name": "Sam Smith", "age": 33, "nationality": "British", "gender": "non-binary"},
    {"name": "Steven Spielberg", "age": 79, "nationality": "American", "gender": "male"},
    {"name": "Sid Sriram", "age": 35, "nationality": "Indian", "gender": "male"},
    {"name": "Keir Starmer", "age": 63, "nationality": "British", "gender": "male"},
    {"name": "Ayra Starr", "age": 23, "nationality": "Nigerian", "gender": "female"},
    {"name": "Stromae", "age": 41, "nationality": "Belgian", "gender": "male"},
    {"name": "Lisa Su", "age": 56, "nationality": "Taiwanese-American", "gender": "female"},
    {"name": "Tash Sultana", "age": 30, "nationality": "Australian", "gender": "non-binary"},
    {"name": "Iga Świątek", "age": 24, "nationality": "Polish", "gender": "female"},
    {"name": "Taylor Swift", "age": 36, "nationality": "American", "gender": "female"},
    {"name": "Anya Taylor-Joy", "age": 29, "nationality": "Argentine", "gender": "female"},
    {"name": "Greta Thunberg", "age": 23, "nationality": "Swedish", "gender": "female"},
    {"name": "Bola Tinubu", "age": 74, "nationality": "Nigerian", "gender": "male"},
    {"name": "Olga Tokarczuk", "age": 64, "nationality": "Polish", "gender": "female"},
    {"name": "Guillermo del Toro", "age": 61, "nationality": "Mexican", "gender": "male"},
    {"name": "Justin Trudeau", "age": 54, "nationality": "Canadian", "gender": "male"},
    {"name": "Tyla", "age": 24, "nationality": "South African", "gender": "female"},
    {"name": "Neil deGrasse Tyson", "age": 67, "nationality": "American", "gender": "male"},
    {"name": "Alok Vaid-Menon", "age": 34, "nationality": "American", "gender": "non-binary"},
    {"name": "Leo Varadkar", "age": 47, "nationality": "Irish", "gender": "male"},
    {"name": "Sasha Velour", "age": 38, "nationality": "American", "gender": "non-binary"},
    {"name": "Taika Waititi", "age": 50, "nationality": "New Zealander", "gender": "male"},
    {"name": "Morgan Wallen", "age": 32, "nationality": "American", "gender": "male"},
    {"name": "Abby Wambach", "age": 45, "nationality": "American", "gender": "female"},
    {"name": "Jackson Wang", "age": 32, "nationality": "Hong Kong", "gender": "male"},
    {"name": "Alex Warren", "age": 25, "nationality": "American", "gender": "male"},
    {"name": "The Weeknd", "age": 36, "nationality": "Canadian", "gender": "male"},
    {"name": "Tang Wei", "age": 46, "nationality": "Chinese", "gender": "female"},
    {"name": "Ai Weiwei", "age": 68, "nationality": "Chinese", "gender": "male"},
    {"name": "Justin Welby", "age": 70, "nationality": "British", "gender": "male"},
    {"name": "Rowan Williams", "age": 75, "nationality": "British", "gender": "male"},
    {"name": "Jamie Windust", "age": 29, "nationality": "British", "gender": "non-binary"},
    {"name": "Cameron Winter", "age": 26, "nationality": "American", "gender": "male"},
    {"name": "Lamine Yamal", "age": 18, "nationality": "Spanish", "gender": "male"},
    {"name": "Michelle Yeoh", "age": 63, "nationality": "Malaysian", "gender": "female"},
    {"name": "Lola Young", "age": 25, "nationality": "British", "gender": "female"},
    {"name": "Malala Yousafzai", "age": 28, "nationality": "Pakistani", "gender": "female"},
    {"name": "Shaykh Hamza Yusuf", "age": 66, "nationality": "American", "gender": "male"},
    {"name": "Volodymyr Zelenskyy", "age": 48, "nationality": "Ukrainian", "gender": "male"},
    {"name": "Pan Zhanle", "age": 21, "nationality": "Chinese", "gender": "male"},
    {"name": "Mark Zuckerberg", "age": 41, "nationality": "American", "gender": "male"},
]


# ── helpers ───────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


_MIN_DIM = 768  # minimum width and height

# ── portrait validation ───────────────────────────────────────────────────────

_VALIDATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "passes": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["passes", "reason"],
    "additionalProperties": False,
}

_VALIDATION_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _VALIDATION_SCHEMA}}

_VALIDATION_SYSTEM = (
    "You are a strict portrait photo quality checker for avatar generation. "
    "Evaluate the image against all criteria and return a single JSON result."
)


def _validate_portrait(
    image_bytes: bytes,
    name: str,
    gateway_url: str,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Ask the vision LLM whether a portrait image meets quality requirements.

    Criteria:
    - Face is roughly frontal (slight tilts OK, no extreme side profiles)
    - Face occupies >= 30% of the frame
    - Face is not obscured by hands, objects, sunglasses, or opaque eyewear (hair is allowed)
    - Image is sharp and high quality (not blurry, noisy, or heavily processed)
    - Image is in full color (not grayscale, sepia, or monochromatic)
    - Image is a real photograph (not illustration, painting, CGI, cartoon, etc.)
    - No watermarks, text overlays, or logos visible

    Returns (passes, reason).  On LLM failure returns (True, "validation skipped")
    so the image is accepted rather than silently discarded.
    """
    if not _GATEWAY_AVAILABLE:
        return True, "validation skipped (gateway unavailable)"

    prompt = (
        f"Examine this portrait photo of {name}.\n\n"
        "Evaluate ALL of the following criteria:\n"
        "1. Face is roughly frontal — slight tilts or turns are acceptable; only reject clear side profiles or extreme angles\n"
        "2. Face fills at least 30% of the image frame\n"
        "3. Face is unobstructed — not covered by hands, microphones, large logos, or any other object; "
        "sunglasses or tinted/opaque eyewear are not allowed (clear/thin glasses frames are fine); "
        "own hair partially falling over the face is acceptable\n"
        "4. Image quality is high — sharp focus, good exposure, not pixelated or heavily compressed\n"
        "5. Image is in full color — not grayscale, sepia, black-and-white, or monochromatic "
        "(e.g. brown-toned, blue-toned, or any dominant single-hue tint)\n"
        "6. Image is a real photograph — not an illustration, painting, drawing, cartoon, CGI render, "
        "or any other non-photographic artwork\n"
        "7. No visible watermarks, text overlays, logos, or copyright stamps on the face\n\n"
        "Set passes=true only if ALL seven criteria are met. "
        "Set passes=false if any criterion fails, and state which one(s) in reason."
    )

    try:
        raw = GatewayClient(gateway_url).image_inspector(
            image_bytes,
            _VALIDATION_SYSTEM,
            prompt,
            timeout=timeout,
            output_config=_VALIDATION_OUTPUT_CONFIG,
        )
    except Exception as exc:
        logger.warning("  portrait validation LLM call failed: %s", exc)
        return True, f"validation skipped ({exc})"

    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        result = json.loads(text)
        passes = bool(result.get("passes", True))
        reason = str(result.get("reason", ""))
        return passes, reason
    except json.JSONDecodeError, AttributeError:
        return True, "validation skipped (parse error)"


def _folder_name(name: str) -> str:
    """Convert display name to snake_case folder name."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s


def _duckduckgo_image_candidates(name: str) -> list[tuple[str, int, int]]:
    """Return a list of (url, width, height) candidates from DuckDuckGo Images.

    Pre-filters to images where both dimensions are >= _MIN_DIM.
    Falls back to all results if none meet the size threshold.
    """
    query = f"{name} portrait"

    encoded = urllib.parse.quote(query)
    init_url = f"https://duckduckgo.com/?q={encoded}&iax=images&ia=images"
    req0 = urllib.request.Request(init_url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req0, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("DuckDuckGo init request failed for %r: %s", name, exc)
        return []

    vqd_match = re.search(r'vqd=([\'"])([^\'"]+)\1', html)
    if not vqd_match:
        vqd_match = re.search(r'"vqd"\s*:\s*"([^"]+)"', html)
    if not vqd_match:
        logger.warning("DuckDuckGo: no VQD token found for %r", name)
        return []
    vqd = vqd_match.group(2) if vqd_match.lastindex >= 2 else vqd_match.group(1)

    params = {
        "l": "us-en",
        "o": "json",
        "q": query,
        "vqd": vqd,
        "f": ",,,,,",
        "p": "1",
    }
    img_url = "https://duckduckgo.com/i.js?" + urllib.parse.urlencode(params)
    req1 = urllib.request.Request(
        img_url, headers={**_HEADERS, "Referer": "https://duckduckgo.com/"}
    )
    try:
        with urllib.request.urlopen(req1, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("DuckDuckGo image search failed for %r: %s", name, exc)
        return []

    results = data.get("results", [])
    if not results:
        logger.warning("DuckDuckGo: no image results for %r", name)
        return []

    candidates: list[tuple[str, int, int]] = []
    fallback: list[tuple[str, int, int]] = []
    for r in results[:20]:
        url = r.get("image", "")
        if not url:
            continue
        w = int(r.get("width", 0) or 0)
        h = int(r.get("height", 0) or 0)
        if w >= _MIN_DIM and h >= _MIN_DIM:
            candidates.append((url, w, h))
        else:
            fallback.append((url, w, h))

    # Return qualifying images first; append fallbacks so we always have something to try.
    return candidates + fallback


def _fetch_image_bytes(url: str) -> bytes | None:
    """Download *url* and return raw bytes, or None on failure."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as exc:
        logger.debug("  fetch failed for %s: %s", url.split("/")[-1][:60], exc)
        return None


def _persona_yml(celeb: dict, appearance: dict | None = None) -> str:
    """Return persona.yml content for *celeb*, with LLM-extracted appearance when available."""
    app = appearance or {}

    bg_color = app.pop("suggested_bg_color", "#4A90D9")
    zodiac = app.pop("zodiac", "unknown")
    religion = app.pop("religion", "unknown")

    # Build structured appearance section from flat LLM dict.
    app_section: dict = {}
    for key in ("skin_tone", "skin_texture", "presentation", "hair_style", "hair_note"):
        if app.get(key):
            app_section[key] = app[key]

    if app.get("hair_color_base"):
        app_section["hair_color"] = {
            "hex_base": app["hair_color_base"],
            "hex_shadow": app.get("hair_color_shadow", app["hair_color_base"]),
        }
    if app.get("eye_color_iris"):
        app_section["eye_color"] = {
            "hex_iris": app["eye_color_iris"],
            "hex_pupil": app.get("eye_color_pupil", "#0A0A0A"),
        }
    for key in (
        "brows_color",
        "eye_shape",
        "brows_style",
        "nose_shape",
        "chin_shape",
        "cheeks_shape",
    ):
        if app.get(key):
            app_section[key] = app[key]
    if app.get("clothing"):
        app_section["clothing"] = app["clothing"]
    if app.get("accessories"):
        app_section["accessories"] = app["accessories"]

    data = {
        "personal": {
            "name": celeb["name"],
            "gender": celeb["gender"],
            "age": celeb["age"],
            "nationality": celeb["nationality"],
            "religion": religion,
            "zodiac": zodiac,
        },
        "style": {
            "bg_color": bg_color,
            "fg_color": "#FFFFFF",
        },
        "appearance": app_section,
    }
    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ── LLM appearance extraction ─────────────────────────────────────────────────

_APPEARANCE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "skin_tone": {"type": "string", "description": "Dominant skin tone #RRGGBB hex"},
        "skin_texture": {
            "type": "string",
            "description": "e.g. smooth clear, oily, textured, matte",
        },
        "presentation": {
            "type": "string",
            "description": "Visual gender presentation: masculine-presenting, feminine-presenting, androgynous, gender-neutral",
        },
        "hair_style": {"type": "string", "description": "Detailed hair style description"},
        "hair_note": {
            "type": "string",
            "description": "CRITICAL note about distinctive hair features (length, shave pattern, texture). Empty string if unremarkable.",
        },
        "hair_color_base": {"type": "string", "description": "Base hair color #RRGGBB"},
        "hair_color_shadow": {"type": "string", "description": "Shadow/darker tone #RRGGBB"},
        "eye_shape": {
            "type": "string",
            "description": "e.g. hooded, almond, round, upturned, monolid, deep-set",
        },
        "eye_color_iris": {"type": "string", "description": "Iris color #RRGGBB"},
        "eye_color_pupil": {
            "type": "string",
            "description": "Pupil color #RRGGBB — typically very dark",
        },
        "brows_style": {
            "type": "string",
            "description": "e.g. angular defined, arched thin, straight thick, bushy natural",
        },
        "brows_color": {"type": "string", "description": "Brow color #RRGGBB"},
        "nose_shape": {
            "type": "string",
            "description": "Brief descriptor e.g. broad rounded, narrow straight, button",
        },
        "chin_shape": {
            "type": "string",
            "description": "Brief descriptor e.g. broad rounded, pointed, square",
        },
        "cheeks_shape": {
            "type": "string",
            "description": "Brief descriptor e.g. high prominent, subtly angular, full round",
        },
        "clothing": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Visible garment name → dominant color #RRGGBB",
        },
        "accessories": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Accessory name → visual description",
        },
        "suggested_bg_color": {
            "type": "string",
            "description": "Background color #RRGGBB that would complement this subject",
        },
        "zodiac": {
            "type": "string",
            "description": "Zodiac sign if you know this celebrity's birthdate; otherwise 'unknown'",
        },
        "religion": {
            "type": "string",
            "description": "Religion if publicly known for this person; otherwise 'unknown'",
        },
    },
    "required": [
        "skin_tone",
        "skin_texture",
        "presentation",
        "hair_style",
        "hair_note",
        "hair_color_base",
        "hair_color_shadow",
        "eye_shape",
        "eye_color_iris",
        "eye_color_pupil",
        "brows_style",
        "brows_color",
        "nose_shape",
        "chin_shape",
        "cheeks_shape",
        "clothing",
        "accessories",
        "suggested_bg_color",
        "zodiac",
        "religion",
    ],
    "additionalProperties": False,
}

_APPEARANCE_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _APPEARANCE_SCHEMA}}

_APPEARANCE_SYSTEM = (
    "You are a meticulous visual appearance analyst for AI avatar generation. "
    "You will be shown a portrait photo of a public figure. "
    "Extract precise visual details from the image — use hex codes for all colors. "
    "For zodiac and religion, draw on your knowledge of this person; if genuinely unknown, use 'unknown'. "
    "Be specific and accurate. Do not guess colors — report what you actually observe."
)


def _extract_appearance(
    image_bytes: bytes,
    celeb: dict,
    gateway_url: str,
    timeout: int = 90,
) -> dict | None:
    """Call the vision LLM to extract appearance fields from a portrait image.

    Returns a flat dict matching _APPEARANCE_SCHEMA, or None on failure.
    """
    if not _GATEWAY_AVAILABLE:
        logger.warning("  GatewayClient not available — skipping LLM appearance extraction")
        return None

    name, age, nat, gender = celeb["name"], celeb["age"], celeb["nationality"], celeb["gender"]
    prompt = (
        f"This is a portrait photo of {name} — {nat}, {gender}, age {age}.\n\n"
        "Carefully examine the image and fill in every field of the appearance schema.\n"
        "Use accurate #RRGGBB hex codes for all color fields based on what you observe.\n"
        "For clothing and accessories, describe only what is clearly visible."
    )

    try:
        raw = GatewayClient(gateway_url).image_inspector(
            image_bytes,
            _APPEARANCE_SYSTEM,
            prompt,
            timeout=timeout,
            output_config=_APPEARANCE_OUTPUT_CONFIG,
        )
    except Exception as exc:
        logger.warning("  LLM appearance extraction failed for %r: %s", name, exc)
        return None

    # Strip code fences if present.
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            logger.info("  extracted appearance via LLM")
            return result
    except json.JSONDecodeError as exc:
        logger.warning("  LLM response JSON parse failed: %s — raw=%r", exc, raw[:200])

    return None


# ── main ──────────────────────────────────────────────────────────────────────

_RESULT_OK = "ok"
_RESULT_SKIP = "skip"
_RESULT_FAIL = "fail"


def _process_celeb(
    celeb: dict,
    overwrite: bool,
    gateway_url: str,
    skip_llm: bool,
    personas_only: bool,
    dry_run: bool,
) -> str:
    """Process a single celebrity — download image + write persona.yml.

    Returns one of _RESULT_OK / _RESULT_SKIP / _RESULT_FAIL.
    """
    folder = EXAMPLES_DIR / _folder_name(celeb["name"])
    persona_path = folder / "persona.yml"
    image_path = folder / "original.jpg"

    if personas_only:
        if not image_path.exists():
            logger.info("skip  %s (no original.jpg)", celeb["name"])
            return _RESULT_SKIP
        if persona_path.exists() and not overwrite:
            logger.info("skip  %s (persona.yml exists)", celeb["name"])
            return _RESULT_SKIP
        logger.info("── %s ── (persona only)", celeb["name"])
        if dry_run:
            logger.info("  [dry-run] would write persona.yml")
            return _RESULT_OK
        appearance: dict | None = None
        if not skip_llm:
            try:
                appearance = _extract_appearance(image_path.read_bytes(), celeb, gateway_url)
            except Exception as exc:
                logger.warning("  %s: appearance extraction error: %s", celeb["name"], exc)
        persona_path.write_text(_persona_yml(celeb, appearance))
        logger.info(
            "  %s: wrote persona.yml%s",
            celeb["name"],
            " (with LLM appearance)" if appearance else " (appearance empty)",
        )
        return _RESULT_OK

    if folder.exists() and not overwrite and persona_path.exists() and image_path.exists():
        logger.info("skip  %s (already complete)", celeb["name"])
        return _RESULT_SKIP

    logger.info("── %s ──", celeb["name"])

    if dry_run:
        logger.info("  [dry-run] would create %s", folder.relative_to(ROOT))
        return _RESULT_OK

    folder.mkdir(parents=True, exist_ok=True)

    # Find and validate a portrait image, trying DuckDuckGo candidates in order.
    accepted_bytes: bytes | None = None
    if overwrite or not image_path.exists():
        candidates = _duckduckgo_image_candidates(celeb["name"])
        if not candidates:
            logger.warning("  no image candidates found for %s", celeb["name"])
            return _RESULT_FAIL

        for idx, (url, w, h) in enumerate(candidates[:10]):
            img_bytes = _fetch_image_bytes(url)
            if img_bytes is None:
                logger.debug("  %s candidate %d: fetch failed", celeb["name"], idx + 1)
                continue

            if skip_llm:
                accepted_bytes = img_bytes
                logger.info(
                    "  %s candidate %d (%dx%d): accepted (validation skipped)",
                    celeb["name"],
                    idx + 1,
                    w,
                    h,
                )
                break

            passes, reason = _validate_portrait(img_bytes, celeb["name"], gateway_url)
            if passes:
                accepted_bytes = img_bytes
                logger.info(
                    "  %s candidate %d (%dx%d): PASS — %s", celeb["name"], idx + 1, w, h, reason
                )
                break
            else:
                logger.info(
                    "  %s candidate %d (%dx%d): FAIL — %s", celeb["name"], idx + 1, w, h, reason
                )

        if accepted_bytes is None:
            logger.warning(
                "  no valid portrait found for %s after trying all candidates", celeb["name"]
            )
            return _RESULT_FAIL

        image_path.write_bytes(accepted_bytes)
        logger.info("  %s: saved original.jpg", celeb["name"])
    else:
        accepted_bytes = (
            image_path.read_bytes() if (overwrite or not persona_path.exists()) else None
        )

    # Extract appearance from the portrait image via LLM.
    appearance = None
    if not skip_llm and (overwrite or not persona_path.exists()):
        image_bytes_for_llm = accepted_bytes or (
            image_path.read_bytes() if image_path.exists() else None
        )
        if image_bytes_for_llm:
            try:
                appearance = _extract_appearance(image_bytes_for_llm, celeb, gateway_url)
            except Exception as exc:
                logger.warning("  %s: appearance extraction error: %s", celeb["name"], exc)

    # Write persona.yml (always refresh if overwrite or missing).
    if overwrite or not persona_path.exists():
        persona_path.write_text(_persona_yml(celeb, appearance))
        logger.info(
            "  %s: wrote persona.yml%s",
            celeb["name"],
            " (with LLM appearance)" if appearance else " (appearance empty)",
        )

    return _RESULT_OK


def run(
    dry_run: bool = False,
    overwrite: bool = False,
    gateway_url: str = "http://127.0.0.1:4096",
    skip_llm: bool = False,
    personas_only: bool = False,
    workers: int = 8,
) -> None:
    ok = skipped = failed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_celeb, celeb, overwrite, gateway_url, skip_llm, personas_only, dry_run
            ): celeb
            for celeb in CELEBRITIES
        }
        for future in as_completed(futures):
            celeb = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.error("  %s: unhandled error: %s", celeb["name"], exc)
                result = _RESULT_FAIL
            if result == _RESULT_OK:
                ok += 1
            elif result == _RESULT_SKIP:
                skipped += 1
            else:
                failed += 1

    logger.info("")
    logger.info(
        "Done. ok=%d  skipped=%d  failed=%d  total=%d", ok, skipped, failed, len(CELEBRITIES)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download celebrity example folders")
    parser.add_argument("--dry-run", action="store_true", help="List what would be done")
    parser.add_argument(
        "--overwrite", action="store_true", help="Re-download even if folder exists"
    )
    parser.add_argument(
        "--gateway",
        default="http://127.0.0.1:4096",
        help="LLM Gateway URL for appearance extraction (default: http://127.0.0.1:4096)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM appearance extraction and write empty appearance",
    )
    parser.add_argument(
        "--personas-only",
        action="store_true",
        help="Skip image download — only (re)generate persona.yml from existing original.jpg",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel download workers (default: 8)",
    )
    args = parser.parse_args()
    run(
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        gateway_url=args.gateway,
        skip_llm=args.skip_llm,
        personas_only=args.personas_only,
        workers=args.workers,
    )
