import numpy as np
from PIL import Image

from config import (
    ASSETS_DIR, ORANGE_PIXEL_RATIO, BLUE_DOM_THRESHOLD, WHITE_PIXEL_DEAD,
    DEAD_LUM_MAX, DEAD_LUM_MIN, DEAD_STD_MAX,
    DEAD_SIM_THRESHOLD, ALIVE_SIM_THRESHOLD,
)


def _load_asset(name: str) -> np.ndarray | None:
    """Loads assets/{name}.png or .webp as an RGB uint8 array. Returns None
    if neither file exists."""
    for ext in (".png", ".webp"):
        p = ASSETS_DIR / f"{name}{ext}"
        if p.exists():
            return np.array(Image.open(p).convert("RGB"))
    return None


def _luminance(rgb: np.ndarray) -> np.ndarray:
    r = rgb[..., 0].astype(np.float32)
    g = rgb[..., 1].astype(np.float32)
    b = rgb[..., 2].astype(np.float32)
    return r * 0.299 + g * 0.587 + b * 0.114


def _resize_nearest(lum: np.ndarray, dst_h: int, dst_w: int) -> np.ndarray:
    """Nearest-neighbour resize, matching main.js's resizeLuminance exactly
    (not PIL's default resampling) so NCC comparisons behave the same way
    the original thresholds were tuned against."""
    src_h, src_w = lum.shape
    ys = (np.arange(dst_h) * (src_h / dst_h)).astype(int)
    xs = (np.arange(dst_w) * (src_w / dst_w)).astype(int)
    return lum[ys][:, xs]


def _ncc_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = a.ravel().astype(np.float64)
    b = b.ravel().astype(np.float64)
    da = a - a.mean()
    db = b - b.mean()
    den = np.sqrt((da @ da) * (db @ db))
    if den < 1e-6:
        return 0.0
    return (float(da @ db / den) + 1) / 2


class Templates:
    def __init__(self):
        dead_rgb = _load_asset("dead")
        alive_rgb = _load_asset("alive")
        alive_half_rgb = _load_asset("alive-half")

        self.dead = _luminance(dead_rgb) if dead_rgb is not None else None
        self.alive = _luminance(alive_rgb) if alive_rgb is not None else None
        self.alive_half = _luminance(alive_half_rgb) if alive_half_rgb is not None else None

        loaded = [n for n, v in [("dead", self.dead), ("alive", self.alive), ("alive-half", self.alive_half)] if v is not None]
        print(f"Templates loaded: {', '.join(loaded) if loaded else '(none found in assets/)'}")


def is_low_health(rgb: np.ndarray) -> bool:
    r = rgb[..., 0].astype(np.int32)
    g = rgb[..., 1].astype(np.int32)
    b = rgb[..., 2].astype(np.int32)
    orange = (r > 140) & (r > b * 2.0) & (r > g * 1.1)
    return bool(orange.mean() >= ORANGE_PIXEL_RATIO)


def has_white_pixels(rgb: np.ndarray) -> bool:
    white = (rgb[..., 0] > 180) & (rgb[..., 1] > 180) & (rgb[..., 2] > 180)
    return bool(white.mean() > WHITE_PIXEL_DEAD)


def has_blue_dominance(rgb: np.ndarray) -> bool:
    diff = rgb[..., 2].astype(np.float32) - rgb[..., 0].astype(np.float32)
    return bool(diff.mean() > BLUE_DOM_THRESHOLD)


def is_in_dead_lum_range(brightness: float) -> bool:
    return DEAD_LUM_MIN <= brightness <= DEAD_LUM_MAX


def has_low_variance(rgb: np.ndarray) -> bool:
    return bool(_luminance(rgb).std() <= DEAD_STD_MAX)


def avg_brightness(rgb: np.ndarray) -> float:
    return float(_luminance(rgb).mean())


def analyse_frame(rgb: np.ndarray, templates: Templates) -> dict:
    """Runs all pixel rules + two-pass NCC on one captured frame. The
    state machine in state.py combines this with each player's rolling
    baseline to actually decide dead/alive."""
    brightness = avg_brightness(rgb)
    low_health = is_low_health(rgb)

    white_absent = not has_white_pixels(rgb)
    blue_dominant = has_blue_dominance(rgb)
    lum_in_range = is_in_dead_lum_range(brightness)
    var_collapsed = has_low_variance(rgb)
    pixel_votes = sum([white_absent, blue_dominant, lum_in_range, var_collapsed])

    dead_sim = 0.0
    alive_sim = 0.0
    if not low_health:
        lum = _luminance(rgb)
        if templates.dead is not None:
            scaled = _resize_nearest(lum, *templates.dead.shape)
            dead_sim = _ncc_similarity(scaled, templates.dead)
        if templates.alive is not None:
            scaled = _resize_nearest(lum, *templates.alive.shape)
            alive_sim = max(alive_sim, _ncc_similarity(scaled, templates.alive))
        if templates.alive_half is not None:
            scaled = _resize_nearest(lum, *templates.alive_half.shape)
            alive_sim = max(alive_sim, _ncc_similarity(scaled, templates.alive_half))

    return {
        "brightness": brightness,
        "low_health": low_health,
        "pixel_votes": pixel_votes,
        "dead_sim": dead_sim,
        "alive_sim": alive_sim,
        "has_dead_template": templates.dead is not None,
        "has_alive_template": templates.alive is not None,
    }