import json
import requests

from config import WEB_BASE_URL, SESSION_FILE

RESOLVE_URL = f"https://realtime-production.vercel.app/api/overlay-token/resolve"


def load_cached_session() -> dict | None:
    """Whatever was last resolved via resolve_broadcast_id, if anything."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            return None
    return None


def disconnect_overlay():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def resolve_broadcast_id(token: str) -> dict:
    """Resolves an overlay token — the same one in the URL of the overlay
    loaded in OBS, copied from Studio's OverlayLinkBox — into the exact
    broadcastId that overlay is subscribed to. Mirrors
    CODMScoreboardOverlay's own resolution logic exactly (org-scoped if
    orgId present, then +productionId if present), so this can't drift out
    of sync with what the loaded overlay is actually listening on.

    This is a public, unauthenticated endpoint — no Clerk sign-in needed
    on the desktop side, the token itself carries everything required.

    Returns {"broadcastToken": ..., "broadcastId": ..., "userId": ...,
    "orgId": ..., "productionId": ...} and caches it to disk.
    """
    resp = requests.get(RESOLVE_URL, params={"token": token}, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"Invalid or expired overlay token: {resp.status_code} {resp.text}")

    data = resp.json()  # {"userId": ..., "orgId": ..., "productionId": ...}
    base = f"org-{data['orgId']}" if data.get("orgId") else data["userId"]
    broadcast_id = f"{base}-{data['productionId']}" if data.get("productionId") else base

    cached = {"broadcastToken": token, "broadcastId": broadcast_id, **data}
    SESSION_FILE.write_text(json.dumps(cached))
    return cached