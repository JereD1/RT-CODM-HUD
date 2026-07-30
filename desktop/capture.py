import numpy as np
import mss


def grab_region(sct: mss.mss, region: dict) -> np.ndarray:
    """region: {"left": int, "top": int, "width": int, "height": int}
    (real desktop pixel coordinates). Returns an (H, W, 3) uint8 RGB array."""
    shot = sct.grab(region)
    arr = np.array(shot)          # (H, W, 4), BGRA order
    return arr[:, :, [2, 1, 0]]   # -> RGB