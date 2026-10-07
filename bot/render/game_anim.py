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
# 동전
# ---------------------------------------------------------------------------


def _coin_face(d: ImageDraw.ImageDraw, cx: float, cy: float, rx: float, ry: float, face: str) -> None:
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(214, 164, 32), outline=(120, 82, 10), width=4)
    if rx > 8:
        irx, iry = rx * 0.82, ry * 0.82
        d.ellipse([cx - irx, cy - iry, cx + irx, cy + iry], fill=(243, 200, 70), outline=(176, 128, 20), width=3)
    if rx > 26:
        size = max(10, int(ry * 1.15 * min(1.0, rx / ry + 0.15)))
        d.text((cx, cy), face, font=font("heavy", size), fill=(120, 82, 10), anchor="mm")


def coin_gif(result: str) -> bytes:
    """result: '앞' | '뒤'. 동전이 튀어 오르며 돈다."""
    R = 78
    half_turns = 10 if result == "앞" else 9      # 짝수 번 뒤집히면 앞면
    n = 26
    frames, durs = [], []
    for i in range(n):
        t = (i + 1) / n
        e = 1 - (1 - t) ** 2.2                         # 점점 느려지게
        theta = math.pi * half_turns * e
        c = math.cos(theta)
        face = "앞" if c >= 0 else "뒤"
        rx = max(4.0, R * abs(c))
        height = math.sin(math.pi * min(1.0, t * 1.1)) * 70 if t < 0.91 else 0
        cy = H / 2 + 10 - height
        img = _bg()
        d = ImageDraw.Draw(img)
        d.ellipse([W / 2 - 60 + (height * 0.2), H - 70, W / 2 + 60 - (height * 0.2), H - 50], fill=(8, 12, 18))
        _coin_face(d, W / 2, cy, rx, R, face)
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


def _die(value: int, size: int = 150, highlight: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=size // 6, fill=(245, 242, 235),
                        outline=GOLD if highlight else (170, 165, 155), width=5 if highlight else 3)
    step, r = size * 0.27, size * 0.075
    for dx, dy in _PIPS[value]:
        x, y = size / 2 + dx * step, size / 2 + dy * step
        d.ellipse([x - r, y - r, x + r, y + r], fill=RED if value == 1 else (30, 30, 36))
    return img


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
        angle = rng.uniform(-1, 1) * (1 - t) * 70
        die = _die(v).rotate(angle, expand=True, resample=Image.BICUBIC)
        img = _bg()
        d = ImageDraw.Draw(img)
        cx = W / 2 + rng.uniform(-1, 1) * shake
        cy = H / 2 - 5 - math.sin(math.pi * t) * 45 * (1 - t * 0.3) + rng.uniform(-1, 1) * shake * 0.3
        d.ellipse([W / 2 - 55, H - 80, W / 2 + 55, H - 58], fill=(8, 12, 18))
        img.paste(die, (int(cx - die.width / 2), int(cy - die.height / 2)), die)
        frames.append(img)
        durs.append(50 + int(110 * t * t))
    final = _bg()
    die = _die(result, 170, highlight=True)
    final.paste(die, (W // 2 - 85, H // 2 - 95), die)
    _banner(final, f"{result}!", GOLD)
    frames.append(final)
    durs.append(3000)
    return gif_bytes(frames, durs)


# ---------------------------------------------------------------------------
# 슬롯
# ---------------------------------------------------------------------------

SLOT_ORDER = ["🍒", "🍋", "🔔", "⭐", "💎"]


def _star_points(cx, cy, r_out, r_in):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw_symbol(d: ImageDraw.ImageDraw, name: str, cx: float, cy: float, s: float) -> None:
    """s: 심볼 크기(지름 정도)."""
    if name == "🍒":
        r = s * 0.2
        for dx in (-0.2, 0.22):
            d.line([(cx + dx * s, cy + 0.12 * s), (cx + 0.05 * s, cy - 0.38 * s)], fill=(60, 140, 60), width=max(2, int(s * 0.05)))
            d.ellipse([cx + dx * s - r, cy + 0.12 * s - r, cx + dx * s + r, cy + 0.12 * s + r], fill=(215, 30, 50), outline=(120, 10, 25), width=2)
        d.ellipse([cx - 0.2 * s - r * 0.5, cy + 0.12 * s - r * 0.7, cx - 0.2 * s - r * 0.1, cy + 0.12 * s - r * 0.3], fill=(255, 150, 160))
    elif name == "🍋":
        d.ellipse([cx - s * 0.42, cy - s * 0.27, cx + s * 0.42, cy + s * 0.27], fill=(250, 225, 50), outline=(190, 160, 20), width=3)
        d.polygon([(cx + s * 0.38, cy - 0.04 * s), (cx + s * 0.5, cy), (cx + s * 0.38, cy + 0.04 * s)], fill=(190, 160, 20))
        d.ellipse([cx - s * 0.25, cy - s * 0.15, cx - s * 0.05, cy - s * 0.05], fill=(255, 245, 160))
    elif name == "🔔":
        d.pieslice([cx - s * 0.32, cy - s * 0.42, cx + s * 0.32, cy + s * 0.22], 180, 360, fill=(245, 190, 40), outline=(160, 110, 10))
        d.polygon([(cx - s * 0.32, cy - s * 0.1), (cx + s * 0.32, cy - s * 0.1), (cx + s * 0.42, cy + s * 0.22), (cx - s * 0.42, cy + s * 0.22)],
                  fill=(245, 190, 40), outline=(160, 110, 10))
        d.ellipse([cx - s * 0.09, cy + s * 0.2, cx + s * 0.09, cy + s * 0.38], fill=(180, 120, 20))
    elif name == "⭐":
        d.polygon(_star_points(cx, cy, s * 0.46, s * 0.2), fill=(255, 215, 40), outline=(170, 120, 10))
    elif name == "💎":
        pts = [(cx - s * 0.32, cy - s * 0.2), (cx - s * 0.18, cy - s * 0.38), (cx + s * 0.18, cy - s * 0.38), (cx + s * 0.32, cy - s * 0.2),
               (cx, cy + s * 0.4)]
        d.polygon(pts, fill=(80, 210, 250), outline=(20, 110, 160))
        d.line([(cx - s * 0.32, cy - s * 0.2), (cx + s * 0.32, cy - s * 0.2)], fill=(200, 245, 255), width=2)
        d.polygon([(cx - s * 0.18, cy - s * 0.38), (cx - 0.04 * s, cy - s * 0.2), (cx - s * 0.12, cy - s * 0.2)], fill=(210, 248, 255))


def slot_gif(reels: list[str]) -> bytes:
    """reels: 최종 그림 3개. 왼쪽부터 차례로 멈춘다."""
    rng = random.Random()
    box_w, box_h, gap = 130, 190, 24
    total_w = box_w * 3 + gap * 2
    x0 = (W - total_w) // 2
    y0 = 38
    cell = 96
    stops = [14, 20, 26]
    n = 28
    seqs = [[rng.choice(SLOT_ORDER) for _ in range(40)] for _ in range(3)]
    frames, durs = [], []
    for f in range(n):
        img = _bg()
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([x0 - 18, y0 - 18, x0 + total_w + 18, y0 + box_h + 18], radius=22, fill=(30, 20, 40), outline=GOLD, width=4)
        for r in range(3):
            bx = x0 + r * (box_w + gap)
            reel = Image.new("RGB", (box_w, box_h), (245, 240, 230))
            rd = ImageDraw.Draw(reel)
            if f >= stops[r]:
                draw_symbol(rd, reels[r], box_w / 2, box_h / 2, cell)
            else:
                off = (f * 47 + r * 31) % cell
                for k in range(-1, box_h // cell + 2):
                    sym = seqs[r][(f * 2 + k + r * 5) % len(seqs[r])]
                    draw_symbol(rd, sym, box_w / 2, k * cell + off + cell / 2, cell * 0.85)
                shade = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
                sd = ImageDraw.Draw(shade)
                sd.rectangle([0, 0, box_w, box_h], fill=(255, 255, 255, 50))
                reel = Image.alpha_composite(reel.convert("RGBA"), shade).convert("RGB")
            img.paste(reel, (bx, y0))
            d.rounded_rectangle([bx, y0, bx + box_w, y0 + box_h], radius=10, outline=(60, 40, 70), width=4)
        d.line([(x0 - 18, y0 + box_h // 2), (x0 + total_w + 18, y0 + box_h // 2)], fill=RED, width=2)
        frames.append(img)
        durs.append(70 if f < stops[0] else 110)
    final = frames[-1].copy()
    if reels[0] == reels[1] == reels[2]:
        _banner(final, "JACKPOT!", GOLD)
    elif len(set(reels)) == 2:
        _banner(final, "2개 일치", TEXT)
    else:
        _banner(final, "꽝", MUTED)
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
