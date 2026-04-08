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
    {"name": "Dandapani", "age": 48, "nationality": "Australian-Indian", "gender": "male"},
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
    # ── Sport – Tennis ───────────────────────────────────────────────────────
    {"name": "Novak Djokovic", "age": 37, "nationality": "Serbian", "gender": "male"},
    {"name": "Rafael Nadal", "age": 38, "nationality": "Spanish", "gender": "male"},
    {"name": "Roger Federer", "age": 43, "nationality": "Swiss", "gender": "male"},
    {"name": "Jannik Sinner", "age": 23, "nationality": "Italian", "gender": "male"},
    {"name": "Daniil Medvedev", "age": 28, "nationality": "Russian", "gender": "male"},
    {"name": "Alexander Zverev", "age": 27, "nationality": "German", "gender": "male"},
    {"name": "Stefanos Tsitsipas", "age": 26, "nationality": "Greek", "gender": "male"},
    {"name": "Tommy Paul", "age": 27, "nationality": "American", "gender": "male"},
    {"name": "Jack Draper", "age": 23, "nationality": "British", "gender": "male"},
    {"name": "Ben Shelton", "age": 22, "nationality": "American", "gender": "male"},
    {"name": "Felix Auger-Aliassime", "age": 24, "nationality": "Canadian", "gender": "male"},
    {"name": "Grigor Dimitrov", "age": 33, "nationality": "Bulgarian", "gender": "male"},
    {"name": "Elena Rybakina", "age": 25, "nationality": "Kazakhstani", "gender": "female"},
    {"name": "Jessica Pegula", "age": 31, "nationality": "American", "gender": "female"},
    {"name": "Emma Raducanu", "age": 22, "nationality": "British", "gender": "female"},
    {"name": "Madison Keys", "age": 30, "nationality": "American", "gender": "female"},
    {"name": "Jasmine Paolini", "age": 29, "nationality": "Italian", "gender": "female"},
    {"name": "Barbora Krejčíková", "age": 29, "nationality": "Czech", "gender": "female"},
    {"name": "Markéta Vondroušová", "age": 25, "nationality": "Czech", "gender": "female"},
    {"name": "Elina Svitolina", "age": 30, "nationality": "Ukrainian", "gender": "female"},
    {"name": "Mirra Andreeva", "age": 18, "nationality": "Russian", "gender": "female"},
    {"name": "Danielle Collins", "age": 31, "nationality": "American", "gender": "female"},
    # ── Sport – Formula 1 ────────────────────────────────────────────────────
    {"name": "Max Verstappen", "age": 27, "nationality": "Dutch", "gender": "male"},
    {"name": "Carlos Sainz", "age": 30, "nationality": "Spanish", "gender": "male"},
    {"name": "George Russell", "age": 27, "nationality": "British", "gender": "male"},
    {"name": "Fernando Alonso", "age": 43, "nationality": "Spanish", "gender": "male"},
    {"name": "Sergio Pérez", "age": 34, "nationality": "Mexican", "gender": "male"},
    {"name": "Yuki Tsunoda", "age": 24, "nationality": "Japanese", "gender": "male"},
    {"name": "Zhou Guanyu", "age": 25, "nationality": "Chinese", "gender": "male"},
    {"name": "Valtteri Bottas", "age": 35, "nationality": "Finnish", "gender": "male"},
    # ── Sport – Football / Soccer ─────────────────────────────────────────────
    {"name": "Robert Lewandowski", "age": 36, "nationality": "Polish", "gender": "male"},
    {"name": "Harry Kane", "age": 31, "nationality": "British", "gender": "male"},
    {"name": "Mohamed Salah", "age": 32, "nationality": "Egyptian", "gender": "male"},
    {"name": "Sadio Mané", "age": 32, "nationality": "Senegalese", "gender": "male"},
    {"name": "Bukayo Saka", "age": 23, "nationality": "British", "gender": "male"},
    {"name": "Jude Bellingham", "age": 21, "nationality": "British", "gender": "male"},
    {"name": "Pedri", "age": 22, "nationality": "Spanish", "gender": "male"},
    {"name": "Virgil van Dijk", "age": 33, "nationality": "Dutch", "gender": "male"},
    {"name": "Rodri", "age": 28, "nationality": "Spanish", "gender": "male"},
    {"name": "Bruno Fernandes", "age": 30, "nationality": "Portuguese", "gender": "male"},
    {"name": "Victor Osimhen", "age": 26, "nationality": "Nigerian", "gender": "male"},
    {"name": "Achraf Hakimi", "age": 26, "nationality": "Moroccan", "gender": "male"},
    {"name": "Neymar", "age": 33, "nationality": "Brazilian", "gender": "male"},
    {"name": "Phil Foden", "age": 24, "nationality": "British", "gender": "male"},
    {"name": "Marcus Rashford", "age": 27, "nationality": "British", "gender": "male"},
    {"name": "Declan Rice", "age": 26, "nationality": "British", "gender": "male"},
    {"name": "Julián Álvarez", "age": 24, "nationality": "Argentine", "gender": "male"},
    {"name": "Antoine Griezmann", "age": 35, "nationality": "French", "gender": "male"},
    {"name": "Marta", "age": 39, "nationality": "Brazilian", "gender": "female"},
    {"name": "Alex Morgan", "age": 35, "nationality": "American", "gender": "female"},
    {"name": "Christine Sinclair", "age": 41, "nationality": "Canadian", "gender": "female"},
    {"name": "Vivianne Miedema", "age": 28, "nationality": "Dutch", "gender": "female"},
    {"name": "Aitana Bonmatí", "age": 27, "nationality": "Spanish", "gender": "female"},
    {"name": "Alexia Putellas", "age": 31, "nationality": "Spanish", "gender": "female"},
    {"name": "Beth Mead", "age": 30, "nationality": "British", "gender": "female"},
    {"name": "Keira Walsh", "age": 27, "nationality": "British", "gender": "female"},
    {"name": "Lena Oberdorf", "age": 23, "nationality": "German", "gender": "female"},
    {"name": "Sam Kerr", "age": 31, "nationality": "Australian", "gender": "female"},
    {"name": "Thembi Kgatlana", "age": 29, "nationality": "South African", "gender": "female"},
    {"name": "Trinity Rodman", "age": 23, "nationality": "American", "gender": "female"},
    {"name": "Sophia Smith", "age": 24, "nationality": "American", "gender": "female"},
    {"name": "Naomi Girma", "age": 25, "nationality": "American", "gender": "female"},
    # ── Sport – Basketball / WNBA ─────────────────────────────────────────────
    {"name": "Kevin Durant", "age": 36, "nationality": "American", "gender": "male"},
    {"name": "Stephen Curry", "age": 37, "nationality": "American", "gender": "male"},
    {"name": "Giannis Antetokounmpo", "age": 30, "nationality": "Greek-Nigerian", "gender": "male"},
    {"name": "Nikola Jokić", "age": 29, "nationality": "Serbian", "gender": "male"},
    {"name": "Joel Embiid", "age": 30, "nationality": "Cameroonian", "gender": "male"},
    {"name": "Jayson Tatum", "age": 27, "nationality": "American", "gender": "male"},
    {"name": "Luka Dončić", "age": 25, "nationality": "Slovenian", "gender": "male"},
    {"name": "Shai Gilgeous-Alexander", "age": 26, "nationality": "Canadian", "gender": "male"},
    {"name": "A'ja Wilson", "age": 28, "nationality": "American", "gender": "female"},
    {"name": "Breanna Stewart", "age": 30, "nationality": "American", "gender": "female"},
    {"name": "Sabrina Ionescu", "age": 27, "nationality": "American", "gender": "female"},
    {"name": "Angel Reese", "age": 22, "nationality": "American", "gender": "female"},
    {"name": "Paige Bueckers", "age": 23, "nationality": "American", "gender": "female"},
    # ── Sport – Athletics / Swimming / Cycling / Combat ───────────────────────
    {"name": "Eliud Kipchoge", "age": 40, "nationality": "Kenyan", "gender": "male"},
    {"name": "Noah Lyles", "age": 27, "nationality": "American", "gender": "male"},
    {"name": "Mondo Duplantis", "age": 25, "nationality": "Swedish-American", "gender": "male"},
    {"name": "Léon Marchand", "age": 22, "nationality": "French", "gender": "male"},
    {"name": "Caeleb Dressel", "age": 28, "nationality": "American", "gender": "male"},
    {"name": "Adam Peaty", "age": 30, "nationality": "British", "gender": "male"},
    {"name": "Tadej Pogačar", "age": 26, "nationality": "Slovenian", "gender": "male"},
    {"name": "Jonas Vingegaard", "age": 27, "nationality": "Danish", "gender": "male"},
    {"name": "Rory McIlroy", "age": 35, "nationality": "Irish", "gender": "male"},
    {"name": "Scottie Scheffler", "age": 27, "nationality": "American", "gender": "male"},
    {"name": "Marcell Jacobs", "age": 30, "nationality": "Italian", "gender": "male"},
    {"name": "Antoine Dupont", "age": 28, "nationality": "French", "gender": "male"},
    {"name": "Joshua Cheptegei", "age": 28, "nationality": "Ugandan", "gender": "male"},
    {"name": "Anthony Joshua", "age": 35, "nationality": "British-Nigerian", "gender": "male"},
    {"name": "Tyson Fury", "age": 36, "nationality": "British", "gender": "male"},
    {"name": "Canelo Álvarez", "age": 34, "nationality": "Mexican", "gender": "male"},
    {"name": "Oleksandr Usyk", "age": 38, "nationality": "Ukrainian", "gender": "male"},
    {"name": "Sydney McLaughlin-Levrone", "age": 25, "nationality": "American", "gender": "female"},
    {"name": "Faith Kipyegon", "age": 31, "nationality": "Kenyan", "gender": "female"},
    {"name": "Beatrice Chebet", "age": 24, "nationality": "Kenyan", "gender": "female"},
    {"name": "Athing Mu", "age": 23, "nationality": "American", "gender": "female"},
    {"name": "Gabby Thomas", "age": 28, "nationality": "American", "gender": "female"},
    {"name": "Yulimar Rojas", "age": 29, "nationality": "Venezuelan", "gender": "female"},
    {"name": "Rebeca Andrade", "age": 25, "nationality": "Brazilian", "gender": "female"},
    {"name": "Suni Lee", "age": 22, "nationality": "American", "gender": "female"},
    {"name": "Jordan Chiles", "age": 23, "nationality": "American", "gender": "female"},
    {"name": "Katie Ledecky", "age": 27, "nationality": "American", "gender": "female"},
    {"name": "Sarah Sjöström", "age": 31, "nationality": "Swedish", "gender": "female"},
    {"name": "Ariarne Titmus", "age": 24, "nationality": "Australian", "gender": "female"},
    {"name": "Torri Huske", "age": 23, "nationality": "American", "gender": "female"},
    {"name": "Nelly Korda", "age": 26, "nationality": "Czech-American", "gender": "female"},
    {"name": "Atthaya Thitikul", "age": 21, "nationality": "Thai", "gender": "female"},
    # ── Sport – Cricket ───────────────────────────────────────────────────────
    {"name": "Smriti Mandhana", "age": 28, "nationality": "Indian", "gender": "female"},
    {"name": "Harmanpreet Kaur", "age": 35, "nationality": "Indian", "gender": "female"},
    {"name": "Ellyse Perry", "age": 34, "nationality": "Australian", "gender": "female"},
    {"name": "Beth Mooney", "age": 30, "nationality": "Australian", "gender": "female"},
    {"name": "Nat Sciver-Brunt", "age": 32, "nationality": "British", "gender": "female"},
    {"name": "Hayley Matthews", "age": 27, "nationality": "Barbadian", "gender": "female"},
    # ── Entertainment – Western Actors ────────────────────────────────────────
    {"name": "Ryan Reynolds", "age": 48, "nationality": "Canadian", "gender": "male"},
    {"name": "Brad Pitt", "age": 61, "nationality": "American", "gender": "male"},
    {"name": "Leonardo DiCaprio", "age": 50, "nationality": "American", "gender": "male"},
    {"name": "Chris Evans", "age": 43, "nationality": "American", "gender": "male"},
    {"name": "Chris Hemsworth", "age": 41, "nationality": "Australian", "gender": "male"},
    {"name": "Ryan Gosling", "age": 44, "nationality": "Canadian", "gender": "male"},
    {"name": "Will Smith", "age": 56, "nationality": "American", "gender": "male"},
    {"name": "Denzel Washington", "age": 70, "nationality": "American", "gender": "male"},
    {"name": "Michael B. Jordan", "age": 37, "nationality": "American", "gender": "male"},
    {"name": "Daniel Kaluuya", "age": 36, "nationality": "British", "gender": "male"},
    {"name": "Dev Patel", "age": 34, "nationality": "British-Indian", "gender": "male"},
    {"name": "Riz Ahmed", "age": 42, "nationality": "British-Pakistani", "gender": "male"},
    {"name": "Simu Liu", "age": 36, "nationality": "Chinese-Canadian", "gender": "male"},
    {"name": "Paul Mescal", "age": 29, "nationality": "Irish", "gender": "male"},
    {"name": "Tom Holland", "age": 28, "nationality": "British", "gender": "male"},
    {"name": "Oscar Isaac", "age": 45, "nationality": "Guatemalan-American", "gender": "male"},
    {"name": "Diego Luna", "age": 44, "nationality": "Mexican", "gender": "male"},
    {"name": "Gael García Bernal", "age": 46, "nationality": "Mexican", "gender": "male"},
    {"name": "Omar Sy", "age": 46, "nationality": "French-Senegalese", "gender": "male"},
    {"name": "Rami Malek", "age": 43, "nationality": "American", "gender": "male"},
    {"name": "Austin Butler", "age": 33, "nationality": "American", "gender": "male"},
    {"name": "Jacob Elordi", "age": 27, "nationality": "Australian", "gender": "male"},
    {"name": "Barry Keoghan", "age": 32, "nationality": "Irish", "gender": "male"},
    {"name": "Andrew Scott", "age": 48, "nationality": "Irish", "gender": "male"},
    {"name": "Ncuti Gatwa", "age": 32, "nationality": "Rwandan-Scottish", "gender": "male"},
    {"name": "Jonathan Bailey", "age": 36, "nationality": "British", "gender": "male"},
    {"name": "Anthony Mackie", "age": 46, "nationality": "American", "gender": "male"},
    {"name": "Sterling K. Brown", "age": 49, "nationality": "American", "gender": "male"},
    {"name": "David Oyelowo", "age": 49, "nationality": "British", "gender": "male"},
    {"name": "Chiwetel Ejiofor", "age": 47, "nationality": "British", "gender": "male"},
    {"name": "Regé-Jean Page", "age": 37, "nationality": "British-Zimbabwean", "gender": "male"},
    {"name": "Zendaya", "age": 28, "nationality": "American", "gender": "female"},
    {"name": "Jennifer Lawrence", "age": 34, "nationality": "American", "gender": "female"},
    {"name": "Emma Stone", "age": 36, "nationality": "American", "gender": "female"},
    {"name": "Saoirse Ronan", "age": 30, "nationality": "Irish", "gender": "female"},
    {"name": "Millie Bobby Brown", "age": 21, "nationality": "British", "gender": "female"},
    {"name": "Sydney Sweeney", "age": 27, "nationality": "American", "gender": "female"},
    {"name": "Hailee Steinfeld", "age": 27, "nationality": "American", "gender": "female"},
    {"name": "Eva Green", "age": 44, "nationality": "French", "gender": "female"},
    {"name": "Cate Blanchett", "age": 55, "nationality": "Australian", "gender": "female"},
    {"name": "Angela Bassett", "age": 66, "nationality": "American", "gender": "female"},
    {"name": "Taraji P. Henson", "age": 54, "nationality": "American", "gender": "female"},
    {"name": "Kerry Washington", "age": 48, "nationality": "American", "gender": "female"},
    {"name": "Keke Palmer", "age": 31, "nationality": "American", "gender": "female"},
    {"name": "Quinta Brunson", "age": 35, "nationality": "American", "gender": "female"},
    {"name": "Issa Rae", "age": 40, "nationality": "American", "gender": "female"},
    {"name": "Mindy Kaling", "age": 45, "nationality": "American-Indian", "gender": "female"},
    {"name": "Sandra Oh", "age": 53, "nationality": "Canadian-Korean", "gender": "female"},
    {"name": "Awkwafina", "age": 36, "nationality": "American", "gender": "female"},
    {"name": "Gemma Chan", "age": 42, "nationality": "British", "gender": "female"},
    {"name": "Nicola Coughlan", "age": 38, "nationality": "Irish", "gender": "female"},
    {"name": "Simone Ashley", "age": 30, "nationality": "British-Indian", "gender": "female"},
    {"name": "Jodie Comer", "age": 32, "nationality": "British", "gender": "female"},
    {"name": "Olivia Colman", "age": 51, "nationality": "British", "gender": "female"},
    {"name": "Alicia Vikander", "age": 36, "nationality": "Swedish", "gender": "female"},
    {"name": "Sofia Boutella", "age": 42, "nationality": "Algerian", "gender": "female"},
    {"name": "Ruth Negga", "age": 42, "nationality": "Ethiopian-Irish", "gender": "female"},
    {"name": "Letitia Wright", "age": 31, "nationality": "British-Guyanese", "gender": "female"},
    {"name": "Danai Gurira", "age": 47, "nationality": "Zimbabwean", "gender": "female"},
    {"name": "America Ferrera", "age": 40, "nationality": "American", "gender": "female"},
    {"name": "Salma Hayek", "age": 58, "nationality": "Mexican", "gender": "female"},
    {"name": "Penélope Cruz", "age": 50, "nationality": "Spanish", "gender": "female"},
    {"name": "Charlize Theron", "age": 50, "nationality": "South African", "gender": "female"},
    {"name": "Nicole Kidman", "age": 57, "nationality": "Australian", "gender": "female"},
    {"name": "Halle Berry", "age": 58, "nationality": "American", "gender": "female"},
    {"name": "Naomi Ackie", "age": 32, "nationality": "British", "gender": "female"},
    # ── Entertainment – South Asian Cinema ────────────────────────────────────
    {"name": "Ranbir Kapoor", "age": 42, "nationality": "Indian", "gender": "male"},
    {"name": "Hrithik Roshan", "age": 51, "nationality": "Indian", "gender": "male"},
    {"name": "Ayushmann Khurrana", "age": 40, "nationality": "Indian", "gender": "male"},
    {"name": "Dulquer Salmaan", "age": 38, "nationality": "Indian", "gender": "male"},
    {"name": "Allu Arjun", "age": 43, "nationality": "Indian", "gender": "male"},
    {"name": "Ram Charan", "age": 39, "nationality": "Indian", "gender": "male"},
    {"name": "Jr. NTR", "age": 42, "nationality": "Indian", "gender": "male"},
    {"name": "Vijay", "age": 50, "nationality": "Indian", "gender": "male"},
    {"name": "Dhanush", "age": 41, "nationality": "Indian", "gender": "male"},
    {"name": "Alia Bhatt", "age": 32, "nationality": "Indian", "gender": "female"},
    {"name": "Rashmika Mandanna", "age": 28, "nationality": "Indian", "gender": "female"},
    {"name": "Taapsee Pannu", "age": 37, "nationality": "Indian", "gender": "female"},
    {"name": "Ananya Panday", "age": 26, "nationality": "Indian", "gender": "female"},
    {"name": "Aishwarya Rai", "age": 51, "nationality": "Indian", "gender": "female"},
    {"name": "Vidya Balan", "age": 46, "nationality": "Indian", "gender": "female"},
    {"name": "Tabu", "age": 54, "nationality": "Indian", "gender": "female"},
    {"name": "Janhvi Kapoor", "age": 28, "nationality": "Indian", "gender": "female"},
    # ── Entertainment – East Asian Cinema / TV ────────────────────────────────
    {"name": "Park Seo-joon", "age": 36, "nationality": "South Korean", "gender": "male"},
    {"name": "Lee Jung-jae", "age": 52, "nationality": "South Korean", "gender": "male"},
    {"name": "Lee Min-ho", "age": 37, "nationality": "South Korean", "gender": "male"},
    {"name": "Gong Yoo", "age": 45, "nationality": "South Korean", "gender": "male"},
    {"name": "Hyun Bin", "age": 42, "nationality": "South Korean", "gender": "male"},
    {"name": "Kim Soo-hyun", "age": 37, "nationality": "South Korean", "gender": "male"},
    {"name": "Park Chan-wook", "age": 62, "nationality": "South Korean", "gender": "male"},
    {"name": "IU", "age": 31, "nationality": "South Korean", "gender": "female"},
    {"name": "Song Hye-kyo", "age": 43, "nationality": "South Korean", "gender": "female"},
    {"name": "Kim Go-eun", "age": 33, "nationality": "South Korean", "gender": "female"},
    {"name": "Han So-hee", "age": 30, "nationality": "South Korean", "gender": "female"},
    {"name": "Kim Tae-ri", "age": 34, "nationality": "South Korean", "gender": "female"},
    {"name": "Liu Yifei", "age": 38, "nationality": "Chinese", "gender": "female"},
    {"name": "Zhang Ziyi", "age": 46, "nationality": "Chinese", "gender": "female"},
    {"name": "Dilraba Dilmurat", "age": 32, "nationality": "Chinese-Uyghur", "gender": "female"},
    {"name": "Gong Li", "age": 59, "nationality": "Chinese", "gender": "female"},
    {"name": "Zhao Wei", "age": 47, "nationality": "Chinese", "gender": "female"},
    # ── Music – Pop / R&B ─────────────────────────────────────────────────────
    {"name": "Harry Styles", "age": 31, "nationality": "British", "gender": "male"},
    {"name": "Zayn Malik", "age": 31, "nationality": "British-Pakistani", "gender": "male"},
    {"name": "Shawn Mendes", "age": 26, "nationality": "Canadian", "gender": "male"},
    {"name": "Bruno Mars", "age": 39, "nationality": "American", "gender": "male"},
    {"name": "Usher", "age": 46, "nationality": "American", "gender": "male"},
    {"name": "Leon Bridges", "age": 36, "nationality": "American", "gender": "male"},
    {"name": "Brent Faiyaz", "age": 29, "nationality": "American", "gender": "male"},
    {"name": "Martin Garrix", "age": 28, "nationality": "Dutch", "gender": "male"},
    {"name": "David Guetta", "age": 57, "nationality": "French", "gender": "male"},
    {"name": "Ariana Grande", "age": 32, "nationality": "American", "gender": "female"},
    {"name": "Nicki Minaj", "age": 42, "nationality": "Trinidadian-American", "gender": "female"},
    {"name": "Cardi B", "age": 32, "nationality": "American", "gender": "female"},
    {"name": "Megan Thee Stallion", "age": 30, "nationality": "American", "gender": "female"},
    {"name": "SZA", "age": 35, "nationality": "American", "gender": "female"},
    {"name": "Lizzo", "age": 37, "nationality": "American", "gender": "female"},
    {"name": "Doja Cat", "age": 29, "nationality": "American", "gender": "female"},
    {"name": "Olivia Rodrigo", "age": 22, "nationality": "American", "gender": "female"},
    {"name": "Sabrina Carpenter", "age": 26, "nationality": "American", "gender": "female"},
    {"name": "Chappell Roan", "age": 27, "nationality": "American", "gender": "female"},
    {"name": "Lady Gaga", "age": 38, "nationality": "American", "gender": "female"},
    {"name": "Katy Perry", "age": 40, "nationality": "American", "gender": "female"},
    {"name": "Miley Cyrus", "age": 32, "nationality": "American", "gender": "female"},
    {"name": "Lana Del Rey", "age": 39, "nationality": "American", "gender": "female"},
    {"name": "Alicia Keys", "age": 44, "nationality": "American", "gender": "female"},
    {"name": "H.E.R.", "age": 27, "nationality": "American", "gender": "female"},
    {"name": "Victoria Monét", "age": 31, "nationality": "American", "gender": "female"},
    {"name": "Summer Walker", "age": 28, "nationality": "American", "gender": "female"},
    {"name": "Arlo Parks", "age": 26, "nationality": "British", "gender": "female"},
    {"name": "Raye", "age": 27, "nationality": "British", "gender": "female"},
    {"name": "Jorja Smith", "age": 27, "nationality": "British", "gender": "female"},
    {"name": "Florence Welch", "age": 38, "nationality": "British", "gender": "female"},
    {"name": "Ellie Goulding", "age": 38, "nationality": "British", "gender": "female"},
    {"name": "Aurora", "age": 29, "nationality": "Norwegian", "gender": "female"},
    {"name": "Robyn", "age": 46, "nationality": "Swedish", "gender": "female"},
    {"name": "Björk", "age": 59, "nationality": "Icelandic", "gender": "female"},
    {"name": "Mitski", "age": 34, "nationality": "Japanese-American", "gender": "female"},
    {"name": "Beabadoobee", "age": 25, "nationality": "Filipino-British", "gender": "female"},
    # ── Music – Hip-Hop / Rap ─────────────────────────────────────────────────
    {"name": "Kendrick Lamar", "age": 37, "nationality": "American", "gender": "male"},
    {"name": "J. Cole", "age": 40, "nationality": "American", "gender": "male"},
    {"name": "ASAP Rocky", "age": 36, "nationality": "American", "gender": "male"},
    {"name": "Jack Harlow", "age": 26, "nationality": "American", "gender": "male"},
    {"name": "Stormzy", "age": 31, "nationality": "British", "gender": "male"},
    {"name": "Dave", "age": 27, "nationality": "British", "gender": "male"},
    {"name": "Little Simz", "age": 31, "nationality": "British", "gender": "female"},
    {"name": "Ninho", "age": 27, "nationality": "French", "gender": "male"},
    {"name": "Jay Park", "age": 37, "nationality": "Korean-American", "gender": "male"},
    # ── Music – Latin ─────────────────────────────────────────────────────────
    {"name": "J Balvin", "age": 39, "nationality": "Colombian", "gender": "male"},
    {"name": "Maluma", "age": 30, "nationality": "Colombian", "gender": "male"},
    {"name": "Rauw Alejandro", "age": 31, "nationality": "Puerto Rican", "gender": "male"},
    {"name": "Peso Pluma", "age": 25, "nationality": "Mexican", "gender": "male"},
    {"name": "Feid", "age": 32, "nationality": "Colombian", "gender": "male"},
    {"name": "Daddy Yankee", "age": 47, "nationality": "Puerto Rican", "gender": "male"},
    {"name": "Ozuna", "age": 32, "nationality": "Puerto Rican", "gender": "male"},
    {"name": "Karol G", "age": 33, "nationality": "Colombian", "gender": "female"},
    {"name": "Rosalía", "age": 31, "nationality": "Spanish", "gender": "female"},
    {"name": "Shakira", "age": 47, "nationality": "Colombian", "gender": "female"},
    {"name": "Jennifer Lopez", "age": 55, "nationality": "American", "gender": "female"},
    {"name": "Camila Cabello", "age": 28, "nationality": "Cuban-American", "gender": "female"},
    {"name": "Anitta", "age": 31, "nationality": "Brazilian", "gender": "female"},
    {"name": "Becky G", "age": 27, "nationality": "American", "gender": "female"},
    {"name": "Jessie Reyez", "age": 33, "nationality": "Colombian-Canadian", "gender": "female"},
    # ── Music – African ───────────────────────────────────────────────────────
    {"name": "Burna Boy", "age": 33, "nationality": "Nigerian", "gender": "male"},
    {"name": "WizKid", "age": 34, "nationality": "Nigerian", "gender": "male"},
    {"name": "Davido", "age": 31, "nationality": "Nigerian", "gender": "male"},
    {"name": "Rema", "age": 24, "nationality": "Nigerian", "gender": "male"},
    {"name": "Omah Lay", "age": 27, "nationality": "Nigerian", "gender": "male"},
    {"name": "Asake", "age": 29, "nationality": "Nigerian", "gender": "male"},
    {"name": "Black Sherif", "age": 23, "nationality": "Ghanaian", "gender": "male"},
    {"name": "Nasty C", "age": 28, "nationality": "South African", "gender": "male"},
    {"name": "Khaligraph Jones", "age": 32, "nationality": "Kenyan", "gender": "male"},
    {"name": "Focalistic", "age": 29, "nationality": "South African", "gender": "male"},
    {"name": "Tems", "age": 30, "nationality": "Nigerian", "gender": "female"},
    {"name": "Simi", "age": 36, "nationality": "Nigerian", "gender": "female"},
    {"name": "Yemi Alade", "age": 35, "nationality": "Nigerian", "gender": "female"},
    {"name": "Fatoumata Diawara", "age": 42, "nationality": "Malian", "gender": "female"},
    {"name": "Oumou Sangaré", "age": 55, "nationality": "Malian", "gender": "female"},
    {"name": "Asa", "age": 38, "nationality": "Nigerian", "gender": "female"},
    {"name": "Sho Madjozi", "age": 32, "nationality": "South African", "gender": "female"},
    {"name": "Ami Faku", "age": 30, "nationality": "South African", "gender": "female"},
    # ── Music – K-pop ─────────────────────────────────────────────────────────
    {"name": "RM", "age": 30, "nationality": "South Korean", "gender": "male"},
    {"name": "V", "age": 29, "nationality": "South Korean", "gender": "male"},
    {"name": "Jungkook", "age": 27, "nationality": "South Korean", "gender": "male"},
    {"name": "G-Dragon", "age": 36, "nationality": "South Korean", "gender": "male"},
    {"name": "Kai", "age": 31, "nationality": "South Korean", "gender": "male"},
    {"name": "Felix", "age": 24, "nationality": "Australian-Korean", "gender": "male"},
    {"name": "Taeyong", "age": 30, "nationality": "South Korean", "gender": "male"},
    {"name": "BLACKPINK Lisa", "age": 27, "nationality": "Thai", "gender": "female"},
    {"name": "BLACKPINK Jennie", "age": 29, "nationality": "South Korean", "gender": "female"},
    {"name": "BLACKPINK Rosé", "age": 27, "nationality": "New Zealand-Korean", "gender": "female"},
    {"name": "BLACKPINK Jisoo", "age": 29, "nationality": "South Korean", "gender": "female"},
    {"name": "TWICE Nayeon", "age": 29, "nationality": "South Korean", "gender": "female"},
    {"name": "TWICE Tzuyu", "age": 25, "nationality": "Taiwanese", "gender": "female"},
    {"name": "aespa Karina", "age": 24, "nationality": "South Korean", "gender": "female"},
    {"name": "NewJeans Hanni", "age": 21, "nationality": "Vietnamese-Australian", "gender": "female"},
    {"name": "Taeyeon", "age": 35, "nationality": "South Korean", "gender": "female"},
    {"name": "Hwasa", "age": 29, "nationality": "South Korean", "gender": "female"},
    # ── Politics / Government ─────────────────────────────────────────────────
    {"name": "Rishi Sunak", "age": 44, "nationality": "British", "gender": "male"},
    {"name": "Olaf Scholz", "age": 66, "nationality": "German", "gender": "male"},
    {"name": "Pedro Sánchez", "age": 52, "nationality": "Spanish", "gender": "male"},
    {"name": "Viktor Orbán", "age": 61, "nationality": "Hungarian", "gender": "male"},
    {"name": "Abiy Ahmed", "age": 48, "nationality": "Ethiopian", "gender": "male"},
    {"name": "Paul Kagame", "age": 66, "nationality": "Rwandan", "gender": "male"},
    {"name": "Prabowo Subianto", "age": 73, "nationality": "Indonesian", "gender": "male"},
    {"name": "Anwar Ibrahim", "age": 77, "nationality": "Malaysian", "gender": "male"},
    {"name": "Lee Hsien Loong", "age": 72, "nationality": "Singaporean", "gender": "male"},
    {"name": "Hakainde Hichilema", "age": 62, "nationality": "Zambian", "gender": "male"},
    {"name": "Shigeru Ishiba", "age": 67, "nationality": "Japanese", "gender": "male"},
    {"name": "Andrzej Duda", "age": 52, "nationality": "Polish", "gender": "male"},
    {"name": "Aleksander Vučić", "age": 54, "nationality": "Serbian", "gender": "male"},
    {"name": "Jacinda Ardern", "age": 44, "nationality": "New Zealander", "gender": "female"},
    {"name": "Christine Lagarde", "age": 69, "nationality": "French", "gender": "female"},
    {"name": "Ngozi Okonjo-Iweala", "age": 71, "nationality": "Nigerian", "gender": "female"},
    {"name": "Erna Solberg", "age": 63, "nationality": "Norwegian", "gender": "female"},
    {"name": "Magdalena Andersson", "age": 57, "nationality": "Swedish", "gender": "female"},
    {"name": "Roberta Metsola", "age": 46, "nationality": "Maltese", "gender": "female"},
    {"name": "Nicola Sturgeon", "age": 55, "nationality": "Scottish", "gender": "female"},
    {"name": "Amina J. Mohammed", "age": 62, "nationality": "Nigerian", "gender": "female"},
    {"name": "Michelle Bachelet", "age": 74, "nationality": "Chilean", "gender": "female"},
    {"name": "Janet Yellen", "age": 79, "nationality": "American", "gender": "female"},
    # ── Business / Technology ─────────────────────────────────────────────────
    {"name": "Andy Jassy", "age": 57, "nationality": "American", "gender": "male"},
    {"name": "Brian Chesky", "age": 43, "nationality": "American", "gender": "male"},
    {"name": "Jack Dorsey", "age": 48, "nationality": "American", "gender": "male"},
    {"name": "Daniel Ek", "age": 41, "nationality": "Swedish", "gender": "male"},
    {"name": "Patrick Collison", "age": 36, "nationality": "Irish", "gender": "male"},
    {"name": "Yann LeCun", "age": 65, "nationality": "French", "gender": "male"},
    {"name": "Yoshua Bengio", "age": 60, "nationality": "Canadian", "gender": "male"},
    {"name": "Geoffrey Hinton", "age": 77, "nationality": "British-Canadian", "gender": "male"},
    {"name": "Andrew Ng", "age": 48, "nationality": "British-Hong Kong", "gender": "male"},
    {"name": "Demis Hassabis", "age": 48, "nationality": "British", "gender": "male"},
    {"name": "Mustafa Suleyman", "age": 40, "nationality": "British", "gender": "male"},
    {"name": "Dario Amodei", "age": 42, "nationality": "American", "gender": "male"},
    {"name": "Tim Berners-Lee", "age": 70, "nationality": "British", "gender": "male"},
    {"name": "Mary Barra", "age": 63, "nationality": "American", "gender": "female"},
    {"name": "Sheryl Sandberg", "age": 55, "nationality": "American", "gender": "female"},
    {"name": "Whitney Wolfe Herd", "age": 35, "nationality": "American", "gender": "female"},
    {"name": "Reshma Saujani", "age": 50, "nationality": "American", "gender": "female"},
    {"name": "Safra Catz", "age": 63, "nationality": "Israeli-American", "gender": "female"},
    {"name": "Anne Wojcicki", "age": 51, "nationality": "American", "gender": "female"},
    # ── Science / Academia / Literature ───────────────────────────────────────
    {"name": "Brian Cox", "age": 57, "nationality": "British", "gender": "male"},
    {"name": "Michio Kaku", "age": 78, "nationality": "American", "gender": "male"},
    {"name": "Chris Hadfield", "age": 65, "nationality": "Canadian", "gender": "male"},
    {"name": "Haruki Murakami", "age": 76, "nationality": "Japanese", "gender": "male"},
    {"name": "Kazuo Ishiguro", "age": 71, "nationality": "British-Japanese", "gender": "male"},
    {"name": "Mohsin Hamid", "age": 52, "nationality": "Pakistani", "gender": "male"},
    {"name": "Ngugi wa Thiong'o", "age": 86, "nationality": "Kenyan", "gender": "male"},
    {"name": "Salman Rushdie", "age": 77, "nationality": "British-Indian", "gender": "male"},
    {"name": "Jennifer Doudna", "age": 61, "nationality": "American", "gender": "female"},
    {"name": "Katalin Karikó", "age": 69, "nationality": "Hungarian", "gender": "female"},
    {"name": "Emmanuelle Charpentier", "age": 56, "nationality": "French", "gender": "female"},
    {"name": "Frances Arnold", "age": 68, "nationality": "American", "gender": "female"},
    {"name": "Roxane Gay", "age": 51, "nationality": "American", "gender": "female"},
    {"name": "Jesmyn Ward", "age": 49, "nationality": "American", "gender": "female"},
    {"name": "Zadie Smith", "age": 49, "nationality": "British", "gender": "female"},
    {"name": "Fatima Bhutto", "age": 42, "nationality": "Pakistani", "gender": "female"},
    {"name": "Ahdaf Soueif", "age": 71, "nationality": "Egyptian", "gender": "female"},
    # ── Arts / Film Directors ─────────────────────────────────────────────────
    {"name": "Kehinde Wiley", "age": 48, "nationality": "American", "gender": "male"},
    {"name": "Alfonso Cuarón", "age": 62, "nationality": "Mexican", "gender": "male"},
    {"name": "Wes Anderson", "age": 55, "nationality": "American", "gender": "male"},
    {"name": "Ava DuVernay", "age": 52, "nationality": "American", "gender": "female"},
    {"name": "Chloé Zhao", "age": 42, "nationality": "Chinese-American", "gender": "female"},
    {"name": "Céline Sciamma", "age": 45, "nationality": "French", "gender": "female"},
    # ── Non-binary / LGBTQ+ representation ───────────────────────────────────
    {"name": "Elliot Page", "age": 38, "nationality": "Canadian", "gender": "male", "pronouns": "he/him"},
    {"name": "Jonathan Van Ness", "age": 37, "nationality": "American", "gender": "non-binary"},
    {"name": "Demi Lovato", "age": 32, "nationality": "American", "gender": "non-binary"},
    {"name": "Willow Smith", "age": 24, "nationality": "American", "gender": "non-binary"},
    {"name": "Moses Sumney", "age": 33, "nationality": "American", "gender": "non-binary"},
    {"name": "Yves Tumor", "age": 33, "nationality": "American", "gender": "non-binary"},
    {"name": "Perfume Genius", "age": 43, "nationality": "American", "gender": "non-binary"},
    {"name": "Jacob Tobia", "age": 33, "nationality": "American", "gender": "non-binary"},
    {"name": "Asia Kate Dillon", "age": 40, "nationality": "American", "gender": "non-binary"},
    {"name": "Amandla Stenberg", "age": 26, "nationality": "American", "gender": "non-binary"},
    {"name": "Yungblud", "age": 27, "nationality": "British", "gender": "non-binary"},
    {"name": "Cara Delevingne", "age": 32, "nationality": "British", "gender": "non-binary"},
    {"name": "Arca", "age": 34, "nationality": "Venezuelan", "gender": "non-binary"},
    {"name": "Anohni", "age": 54, "nationality": "British", "gender": "non-binary"},
    {"name": "Keiynan Lonsdale", "age": 32, "nationality": "Australian", "gender": "non-binary"},
    {"name": "Yasmin Benoit", "age": 28, "nationality": "British", "gender": "non-binary"},
    {"name": "Kae Tempest", "age": 40, "nationality": "British", "gender": "non-binary"},
    {"name": "Mykki Blanco", "age": 38, "nationality": "American", "gender": "non-binary"},
    {"name": "Quannah Chasinghorse", "age": 24, "nationality": "Native American", "gender": "non-binary"},
    {"name": "Pabllo Vittar", "age": 31, "nationality": "Brazilian", "gender": "non-binary"},
    {"name": "Kehlani", "age": 30, "nationality": "American", "gender": "non-binary"},
    {"name": "Ibeyi", "age": 30, "nationality": "Cuban-French", "gender": "non-binary"},
    {"name": "Kim Petras", "age": 32, "nationality": "German", "gender": "female"},
    {"name": "Jeffrey Marsh", "age": 48, "nationality": "American", "gender": "non-binary"},
    {"name": "Ezra Furman", "age": 38, "nationality": "American", "gender": "non-binary"},
    {"name": "CN Lester", "age": 36, "nationality": "British", "gender": "non-binary"},
    {"name": "Rain Dove", "age": 39, "nationality": "American", "gender": "non-binary"},
    {"name": "Tourmaline", "age": 38, "nationality": "American", "gender": "non-binary"},
    {"name": "Big Freedia", "age": 44, "nationality": "American", "gender": "non-binary"},
    {"name": "Gottmik", "age": 31, "nationality": "American", "gender": "non-binary"},
    {"name": "Gigi Goode", "age": 27, "nationality": "American", "gender": "non-binary"},
    {"name": "Bob the Drag Queen", "age": 37, "nationality": "American", "gender": "non-binary"},
    {"name": "Symone", "age": 30, "nationality": "American", "gender": "non-binary"},
]


# ── helpers ───────────────────────────────────────────────────────────────────


def _default_pronouns(gender: str) -> str:
    """Derive default pronouns from gender field."""
    return {"male": "he/him", "female": "she/her", "non-binary": "they/them"}.get(
        gender, "they/them"
    )


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
    except (json.JSONDecodeError, AttributeError):
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

    pronouns = celeb.get("pronouns") or _default_pronouns(celeb["gender"])

    data = {
        "personal": {
            "name": celeb["name"],
            "gender": celeb["gender"],
            "pronouns": pronouns,
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
