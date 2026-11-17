import os
import sys
from pathlib import Path

WEB_BASE_URL = os.environ.get("HEALTH_CAPTURE_WEB_URL", "https://realtime-production.vercel.app").rstrip("/")
POST_ENDPOINT = f"{WEB_BASE_URL}/api/pusher/scoreboard"
RESOLVE_URL = f"{WEB_BASE_URL}/api/overlay-token/resolve"

APP_DIR = Path.home() / ".realtime-HUD"
APP_DIR.mkdir(exist_ok=True)
SESSION_FILE = APP_DIR / "session.json"
LAYOUTS_FILE = APP_DIR / "layouts.json"

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-bundled .exe — everything shipped via
    # --add-data (including assets/) gets extracted under this temp dir
    # at launch, not next to this file like it is in development.
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent.parent

ASSETS_DIR = BASE_DIR / "assets"

NUM_TEAMS        = 2
PLAYERS_PER_TEAM = 5

POLL_INTERVAL_MS = 80

# ── Detection: the health bar under each player card ──────────────────────
# In the CODM spectator HUD every player card has a health bar under the
# portrait: white (orange at low health) while alive, gone the moment the
# player dies, back at full length on respawn. Each capture box has to
# cover the portrait and that bar.

# The bar is a band of rows at least BAR_MIN_ROWS thick (6 px at 1080p,
# 4 px at 720p) in the lower half of the box, where bar colour runs from
# near the left edge. The spectate border's bottom line is 1-2 px, so the
# thickness rule skips it.
BAR_MIN_ROWS = 3
# A white run must cover this share of the box: the player number on the
# portrait is ~12%, and the bar turns orange before it gets that short.
BAR_WHITE_RUN = 0.2
# An orange (low health) run counts from this share of the box, 2 px
# minimum: at 1-2% health the bar is only 2-4 px long
BAR_PRESENT_RUN = 0.02
# Health below this share of the full bar shows as "low"
LOW_HEALTH = 0.35

# Frames in a row before a player flips (one frame every POLL_INTERVAL_MS)
DEAD_FRAMES  = 3
ALIVE_FRAMES = 2
# A missing bar only counts as a death if the portrait has also changed
# from that player's normal look by at least this much (mean colour
# difference, 0..1): the death fade greys and dims it. So something passing
# over the bar for a moment can't kill anyone. After DEAD_FAILSAFE_FRAMES
# (1.6 s) without a bar the player is dead regardless.
DEAD_PORTRAIT_CHANGE = 0.08
DEAD_FAILSAFE_FRAMES = 20

# ── Quick setup: where the 10 cards sit, as a share of a 1920×1080 frame ──
# Left team cards start at x=16 px, right team at x=1383 px, every 105 px,
# 101 px wide; y=8 px, 108 px tall (portrait, bar and the line under it).
CARD_LEFT_X   = 16 / 1920
CARD_RIGHT_X  = 1383 / 1920
CARD_PITCH    = 105 / 1920
CARD_WIDTH    = 101 / 1920
CARD_TOP      = 8 / 1080
CARD_HEIGHT   = 108 / 1080
