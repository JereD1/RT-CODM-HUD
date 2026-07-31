import numpy as np
import mss


def grab_region(sct: mss.mss, region: dict) -> np.ndarray:
    """region: {"left": int, "top": int, "width": int, "height": int}
    (real desktop pixel coordinates). Returns an (H, W, 3) uint8 RGB array."""
    shot = sct.grab(region)
    arr = np.array(shot)          # (H, W, 4), BGRA order
    return arr[:, :, [2, 1, 0]]   # -> RGB


def list_monitors(sct: mss.mss) -> list[dict]:
    """Returns physical monitors only (skips mss.monitors[0], which is
    the special "all monitors combined" virtual entry). Each dict has
    left/top/width/height in absolute virtual-desktop pixel coordinates —
    the same coordinate space region dicts already use."""
    return [dict(m) for m in sct.monitors[1:]]


def monitor_for_region(sct: mss.mss, region: dict) -> dict | None:
    """Returns whichever physical monitor contains a region's top-left
    point, or None if it doesn't fall inside any currently-known monitor
    (e.g. the monitor it was picked on has since been disconnected)."""
    x, y = region["left"], region["top"]
    for m in list_monitors(sct):
        if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
            return m
    return None


def monitor_signature(monitor: dict) -> str:
    """Stable identifier for a physical monitor based on its position
    and resolution — used to detect 'is this the same monitor as last
    time' across app restarts, since mss's index order isn't guaranteed
    to stay stable when monitors are reconnected or rearranged."""
    return f"{monitor['left']},{monitor['top']},{monitor['width']}x{monitor['height']}"