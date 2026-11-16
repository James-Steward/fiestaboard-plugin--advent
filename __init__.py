"""Christmas advent tree plugin for FiestaBoard.

A pixel-art Christmas tree drawn in Vestaboard colour tiles. Every day from
1 December one more coloured bauble is hung on it, so the tree
fills up like an advent calendar. On Christmas Day the star goes on top and
presents appear underneath.

Fully offline: no API, no key, no network calls.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:  # pragma: no cover - exercised implicitly by the host application
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        """Raised when the zoneinfo database is unavailable."""


from src.plugins.base import PluginBase, PluginResult

logger = logging.getLogger(__name__)

# Vestaboard colour tiles. Written as {NN} in template output; each one
# occupies exactly one tile on the board.
RED, ORANGE, YELLOW, GREEN, BLUE, VIOLET, WHITE, BLACK = 63, 64, 65, 66, 67, 68, 69, 70

BOARD_WIDTH = {"note": 15, "flagship": 22}
BOARD_ROWS = {"note": 3, "flagship": 6}

# Bauble colours, cycled in the order the baubles appear. Spread so that two
# baubles hung on consecutive days are never the same colour.
BAUBLE_COLORS = [RED, YELLOW, BLUE, WHITE, VIOLET, ORANGE]

STAR = YELLOW
PRESENTS = [RED, BLUE, VIOLET, WHITE]

COUNTDOWN_STYLES = ("sleeps", "days")

# ----------------------------------------------------------------------
# Tree geometry
#
# Each layout is the tree's foliage as (row, col) tiles, the bauble slots in
# the order they are hung, the star tile, the presents, and the text column.
# ----------------------------------------------------------------------


def _triangle(top_row: int, centre: int, widths: List[int]) -> List[Tuple[int, int]]:
    cells: List[Tuple[int, int]] = []
    for offset, width in enumerate(widths):
        half = width // 2
        cells.extend((top_row + offset, col) for col in range(centre - half, centre + half + 1))
    return cells


def _spread_order(cells: List[Tuple[int, int]], first: Tuple[int, int]) -> List[Tuple[int, int]]:
    """Order tiles so each new one is as far as possible from those already lit.

    Greedy farthest-point ordering: at every step the tree looks evenly
    decorated rather than filling up from one side. Ties break on row then
    column, so the order is fixed and every board shows the same tree.
    """
    remaining = [c for c in cells if c != first]
    order = [first]
    while remaining:
        def score(cell):
            # Rows are visually taller than columns are wide on a Vestaboard,
            # so weight vertical distance a little more.
            nearest = min((1.6 * (cell[0] - o[0])) ** 2 + (cell[1] - o[1]) ** 2 for o in order)
            return (-nearest, cell[0], cell[1])

        best = min(remaining, key=score)
        order.append(best)
        remaining.remove(best)
    return order


def _checker(cells: List[Tuple[int, int]], parity: int) -> List[Tuple[int, int]]:
    """Every other tile, so each bauble sits in green rather than in a clump."""
    return [(r, c) for r, c in cells if (r + c) % 2 == parity]


# Flagship (22x6): a six-row tree (3 to 13 tiles wide) on the left. Baubles
# hang on a checkerboard of 24 slots, one per day of advent, so even on
# Christmas Eve every bauble is framed by green. The top-centre tile becomes
# the star on Christmas Day. Presents sit under the caption.
_FLAG_CENTRE = 6
_FLAG_FOLIAGE = _triangle(0, _FLAG_CENTRE, [3, 5, 7, 9, 11, 13])
_FLAG_SLOTS = [
    cell
    for cell in _checker(_FLAG_FOLIAGE, 1)
    if cell[0] != 0 and cell != (5, _FLAG_CENTRE)
]
FLAGSHIP = {
    "foliage": _FLAG_FOLIAGE,
    "baubles": _spread_order(_FLAG_SLOTS, (3, _FLAG_CENTRE)),
    "star": (0, _FLAG_CENTRE),
    "presents": [(5, 15), (5, 16), (5, 19), (5, 20)],
    "text_col": 14,
    "text_width": 8,
}

# Note (15x3): a three-row tree (3, 5, 7 wide) with 9 bauble slots shared
# across the 24 days, so on a Note a bauble appears every two or three days.
_NOTE_CENTRE = 3
_NOTE_FOLIAGE = _triangle(0, _NOTE_CENTRE, [3, 5, 7])
NOTE = {
    "foliage": _NOTE_FOLIAGE,
    "baubles": _spread_order(_checker(_NOTE_FOLIAGE, 0), (1, _NOTE_CENTRE)),
    "star": (0, _NOTE_CENTRE),
    "presents": [],
    "text_col": 8,
    "text_width": 7,
}

LAYOUTS = {"flagship": FLAGSHIP, "note": NOTE}

ADVENT_DAYS = 24


# ----------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------


def phase_for(today: date) -> Dict[str, Any]:
    """Work out where in the season ``today`` falls.

    Phases:
      PRE     before 1 December: bare tree, counting down to advent
      ADVENT  1-24 December: one more bauble each day
      XMAS    25 December: full tree, star and presents
      HOLS    26-31 December: tree stays fully decorated
      NEWYEAR 1-6 January: tree stays up until Twelfth Night
    """
    year = today.year
    if today.month == 12 and today.day <= ADVENT_DAYS:
        return {"phase": "ADVENT", "day": today.day, "sleeps": (date(year, 12, 25) - today).days}
    if today.month == 12 and today.day == 25:
        return {"phase": "XMAS", "day": 25, "sleeps": 0}
    if today.month == 12:
        return {"phase": "HOLS", "day": today.day, "sleeps": 0}
    if today.month == 1 and today.day <= 6:
        return {"phase": "NEWYEAR", "day": 0, "sleeps": 0, "year": year}
    start = date(year, 12, 1)
    return {"phase": "PRE", "day": 0, "sleeps": 0, "days_to_advent": (start - today).days}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}S"


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------


def _blank_grid(board: str) -> List[List[str]]:
    return [[" "] * BOARD_WIDTH[board] for _ in range(BOARD_ROWS[board])]


def _tile(color: int) -> str:
    return "{%d}" % color


def draw_tree(board: str, state: Dict[str, Any], twinkle_offset: int = 0) -> List[List[str]]:
    """Paint the tree for ``state`` onto a blank grid of board tiles."""
    layout = LAYOUTS[board]
    grid = _blank_grid(board)
    phase = state["phase"]

    for row, col in layout["foliage"]:
        grid[row][col] = _tile(GREEN)

    if phase == "ADVENT":
        slots = len(layout["baubles"])
        lit = math.ceil(state["day"] * slots / ADVENT_DAYS)
    elif phase == "PRE":
        lit = 0
    else:
        lit = len(layout["baubles"])

    for index, (row, col) in enumerate(layout["baubles"][:lit]):
        color = BAUBLE_COLORS[(index + twinkle_offset) % len(BAUBLE_COLORS)]
        grid[row][col] = _tile(color)

    star_row, star_col = layout["star"]
    if phase in ("XMAS", "HOLS", "NEWYEAR"):
        grid[star_row][star_col] = _tile(STAR)

    if phase in ("XMAS", "HOLS"):
        for index, (row, col) in enumerate(layout["presents"]):
            grid[row][col] = _tile(PRESENTS[index % len(PRESENTS)])

    return grid


def caption(board: str, state: Dict[str, Any], style: str) -> List[str]:
    """Text for the column beside the tree, one entry per board row."""
    phase = state["phase"]
    rows = BOARD_ROWS[board]
    unit = "SLEEP" if style == "sleeps" else "DAY"

    if board == "note":
        if phase == "PRE":
            days = state["days_to_advent"]
            text = ["ADVENT", f"IN {days}", "DAY" if days == 1 else "DAYS"]
        elif phase == "ADVENT":
            sleeps = state["sleeps"]
            text = [str(sleeps), unit if sleeps == 1 else unit + "S", "TO XMAS"]
        elif phase == "XMAS":
            text = ["MERRY", "XMAS!", "HO HO"]
        elif phase == "HOLS":
            text = ["HAPPY", "HOLS!", ""]
        else:
            text = ["HAPPY", "NEW YR", str(state["year"])]
    else:
        if phase == "PRE":
            days = state["days_to_advent"]
            text = ["", "ADVENT", f"IN {days}", "DAY" if days == 1 else "DAYS", "", ""]
        elif phase == "ADVENT":
            sleeps = state["sleeps"]
            text = ["", str(sleeps), unit if sleeps == 1 else unit + "S", "TO XMAS", "", ""]
        elif phase == "XMAS":
            text = ["", "MERRY", "XMAS!", "", "HO HO HO", ""]
        elif phase == "HOLS":
            text = ["", "HAPPY", "HOLS!", "", "", ""]
        else:
            text = ["", "HAPPY", "NEW YEAR", str(state["year"]), "", ""]

    return (text + [""] * rows)[:rows]


def headline(state: Dict[str, Any], style: str) -> str:
    phase = state["phase"]
    if phase == "PRE":
        return f"ADVENT IN {_plural(state['days_to_advent'], 'DAY')}"
    if phase == "ADVENT":
        unit = "SLEEP" if style == "sleeps" else "DAY"
        return f"{_plural(state['sleeps'], unit)} TO XMAS"
    if phase == "XMAS":
        return "MERRY CHRISTMAS!"
    if phase == "HOLS":
        return "HAPPY HOLIDAYS!"
    return f"HAPPY NEW YEAR {state['year']}"


def compose(board: str, state: Dict[str, Any], style: str, twinkle_offset: int = 0) -> List[str]:
    """Full board rows: tree on the left, caption centred in the right column."""
    layout = LAYOUTS[board]
    grid = draw_tree(board, state, twinkle_offset)
    width = layout["text_width"]
    for row, text in enumerate(caption(board, state, style)):
        text = text[:width].center(width).rstrip()
        for offset, char in enumerate(text):
            if char != " ":
                grid[row][layout["text_col"] + offset] = char
    return ["".join(cells).rstrip() for cells in grid]


# ----------------------------------------------------------------------
# Plugin
# ----------------------------------------------------------------------


class AdventPlugin(PluginBase):
    """Pixel-art Christmas tree that fills with baubles through December."""

    @property
    def plugin_id(self) -> str:
        return "advent"

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        errors: List[str] = []

        board = config.get("board", "note")
        if board not in BOARD_WIDTH:
            errors.append(f"Invalid board size: {board}. Use 'note' or 'flagship'.")

        style = config.get("countdown_style", "sleeps")
        if style not in COUNTDOWN_STYLES:
            errors.append(f"Invalid countdown style: {style}. Use 'sleeps' or 'days'.")

        tz_name = config.get("timezone")
        if tz_name:
            try:
                self._zone(tz_name)
            except Exception:
                errors.append(f"Invalid timezone: {tz_name}")

        for key, low, high in (("demo_day", 0, 31), ("refresh_seconds", 60, 86400)):
            value = config.get(key)
            if value is None:
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                errors.append(f"{key} must be a whole number")
                continue
            if not low <= number <= high:
                errors.append(f"{key} must be between {low} and {high}")

        return errors

    @staticmethod
    def _zone(name: str):
        if ZoneInfo is None:  # pragma: no cover - only on very old runtimes
            return timezone.utc
        return ZoneInfo(name)

    def _tz(self):
        name = self.config.get("timezone") or os.getenv("ADVENT_TIMEZONE") or "UTC"
        try:
            return self._zone(name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            logger.warning("Unknown timezone %s, falling back to UTC", name)
            return timezone.utc

    def _int_setting(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _today(self, now: datetime) -> date:
        today = now.astimezone(self._tz()).date()
        demo = self._int_setting("demo_day", 0)
        if 1 <= demo <= 31:
            return date(today.year, 12, demo)
        return today

    def fetch_data(self, now: Optional[datetime] = None) -> PluginResult:
        try:
            now = now or datetime.now(timezone.utc)
            board = self.config.get("board", "note")
            if board not in BOARD_WIDTH:
                board = "note"
            style = self.config.get("countdown_style", "sleeps")
            if style not in COUNTDOWN_STYLES:
                style = "sleeps"

            state = phase_for(self._today(now))

            twinkle_offset = 0
            if self.config.get("twinkle") and state["phase"] != "PRE":
                step = max(60, self._int_setting("refresh_seconds", 300))
                twinkle_offset = int(now.timestamp() // step) % len(BAUBLE_COLORS)

            lines = compose(board, state, style, twinkle_offset)
            unit = "SLEEP" if style == "sleeps" else "DAY"
            count = state.get("sleeps") or state.get("days_to_advent") or 0
            label = unit if count == 1 else unit + "S"
            if state["phase"] == "PRE":
                label = "DAY" if count == 1 else "DAYS"

            data: Dict[str, Any] = {
                "phase": state["phase"],
                "door": state["day"] if state["phase"] == "ADVENT" else 0,
                "sleeps": state["sleeps"],
                "days_to_advent": state.get("days_to_advent", 0),
                "count_label": label,
                "headline": headline(state, style),
                "updated": now.astimezone(self._tz()).strftime("%H:%M"),
            }
            for index in range(6):
                data[f"line{index + 1}"] = lines[index] if index < len(lines) else ""

            return PluginResult(available=True, data=data, formatted_lines=lines)
        except Exception as exc:  # noqa: BLE001 - fetch_data must never raise
            logger.exception("Unexpected error in advent plugin")
            return PluginResult(available=False, error=str(exc))
