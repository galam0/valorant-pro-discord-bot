"""선수 설정 이미지 카드: 사진, 감도, 장비, 크로스헤어 미리보기."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from bot.render.base import (
    BG, GOLD, LINE, MUTED, PANEL, PANEL_2, RED, TEXT,
    fit_text, font, paste_logo, text_w, to_png,
)

W = 1100
PAD = 30
HEADER_H = 270
TILE_H = 110
FOOTER_H = 56


def _hex(color: str | None, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    if not color:
        return default
    c = color.strip().lstrip("#")
    if len(c) == 6:
        try:
            return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            pass
    return default


def _num(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _rounded_photo(photo: Image.Image | None, size: int, name: str) -> Image.Image:
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=28, fill=255)
    bg = Image.new("RGBA", (size, size), PANEL_2 + (255,))
    if photo is not None:
        ph = photo.convert("RGBA")
        ph.thumbnail((size, size), Image.LANCZOS)
        bg.paste(ph, ((size - ph.width) // 2, size - ph.height), ph)  # 아래 정렬 (상반신 사진)
    else:
        d = ImageDraw.Draw(bg)
        d.text((size / 2, size / 2), (name[:1] or "?").upper(), font=font("heavy", int(size * 0.4)),
               fill=TEXT, anchor="mm")
    tile.paste(bg, (0, 0), mask)
    return tile


def draw_crosshair(size: int, ch: dict[str, Any]) -> Image.Image:
    """설정값으로 크로스헤어 미리보기를 그린다 (게임 1픽셀 = scale 픽셀)."""
    scale = max(3, size // 30)
    img = Image.new("RGB", (size, size), (52, 58, 66))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2
    primary = ch.get("primary") or {}
    color = _hex(primary.get("crosshair_color"))
    outline_on = str(primary.get("outlines", "")).lower().startswith("on")
    outline_t = _num(primary.get("outline_thickness"), 1) * scale

    def rect(x0: float, y0: float, x1: float, y1: float) -> None:
        if outline_on:
            d.rectangle([x0 - outline_t, y0 - outline_t, x1 + outline_t, y1 + outline_t], fill=(0, 0, 0))
        d.rectangle([x0, y0, x1, y1], fill=color)

    def lines(part: dict[str, Any], prefix: str) -> None:
        if str(part.get(f"show_{prefix}_lines", "")).lower() != "on":
            return
        length = _num(part.get(f"{prefix}_line_length"), 0) * scale
        thick = max(1.0, _num(part.get(f"{prefix}_line_thickness"), 0) * scale)
        offset = _num(part.get(f"{prefix}_line_offset"), 0) * scale
        if length <= 0:
            return
        h = thick / 2
        rect(cx - h, cy - offset - length, cx + h - 1, cy - offset - 1)   # 위
        rect(cx - h, cy + offset, cx + h - 1, cy + offset + length - 1)   # 아래
        rect(cx - offset - length, cy - h, cx - offset - 1, cy + h - 1)   # 왼쪽
        rect(cx + offset, cy - h, cx + offset + length - 1, cy + h - 1)   # 오른쪽

    lines(ch.get("outer") or {}, "outer")
    lines(ch.get("inner") or {}, "inner")
    if str(primary.get("center_dot", "")).lower().startswith("on"):
        t = max(1.0, _num(primary.get("center_dot_thickness"), 2) * scale) / 2
        rect(cx - t, cy - t, cx + t - 1, cy + t - 1)
    return img


def render_player_card(data: dict[str, Any], images: dict[str, Any] | None = None) -> bytes:
    """data: build_player_card_data()가 만든 dict. images: {'photo','team'}"""
    images = images or {}
    tiles: list[tuple[str, str, bool]] = data.get("tiles") or []
    gear: list[tuple[str, str]] = data.get("gear") or []
    ch_rows: list[tuple[str, str]] = data.get("crosshair_rows") or []
    has_settings = bool(tiles)

    tile_rows = -(-len(tiles) // 3) if tiles else 0
    gear_h = 44 + max(1, len(gear)) * 50 + 16 if gear else 0
    ch_h = 44 + 270 if ch_rows else 0
    body_h = (44 + tile_rows * (TILE_H + 14) + 52 + gear_h + ch_h) if has_settings else 140
    H = HEADER_H + 20 + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # --- 머리 ---
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H - 4, W, HEADER_H], fill=RED)
    photo = _rounded_photo(images.get("photo"), 210, data["name"])
    img.paste(photo, (PAD, 30), photo)
    x = PAD + 240
    name, nf = fit_text(d, data["name"], "heavy", 64, W - x - PAD, 30)
    d.text((x, 40), name, font=nf, fill=TEXT)
    if data.get("real_name"):
        rn, rf = fit_text(d, data["real_name"], "regular", 24, W - x - PAD)
        d.text((x, 122), rn, font=rf, fill=MUTED)
    y = 170
    if data.get("team"):
        if images.get("team") is not None:
            paste_logo(img, images["team"], (x + 20, y + 20), 40)
            tx = x + 50
        else:
            tx = x
        d.text((tx, y + 20), data["team"], font=font("heavy", 28), fill=TEXT, anchor="lm")
        x2 = tx + text_w(d, data["team"], font("heavy", 28)) + 24
    else:
        x2 = x
    if data.get("country"):
        d.text((x2, y + 20), data["country"], font=font("bold", 22), fill=MUTED, anchor="lm")

    y = HEADER_H + 20
    if not has_settings:
        d.text((W / 2, y + 60), data.get("empty_message") or "ProSettings에 등록된 설정이 없습니다.",
               font=font("regular", 24), fill=MUTED, anchor="mm")
    else:
        # --- 감도 타일 ---
        d.text((PAD, y), "게임 설정", font=font("heavy", 24), fill=TEXT)
        y += 44
        tw = (W - PAD * 2 - 14 * 2) / 3
        for i, (label, value, highlight) in enumerate(tiles):
            col, row = i % 3, i // 3
            x0 = PAD + col * (tw + 14)
            y0 = y + row * (TILE_H + 14)
            d.rounded_rectangle([x0, y0, x0 + tw, y0 + TILE_H], radius=14, fill=PANEL,
                                outline=GOLD if highlight else LINE, width=2 if highlight else 1)
            d.text((x0 + 22, y0 + 18), label, font=font("bold", 19), fill=MUTED)
            v, vf = fit_text(d, value, "heavy", 40, tw - 44, 20)
            d.text((x0 + 22, y0 + 50), v, font=vf, fill=GOLD if highlight else TEXT)
        y += tile_rows * (TILE_H + 14)
        if data.get("video"):
            d.text((PAD, y + 4), data["video"], font=font("regular", 19), fill=MUTED)
        y += 52

        # --- 장비 ---
        if gear:
            d.text((PAD, y), "장비", font=font("heavy", 24), fill=TEXT)
            y += 44
            for i, (label, value) in enumerate(gear):
                y0 = y + i * 50
                if i % 2 == 0:
                    d.rounded_rectangle([PAD, y0, W - PAD, y0 + 46], radius=10, fill=PANEL)
                d.text((PAD + 22, y0 + 23), label, font=font("bold", 20), fill=MUTED, anchor="lm")
                v, vf = fit_text(d, value, "bold", 22, W - PAD * 2 - 220)
                d.text((PAD + 200, y0 + 23), v, font=vf, fill=TEXT, anchor="lm")
            y += len(gear) * 50 + 16

        # --- 크로스헤어 ---
        if ch_rows:
            d.text((PAD, y), "크로스헤어", font=font("heavy", 24), fill=TEXT)
            y += 44
            preview = draw_crosshair(220, data.get("crosshair_raw") or {})
            mask = Image.new("L", preview.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, 219, 219], radius=16, fill=255)
            img.paste(preview, (PAD, y), mask)
            rx = PAD + 250
            for i, (label, value) in enumerate(ch_rows):
                yy = y + 6 + i * 38
                d.text((rx, yy), label, font=font("bold", 19), fill=MUTED)
                v, vf = fit_text(d, value, "bold", 21, W - PAD - rx - 170)
                d.text((rx + 150, yy), v, font=vf, fill=TEXT)
            if data.get("crosshair_code"):
                code, cf = fit_text(d, data["crosshair_code"], "regular", 17, W - PAD * 2 - 260, 12)
                d.rounded_rectangle([rx - 10, y + 228, W - PAD, y + 262], radius=8, fill=PANEL)
                d.text((rx, y + 245), code, font=cf, fill=TEXT, anchor="lm")

    # --- 바닥글 ---
    fy = H - FOOTER_H
    d.line([PAD, fy, W - PAD, fy], fill=LINE, width=1)
    d.text((PAD, fy + FOOTER_H / 2), "출처: ProSettings.net", font=font("regular", 16), fill=MUTED, anchor="lm")
    if data.get("updated"):
        d.text((W - PAD, fy + FOOTER_H / 2), f"설정 업데이트 {data['updated']}", font=font("regular", 16),
               fill=MUTED, anchor="rm")
    return to_png(img)
