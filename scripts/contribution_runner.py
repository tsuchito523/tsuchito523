"""Render a GitHub contribution platformer using the supplied PNG animation frames."""
import argparse
import json
import math
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
STEP, CELL, LEFT, TOP, FLOOR = 17, 13, 38, 108, 244
HEIGHT, FPS = 286, 20
SPRITE_SIZE = 30
COLORS = ['#202b36', '#0e4429', '#006d32', '#26a641', '#39d353']


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.days = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'data-date' in a and 'data-level' in a:
            day, level = a['data-date'], int(a['data-level'])
            date.fromisoformat(day)
            if level not in range(5):
                raise ValueError('Invalid contribution level')
            self.days[day] = level


def fetch_days(user):
    import re
    if not re.fullmatch(r'[A-Za-z0-9-]+', user):
        raise ValueError('Invalid username')
    req = Request(f'https://github.com/users/{user}/contributions', headers={'User-Agent': 'contribution-runner'})
    with urlopen(req, timeout=45) as response:
        parser = CalendarParser()
        parser.feed(response.read().decode())
    if len(parser.days) < 300:
        raise ValueError('Incomplete GitHub calendar; refusing to replace animation')
    return [{'date': d, 'level': v} for d, v in sorted(parser.days.items())]


def layout(days):
    first = date.fromisoformat(days[0]['date'])
    sunday = first - timedelta(days=(first.weekday() + 1) % 7)
    cells = []
    for day in days:
        delta = (date.fromisoformat(day['date']) - sunday).days
        cells.append((delta // 7, delta % 7, day['level']))
    return cells, max(c[0] for c in cells) + 1


class Route(list):
    """Waypoints with explicit bank targets, distinguishing leaps from falls."""
    def __init__(self, points, jump_targets):
        super().__init__(points)
        self.jump_targets = jump_targets


def route(cells, columns):
    # Use the topmost green block in each week: no higher solid block can
    # intersect the character. Empty weeks become a ground-running section.
    surface = {}
    for col, row, level in cells:
        if level:
            surface[col] = min(surface.get(col, 7), row)
    points = [(-30, FLOOR)]
    jump_targets = set()
    heights = [TOP + surface[c] * STEP if c in surface else FLOOR for c in range(columns)]
    col = 0
    while col < columns:
        points.append((LEFT + col * STEP + CELL / 2,
                       heights[col]))
        # Cross even shallow valleys. A bank rises above every intervening
        # column; it need not be as high as the takeoff platform.
        bank = None
        # Deep valleys may span more than three columns. Stay airborne until
        # the first green bank that rises out of the three-row-deep region.
        if col in surface and col + 1 < columns and heights[col + 1] - heights[col] >= 3 * STEP:
            candidate = col + 1
            while candidate < columns and heights[candidate] - heights[col] >= 3 * STEP:
                candidate += 1
            if candidate in surface:
                bank = candidate
        if bank is None and col in surface and col + 1 < columns and heights[col + 1] > heights[col]:
            valley_top = heights[col + 1]
            for candidate in range(col + 2, min(columns, col + 5)):
                if candidate in surface and heights[candidate] < valley_top:
                    bank = candidate
                    break
                valley_top = min(valley_top, heights[candidate])
        if bank is not None:
            jump_targets.add(LEFT + bank * STEP + CELL / 2)
            col = bank
            continue
        # If descending onto a clear flat stretch, land up to two columns
        # farther ahead instead of dropping beside the ledge.
        if col + 1 < columns and heights[col + 1] > heights[col]:
            landing = col + 1
            while (landing < min(columns - 1, col + 3)
                   and heights[landing + 1] == heights[landing]):
                landing += 1
            col = landing
            continue
        col += 1
    points.append((LEFT + columns * STEP + 45, FLOOR))
    # For an ascent, use up to two additional flat columns as takeoff room.
    # Never rewind across a previous landing or another change in height.
    adjusted = []
    for point in points:
        if adjusted and point[1] < adjusted[-1][1]:
            for _ in range(2):
                if (len(adjusted) < 2 or adjusted[-2][1] != adjusted[-1][1]
                        or adjusted[-1][0] - adjusted[-2][0] > STEP * 1.1):
                    break
                adjusted.pop()
        adjusted.append(point)
    return Route(adjusted, jump_targets)


def motion(points):
    frames = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        crossing = isinstance(points, Route) and x1 in points.jump_targets
        big_jump = crossing or (x1 - x0 > STEP * 1.5 and y1 <= y0 and y0 < FLOOR and y1 < FLOOR)
        falling = y1 > y0 and not crossing
        jump = y1 < y0 or big_jump
        duration = max(0.22, (x1 - x0) / 85)
        if y0 != y1:
            duration = max(duration, 0.5 + abs(y1 - y0) / 350)
        if falling:
            # Constant gravity: start with zero vertical speed, then accelerate.
            # Scale flight time with sqrt(height), rather than halving all falls.
            edge_fraction = min(0.45, (CELL / 2) / (x1 - x0))
            duration = max(0.3, math.sqrt(2 * (y1 - y0) / 1000) / (1 - edge_fraction))
        count = math.ceil(duration * FPS)
        # Parabola remains above the segment. Landing on every green block
        # preserves the original calendar rather than inventing contributions.
        arc = 13 if y0 == y1 else 25 + abs(y1 - y0) * 0.28
        if big_jump:
            duration = max(duration, 0.8)
            count = math.ceil(duration * FPS)
            arc = max(arc, 36 + (x1 - x0) * 0.15)
        # Long crossings must remain inside the image, including the sprite.
        arc = min(arc, min(y0, y1) - SPRITE_SIZE - 8)
        for n in range(count):
            t = n / count
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t - (4 * arc * t * (1 - t) if jump else 0)
            pose = f'Jump{0 if t < .34 else 1 if t < .70 else 2}' if jump else f'Run{(len(frames) // 2) % 4}'
            if falling:
                # Walk from the block center to its edge before gravity takes
                # over. No upward impulse; use the descending sprite in air.
                edge = min(0.45, (CELL / 2) / (x1 - x0))
                fall_t = max(0.0, (t - edge) / (1 - edge))
                y = y0 + (y1 - y0) * fall_t ** 2
                if t >= edge:
                    pose = 'Jump2'
            frames.append((x, y, pose))
    return frames


def render(days, user, output):
    cells, columns = layout(days)
    width = LEFT * 2 + columns * STEP
    canvas = Image.new('RGB', (width, HEIGHT), '#0d1117')
    d = ImageDraw.Draw(canvas)
    # Render the title into the background, before compositing the character.
    # Sharing one canvas removes the separate heading image's vertical gap.
    font = ImageFont.truetype(str(ROOT / 'assets/fonts/Outfit.ttf'), 38)
    font.set_variation_by_axes([600])
    title = "Welcome to Tsuchito's profile"
    left, top, right, bottom = d.textbbox((0, 0), title, font=font)
    d.text(((width - (right - left)) / 2 - left, 24 - top),
           title, font=font, fill='white')
    for col, row, level in cells:
        x, y = LEFT + col * STEP, TOP + row * STEP
        d.rounded_rectangle((x, y, x + CELL - 1, y + CELL - 1), radius=2, fill=COLORS[level])
    d.line((0, FLOOR, width, FLOOR), fill='#36414d', width=2)
    for x in range(0, width, 12):
        d.line((x, FLOOR + 6, x + 4, FLOOR + 6), fill='#202b36')
    for i, color in enumerate(COLORS):
        x = width - LEFT - 5 * 15 + i * 15
        d.rounded_rectangle((x, HEIGHT - 21, x + 10, HEIGHT - 11), radius=2, fill=color)
    sprites = {}
    for name in ['Run0', 'Run1', 'Run2', 'Run3', 'Jump0', 'Jump1', 'Jump2']:
        # Preserve original shared canvas and foot baseline; no per-frame crop.
        sprites[name] = Image.open(ROOT / f'assets/runner/{name}.png').convert('RGBA').resize((SPRITE_SIZE, SPRITE_SIZE), Image.Resampling.LANCZOS)
    # One shared palette eliminates color flicker between GIF frames.
    sample = canvas.copy()
    sample.paste(sprites['Run0'], (LEFT, 65), sprites['Run0'])
    palette = sample.quantize(colors=128)
    frames = []
    poses = motion(route(cells, columns))
    for x, feet, pose in poses:
        frame = canvas.copy()
        frame.paste(sprites[pose], (round(x - SPRITE_SIZE / 2), round(feet - SPRITE_SIZE)), sprites[pose])
        frames.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=1000 // FPS,
                   loop=0, optimize=True, disposal=1)
    # Static companion for inspection and readers who prefer no animation.
    frames[len(frames) // 2].convert('RGB').save(output.with_suffix('.png'))
    print(f'{output}: {width}x{HEIGHT}, {len(frames)} frames, {len(frames)/FPS:.1f}s, {output.stat().st_size:,} bytes')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--user', default='tsuchito523')
    p.add_argument('--fetch', action='store_true')
    p.add_argument('--data', type=Path, default=ROOT / 'data/contributions.json')
    p.add_argument('--output', type=Path, default=ROOT / 'assets/contribution-runner.gif')
    args = p.parse_args()
    if args.fetch:
        days = fetch_days(args.user)
        args.data.parent.mkdir(parents=True, exist_ok=True)
        args.data.write_text(json.dumps(days, indent=2) + '\n', encoding='utf-8')
    else:
        days = json.loads(args.data.read_text(encoding='utf-8'))
    render(days, args.user, args.output)


if __name__ == '__main__':
    main()
