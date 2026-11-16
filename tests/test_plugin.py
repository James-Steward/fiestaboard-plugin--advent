"""Tests for the FiestaBoard Christmas advent tree plugin."""

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from conftest import load_plugin_module

advent = load_plugin_module()
AdventPlugin = advent.AdventPlugin

PLUGIN_DIR = Path(__file__).resolve().parent.parent
BOARD_WIDTHS = {"note": 15, "flagship": 22}
BOARD_ROWS = {"note": 3, "flagship": 6}
GREEN = "{66}"


def tile_count(row: str) -> int:
    return len(re.sub(r"\{\d{2}\}", "#", row))


def tiles(row: str):
    return re.findall(r"\{\d{2}\}|.", row)


def bauble_count(rows):
    return sum(
        1 for row in rows for t in tiles(row) if re.fullmatch(r"\{\d{2}\}", t) and t != GREEN
    )


def make(config, manifest):
    plugin = AdventPlugin(manifest)
    plugin.config = config
    return plugin


# ----------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "day,phase",
    [
        (date(2026, 11, 15), "PRE"),
        (date(2026, 12, 1), "ADVENT"),
        (date(2026, 12, 24), "ADVENT"),
        (date(2026, 12, 25), "XMAS"),
        (date(2026, 12, 26), "HOLS"),
        (date(2026, 12, 31), "HOLS"),
        (date(2027, 1, 1), "NEWYEAR"),
        (date(2027, 1, 6), "NEWYEAR"),
        (date(2027, 1, 7), "PRE"),
    ],
)
def test_phases(day, phase):
    assert advent.phase_for(day)["phase"] == phase


def test_sleeps_and_days_to_advent():
    assert advent.phase_for(date(2026, 12, 1))["sleeps"] == 24
    assert advent.phase_for(date(2026, 12, 24))["sleeps"] == 1
    assert advent.phase_for(date(2026, 11, 15))["days_to_advent"] == 16
    assert advent.phase_for(date(2026, 11, 30))["days_to_advent"] == 1


# ----------------------------------------------------------------------
# Tree
# ----------------------------------------------------------------------


def test_flagship_has_one_slot_per_day():
    assert len(advent.FLAGSHIP["baubles"]) == 24
    assert len(set(advent.FLAGSHIP["baubles"])) == 24
    assert set(advent.FLAGSHIP["baubles"]) <= set(advent.FLAGSHIP["foliage"])


@pytest.mark.parametrize("board", ["flagship", "note"])
def test_baubles_never_touch_each_other(board):
    slots = set(advent.LAYOUTS[board]["baubles"])
    for row, col in slots:
        assert (row, col + 1) not in slots


def test_flagship_gains_exactly_one_bauble_per_day():
    previous = 0
    for day in range(1, 25):
        rows = advent.compose("flagship", advent.phase_for(date(2026, 12, day)), "sleeps")
        count = bauble_count(rows)
        assert count == day
        assert count == previous + 1
        previous = count


def test_note_bauble_count_never_decreases_and_fills_on_christmas_eve():
    counts = [
        bauble_count(advent.compose("note", advent.phase_for(date(2026, 12, d)), "sleeps"))
        for d in range(1, 25)
    ]
    assert counts == sorted(counts)
    assert counts[0] == 1
    assert counts[-1] == len(advent.NOTE["baubles"])


def test_earlier_baubles_stay_put():
    day5 = advent.draw_tree("flagship", advent.phase_for(date(2026, 12, 5)))
    day6 = advent.draw_tree("flagship", advent.phase_for(date(2026, 12, 6)))
    changed = [
        (r, c) for r in range(6) for c in range(22) if day5[r][c] != day6[r][c]
    ]
    assert len(changed) == 1


def test_bare_tree_before_advent():
    rows = advent.compose("flagship", advent.phase_for(date(2026, 11, 15)), "sleeps")
    assert bauble_count(rows) == 0
    assert "ADVENT" in "".join(rows)


def test_star_and_presents_on_christmas():
    grid = advent.draw_tree("flagship", advent.phase_for(date(2026, 12, 25)))
    row, col = advent.FLAGSHIP["star"]
    assert grid[row][col] == "{%d}" % advent.STAR
    for r, c in advent.FLAGSHIP["presents"]:
        assert grid[r][c] != " "
    before = advent.draw_tree("flagship", advent.phase_for(date(2026, 12, 24)))
    assert before[row][col] == GREEN


@pytest.mark.parametrize("board", ["flagship", "note"])
@pytest.mark.parametrize("style", ["sleeps", "days"])
def test_every_day_fits_the_board(board, style):
    day = date(2026, 11, 1)
    while day <= date(2027, 1, 10):
        rows = advent.compose(board, advent.phase_for(day), style)
        assert len(rows) == BOARD_ROWS[board]
        for row in rows:
            assert tile_count(row) <= BOARD_WIDTHS[board], (day, row)
            assert row == row.upper()
        day = date.fromordinal(day.toordinal() + 1)


def test_caption_never_overlaps_tree():
    for board, layout in advent.LAYOUTS.items():
        rightmost = max(col for _, col in layout["foliage"])
        assert layout["text_col"] > rightmost + 1
        assert layout["text_col"] + layout["text_width"] <= BOARD_WIDTHS[board]


def test_singular_sleep():
    rows = advent.compose("note", advent.phase_for(date(2026, 12, 24)), "sleeps")
    assert rows[1].endswith("SLEEP")
    rows = advent.compose("flagship", advent.phase_for(date(2026, 12, 24)), "days")
    assert any(r.strip().endswith(" DAY") or r.endswith("DAY") for r in rows)


# ----------------------------------------------------------------------
# Plugin
# ----------------------------------------------------------------------


def test_fetch_data_uses_local_date(manifest, sample_config):
    plugin = make(sample_config, manifest)
    # 30 Nov 14:00 UTC is already 1 Dec in Sydney.
    result = plugin.fetch_data(datetime(2026, 11, 30, 14, tzinfo=timezone.utc))
    assert result.available
    assert result.data["phase"] == "ADVENT"
    assert result.data["door"] == 1
    assert result.data["sleeps"] == 24
    assert result.data["headline"] == "24 SLEEPS TO XMAS"
    assert len(result.formatted_lines) == 6


def test_demo_day_overrides_date(manifest, sample_config):
    plugin = make(dict(sample_config, demo_day=25), manifest)
    result = plugin.fetch_data(datetime(2026, 11, 15, tzinfo=timezone.utc))
    assert result.data["phase"] == "XMAS"
    assert result.data["headline"] == "MERRY CHRISTMAS!"


def test_note_lines(manifest, sample_config):
    plugin = make(dict(sample_config, board="note", demo_day=7), manifest)
    result = plugin.fetch_data(datetime(2026, 11, 15, tzinfo=timezone.utc))
    assert len(result.formatted_lines) == 3
    assert result.data["line4"] == ""
    assert result.data["line1"].endswith("18")
    assert "DOOR" not in "".join(result.formatted_lines)


def test_twinkle_changes_colours_not_count(manifest, sample_config):
    plugin = make(dict(sample_config, twinkle=True, demo_day=10), manifest)
    a = plugin.fetch_data(datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)).formatted_lines
    b = plugin.fetch_data(datetime(2026, 11, 15, 0, 5, tzinfo=timezone.utc)).formatted_lines
    assert a != b
    assert bauble_count(a) == bauble_count(b) == 10


def test_bad_config_falls_back(manifest):
    plugin = make({"board": "huge", "countdown_style": "weeks", "timezone": "Nowhere/Land"}, manifest)
    result = plugin.fetch_data(datetime(2026, 12, 3, tzinfo=timezone.utc))
    assert result.available
    assert len(result.formatted_lines) == 3


def test_validate_config(manifest, sample_config):
    plugin = AdventPlugin(manifest)
    assert plugin.validate_config(sample_config) == []
    errors = plugin.validate_config(
        {"board": "huge", "countdown_style": "weeks", "timezone": "Nowhere/Land", "demo_day": 40}
    )
    assert len(errors) == 4


# ----------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------


def test_manifest_matches_plugin(manifest):
    assert manifest["id"] == AdventPlugin(manifest).plugin_id
    assert manifest["version"]
    props = manifest["settings_schema"]["properties"]
    assert props["board"]["enum"] == ["note", "flagship"]


def test_manifest_previews_fit(manifest):
    for preview in manifest["previews"]:
        width = BOARD_WIDTHS[preview["device_type"]]
        assert len(preview["rows"]) <= BOARD_ROWS[preview["device_type"]]
        for row in preview["rows"]:
            assert tile_count(row) <= width
    assert tile_count(manifest["teaser"]) <= 15


def test_manifest_variables_cover_data(manifest, sample_config):
    plugin = make(sample_config, manifest)
    data = plugin.fetch_data(datetime(2026, 12, 3, tzinfo=timezone.utc)).data
    declared = set(manifest["variables"]["simple"])
    assert set(data) == declared
