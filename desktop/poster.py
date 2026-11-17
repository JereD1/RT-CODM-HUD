import requests
from config import POST_ENDPOINT


def post_alive_status(broadcast_id: str, overlay_token: str, team1_alive: list, team2_alive: list) -> tuple[bool, str]:
    """Sends both teams' alive lists to the Scoreboard overlay. The overlay
    token (from the link pasted in "Connect overlay") goes in the
    x-overlay-token header: that is all the website needs, no sign-in. It
    only lets this app set who is alive, nothing else on the scoreboard."""
    try:
        resp = requests.post(
            POST_ENDPOINT,
            headers={"x-overlay-token": overlay_token},
            json={
                "broadcastId": broadcast_id,
                "team1AliveStatus": team1_alive,
                "team2AliveStatus": team2_alive,
            },
            timeout=5,
        )
        if resp.status_code == 401:
            return False, "401: overlay link invalid or reset - paste the current link and Connect again"
        return resp.ok, str(resp.status_code)
    except requests.RequestException as e:
        return False, str(e)
