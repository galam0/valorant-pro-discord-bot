"""이미지 카드 공통: 폰트, 색, 그리기 헬퍼.

폰트: 프로젝트의 fonts/ 폴더(나눔고딕)를 우선 쓰고, 없으면 시스템 Noto Sans CJK를 찾는다.
둘 다 없으면 이미지 카드를 끄고 기존 텍스트 Embed로 대체한다 (render_enabled()).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = ROOT / "fonts"

# (파일, ttc 인덱스) 후보. 굵기별로 앞에서부터 찾는다.
_FONT_CANDIDATES: dict[str, list[tuple[Path, int]]] = {
    "regular": [
        (FONT_DIR / "NanumGothic.ttf", 0),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 1),
    ],
    "bold": [
        (FONT_DIR / "NanumGothicBold.ttf", 0),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"), 1),
    ],
    "heavy": [
        (FONT_DIR / "NanumGothicExtraBold.ttf", 0),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"), 1),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"), 1),
    ],
}

# --- 색 (VALORANT 느낌의 어두운 남색 + 레드) ---
BG = (15, 25, 35)
PANEL = (26, 39, 51)
PANEL_2 = (33, 48, 62)
LINE = (45, 62, 78)
TEXT = (236, 232, 225)
MUTED = (139, 151, 161)
RED = (255, 70, 85)
GREEN = (61, 220, 151)
GOLD = (240, 196, 25)
LIVE = (237, 66, 69)


def _resolve(weight: str) -> tuple[Path, int] | None:
    for path, index in _FONT_CANDIDATES[weight]:
        if path.exists():
            return path, index
    return None


def render_enabled() -> bool:
    return all(_resolve(w) for w in _FONT_CANDIDATES) and os.getenv("IMAGE_CARDS", "1") != "0"


@lru_cache(maxsize=64)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    found = _resolve(weight)
    if found is None:
        raise RuntimeError("카드용 한글 폰트가 없습니다 (fonts/ 폴더 확인)")
    return ImageFont.truetype(str(found[0]), size, index=found[1])


def text_w(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=f)


def fit_text(draw: ImageDraw.ImageDraw, text: str, weight: str, size: int, max_w: float, min_size: int = 14) -> tuple[str, ImageFont.FreeTypeFont]:
    """max_w 안에 들어가게 글자 크기를 줄이고, 그래도 넘치면 … 처리."""
    while size > min_size and text_w(draw, text, font(weight, size)) > max_w:
        size -= 1
    f = font(weight, size)
    if text_w(draw, text, f) > max_w:
        while text and text_w(draw, text + "…", f) > max_w:
            text = text[:-1]
        text += "…"
    return text, f


def pill(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fill: tuple[int, int, int],
         f: ImageFont.FreeTypeFont, fg: tuple[int, int, int] = (255, 255, 255), pad_x: int = 14, h: int = 34) -> float:
    """둥근 배지. 오른쪽 끝 x 좌표를 반환."""
    x, y = xy
    w = text_w(draw, text, f) + pad_x * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=fill)
    draw.text((x + w / 2, y + h / 2), text, font=f, fill=fg, anchor="mm")
    return x + w


DARK_VALUE = 90         # R·G·B 중 가장 밝은 값이 이보다 낮은 픽셀만 '검정 계열'로 본다 (0~255)
                        # 밝기(휘도) 기준이면 진한 빨강(농심 등)도 어둡게 잡혀 흰색이 돼 버린다
DARK_SHARE = 0.5        # 로고의 보이는 픽셀 중 이 비율 이상이 검정 계열이면 흰색으로 바꾼다


def lighten_dark_logo(lg: Image.Image) -> Image.Image:
    """검정·남색 위주의 로고를 흰색으로 바꾼다 (어두운 카드 배경에서 안 보이는 문제).

    색이 있는 로고(검정은 외곽선뿐인 경우)는 그대로 둔다: 어두운 픽셀이 절반 미만이면 원본 반환.
    투명도(알파)는 유지해서 가장자리가 깨지지 않는다.
    """
    lg = lg.convert("RGBA")
    alpha = lg.getchannel("A")
    opaque = alpha.point(lambda a: 255 if a > 40 else 0)
    total = opaque.histogram()[255]
    if total == 0:
        return lg
    r, g, b, _ = lg.split()
    value = ImageChops.lighter(ImageChops.lighter(r, g), b)       # 픽셀별 max(R, G, B)
    dark = ImageChops.multiply(value.point(lambda v: 255 if v < DARK_VALUE else 0), opaque)
    if dark.histogram()[255] / total < DARK_SHARE:
        return lg
    white = Image.new("RGB", lg.size, (245, 245, 245))
    out = Image.composite(white, lg.convert("RGB"), dark).convert("RGBA")
    out.putalpha(alpha)
    return out


def paste_logo(img: Image.Image, logo: Image.Image | None, center: tuple[int, int], size: int,
               fallback_text: str = "?") -> None:
    """로고를 정사각형 안에 맞춰 붙인다. 없으면 이니셜 원으로 대체."""
    cx, cy = center
    if logo is not None:
        lg = logo.convert("RGBA")
        lg.thumbnail((size, size), Image.LANCZOS)
        lg = lighten_dark_logo(lg)
        img.paste(lg, (cx - lg.width // 2, cy - lg.height // 2), lg)
        return
    d = ImageDraw.Draw(img)
    r = size // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PANEL_2, outline=LINE, width=3)
    initials = "".join(w[0] for w in fallback_text.split()[:2]).upper() or "?"
    d.text((cx, cy), initials, font=font("heavy", int(size * 0.36)), fill=TEXT, anchor="mm")


def to_png(img: Image.Image) -> bytes:
    from io import BytesIO

    out = BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()
