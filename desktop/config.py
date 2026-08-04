import os
import sys
from pathlib import Path

WEB_BASE_URL = os.environ.get("HEALTH_CAPTURE_WEB_URL", "https://realtime-production.vercel.app")
POST_ENDPOINT = f"https://realtime-production.vercel.app/api/pusher/scoreboard"

APP_DIR = Path.home() / ".realtime-HUD"
APP_DIR.mkdir(exist_ok=True)
SESSION_FILE = APP_DIR / "session.json"
LAYOUTS_FILE = APP_DIR / "layouts.json"

QUICKSETUP_BOX_WIDTH  = 70
QUICKSETUP_BOX_HEIGHT = 90
QUICKSETUP_GAP        = 8
QUICKSETUP_TOP_MARGIN = 30

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-bundled .exe — everything shipped via
    # --add-data (including assets/) gets extracted under this temp dir
    # at launch, not next to this file like it is in development.
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent.parent

ASSETS_DIR = BASE_DIR / "assets"

POLL_INTERVAL_MS   = 80
WINDOW_SIZE        = 40
DEAD_SIGMA         = 2.2
ALIVE_SIGMA        = 1.2
MIN_STDDEV         = 8
CONSISTENCY_FRAMES = 3
COOLDOWN_MS        = 1500

DEAD_SIM_THRESHOLD  = 0.52
ALIVE_SIM_THRESHOLD = 0.58

ORANGE_PIXEL_RATIO = 0.022
BLUE_DOM_THRESHOLD = 8
WHITE_PIXEL_DEAD   = 0.02
DEAD_LUM_MAX       = 145
# Was 60 — real dead-labeled frames measured brightness=48 and
# brightness=52 (both below 60), losing the lum_in_range vote and
# capping pixel_votes at 2/4, one short of the required 3. Lowered with
# margin below both observed values. Provisional on a small number of
# real samples — worth re-checking as more players/lighting get tested.
DEAD_LUM_MIN       = 30
DEAD_STD_MAX       = 30

NUM_TEAMS        = 2
PLAYERS_PER_TEAM = 5