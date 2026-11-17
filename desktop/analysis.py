"""Reads one CODM player card: is the health bar under the portrait there,
how long is it, and how bright is the portrait.

The bar is looked for in every frame, because it moves: the card of the
player being spectated gets a white border and its bar sits a few pixels
higher. It is the thickest band of rows in the lower part of the box where
bar colour runs from near the left edge. That rules out:
- the white player number on the portrait (too short),
- the spectate border's bottom line (only 1-2 rows thick),
- the border's left edge (a few pixels wide).
"""
from dataclasses import dataclass

import numpy as np

from config import BAR_MIN_ROWS, BAR_WHITE_RUN, BAR_PRESENT_RUN


@dataclass
class BarReading:
    present: bool
    run: int          # bar length in pixels (median over the band's rows)
    orange: bool      # low-health colour
    top: int = 0      # band rows inside the box, when present
    bottom: int = 0


def bar_masks(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pixels that are health-bar colour: white, or orange at low health.
    Returns (bar, orange)."""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    white = (r > 185) & (g > 185) & (b > 185)
    # Low-health orange runs from deep (245,149,53) to pale (227,183,139)
    # at the very end. Green under 82% of red keeps out yellow portraits
    # (lightning bolts ~0.88); green over 60 keeps out red ones.
    orange = (r > 160) & (g > 60) & (r - b > 60) & (g * 100 < r * 82)
    return white | orange, orange


def row_runs(mask: np.ndarray, max_start: int) -> tuple[np.ndarray, np.ndarray]:
    """For each row, the longest run of True that starts before max_start
    (the bar fills from the left). Returns (start, length) arrays."""
    h, w = mask.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    edges = np.diff(padded, axis=1)
    starts = np.zeros(h, dtype=np.int32)
    lengths = np.zeros(h, dtype=np.int32)
    for y in range(h):
        s = np.flatnonzero(edges[y] == 1)
        e = np.flatnonzero(edges[y] == -1)
        keep = s < max_start
        if not keep.any():
            continue
        lens = e[keep] - s[keep]
        i = int(np.argmax(lens))
        starts[y], lengths[y] = s[keep][i], lens[i]
    return starts, lengths


def read_bar(rgb: np.ndarray) -> BarReading:
    """Finds the health bar in the lower half of the box, if it is there."""
    h, w = rgb.shape[:2]
    first = int(h * 0.5)
    bar, orange = bar_masks(rgb[first:])
    starts, lengths = row_runs(bar, max(3, int(w * 0.2)))

    white_min = BAR_WHITE_RUN * w
    any_min = max(2, BAR_PRESENT_RUN * w)
    good = np.zeros(len(lengths), dtype=bool)
    is_orange = np.zeros(len(lengths), dtype=bool)
    for y, (s, n) in enumerate(zip(starts, lengths)):
        if n < any_min:
            continue
        is_orange[y] = orange[y, s:s + n].mean() > 0.5
        # A white bar is never very short (it turns orange first), so a short
        # white run is the player number, not the bar
        good[y] = n >= white_min or is_orange[y]

    best = None
    y = 0
    while y < len(good):
        if not good[y]:
            y += 1
            continue
        top = y
        while y < len(good) and good[y]:
            y += 1
        if y - top >= BAR_MIN_ROWS and (best is None or y - top >= best[1] - best[0]):
            best = (top, y)
    if best is None:
        return BarReading(False, 0, False)
    top, end = best
    return BarReading(
        True, int(np.median(lengths[top:end])), bool(is_orange[top:end].mean() > 0.5),
        first + top, first + end - 1,
    )


def portrait_thumb(rgb: np.ndarray, bar_top: int | None) -> np.ndarray:
    """A small 8×8 colour snapshot of the middle of the portrait (above the
    bar, away from the edges where the spectate border and team frame
    sit), as 0..1 floats. Comparing it with the player's normal snapshot
    shows the death fade whichever way it shifts the colours: a green card
    darkens, a red one turns grey and reads lighter."""
    h, w = rgb.shape[:2]
    bottom = (bar_top - 3) if bar_top else int(h * 0.75)
    top = int(h * 0.1)
    if bottom - top < 8:
        top, bottom = int(h * 0.1), int(h * 0.75)
    crop = rgb[top:bottom, int(w * 0.15):int(w * 0.85)].astype(np.float32) / 255
    ch, cw = crop.shape[:2]
    crop = crop[: ch - ch % 8, : cw - cw % 8]
    return crop.reshape(8, crop.shape[0] // 8, 8, crop.shape[1] // 8, 3).mean(axis=(1, 3))


def thumb_change(a: np.ndarray, b: np.ndarray) -> float:
    """How different two portrait snapshots are: mean colour difference, 0..1."""
    return float(np.abs(a - b).mean())
