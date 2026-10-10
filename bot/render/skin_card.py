"""스킨·세트 카드 이미지 (Pillow). 무기 이미지와 등급 아이콘은 호출하는 쪽이 받아서 넘겨 준다."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from bot.render.base import BG, LINE, MUTED, PANEL, PANEL_2, TEXT, fit_text, font

W = 900
SKIN_H = 480
MAX_ROWS = 10


def _tier_rgb(color: int | None) -> tuple[int, int, int]:
    if color is None:
        return (255, 70, 85)
    return ((color >> 16) & 255, (color >> 8) & 255, color & 255)


def _background(w: int, h: int, accent: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip((24, 36, 49), (11, 18, 27))))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([w * 0.35, h * 0.1, w * 1.05, h * 1.0], fill=tuple(int(c * 0.45) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    return _add(img, glow)


def _add(base: Image.Image, top: Image.Image) -> Image.Image:
    from PIL import ImageChops

    return ImageChops.add(base, top)


def _paste_fit(img: Image.Image, pic: Image.Image, box: tuple[int, int, int, int]) -> None:
    """상자 안에 비율을 지켜 가운데 맞춰 붙인다 (작은 그림은 키운다)."""
    bw, bh = box[2] - box[0], box[3] - box[1]
    scale = min(bw / pic.width, bh / pic.height)
    size = (max(1, int(pic.width * scale)), max(1, int(pic.height * scale)))
    pic = pic.resize(size, Image.LANCZOS)
    img.paste(pic, (box[0] + (bw - size[0]) // 2, box[1] + (bh - size[1]) // 2), pic)


def _icon(img: Image.Image, pic: Image.Image | None, xy: tuple[int, int], size: int) -> None:
    if pic is not None:
        _paste_fit(img, pic, (xy[0], xy[1], xy[0] + size, xy[1] + size))


def _chip(d: ImageDraw.ImageDraw, x: int, y: int, label: str, value: str, accent) -> int:
    f_l, f_v = font("regular", 14), font("bold", 24)
    w = int(max(d.textlength(label, font=f_l), d.textlength(value, font=f_v))) + 36
    d.rounded_rectangle([x, y, x + w, y + 62], radius=12, fill=PANEL, outline=LINE)
    d.rectangle([x, y + 12, x + 3, y + 50], fill=accent)
    d.text((x + 18, y + 10), label, font=f_l, fill=MUTED)
    d.text((x + 18, y + 30), value, font=f_v, fill=TEXT)
    return x + w + 12


def _png(img: Image.Image) -> bytes:
    out = BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()


def render_skin_card(skin, idx: int, weapon_img: Image.Image | None, tier_img: Image.Image | None) -> bytes:
    from bot.services.skin_service import price_text

    accent = _tier_rgb(skin.color)
    img = _background(W, SKIN_H, accent)
    d = ImageDraw.Draw(img)

    # 등급 아이콘 + 이름
    _icon(img, tier_img, (40, 30), 44)
    d.text((96, 52), skin.tier or "등급 없음", font=font("bold", 22), fill=accent, anchor="lm")

    title, f_title = fit_text(d, skin.name, "heavy", 46, W - 80)
    d.text((40, 100), title, font=f_title, fill=TEXT, anchor="lm")
    sub = " · ".join(x for x in (skin.weapon, skin.theme) if x)
    d.text((40, 142), sub, font=font("regular", 20), fill=MUTED, anchor="lm")

    # 무기 이미지
    label, image = skin.variants[idx][0], skin.variants[idx][1]
    if weapon_img is not None:
        _paste_fit(img, weapon_img, (70, 170, W - 70, 380))
    else:
        d.text((W // 2, 275), "이미지를 불러오지 못했어요", font=font("regular", 20), fill=MUTED, anchor="mm")

    # 아래 줄: 정보 칩 + 색상 점
    y = 396
    x = 40
    price = price_text(skin)
    x = _chip(d, x, y, "가격", price or ("패스 보상" if getattr(skin, "reward", False) else "정보 없음"), accent)
    x = _chip(d, x, y, "레벨", f"{skin.levels}단계" if skin.levels else "-", accent)
    x = _chip(d, x, y, "색상 변형", f"{skin.chromas}개", accent)

    n = len(skin.variants)
    if n > 1:
        d.text((W - 40, 410), f"색상  {label}", font=font("bold", 18), fill=TEXT, anchor="rm")
        shown = min(n, 12)
        start = W - 40 - shown * 18
        for i in range(shown):
            cx = start + i * 18 + 6
            on = i == idx if n <= 12 else i == min(idx, 11)
            d.ellipse([cx - 5, 432, cx + 5, 442], fill=accent if on else PANEL_2, outline=LINE)
        d.text((W - 40, 456), f"{idx + 1} / {n}", font=font("regular", 14), fill=MUTED, anchor="rm")
    return _png(img)


def render_set_card(bundle, images: dict[str, Image.Image | None]) -> bytes:
    """세트(번들) 한 장: 왼쪽에 번들 그림, 오른쪽에 포함 스킨 목록. images: 'bundle' + 등급 아이콘 URL."""
    from bot.services.skin_service import price_text

    skins = bundle.skins[:MAX_ROWS]
    rows = max(len(skins), 1)
    h = max(120 + rows * 44 + 50, 440)
    first = bundle.skins[0] if bundle.skins else None
    accent = _tier_rgb(first.color if first else None)
    img = _background(W, h, accent)
    d = ImageDraw.Draw(img)

    title, f_title = fit_text(d, bundle.label or bundle.name, "heavy", 42, W - 80)
    d.text((40, 52), title, font=f_title, fill=TEXT, anchor="lm")
    sub = bundle.subtext or (f"스킨 {len(bundle.skins)}개" if bundle.skins else "")
    if sub:
        d.text((40, 92), sub[:40], font=font("regular", 20), fill=MUTED, anchor="lm")

    pic = images.get("bundle")
    if pic is not None:
        _paste_fit(img, pic, (40, 120, 340, h - 40))
    else:
        d.rounded_rectangle([40, 120, 340, h - 40], radius=14, fill=PANEL, outline=LINE)

    x0 = 370
    if not skins:
        d.text((x0, 150), "스킨 구성 정보를 찾지 못했어요", font=font("regular", 20), fill=MUTED)
    for i, s in enumerate(skins):
        y = 124 + i * 44
        d.rounded_rectangle([x0, y, W - 40, y + 38], radius=10, fill=PANEL if i % 2 == 0 else PANEL_2)
        _icon(img, images.get(s.tier_icon or ""), (x0 + 8, y + 4), 30)
        name, f = fit_text(d, s.name, "bold", 20, 330)
        d.text((x0 + 48, y + 19), name, font=f, fill=TEXT, anchor="lm")
        d.text((W - 150, y + 19), s.weapon, font=font("regular", 15), fill=MUTED, anchor="rm")
        p = price_text(s)
        d.text((W - 54, y + 19), p or "-", font=font("bold", 16), fill=TEXT, anchor="rm")
    if len(bundle.skins) > MAX_ROWS:
        d.text((x0, 124 + rows * 44 + 4), f"…외 {len(bundle.skins) - MAX_ROWS}개", font=font("regular", 16), fill=MUTED)
    d.text((W - 40, h - 20), "'약'이 붙은 가격은 어림값이에요", font=font("regular", 13), fill=MUTED, anchor="rm")
    return _png(img)


GRID_COLS, GRID_ROWS = 5, 4
GRID_PER_PAGE = GRID_COLS * GRID_ROWS
_CELL_W, _CELL_H, _GAP, _MARGIN = 190, 214, 14, 30


def render_set_grid(bundles: list, images: dict[str, Image.Image | None], page: int, pages: int, total: int, start_no: int = 1) -> bytes:
    """세트 목록 한 쪽 (5×4 = 20개): 그림 + 번호 뱃지 + 이름. images: 세트 uuid → 그림."""
    w = _MARGIN * 2 + GRID_COLS * _CELL_W + (GRID_COLS - 1) * _GAP
    rows = max(1, -(-len(bundles) // GRID_COLS))
    h = 84 + rows * _CELL_H + (rows - 1) * _GAP + 56
    img = _background(w, h, (255, 70, 85))
    d = ImageDraw.Draw(img)
    d.text((_MARGIN, 44), "세트 목록", font=font("heavy", 32), fill=TEXT, anchor="lm")
    d.text((w - _MARGIN, 44), f"{page + 1} / {pages}쪽 · 전체 {total}개", font=font("bold", 18), fill=MUTED, anchor="rm")
    for i, b in enumerate(bundles):
        r, c = divmod(i, GRID_COLS)
        x = _MARGIN + c * (_CELL_W + _GAP)
        y = 84 + r * (_CELL_H + _GAP)
        from bot.services.skin_service import set_tier, short_tier

        rep = set_tier(b)
        accent = _tier_rgb(rep.color if rep else None)
        d.rounded_rectangle([x, y, x + _CELL_W, y + _CELL_H], radius=14, fill=PANEL, outline=LINE)
        d.rounded_rectangle([x, y, x + _CELL_W, y + 4], radius=2, fill=accent)
        pic = images.get(b.uuid)
        if pic is not None:
            _paste_fit(img, pic, (x + 8, y + 12, x + _CELL_W - 8, y + 148))
        tier_pic = images.get(rep.tier_icon or "") if rep else None
        icon_w = 26 if tier_pic is not None else 0           # 이름 앞에 등급 아이콘
        name, f = fit_text(d, b.label or b.name, "bold", 16, _CELL_W - 20 - icon_w, min_size=12)
        total = icon_w + d.textlength(name, font=f)
        left = x + (_CELL_W - total) / 2
        if tier_pic is not None:
            _icon(img, tier_pic, (int(left), y + 161), 22)
        d.text((left + icon_w, y + 172), name, font=f, fill=TEXT, anchor="lm")
        info = f"{short_tier(rep.tier)} · 스킨 {len(b.skins)}개" if rep and rep.tier else f"스킨 {len(b.skins)}개"
        d.text((x + _CELL_W // 2, y + 196), info, font=font("regular", 13), fill=accent if rep and rep.tier else MUTED, anchor="mm")
        d.ellipse([x + 8, y + 12, x + 38, y + 42], fill=(0, 0, 0), outline=accent, width=2)
        d.text((x + 23, y + 27), str(start_no + i), font=font("bold", 15), fill=TEXT, anchor="mm")
    d.text((w // 2, h - 26), "아래 메뉴에서 번호의 세트를 고르면 자세히 보여줘요", font=font("regular", 15), fill=MUTED, anchor="mm")
    return _png(img)


def render_skin_grid(skins: list, images: dict[str, Image.Image | None], title: str, right: str, start_no: int = 1) -> bytes:
    """스킨 목록 한 쪽 (5×4 = 20개). images: 스킨 uuid → 그림, 등급 아이콘 주소 → 아이콘."""
    from bot.services.skin_service import price_text, short_tier

    w = _MARGIN * 2 + GRID_COLS * _CELL_W + (GRID_COLS - 1) * _GAP
    rows = max(1, -(-len(skins) // GRID_COLS))
    h = 84 + rows * _CELL_H + (rows - 1) * _GAP + 40
    img = _background(w, h, (255, 70, 85))
    d = ImageDraw.Draw(img)
    d.text((_MARGIN, 44), title, font=font("heavy", 32), fill=TEXT, anchor="lm")
    d.text((w - _MARGIN, 44), right, font=font("bold", 18), fill=MUTED, anchor="rm")
    for i, s in enumerate(skins):
        r, c = divmod(i, GRID_COLS)
        x = _MARGIN + c * (_CELL_W + _GAP)
        y = 84 + r * (_CELL_H + _GAP)
        accent = _tier_rgb(s.color)
        d.rounded_rectangle([x, y, x + _CELL_W, y + _CELL_H], radius=14, fill=PANEL, outline=LINE)
        d.rounded_rectangle([x, y, x + _CELL_W, y + 4], radius=2, fill=accent)
        pic = images.get(s.uuid)
        if pic is not None:
            _paste_fit(img, pic, (x + 8, y + 24, x + _CELL_W - 8, y + 148))
        tier_pic = images.get(s.tier_icon or "")
        icon_w = 26 if tier_pic is not None else 0
        name, f = fit_text(d, s.name, "bold", 16, _CELL_W - 20 - icon_w, min_size=12)
        left = x + (_CELL_W - (icon_w + d.textlength(name, font=f))) / 2
        if tier_pic is not None:
            _icon(img, tier_pic, (int(left), y + 161), 22)
        d.text((left + icon_w, y + 172), name, font=f, fill=TEXT, anchor="lm")
        parts = [p for p in (short_tier(s.tier), price_text(s)) if p]
        d.text((x + _CELL_W // 2, y + 196), " · ".join(parts) or "-", font=font("regular", 13),
               fill=accent if s.tier else MUTED, anchor="mm")
        d.ellipse([x + 8, y + 12, x + 38, y + 42], fill=(0, 0, 0), outline=accent, width=2)
        d.text((x + 23, y + 27), str(start_no + i), font=font("bold", 15), fill=TEXT, anchor="mm")
    return _png(img)
