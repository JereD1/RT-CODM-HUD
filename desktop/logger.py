import json
import time

from config import LOG_DIR


class SessionLogger:
    """Opens one timestamped JSON-lines log file per capture session.
    Deliberately simple — this is what you grep through after "why did
    player 3 show dead for 10 seconds" on stream, not a general-purpose
    logging framework."""

    def __init__(self):
        self._file = None
        self.path = None

    def start(self, monitor_info: str | None, layout_summary: dict, broadcast_id: str | None = None):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.path = LOG_DIR / f"session-{ts}.jsonl"
        self._file = open(self.path, "a", encoding="utf-8")
        self._write("session_start", {
            "monitor": monitor_info,
            "regions": layout_summary,
            "broadcast_id": broadcast_id,
        })
        return self.path

    def stop(self):
        if self._file:
            self._write("session_stop", {})
            self._file.close()
            self._file = None

    def state_change(self, team: int, player: int, old_status: str, new_status: str, signal: dict):
        self._write("state_change", {
            "team": team, "player": player, "old": old_status, "new": new_status,
            "brightness": signal.get("brightness"),
            "dead_sim": signal.get("dead_sim"),
            "alive_sim": signal.get("alive_sim"),
            "pixel_votes": signal.get("pixel_votes"),
        })

    def correction(self, team: int, player: int, shown_status: str, corrected_label: str, signal: dict):
        """Logs an operator's manual Alive/Low/Dead button press — i.e.
        the detector showed one thing and a human said it was wrong.
        Kept as its own event type (not folded into state_change) since
        this is ground-truth operator input, not a detector decision —
        it's exactly the moment worth finding first when reviewing a log
        after a bad stretch on stream, and it doubles as a pointer back
        into calibrate.py's CALIBRATION_LOG for the matching sample."""
        self._write("correction", {
            "team": team, "player": player,
            "shown_as": shown_status, "corrected_to": corrected_label,
            "brightness": signal.get("brightness"),
            "dead_sim": signal.get("dead_sim"),
            "alive_sim": signal.get("alive_sim"),
            "pixel_votes": signal.get("pixel_votes"),
        })

    def error(self, context: str, message: str):
        self._write("error", {"context": context, "message": message})

    def _write(self, event_type: str, payload: dict):
        if not self._file:
            return
        line = {"ts": time.time(), "event": event_type, **payload}
        self._file.write(json.dumps(line) + "\n")
        self._file.flush()