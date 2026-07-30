import os
from pathlib import Path

WEB_BASE_URL = os.environ.get("HEALTH_CAPTURE_WEB_URL", "https://your-broadcast-app.example.com")
POST_ENDPOINT = f"{WEB_BASE_URL}/api/pusher/scoreboard"
AUTH_START_PATH = "/desktop-auth"
EXCHANGE_URL = f"{WEB_BASE_URL}/api/desktop-auth/exchange"

APP_DIR = Path.home() / ".health-capture"
APP_DIR.mkdir(exist_ok=True)
SESSION_FILE = APP_DIR / "session.json"
LAYOUTS_FILE = APP_DIR / "layouts.json"

ASSETS_DIR = Path(__file__).parent / "assets"

# Poll / detection tuning — copied verbatim from the Electron version's
# main.js. These were empirically derived from real template pixel
# analysis; don't change them without re-measuring against actual
# in-game captures.
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
DEAD_LUM_MIN       = 60
DEAD_STD_MAX       = 30

NUM_TEAMS        = 2
PLAYERS_PER_TEAM = 5