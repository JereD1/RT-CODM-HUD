"""Turns each frame's card reading into a steady alive/dead state.

- Alive → dead: the health bar is missing DEAD_FRAMES frames in a row and
  the portrait has changed from the player's normal look (the death fade),
  or the bar has been missing DEAD_FAILSAFE_FRAMES frames whatever the
  portrait does.
- Dead → alive: the bar is back ALIVE_FRAMES frames in a row (it returns
  at full length on respawn).

The HUD as a whole decides two more things (hud_visible: does any card
show a bar this frame?):
- Hidden HUD (scoreboard, killcam, between rounds): nobody changes.
- A box that has never shown a bar while other cards do is a player who
  was already dead when capture started (Search & Destroy), so the same
  rules apply to it as to anyone else.
"""
from dataclasses import dataclass

import numpy as np

from analysis import BarReading, portrait_thumb, thumb_change
from config import (
    DEAD_FRAMES, ALIVE_FRAMES, DEAD_PORTRAIT_CHANGE, DEAD_FAILSAFE_FRAMES, LOW_HEALTH,
)


@dataclass
class PlayerState:
    team_index: int
    player_index: int
    is_dead: bool = False
    health: float = 1.0
    full_run: int = 0          # longest bar seen = full health, in pixels
    missing: int = 0
    present: int = 0
    # The player's normal portrait while alive with a bar, kept as a slow
    # running average so the spectate highlight or a flash doesn't stick
    normal_thumb: np.ndarray | None = None

    def reset(self, forget_box: bool = False):
        """Everyone alive again. forget_box also drops what was learned
        about the box (bar length, normal portrait), for a moved box."""
        if forget_box:
            self.full_run = 0
            self.normal_thumb = None
        self.is_dead = False
        self.health = 1.0
        self.missing = 0
        self.present = 0


def evaluate(state: PlayerState, rgb: np.ndarray, bar: BarReading, hud_visible: bool) -> tuple[bool, str, dict]:
    """bar: read_bar(rgb) for this box. hud_visible: some card shows a bar
    this frame. Returns (flipped, status, info); status is paused, alive,
    low or dead."""
    thumb = portrait_thumb(rgb, bar.top if bar.present else None)
    change = thumb_change(thumb, state.normal_thumb) if state.normal_thumb is not None else None
    if bar.present:
        state.full_run = max(state.full_run, bar.run)
    health = bar.run / state.full_run if bar.present and state.full_run else 0.0
    info = {"health": health, "change": change, "run": bar.run}

    if not hud_visible:
        return False, "paused", info

    flipped = False
    if not state.is_dead:
        if bar.present:
            state.missing = 0
            state.health = health
            state.normal_thumb = thumb if state.normal_thumb is None else state.normal_thumb * 0.9 + thumb * 0.1
        else:
            state.missing += 1
            faded = change is None or change >= DEAD_PORTRAIT_CHANGE
            if (state.missing >= DEAD_FRAMES and faded) or state.missing >= DEAD_FAILSAFE_FRAMES:
                state.is_dead = True
                state.health = 0.0
                state.present = 0
                flipped = True
    else:
        if bar.present:
            state.present += 1
            if state.present >= ALIVE_FRAMES:
                state.is_dead = False
                state.health = health
                state.missing = 0
                flipped = True
        else:
            state.present = 0

    if state.is_dead:
        status = "dead"
    elif bar.present and (bar.orange or health < LOW_HEALTH):
        status = "low"
    else:
        status = "alive"
    return flipped, status, info
