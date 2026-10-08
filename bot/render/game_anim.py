"""미니게임 연출용 이미지/GIF (동전·주사위·슬롯·블랙잭) — 전부 Pillow로 직접 그린다 (외부 이미지 불필요)."""

from __future__ import annotations

import math
import random
from pathlib import Path
from io import BytesIO
from functools import lru_cache
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
SYMBOL_NAMES = ["🍒", "🍀", "🔥", "👑", "💎"]
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


V_RED, V_RED_D, V_NAVY, V_OFF = (255, 70, 85), (204, 46, 62), (15, 25, 35), (236, 232, 225)
V_WHITE, V_WHITE_D = (252, 250, 245), (232, 228, 220)
# 동전 포인트 색 (테두리, 홈, 글자) — COIN_THEME 으로 선택
COIN_THEMES = {
    "red": ((255, 70, 85), (204, 46, 62)),
    "blue": ((64, 140, 255), (38, 100, 205)),
    "gold": ((240, 180, 40), (190, 135, 20)),
    "teal": ((30, 200, 170), (18, 150, 128)),
    "purple": ((150, 100, 255), (110, 70, 205)),
}
COIN_THEME = "red"


def coin_sprite(face: str, size: int = 210) -> Image.Image:
    """흰 바탕에 빨간 글자 동전. 앞면=V, 뒷면=VP. (공식 로고 모양이 아닌 일반 글꼴)"""
    key = ("coin", face, size, COIN_THEME)
    if key in _sprites:
        return _sprites[key]
    img, d, n = _canvas(size)
    c = n / 2
    ACC, ACC_D = COIN_THEMES[COIN_THEME]

    def circle(r, fill=None, outline=None, width=0):
        d.ellipse([c - r, c - r, c + r, c + r], fill=fill, outline=outline, width=width)

    circle(n * 0.485, fill=V_NAVY)                         # 외곽선
    circle(n * 0.455, fill=ACC)                          # 빨간 테두리 링
    for k in range(32):                                    # 링의 톱니 홈
        ang = math.radians(k * 360 / 32)
        d.line([(c + n * 0.405 * math.cos(ang), c + n * 0.405 * math.sin(ang)),
                (c + n * 0.448 * math.cos(ang), c + n * 0.448 * math.sin(ang))], fill=ACC_D, width=int(n * 0.014))
    circle(n * 0.385, fill=V_NAVY)
    disc = Image.new("RGBA", (n, n), (0, 0, 0, 0))          # 흰 원판 (대각선으로 아주 살짝 다른 톤)
    dd = ImageDraw.Draw(disc)
    dd.ellipse([c - n * 0.36, c - n * 0.36, c + n * 0.36, c + n * 0.36], fill=V_WHITE)
    dd.polygon([(n * 0.12, n * 0.9), (n * 0.9, n * 0.12), (n, n * 0.12), (n, n), (0, n)], fill=V_WHITE_D)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).ellipse([c - n * 0.36, c - n * 0.36, c + n * 0.36, c + n * 0.36], fill=255)
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    layer.paste(disc, (0, 0), mask)
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    d.arc([c - n * 0.43, c - n * 0.43, c + n * 0.43, c + n * 0.43], 200, 255, fill=(255, 255, 255), width=int(n * 0.022))
    text, px = ("V", 0.56) if face == "앞" else ("VP", 0.38)
    d.text((c, c + n * 0.02), text, font=font("heavy", int(n * px)), fill=ACC, anchor="mm")
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
        edge = Image.new("RGBA", flat.size, (160, 154, 146, 255))
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


SYMBOL_FILES = {"🍒": "cherries", "🍀": "clover", "🔥": "fire", "👑": "crown", "💎": "gem"}
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "slot"


def symbol_sprite(name: str, size: int = 200) -> Image.Image:
    """슬롯 심볼: Microsoft Fluent Emoji 3D (MIT) — assets/slot/. 파일이 없으면 색 원으로 대신한다."""
    key = ("sym", name, size)
    if key in _sprites:
        return _sprites[key]
    path = ASSET_DIR / f"{SYMBOL_FILES.get(name, '')}.png"
    try:
        out = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        out, d, n = _canvas(size)
        d.ellipse([n * 0.12, n * 0.12, n * 0.88, n * 0.88], fill=(255, 84, 98))
        out = _down(out, size)
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


def _coin_gif(result: str, variant: int = 0) -> bytes:
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
        height = math.sin(math.pi * min(1.0, t * 1.1)) * 40 if t < 0.91 else 0
        img = _scene()
        d = ImageDraw.Draw(img)
        sw = 60 - height * 0.25
        d.ellipse([W / 2 - sw, H - 78, W / 2 + sw, H - 58], fill=(22, 31, 44))
        _coin_at(img, W / 2, H / 2 - 12 - height, c, face)
        frames.append(img)
        durs.append(60 + int(70 * t))
    final = frames[-1].copy()
    _banner(final, f"{result}면!", V_RED)
    frames.append(final)
    durs.append(3000)
    return gif_bytes(frames, durs)


# ---------------------------------------------------------------------------
# 주사위
# ---------------------------------------------------------------------------

_PIPS = {1: [(0, 0)], 2: [(-1, -1), (1, 1)], 3: [(-1, -1), (0, 0), (1, 1)], 4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
         5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)], 6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)]}


def _dice_gif(result: int, variant: int = 0) -> bytes:
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
# 슬롯 (모던 미니멀: 어두운 본체 + 밝은 심볼 + 포인트 컬러 한 가지)
# ---------------------------------------------------------------------------

ACCENT = (255, 84, 98)
BODY, PANEL_C, CARD = (30, 34, 54), (20, 23, 38), (40, 45, 72)
WIN_W, WIN_H, WIN_GAP, WIN_X, WIN_Y = 118, 150, 12, 92, 84
_cabinet: Image.Image | None = None


def _cabinet_img() -> Image.Image:
    global _cabinet
    if _cabinet is not None:
        return _cabinet
    img = Image.new("RGB", (W, H), (17, 19, 31))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([60, 10, 500, 306], radius=30, fill=BODY)
    d.rounded_rectangle([80, 70, 480, 252], radius=20, fill=PANEL_C)
    for k in range(3):
        x = WIN_X + k * (WIN_W + WIN_GAP)
        d.rounded_rectangle([x, WIN_Y, x + WIN_W, WIN_Y + WIN_H], radius=14, fill=CARD)
    _cabinet = img
    return img


def _confetti(d: ImageDraw.ImageDraw, rng: random.Random, n: int = 26) -> None:
    cols = [(255, 214, 60), ACCENT, (110, 220, 255), (120, 235, 160), (255, 255, 255)]
    for _ in range(n):
        x, y = rng.randint(30, 530), rng.randint(4, 306)
        c = rng.choice(cols)
        if rng.random() < 0.5:
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=c)
        else:
            d.rectangle([x - 3, y - 6, x + 3, y + 6], fill=c)


def _draw_reels(img: Image.Image, reels: list[str], f: int, stops: list[int], seqs, cell: int = 100, glow: bool = False) -> None:
    d = ImageDraw.Draw(img)
    for r in range(3):
        x = WIN_X + r * (WIN_W + WIN_GAP)
        win = Image.new("RGBA", (WIN_W, WIN_H), CARD + (255,))
        if f >= stops[r]:
            spr = symbol_sprite(reels[r], 104)
            win.paste(spr, ((WIN_W - 104) // 2, (WIN_H - 104) // 2), spr)
        else:
            off = (f * 57 + r * 29) % cell
            for k in range(-1, WIN_H // cell + 2):
                sym = seqs[r][(f * 2 + k + r * 5) % len(seqs[r])]
                spr = symbol_sprite(sym, 80)
                y = k * cell + off + (cell - 80) // 2
                ghost = spr.copy()
                ghost.putalpha(ghost.getchannel("A").point(lambda v: v // 3))
                win.paste(ghost, ((WIN_W - 80) // 2, y - 30), ghost)      # 번짐 효과
                win.paste(spr, ((WIN_W - 80) // 2, y), spr)
            for i in range(8):                                            # 위·아래로 흐려지는 페이드
                a = int(150 * (1 - i / 8) ** 2)
                band = Image.new("RGBA", (WIN_W, 4), CARD + (a,))
                win.alpha_composite(band, (0, i * 4))
                win.alpha_composite(band, (0, WIN_H - (i + 1) * 4))
        mask = Image.new("L", (WIN_W, WIN_H), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, WIN_W - 1, WIN_H - 1], radius=14, fill=255)
        img.paste(win.convert("RGB"), (x, WIN_Y), mask)
        if glow:
            d.rounded_rectangle([x - 2, WIN_Y - 2, x + WIN_W + 2, WIN_Y + WIN_H + 2], radius=16, outline=(255, 214, 60), width=3)
    cy = WIN_Y + WIN_H // 2
    xr = WIN_X + 3 * WIN_W + 2 * WIN_GAP
    d.polygon([(WIN_X - 12, cy - 7), (WIN_X - 12, cy + 7), (WIN_X - 2, cy)], fill=ACCENT)      # 당첨선 표시 (창 바깥 양쪽)
    d.polygon([(xr + 12, cy - 7), (xr + 12, cy + 7), (xr + 2, cy)], fill=ACCENT)


def _chrome(img: Image.Image, led: str, led_color, pull: float, glow: bool = False) -> None:
    d = ImageDraw.Draw(img)
    d.text((280, 38), "VP SLOTS", font=font("heavy", 22), fill=(236, 238, 248), anchor="mm")
    d.rounded_rectangle([262, 52, 298, 56], radius=2, fill=ACCENT)
    pill = (60, 20, 28) if led_color == ACCENT else (28, 32, 52)
    d.rounded_rectangle([190, 266, 370, 296], radius=15, fill=PANEL_C, outline=led_color if glow else (50, 56, 86), width=2)
    d.text((280, 281), led, font=font("heavy", 16), fill=led_color, anchor="mm")
    top, rest = 96, 170                                                       # 레버 손잡이 높이 (당기면 아래로)
    ky = top + (rest - top) * 0.0 + 70 * pull
    d.rounded_rectangle([510, 110, 518, 200], radius=4, fill=(60, 66, 100))
    d.rounded_rectangle([508, 196, 520, 210], radius=5, fill=(60, 66, 100))
    d.line([(514, 200), (514, 124 + ky - 96)], fill=(150, 158, 190), width=5)
    d.ellipse([502, 112 + ky - 96, 526, 136 + ky - 96], fill=ACCENT)
    d.ellipse([507, 116 + ky - 96, 515, 124 + ky - 96], fill=(255, 170, 180))


def _slot_gif(reels: tuple[str, ...], variant: int = 0) -> bytes:
    rng = random.Random()
    stops = [14, 20, 26]
    n = 28
    seqs = [[rng.choice(SYMBOL_NAMES) for _ in range(40)] for _ in range(3)]
    frames, durs = [], []
    cab = _cabinet_img()
    for f in range(n):
        img = cab.copy()
        _draw_reels(img, reels, f, stops, seqs)
        pull = min(f, 4) / 4 if f < 9 else max(0.0, 1 - (f - 9) / 4)
        _chrome(img, "SPINNING" if f < stops[2] else "", (150, 158, 190), pull)
        frames.append(img)
        durs.append(70 if f < stops[0] else 110)
    jackpot = reels[0] == reels[1] == reels[2]
    pair = len(set(reels)) == 2
    label, col = (("JACKPOT", (255, 214, 60)) if jackpot else (("2 MATCH", (120, 235, 160)) if pair else ("TRY AGAIN", (130, 138, 170))))
    if jackpot or pair:
        for k in range(4 if jackpot else 2):
            img = cab.copy()
            _draw_reels(img, reels, 99, stops, seqs, glow=(k % 2 == 0))
            _chrome(img, label, col, 0.0, glow=True)
            if jackpot:
                _confetti(ImageDraw.Draw(img), rng)
            frames.append(img)
            durs.append(170)
    final = cab.copy()
    _draw_reels(final, reels, 99, stops, seqs, glow=jackpot)
    _chrome(final, label, col, 0.0, glow=jackpot or pair)
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


# ---------------------------------------------------------------------------
# 캐시: 결과의 경우의 수가 적어서(동전 2·주사위 6·슬롯 125) 같은 연출을 다시 쓴다.
# 여러 명이 동시에 해도 그림 생성 비용이 거의 들지 않는다. 변형(variant) 3가지를 섞어 매번 똑같아 보이지 않게 한다.
# ---------------------------------------------------------------------------

VARIANTS = 3


@lru_cache(maxsize=8)
def _coin_cached(result: str, variant: int) -> bytes:
    return _coin_gif(result, variant)


@lru_cache(maxsize=24)
def _dice_cached(result: int, variant: int) -> bytes:
    return _dice_gif(result, variant)


@lru_cache(maxsize=48)
def _slot_cached(reels: tuple[str, ...], variant: int) -> bytes:
    return _slot_gif(reels, variant)


def coin_gif(result: str) -> bytes:
    return _coin_cached(result, random.randrange(VARIANTS))


def dice_gif(result: int) -> bytes:
    return _dice_cached(result, random.randrange(VARIANTS))


def slot_gif(reels: list[str]) -> bytes:
    return _slot_cached(tuple(reels), random.randrange(VARIANTS))
