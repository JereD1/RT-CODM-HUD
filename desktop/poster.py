import requests
from config import POST_ENDPOINT


def post_alive_status(broadcast_id: str, team1_alive: list, team2_alive: list) -> tuple[bool, str]:
    """Fixes the bug in the Electron version: the original firePost()
    never sent broadcastId, so every POST hit /api/pusher/scoreboard's
    `if (!broadcastId) return 400` guard. This includes it."""
    try:
        resp = requests.post(
            POST_ENDPOINT,
            json={
                "broadcastId": broadcast_id,
                "team1AliveStatus": team1_alive,
                "team2AliveStatus": team2_alive,
            },
            timeout=5,
        )
        return resp.ok, str(resp.status_code)
    except requests.RequestException as e:
        return False, str(e)