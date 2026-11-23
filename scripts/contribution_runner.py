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


def route(cells, columns):
    # Use the topmost green block in each week: no higher solid block can
    # intersect the character. Empty weeks become a ground-running section.
    surface = {}
    for col, row, level in cells:
        if level:
            surface[col] = min(surface.get(col, 7), row)
    points = [(-30, FLOOR)]
    for col in range(columns):
        points.append((LEFT + col * STEP + CELL / 2,
                       TOP + surface[col] * STEP if col in surface else FLOOR))
    points.append((LEFT + columns * STEP + 45, FLOOR))
    return points


def motion(points):
    frames = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        jump = y0 != y1
        duration = max(0.22, (x1 - x0) / 85)
        if y0 != y1:
            duration = max(duration, 0.5 + abs(y1 - y0) / 350)
        count = math.ceil(duration * FPS)
        # Parabola remains above the segment. Landing on every green block
        # preserves the original calendar rather than inventing contributions.
        arc = 13 if y0 == y1 else 25 + abs(y1 - y0) * 0.28
        for n in range(count):
            t = n / count
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t - (4 * arc * t * (1 - t) if jump else 0)
            pose = f'Jump{0 if t < .34 else 1 if t < .70 else 2}' if jump else f'Run{(len(frames) // 2) % 4}'
            frames.append((x, y, pose))
    return frames


def render(days, user, output):
    cells, columns = layout(days)
    width = LEFT * 2 + columns * STEP
    canvas = Image.new('RGB', (width, HEIGHT), '#0d1117')
    d = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=13)
    small = ImageFont.load_default(size=11)
    d.text((LEFT, 20), 'CONTRIBUTION RUNNER', fill='#f7b7bd', font=font)
    d.text((LEFT, 43), f'@{user}  /  {days[0]["date"]} - {days[-1]["date"]}', fill='#8b949e', font=small)
    for col, row, level in cells:
        x, y = LEFT + col * STEP, TOP + row * STEP
        d.rounded_rectangle((x, y, x + CELL - 1, y + CELL - 1), radius=2, fill=COLORS[level])
        if level:
            d.line((x + 2, y + 1, x + CELL - 3, y + 1), fill='#69d88a')
    d.line((0, FLOOR, width, FLOOR), fill='#36414d', width=2)
    for x in range(0, width, 12):
        d.line((x, FLOOR + 6, x + 4, FLOOR + 6), fill='#202b36')
    d.text((LEFT, HEIGHT - 21), 'A little progress, a little adventure.', fill='#8b949e', font=small)
    for i, color in enumerate(COLORS):
        x = width - LEFT - 5 * 15 + i * 15
        d.rounded_rectangle((x, HEIGHT - 21, x + 10, HEIGHT - 11), radius=2, fill=color)
    sprites = {}
    for name in ['Run0', 'Run1', 'Run2', 'Run3', 'Jump0', 'Jump1', 'Jump2']:
        # Preserve original shared canvas and foot baseline; no per-frame crop.
        sprites[name] = Image.open(ROOT / f'assets/runner/{name}.png').convert('RGBA').resize((38, 38), Image.Resampling.LANCZOS)
    # One shared palette eliminates color flicker between GIF frames.
    sample = canvas.copy()
    sample.paste(sprites['Run0'], (LEFT, 65), sprites['Run0'])
    palette = sample.quantize(colors=128)
    frames = []
    poses = motion(route(cells, columns))
    for x, feet, pose in poses:
        frame = canvas.copy()
        frame.paste(sprites[pose], (round(x - 19), round(feet - 38)), sprites[pose])
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
