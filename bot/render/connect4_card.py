"""사목 판 그림. 작고 단순하게 그려서 느린 서버에서도 한 수에 수십 ms 안에 만든다."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from bot.render.base import BG, TEXT, font

CELL = 76          # 한 칸 크기
PAD = 22           # 판 바깥 여백
TOP = 54           # 번호 줄 높이
BOARD = (24, 70, 160)
BOARD_EDGE = (16, 48, 118)
HOLE = (12, 20, 32)
COLORS = {1: ((235, 64, 72), (170, 30, 40)), 2: ((250, 204, 60), (196, 150, 20))}   # (돌 색, 테두리)
WIN_RING = (255, 255, 255)


def render_board(board, last: tuple[int, int] | None = None) -> bytes:
    rows, cols = len(board.grid), len(board.grid[0])
    w = PAD * 2 + cols * CELL
    h = TOP + PAD + rows * CELL
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    # 위 번호 (버튼 번호와 같음). 놓을 수 없는 줄은 흐리게
    f = font("heavy", 26)
    for c in range(cols):
        x = PAD + c * CELL + CELL // 2
        full = board.grid[0][c] != 0
        d.text((x, TOP // 2 + 2), str(c + 1), font=f, fill=(90, 100, 112) if full else TEXT, anchor="mm")

    # 판
    d.rounded_rectangle([PAD - 8, TOP - 8, w - PAD + 8, h - PAD + 8], radius=18, fill=BOARD_EDGE)
    d.rounded_rectangle([PAD - 4, TOP - 4, w - PAD + 4, h - PAD + 4], radius=16, fill=BOARD)

    win = set(board.line)
    m = 9
    for r in range(rows):
        for c in range(cols):
            x0, y0 = PAD + c * CELL + m, TOP + r * CELL + m
            x1, y1 = x0 + CELL - 2 * m, y0 + CELL - 2 * m
            v = board.grid[r][c]
            if not v:
                d.ellipse([x0, y0, x1, y1], fill=HOLE)
                continue
            fill, edge = COLORS[v]
            d.ellipse([x0, y0, x1, y1], fill=edge)
            d.ellipse([x0 + 4, y0 + 4, x1 - 4, y1 - 4], fill=fill)
            d.ellipse([x0 + 12, y0 + 10, x0 + 26, y0 + 22], fill=tuple(min(255, ch + 50) for ch in fill))  # 반짝임
            if (r, c) in win:
                d.ellipse([x0 - 4, y0 - 4, x1 + 4, y1 + 4], outline=WIN_RING, width=5)
            elif last == (r, c):
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=(255, 255, 255))   # 방금 둔 돌
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
