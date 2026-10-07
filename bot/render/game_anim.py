"""미니게임 연출용 이미지/GIF (동전·주사위·슬롯·블랙잭) — 전부 Pillow로 직접 그린다 (외부 이미지 불필요)."""

from __future__ import annotations

import math
import random
from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter

from bot.render.base import BG, GOLD, GREEN, LINE, MUTED, PANEL, PANEL_2, RED, TEXT, font

W, H = 560, 315
FELT = (16, 78, 60)
FELT_DARK = (10, 52, 40)
CYAN = (90, 220, 255)


def gif_bytes(frames: Sequence[Image.Image], durations: Sequence[int], loop: int = 1) -> bytes:
    """프레임들을 GIF로. 마지막 프레임은 오래 보여준다."""
    pal = [f.convert("RGB").quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    out = BytesIO()
    pal[0].save(out, format="GIF", save_all=True, append_images=pal[1:], duration=list(durations), loop=loop,
                disposal=1, optimize=False)
    return out.getvalue()


def _bg(top=(22, 34, 48), bottom=(11, 18, 27), size=(W, H)) -> Image.Image:
    img = Image.new("RGB", size, top)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / size[1]
        d.line([(0, y), (size[0], y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def _banner(img: Image.Image, text: str, color=TEXT) -> None:
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([W // 2 - 150, H - 58, W // 2 + 150, H - 14], radius=20, fill=(0, 0, 0))
    d.text((W // 2, H - 36), text, font=font("heavy", 26), fill=color, anchor="mm")


# ---------------------------------------------------------------------------
# 스프라이트 (플랫 벡터 스타일: 단색 면 + 굵은 외곽선, 4배 크기로 그려서 줄여 계단 현상 없앰)
# ---------------------------------------------------------------------------

NAVY = (27, 36, 51)
GOLD_L, GOLD_M, GOLD_D = (255, 228, 138), (255, 200, 61), (224, 162, 27)
SS = 4
SYMBOL_NAMES = ["🍒", "🍋", "🔔", "⭐", "💎"]
_sprites: dict = {}


def _canvas(size: int):
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), n


def _down(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.LANCZOS)


def _star(cx, cy, ro, ri, rot=-math.pi / 2):
    return [(cx + (ro if i % 2 == 0 else ri) * math.cos(rot + i * math.pi / 5),
             cy + (ro if i % 2 == 0 else ri) * math.sin(rot + i * math.pi / 5)) for i in range(10)]


def coin_sprite(face: str, size: int = 210) -> Image.Image:
    key = ("coin", face, size)
    if key in _sprites:
        return _sprites[key]
    img, d, n = _canvas(size)
    p = n * 0.03
    d.ellipse([p, p, n - p, n - p], fill=NAVY)
    q = n * 0.065
    d.ellipse([q, q, n - q, n - q], fill=GOLD_M)
    r = n * 0.15
    d.ellipse([r, r, n - r, n - r], outline=GOLD_D, width=int(n * 0.025))
    d.arc([q + n * 0.03, q + n * 0.03, n - q - n * 0.03, n - q - n * 0.03], 200, 260, fill=GOLD_L, width=int(n * 0.035))
    c = n / 2
    if face == "앞":
        d.polygon(_star(c, c + n * 0.015, n * 0.27, n * 0.115), fill=GOLD_D, outline=NAVY, width=int(n * 0.012))
    else:
        w, h = n * 0.24, n * 0.14
        pts = [(c - w, c + h), (c - w, c - h * 0.8), (c - w * 0.5, c), (c, c - h * 1.3), (c + w * 0.5, c), (c + w, c - h * 0.8), (c + w, c + h)]
        d.polygon(pts, fill=GOLD_D, outline=NAVY, width=int(n * 0.012))
        for px, py in ((c - w, c - h * 0.8), (c, c - h * 1.3), (c + w, c - h * 0.8)):
            d.ellipse([px - n * 0.035, py - n * 0.035, px + n * 0.035, py + n * 0.035], fill=GOLD_L, outline=NAVY, width=int(n * 0.01))
        d.rectangle([c - w, c + h * 0.45, c + w, c + h], fill=NAVY)
    out = _down(img, size)
    _sprites[key] = out
    return out


def _coin_at(canvas: Image.Image, cx: float, cy: float, c: float, face: str, size: int = 210) -> None:
    """c = cos(회전각): 1이면 정면, 0이면 옆면. 옆면은 얇은 금속 테두리로 보인다."""
    spr = coin_sprite(face, size)
    w = max(10, int(size * abs(c)))
    flat = spr.resize((w, size), Image.LANCZOS)
    thick = int((1 - abs(c)) * 16)
    if thick > 0:
        edge = Image.new("RGBA", flat.size, (176, 122, 16, 255))
        edge.putalpha(flat.getchannel("A"))
        for t in range(thick, 0, -2):
            canvas.paste(edge, (int(cx - w / 2 + t), int(cy - size / 2)), edge)
    canvas.paste(flat, (int(cx - w / 2), int(cy - size / 2)), flat)


def die_sprite(value: int, size: int = 240, highlight: bool = False) -> Image.Image:
    key = ("die", value, size, highlight)
    if key in _sprites:
        return _sprites[key]
    img, d, n = _canvas(size)
    m, rad, off = n * 0.05, n * 0.17, n * 0.045
    d.rounded_rectangle([m + off, m + off, n - m, n - m], radius=rad, fill=NAVY)
    d.rounded_rectangle([m, m, n - m - off, n - m - off], radius=rad, fill=(246, 243, 236), outline=GOLD_M if highlight else NAVY, width=int(n * 0.035))
    bev = n * 0.06
    d.rounded_rectangle([m + n * 0.05, m + n * 0.05, n - m - off - n * 0.05, n - m - off - n * 0.05], radius=rad * 0.7, outline=(226, 220, 207), width=int(bev * 0.5))
    side = (n - 2 * m - off)
    step, pr = side * 0.27, side * 0.075
    cx = cy = m + side / 2
    for dx, dy in _PIPS[value]:
        x, y = cx + dx * step, cy + dy * step
        big = 1.35 if value == 1 else 1.0
        col = (232, 67, 79) if value == 1 else NAVY
        d.ellipse([x - pr * big, y - pr * big, x + pr * big, y + pr * big], fill=col)
    out = _down(img, size)
    _sprites[key] = out
    return out


def symbol_sprite(name: str, size: int = 200) -> Image.Image:
    key = ("sym", name, size)
    if key in _sprites:
        return _sprites[key]
    img, d, n = _canvas(size)
    ow = int(n * 0.035)
    if name == "🍒":
        for cx, cy in ((0.3, 0.68), (0.7, 0.72)):
            d.line([(cx * n, cy * n), (0.52 * n, 0.2 * n)], fill=(60, 160, 80), width=int(n * 0.04))
        d.polygon([(0.52 * n, 0.2 * n), (0.78 * n, 0.12 * n), (0.62 * n, 0.3 * n)], fill=(70, 190, 100), outline=NAVY, width=ow)
        for cx, cy in ((0.3, 0.68), (0.7, 0.72)):
            r = n * 0.2
            d.ellipse([cx * n - r, cy * n - r, cx * n + r, cy * n + r], fill=(232, 67, 79), outline=NAVY, width=ow)
            d.ellipse([cx * n - r * 0.55, cy * n - r * 0.6, cx * n - r * 0.15, cy * n - r * 0.25], fill=(255, 150, 160))
    elif name == "🍋":
        d.ellipse([0.1 * n, 0.25 * n, 0.9 * n, 0.75 * n], fill=(255, 224, 70), outline=NAVY, width=ow)
        d.polygon([(0.86 * n, 0.44 * n), (0.97 * n, 0.5 * n), (0.86 * n, 0.56 * n)], fill=(255, 224, 70), outline=NAVY, width=ow)
        d.polygon([(0.14 * n, 0.44 * n), (0.03 * n, 0.5 * n), (0.14 * n, 0.56 * n)], fill=(255, 224, 70), outline=NAVY, width=ow)
        d.arc([0.2 * n, 0.32 * n, 0.55 * n, 0.6 * n], 190, 260, fill=(255, 245, 170), width=int(n * 0.04))
    elif name == "🔔":
        d.ellipse([0.44 * n, 0.08 * n, 0.56 * n, 0.2 * n], fill=GOLD_M, outline=NAVY, width=ow)
        d.pieslice([0.2 * n, 0.15 * n, 0.8 * n, 0.75 * n], 180, 360, fill=GOLD_M, outline=NAVY, width=ow)
        d.polygon([(0.2 * n, 0.45 * n), (0.8 * n, 0.45 * n), (0.9 * n, 0.76 * n), (0.1 * n, 0.76 * n)], fill=GOLD_M, outline=NAVY, width=ow)
        d.rectangle([0.22 * n, 0.44 * n, 0.78 * n, 0.5 * n], fill=GOLD_M)
        d.ellipse([0.4 * n, 0.74 * n, 0.6 * n, 0.92 * n], fill=GOLD_D, outline=NAVY, width=ow)
        d.arc([0.3 * n, 0.25 * n, 0.5 * n, 0.5 * n], 190, 260, fill=GOLD_L, width=int(n * 0.04))
    elif name == "⭐":
        d.polygon(_star(n / 2, n * 0.54, n * 0.46, n * 0.2), fill=GOLD_M, outline=NAVY, width=ow)
        d.polygon(_star(n / 2, n * 0.54, n * 0.22, n * 0.1), fill=GOLD_L)
    else:
        pts = [(0.2 * n, 0.3 * n), (0.33 * n, 0.1 * n), (0.67 * n, 0.1 * n), (0.8 * n, 0.3 * n), (0.5 * n, 0.9 * n)]
        d.polygon(pts, fill=(90, 205, 245), outline=NAVY, width=ow)
        d.polygon([(0.33 * n, 0.1 * n), (0.42 * n, 0.3 * n), (0.5 * n, 0.1 * n)], fill=(160, 232, 255))
        d.polygon([(0.2 * n, 0.3 * n), (0.8 * n, 0.3 * n), (0.5 * n, 0.9 * n)], fill=(60, 170, 225))
        d.line([(0.2 * n, 0.3 * n), (0.8 * n, 0.3 * n)], fill=NAVY, width=int(n * 0.025))
    out = _down(img, size)
    _sprites[key] = out
    return out


def _scene() -> Image.Image:
    img = Image.new("RGB", (W, H), (30, 42, 58))
    d = ImageDraw.Draw(img)
    for i in range(-H, W, 46):                       # 은은한 대각선 줄무늬
        d.line([(i, H), (i + H, 0)], fill=(35, 49, 67), width=14)
    return img


# ---------------------------------------------------------------------------
# 동전
# ---------------------------------------------------------------------------


def coin_gif(result: str) -> bytes:
    """result: '앞' | '뒤'. 동전이 튀어 오르며 돈다."""
    half_turns = 10 if result == "앞" else 9      # 짝수 번 뒤집히면 앞면
    n = 26
    frames, durs = [], []
    for i in range(n):
        t = (i + 1) / n
        e = 1 - (1 - t) ** 2.2
        theta = math.pi * half_turns * e
        c = math.cos(theta)
        face = "앞" if c >= 0 else "뒤"
        height = math.sin(math.pi * min(1.0, t * 1.1)) * 52 if t < 0.91 else 0
        img = _scene()
        d = ImageDraw.Draw(img)
        sw = 60 - height * 0.25
        d.ellipse([W / 2 - sw, H - 78, W / 2 + sw, H - 58], fill=(22, 31, 44))
        _coin_at(img, W / 2, H / 2 - 20 - height, c, face)
        frames.append(img)
        durs.append(60 + int(70 * t))
    final = frames[-1].copy()
    _banner(final, f"{result}면!", GOLD)
    frames.append(final)
    durs.append(3000)
    return gif_bytes(frames, durs)


# ---------------------------------------------------------------------------
# 주사위
# ---------------------------------------------------------------------------

_PIPS = {1: [(0, 0)], 2: [(-1, -1), (1, 1)], 3: [(-1, -1), (0, 0), (1, 1)], 4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
         5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)], 6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)]}


def dice_gif(result: int) -> bytes:
    rng = random.Random()
    n = 18
    frames, durs = [], []
    last = 0
    for i in range(n):
        t = (i + 1) / n
        v = result if i == n - 1 else rng.choice([x for x in range(1, 7) if x != last])
        last = v
        shake = (1 - t) * 40
        angle = rng.uniform(-1, 1) * (1 - t) * 80
        die = die_sprite(v).rotate(angle, expand=True, resample=Image.BICUBIC)
        img = _scene()
        d = ImageDraw.Draw(img)
        cx = W / 2 + rng.uniform(-1, 1) * shake
        cy = H / 2 - 5 - math.sin(math.pi * t) * 55 * (1 - t * 0.3) + rng.uniform(-1, 1) * shake * 0.3
        d.ellipse([W / 2 - 58, H - 80, W / 2 + 58, H - 58], fill=(22, 31, 44))
        img.paste(die, (int(cx - die.width / 2), int(cy - die.height / 2)), die)
        frames.append(img)
        durs.append(50 + int(110 * t * t))
    final = _scene()
    die = die_sprite(result, 250, highlight=True)
    final.paste(die, (W // 2 - 125, H // 2 - 140), die)
    _banner(final, f"{result}!", GOLD)
    frames.append(final)
    durs.append(3000)
    return gif_bytes(frames, durs)


# ---------------------------------------------------------------------------
# 슬롯
# ---------------------------------------------------------------------------

_cabinet: Image.Image | None = None
WIN_W, WIN_H, WIN_GAP, WIN_X, WIN_Y = 108, 150, 14, 103, 82


def _cabinet_img() -> Image.Image:
    global _cabinet
    if _cabinet is not None:
        return _cabinet
    img = _scene()
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([64, 8, 496, 312], radius=34, fill=NAVY)
    d.rounded_rectangle([70, 12, 490, 306], radius=30, fill=(222, 58, 74))
    d.rounded_rectangle([70, 12, 490, 90], radius=30, fill=(236, 84, 98))
    d.rounded_rectangle([88, 56, 472, 258], radius=18, fill=NAVY)
    d.rounded_rectangle([94, 62, 466, 252], radius=14, fill=(255, 214, 95))
    d.rounded_rectangle([98, 266, 462, 298], radius=12, fill=NAVY)
    d.rounded_rectangle([102, 270, 458, 294], radius=9, fill=(150, 30, 45))
    for k in range(3):
        x = WIN_X + k * (WIN_W + WIN_GAP)
        d.rounded_rectangle([x - 5, WIN_Y - 5, x + WIN_W + 5, WIN_Y + WIN_H + 5], radius=12, fill=NAVY)
    # 레버 받침
    d.rounded_rectangle([498, 150, 518, 214], radius=8, fill=NAVY)
    d.rounded_rectangle([502, 154, 514, 210], radius=5, fill=(180, 190, 205))
    _cabinet = img
    return img


def slot_gif(reels: list[str]) -> bytes:
    rng = random.Random()
    cell = 100
    stops = [14, 20, 26]
    n = 28
    seqs = [[rng.choice(SYMBOL_NAMES) for _ in range(40)] for _ in range(3)]
    frames, durs = [], []
    cab = _cabinet_img()
    for f in range(n):
        img = cab.copy()
        d = ImageDraw.Draw(img)
        # 상단 전구 (번갈아 깜빡)
        for b in range(14):
            on = (b + f) % 2 == 0
            x = 98 + b * 26.5
            d.ellipse([x - 6, 18, x + 6, 30], fill=(255, 236, 130) if on else (170, 40, 56), outline=NAVY, width=2)
        # 레버: 처음 6프레임 동안 아래로 당겼다가 올라옴
        pull = min(f, 5) / 5 if f < 10 else max(0, 1 - (f - 10) / 4)
        ky = 120 + pull * 70
        d.line([(508, 160), (508, ky)], fill=(180, 190, 205), width=8)
        d.ellipse([496, ky - 16, 520, ky + 8], fill=(255, 224, 70), outline=NAVY, width=3)
        for r in range(3):
            x = WIN_X + r * (WIN_W + WIN_GAP)
            reel = Image.new("RGB", (WIN_W, WIN_H), (252, 249, 240))
            if f >= stops[r]:
                spr = symbol_sprite(reels[r], 104)
                reel.paste(spr, ((WIN_W - 104) // 2, (WIN_H - 104) // 2), spr)
            else:
                off = (f * 53 + r * 31) % cell
                for k in range(-1, WIN_H // cell + 2):
                    sym = seqs[r][(f * 2 + k + r * 5) % len(seqs[r])]
                    spr = symbol_sprite(sym, 84)
                    reel.paste(spr, ((WIN_W - 84) // 2, k * cell + off + (cell - 84) // 2), spr)
                veil = Image.new("RGBA", (WIN_W, WIN_H), (255, 255, 255, 70))
                reel = Image.alpha_composite(reel.convert("RGBA"), veil).convert("RGB")
            img.paste(reel, (x, WIN_Y))
        d.line([(WIN_X - 5, WIN_Y + WIN_H // 2), (WIN_X + 3 * WIN_W + 2 * WIN_GAP + 5, WIN_Y + WIN_H // 2)], fill=(222, 58, 74), width=3)
        d.text((280, 45), "SLOT", font=font("heavy", 20), fill=(255, 245, 220), anchor="mm")
        frames.append(img)
        durs.append(70 if f < stops[0] else 110)
    final = frames[-1].copy()
    d = ImageDraw.Draw(final)
    label, col = (("JACKPOT!", (200, 30, 50)) if reels[0] == reels[1] == reels[2] else
                  (("2개 일치", NAVY) if len(set(reels)) == 2 else ("꽝", (120, 120, 130))))
    d.rounded_rectangle([195, 34, 365, 57], radius=11, fill=(255, 214, 95), outline=NAVY, width=2)
    d.text((280, 46), label, font=font("heavy", 20), fill=col, anchor="mm")
    frames.append(final)
    durs.append(3000)
    return gif_bytes(frames, durs)


# ---------------------------------------------------------------------------
# 블랙잭
# ---------------------------------------------------------------------------

CARD_W, CARD_H = 84, 120


def _suit(d: ImageDraw.ImageDraw, suit: str, cx: float, cy: float, s: float, color) -> None:
    if suit in "♥♠":
        # 하트 / 스페이드(뒤집은 하트 + 줄기)
        sign = 1 if suit == "♥" else -1
        r = s * 0.27
        lobe_y = cy - sign * 0.18 * s
        d.ellipse([cx - 0.5 * s, lobe_y - r, cx - 0.5 * s + 2 * r, lobe_y + r], fill=color)
        d.ellipse([cx + 0.5 * s - 2 * r, lobe_y - r, cx + 0.5 * s, lobe_y + r], fill=color)
        tip = cy + sign * 0.48 * s
        d.polygon([(cx - 0.5 * s + 0.02 * s, lobe_y + sign * r * 0.55), (cx + 0.5 * s - 0.02 * s, lobe_y + sign * r * 0.55), (cx, tip)], fill=color)
        if suit == "♠":
            d.polygon([(cx - 0.12 * s, cy + 0.5 * s), (cx + 0.12 * s, cy + 0.5 * s), (cx, cy + 0.15 * s)], fill=color)
    elif suit == "♦":
        d.polygon([(cx, cy - 0.5 * s), (cx + 0.36 * s, cy), (cx, cy + 0.5 * s), (cx - 0.36 * s, cy)], fill=color)
    else:   # 클럽
        r = s * 0.2
        for dx, dy in ((0, -0.22), (-0.24, 0.1), (0.24, 0.1)):
            d.ellipse([cx + dx * s - r, cy + dy * s - r, cx + dx * s + r, cy + dy * s + r], fill=color)
        d.polygon([(cx - 0.1 * s, cy + 0.5 * s), (cx + 0.1 * s, cy + 0.5 * s), (cx, cy)], fill=color)


def draw_card(d: ImageDraw.ImageDraw, x: int, y: int, card: str | None) -> None:
    """card=None 이면 뒷면."""
    d.rounded_rectangle([x + 3, y + 4, x + CARD_W + 3, y + CARD_H + 4], radius=9, fill=(0, 0, 0))
    if card is None:
        d.rounded_rectangle([x, y, x + CARD_W, y + CARD_H], radius=9, fill=(150, 30, 45), outline=(240, 235, 225), width=3)
        d.rounded_rectangle([x + 9, y + 9, x + CARD_W - 9, y + CARD_H - 9], radius=6, outline=(230, 150, 160), width=2)
        for i in range(-3, 4):
            d.line([(x + 10, y + CARD_H // 2 + i * 14), (x + CARD_W - 10, y + CARD_H // 2 + i * 14 + 20)], fill=(185, 60, 75), width=2)
        return
    d.rounded_rectangle([x, y, x + CARD_W, y + CARD_H], radius=9, fill=(250, 248, 242), outline=(150, 145, 135), width=2)
    rank, suit = card[:-1], card[-1]
    color = (200, 25, 40) if suit in "♥♦" else (25, 25, 32)
    d.text((x + 8, y + 6), rank, font=font("heavy", 22 if len(rank) == 1 else 19), fill=color)
    _suit(d, suit, x + 15, y + 40, 15, color)
    _suit(d, suit, x + CARD_W / 2 + 4, y + CARD_H / 2 + 14, 40, color)


def _hand_row(d, cards: list[str | None], y: int, label: str, total: str) -> None:
    d.text((22, y - 22), label, font=font("bold", 18), fill=(190, 225, 210))
    d.text((W - 22, y - 22), total, font=font("heavy", 20), fill=GOLD, anchor="ra")
    step = min(66, (W - 44 - CARD_W) // max(1, len(cards) - 1)) if len(cards) > 1 else 0
    start = 22
    for i, c in enumerate(cards):
        draw_card(d, start + i * step, y, c)


def table_image(player: list[str], dealer: list[str], hide_hole: bool, *, player_n: int | None = None, dealer_n: int | None = None) -> Image.Image:
    """블랙잭 테이블. player_n/dealer_n 은 지금까지 보여줄 카드 수(딜 애니메이션용)."""
    from bot.services.games import hand_value

    img = _bg(FELT, FELT_DARK, (W, 380))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, W - 9, 371], radius=24, outline=(120, 90, 40), width=4)
    p = player[:player_n] if player_n is not None else player
    dl = dealer[:dealer_n] if dealer_n is not None else dealer
    dealer_cards: list[str | None] = [dl[0]] + [None if (hide_hole and i == 1) else c for i, c in enumerate(dl) if i >= 1] if dl else []
    dtotal = "?" if hide_hole else (str(hand_value(dl)) if dl else "")
    _hand_row(d, dealer_cards, 48, "딜러", dtotal)
    d.text((W // 2, 190), "BLACKJACK", font=font("heavy", 20), fill=(40, 120, 95), anchor="mm")
    _hand_row(d, list(p), 232, "나", str(hand_value(p)) if p else "")
    return img


def deal_gif(player: list[str], dealer: list[str]) -> bytes:
    steps = [(1, 0), (1, 1), (2, 1), (2, 2)]
    frames = [table_image(player, dealer, True, player_n=p, dealer_n=dl) for p, dl in steps]
    return gif_bytes(frames, [450, 450, 450, 4000])


def finish_gif(player: list[str], dealer: list[str]) -> bytes:
    """딜러가 숨긴 카드를 뒤집고 필요하면 한 장씩 더 뽑는다."""
    frames = [table_image(player, dealer[:2], True), table_image(player, dealer[:2], False)]
    for k in range(3, len(dealer) + 1):
        frames.append(table_image(player, dealer[:k], False))
    return gif_bytes(frames, [500] + [750] * (len(frames) - 2) + [4000])


def table_png(player: list[str], dealer: list[str], hide_hole: bool) -> bytes:
    out = BytesIO()
    table_image(player, dealer, hide_hole).save(out, format="PNG")
    return out.getvalue()


# ---------------------------------------------------------------------------
# 블라인드 퀴즈 이미지
# ---------------------------------------------------------------------------


def quiz_image(art: Image.Image, *, silhouette: bool, caption: str | None = None) -> bytes:
    """art: 투명 배경 RGBA. silhouette=True 면 검은 실루엣."""
    img = _bg((46, 58, 78), (14, 20, 30), (W, H))
    art = art.convert("RGBA")
    box_w, box_h = W - 40, H - (70 if caption else 24)
    scale = min(box_w / art.width, box_h / art.height)
    art = art.resize((max(1, int(art.width * scale)), max(1, int(art.height * scale))), Image.LANCZOS)
    pos = ((W - art.width) // 2, 12 + (box_h - art.height) // 2)
    if silhouette:
        alpha = art.getchannel("A")
        glow = Image.new("RGBA", art.size, (120, 150, 200, 0))
        glow.putalpha(alpha.filter(ImageFilter.GaussianBlur(7)).point(lambda v: min(255, v * 2)))
        img.paste(glow, pos, glow)
        black = Image.new("RGBA", art.size, (0, 0, 0, 255))
        black.putalpha(alpha)
        img.paste(black, pos, black)
        d = ImageDraw.Draw(img)
        d.text((W - 16, 14), "?", font=font("heavy", 46), fill=(255, 255, 255), anchor="ra")
    else:
        img.paste(art, pos, art)
    if caption:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([W // 2 - 190, H - 52, W // 2 + 190, H - 12], radius=18, fill=(0, 0, 0))
        d.text((W // 2, H - 32), caption, font=font("heavy", 24), fill=GOLD, anchor="mm")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
