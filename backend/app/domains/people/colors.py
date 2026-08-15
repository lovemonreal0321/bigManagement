"""Person display colours (spec §5).

Each person gets one colour, used consistently across calendar, cards, charts
and badges. These are chosen to stay legible on both light and dark surfaces
and to remain distinguishable from one another — and they are deliberately
NOT the status palette (spec §42), which carries separate meaning.
"""

from __future__ import annotations

import re

#: Assigned in order, wrapping around once exhausted.
#:
#: The ORDER is not cosmetic. People are assigned the next free colour, so the
#: earliest slots are the ones most likely to be compared side by side on a
#: chart or calendar. This sequence was checked with a palette validator rather
#: than by eye, against both the light (#ffffff) and dark (#111827) surfaces:
#:
#:   * lightness band and chroma floor: pass for all 12
#:   * worst adjacent pair under deuteranopia: ΔE 10.1 (threshold 8)
#:   * worst adjacent pair with normal vision: ΔE 19.5 (threshold 15)
#:
#: An earlier ordering put pink at slot 2 and green at slot 3, which measured
#: ΔE 6.1 under deuteranopia — the second and third people added would have
#: been hard to tell apart. Reordering fixed it at no cost.
#:
#: Slot 11 (#4f46e5) dips below 3:1 contrast on the dark surface, which is
#: acceptable because every chart here also carries a legend, direct labels and
#: a table view, so colour is never the only channel.
PERSON_COLOR_PALETTE: list[str] = [
    "#2563eb",  # blue
    "#ea580c",  # orange
    "#0d9488",  # teal
    "#c026d3",  # fuchsia
    "#dc2626",  # red
    "#7c3aed",  # violet
    "#4d7c0f",  # olive
    "#0891b2",  # cyan
    "#a16207",  # bronze
    "#db2777",  # pink
    "#4f46e5",  # indigo
    "#059669",  # emerald
]

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def is_valid_color(value: str | None) -> bool:
    return bool(value and HEX_COLOR_RE.match(value))


def next_available_color(taken: list[str]) -> str:
    """Pick the first palette colour nobody is using yet.

    Once every colour is taken, wrap around — duplicates are better than
    refusing to add a person.
    """
    normalised = {c.lower() for c in taken if c}
    for color in PERSON_COLOR_PALETTE:
        if color.lower() not in normalised:
            return color
    return PERSON_COLOR_PALETTE[len(normalised) % len(PERSON_COLOR_PALETTE)]


def derive_initials(name: str) -> str:
    """"John Smith" -> "JS"; "Madonna" -> "MA"; falls back to "?"."""
    parts = [p for p in re.split(r"[\s\-_]+", name.strip()) if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()
