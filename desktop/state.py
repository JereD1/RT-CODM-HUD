import time
from dataclasses import dataclass, field
from statistics import mean, pstdev

from config import (
    WINDOW_SIZE, DEAD_SIGMA, ALIVE_SIGMA, MIN_STDDEV,
    CONSISTENCY_FRAMES, COOLDOWN_MS, DEAD_SIM_THRESHOLD, ALIVE_SIM_THRESHOLD,
)


@dataclass
class PlayerState:
    team_index: int
    player_index: int
    is_dead: bool = False
    cooldown_until: float = 0.0
    samples: list = field(default_factory=list)
    consecutive_dead: int = 0
    consecutive_alive: int = 0

    def in_cooldown(self) -> bool:
        return time.monotonic() < self.cooldown_until

    def start_cooldown(self):
        self.cooldown_until = time.monotonic() + (COOLDOWN_MS / 1000)


def evaluate(state: PlayerState, signal: dict) -> tuple[bool, str]:
    """Feeds one frame's analysis signal into a player's rolling state
    machine. Returns (flipped, status_label) — a faithful port of
    main.js's analyse-batch handler, warm-up phase included."""
    brightness = signal["brightness"]
    low_health = signal["low_health"]
    pixel_votes = signal["pixel_votes"]
    dead_sim = signal["dead_sim"]
    alive_sim = signal["alive_sim"]

    if len(state.samples) < 5:
        if not low_health:
            state.samples.append(brightness)
            if len(state.samples) > WINDOW_SIZE:
                state.samples.pop(0)
        return False, "warming"

    mu = mean(state.samples)
    sd = max(pstdev(state.samples) if len(state.samples) > 1 else 0, MIN_STDDEV)
    dead_threshold = mu - DEAD_SIGMA * sd
    alive_threshold = mu - ALIVE_SIGMA * sd

    sigma_votes_dead = brightness < dead_threshold
    ncc_votes_dead = (
        True if not signal["has_dead_template"]
        else (dead_sim >= DEAD_SIM_THRESHOLD and alive_sim < ALIVE_SIM_THRESHOLD)
    )

    frame_is_dead = (not low_health) and pixel_votes >= 3 and sigma_votes_dead and ncc_votes_dead

    if not state.is_dead:
        if frame_is_dead:
            state.consecutive_dead += 1
            state.consecutive_alive = 0
        else:
            state.consecutive_dead = 0
            if (not low_health and brightness >= alive_threshold) or low_health:
                state.samples.append(brightness)
                if len(state.samples) > WINDOW_SIZE:
                    state.samples.pop(0)
    else:
        reviving = brightness > alive_threshold and (
            not signal["has_alive_template"] or alive_sim >= ALIVE_SIM_THRESHOLD
        )
        if reviving:
            state.consecutive_alive += 1
            state.consecutive_dead = 0
        else:
            state.consecutive_alive = 0

    flipped = False
    if not state.is_dead and state.consecutive_dead >= CONSISTENCY_FRAMES:
        state.is_dead = True
        state.consecutive_dead = 0
        state.consecutive_alive = 0
        flipped = True
    elif state.is_dead and state.consecutive_alive >= CONSISTENCY_FRAMES:
        state.is_dead = False
        state.consecutive_dead = 0
        state.consecutive_alive = 0
        state.samples = [brightness] * WINDOW_SIZE
        flipped = True

    if flipped:
        state.start_cooldown()

    status = "low" if low_health else ("dead" if state.is_dead else "alive")
    return flipped, status