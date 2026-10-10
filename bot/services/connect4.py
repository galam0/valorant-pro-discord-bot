"""사목(Connect 4) 판 — 디스코드와 무관한 순수 로직.

7칸 × 6줄. 고른 줄 맨 아래 빈 칸에 돌이 떨어지고, 가로·세로·대각선으로 4개를 먼저 이으면 승리.
"""

from __future__ import annotations

ROWS, COLS = 6, 7
EMPTY = 0
DISC = {1: "🔴", 2: "🟡"}
WIN_DISC = {1: "🟥", 2: "🟨"}      # 이긴 줄 표시
HOLE = "⚫"
HEADER = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"


class Board:
    def __init__(self) -> None:
        self.grid = [[EMPTY] * COLS for _ in range(ROWS)]   # grid[0] 이 맨 위 줄
        self.turn = 1
        self.winner: int | None = None
        self.line: list[tuple[int, int]] = []
        self.moves = 0

    def can_drop(self, col: int) -> bool:
        return self.winner is None and 0 <= col < COLS and self.grid[0][col] == EMPTY

    @property
    def full(self) -> bool:
        return self.moves >= ROWS * COLS

    @property
    def over(self) -> bool:
        return self.winner is not None or self.full

    def drop(self, col: int) -> int | None:
        """지금 차례의 돌을 떨어뜨린다. 놓인 줄 번호(없으면 None)."""
        if not self.can_drop(col):
            return None
        row = max(r for r in range(ROWS) if self.grid[r][col] == EMPTY)
        self.grid[row][col] = self.turn
        self.moves += 1
        line = self._line_through(row, col)
        if line:
            self.winner, self.line = self.turn, line
        else:
            self.turn = 3 - self.turn
        return row

    def _line_through(self, row: int, col: int) -> list[tuple[int, int]]:
        me = self.grid[row][col]
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            cells = [(row, col)]
            for sign in (1, -1):
                r, c = row + dr * sign, col + dc * sign
                while 0 <= r < ROWS and 0 <= c < COLS and self.grid[r][c] == me:
                    cells.append((r, c))
                    r, c = r + dr * sign, c + dc * sign
            if len(cells) >= 4:
                return cells
        return []

    def text(self) -> str:
        win = set(self.line)
        rows = []
        for r in range(ROWS):
            rows.append("".join(
                (WIN_DISC if (r, c) in win else DISC).get(v, HOLE) for c, v in enumerate(self.grid[r])))
        return HEADER + "\n" + "\n".join(rows)
