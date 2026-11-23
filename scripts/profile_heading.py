"""Render the profile heading in Outfit without relying on README CSS."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SCALE = 2
image = Image.new('RGB', (977 * SCALE, 88 * SCALE), '#0d1117')
font = ImageFont.truetype(str(ROOT / 'assets/fonts/Outfit.ttf'), 38 * SCALE)
font.set_variation_by_axes([600])
draw = ImageDraw.Draw(image)
text = "Welcome to Tsuchito's profile"
left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
draw.text(((image.width - (right - left)) / 2 - left,
           (image.height - (bottom - top)) / 2 - top), text, font=font, fill='white')
image.save(ROOT / 'assets/profile-heading.png')
