"""지뢰찾기 판 (디스코드와 무관한 순수 로직 — 테스트하기 쉽게).

- 첫 칸은 반드시 안전: 지뢰는 첫 클릭 뒤에 그 칸(과 가능하면 주변)을 피해서 깐다.
- 빈 칸(주변 지뢰 0)을 열면 이어진 빈 칸과 그 테두리 숫자까지 한 번에 열린다.
"""

from __future__ import annotations

import random

NUMBER_EMOJI = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
MINE = "💣"


class Board:
    def __init__(self, rows: int, cols: int, mines: int, rng: random.Random | None = None) -> None:
        if not 0 < mines < rows * cols:
            raise ValueError("지뢰 수가 판 크기와 맞지 않아요")
        self.rows, self.cols, self.mines = rows, cols, mines
        self.rng = rng or random.Random()
        self.mine: set[tuple[int, int]] = set()
        self.opened: set[tuple[int, int]] = set()
        self.flags: set[tuple[int, int]] = set()
        self.started = False
        self.lost_at: tuple[int, int] | None = None

    # -- 기본 ----------------------------------------------------------
    def cells(self):
        return ((r, c) for r in range(self.rows) for c in range(self.cols))

    def around(self, r: int, c: int):
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, c + dc
                if (dr or dc) and 0 <= rr < self.rows and 0 <= cc < self.cols:
                    yield rr, cc

    def count(self, r: int, c: int) -> int:
        return sum(p in self.mine for p in self.around(r, c))

    def place(self, safe: tuple[int, int]) -> None:
        """safe 칸과 그 주변을 피해서 지뢰를 깐다 (자리가 모자라면 safe 칸만 피함)."""
        avoid = {safe, *self.around(*safe)}
        spots = [p for p in self.cells() if p not in avoid]
        if len(spots) < self.mines:
            spots = [p for p in self.cells() if p != safe]
        self.mine = set(self.rng.sample(spots, self.mines))
        self.started = True

    # -- 상태 ----------------------------------------------------------
    @property
    def lost(self) -> bool:
        return self.lost_at is not None

    @property
    def won(self) -> bool:
        return not self.lost and self.started and len(self.opened) == self.rows * self.cols - self.mines

    @property
    def over(self) -> bool:
        return self.lost or self.won

    # -- 행동 ----------------------------------------------------------
    def reveal(self, r: int, c: int) -> None:
        if self.over or (r, c) in self.flags or (r, c) in self.opened:
            return
        if not self.started:
            self.place((r, c))
        if (r, c) in self.mine:
            self.lost_at = (r, c)
            return
        stack = [(r, c)]
        while stack:
            p = stack.pop()
            if p in self.opened or p in self.mine:
                continue
            self.opened.add(p)
            self.flags.discard(p)
            if self.count(*p) == 0:
                stack.extend(q for q in self.around(*p) if q not in self.opened)

    def toggle_flag(self, r: int, c: int) -> None:
        if self.over or (r, c) in self.opened:
            return
        self.flags ^= {(r, c)}


def spoiler_board(rows: int, cols: int, mines: int, rng: random.Random | None = None) -> str:
    """스포일러(||칸||)로 가린 판. 시작점으로 빈 칸 하나는 열어 둔다."""
    rng = rng or random.Random()
    b = Board(rows, cols, mines, rng)
    start = (rng.randrange(rows), rng.randrange(cols))
    b.place(start)
    zeros = [p for p in b.cells() if p not in b.mine and b.count(*p) == 0]
    start = start if start in zeros or not zeros else rng.choice(zeros)
    lines = []
    for r in range(rows):
        row = []
        for c in range(cols):
            face = MINE if (r, c) in b.mine else NUMBER_EMOJI[b.count(r, c)]
            row.append(face if (r, c) == start else f"||{face}||")
        lines.append("".join(row))
    return "\n".join(lines)
