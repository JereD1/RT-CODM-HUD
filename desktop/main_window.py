import json
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QMessageBox, QLineEdit,
)
import numpy as np
import mss

from config import LAYOUTS_FILE, POLL_INTERVAL_MS, NUM_TEAMS, PLAYERS_PER_TEAM
from analysis import Templates, analyse_frame
from state import PlayerState, evaluate
from capture import grab_region, list_monitors, monitor_for_region, monitor_signature
from poster import post_alive_status
from region_selector import RegionSelector, QuickRegionSetup
from overlay_window import OverlayWindow
from logger import SessionLogger
from calibrate import log_sample
import auth


def _rgb_to_pixmap(rgb: np.ndarray) -> QPixmap:
    h, w, _ = rgb.shape
    contiguous = np.ascontiguousarray(rgb)
    qimg = QImage(contiguous.data, w, h, w * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())  # .copy() detaches from the numpy buffer


class SlotRow(QWidget):
    def __init__(self, team_index: int, player_index: int, on_pick_region, on_log_correction):
        super().__init__()
        self.team_index = team_index
        self.player_index = player_index
        self.region = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.name_label = QLabel(f"P{player_index + 1}")
        self.name_label.setFixedWidth(30)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(48, 30)
        self.thumb_label.setStyleSheet("background: #111; border: 1px solid #333;")

        self.region_label = QLabel("no region")
        self.region_label.setFixedWidth(150)
        self.region_label.setStyleSheet("color: #888;")

        self.pick_btn = QPushButton("Pick region")
        self.pick_btn.clicked.connect(lambda: on_pick_region(self))

        self.status_label = QLabel("—")
        self.status_label.setFixedWidth(60)

        self.signal_label = QLabel("")
        self.signal_label.setFixedWidth(150)
        self.signal_label.setStyleSheet("color: #666; font-size: 10px;")

        # ── Correction buttons — press whichever one is actually true
        # right now if status_label is showing the wrong thing. Each one
        # grabs a fresh frame from this slot's current region and logs it
        # via calibrate.py's log_sample(), feeding the same dataset
        # `python calibrate.py summarize` reads. ─────────────────────
        self.alive_btn = QPushButton("Alive")
        self.alive_btn.setFixedWidth(48)
        self.alive_btn.setStyleSheet("background-color: #16532d; color: #4ade80;")
        self.alive_btn.clicked.connect(lambda: on_log_correction(self, "alive"))

        self.low_btn = QPushButton("Low")
        self.low_btn.setFixedWidth(42)
        self.low_btn.setStyleSheet("background-color: #5c4a12; color: #fbbf24;")
        self.low_btn.clicked.connect(lambda: on_log_correction(self, "low"))

        self.dead_btn = QPushButton("Dead")
        self.dead_btn.setFixedWidth(46)
        self.dead_btn.setStyleSheet("background-color: #5c1a1a; color: #f87171;")
        self.dead_btn.clicked.connect(lambda: on_log_correction(self, "dead"))

        layout.addWidget(self.name_label)
        layout.addWidget(self.thumb_label)
        layout.addWidget(self.pick_btn)
        layout.addWidget(self.region_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.signal_label)
        layout.addWidget(self.alive_btn)
        layout.addWidget(self.low_btn)
        layout.addWidget(self.dead_btn)

    def set_region(self, region):
        self.region = region
        if region:
            self.region_label.setText(f"{region['width']}×{region['height']} @ {region['left']},{region['top']}")
            self.region_label.setStyleSheet("color: #888;")
        else:
            self.region_label.setText("no region")

    def flag_monitor_missing(self):
        self.region_label.setText((self.region_label.text() or "") + "  ⚠ monitor not found — reselect")
        self.region_label.setStyleSheet("color: #f87171; font-weight: bold;")

    def set_status(self, status: str, signal: dict | None = None):
        colors = {"alive": "#4ade80", "dead": "#f87171", "low": "#fbbf24", "warming": "#94a3b8", "—": "#666"}
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {colors.get(status, '#888')}; font-weight: bold;")
        if signal:
            self.signal_label.setText(
                f"b={signal.get('brightness', 0):.0f} d={signal.get('dead_sim', 0):.2f} "
                f"a={signal.get('alive_sim', 0):.2f} v={signal.get('pixel_votes', 0)}"
            )

    def set_thumbnail(self, rgb: np.ndarray):
        pix = _rgb_to_pixmap(rgb).scaled(
            self.thumb_label.width(), self.thumb_label.height())
        self.thumb_label.setPixmap(pix)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Health Capture")
        self.resize(1000, 600)

        # No Clerk sign-in anymore — the overlay token resolve endpoint is
        # public and carries everything needed (userId/orgId/productionId),
        # so broadcast_id comes only from a previously-connected overlay.
        self.session = auth.load_cached_session()
        self.broadcast_id = self.session.get("broadcastId") if self.session else None

        self.templates = Templates()
        self.sct = mss.mss()
        self.logger = SessionLogger()
        self.player_states = {
            (t, p): PlayerState(t, p)
            for t in range(NUM_TEAMS) for p in range(PLAYERS_PER_TEAM)
        }
        self.team_alive = {0: [True] * PLAYERS_PER_TEAM, 1: [True] * PLAYERS_PER_TEAM}
        self.slots = {}
        self.overlay_window = None
        self.running = False

        self._build_ui()
        self._load_layout()

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        broadcast_row = QHBoxLayout()
        self.broadcast_input = QLineEdit()
        self.broadcast_input.setPlaceholderText("Paste the Scoreboard overlay link or token from Studio")
        connect_btn = QPushButton("Connect overlay")
        connect_btn.clicked.connect(self._handle_connect_overlay)
        broadcast_row.addWidget(self.broadcast_input)
        broadcast_row.addWidget(connect_btn)
        root.addLayout(broadcast_row)

        self.broadcast_label = QLabel(self._broadcast_label_text())
        root.addWidget(self.broadcast_label)

        monitor_row = QHBoxLayout()
        self.monitor_label = QLabel(self._monitor_label_text())
        monitor_row.addWidget(self.monitor_label)
        monitor_row.addStretch()
        root.addLayout(monitor_row)

        grid = QGridLayout()
        for team in range(NUM_TEAMS):
            header = QLabel(f"Team {team + 1}")
            header.setStyleSheet("font-weight: bold; margin-top: 6px;")
            grid.addWidget(header, 0, team)
            for player in range(PLAYERS_PER_TEAM):
                row = SlotRow(team, player, self._pick_region, self._log_correction)
                self.slots[(team, player)] = row
                grid.addWidget(row, player + 1, team)
        root.addLayout(grid)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start capture")
        self.start_btn.clicked.connect(self._toggle_capture)
        quick_setup_btn = QPushButton("Quick setup (10 boxes)")
        quick_setup_btn.clicked.connect(self._quick_setup)
        reset_btn = QPushButton("Reset all")
        reset_btn.clicked.connect(self._reset_all)
        alive_btn = QPushButton("Set all alive")
        alive_btn.clicked.connect(self._set_all_alive)
        overlay_btn = QPushButton("Toggle overlay window")
        overlay_btn.clicked.connect(self._toggle_overlay_window)
        controls.addWidget(self.start_btn)
        controls.addWidget(quick_setup_btn)
        controls.addWidget(reset_btn)
        controls.addWidget(alive_btn)
        controls.addWidget(overlay_btn)
        root.addLayout(controls)

        self.status_bar_label = QLabel("")
        root.addWidget(self.status_bar_label)

        self.setCentralWidget(central)

    def _broadcast_label_text(self) -> str:
        return f"Broadcasting to: {self.broadcast_id}" if self.broadcast_id else "No overlay connected"

    def _monitor_label_text(self) -> str:
        monitors = list_monitors(self.sct)
        return f"{len(monitors)} monitor(s) detected: " + ", ".join(
            f"{m['width']}×{m['height']} @ {m['left']},{m['top']}" for m in monitors)

    def _handle_connect_overlay(self):
        raw = self.broadcast_input.text().strip()
        if not raw:
            return
        # Accept either a bare token or a full pasted overlay URL
        token = parse_qs(urlparse(raw).query).get("token", [raw])[0]
        try:
            self.session = auth.resolve_broadcast_id(token)
        except Exception as e:
            QMessageBox.warning(self, "Couldn't connect overlay", str(e))
            return
        self.broadcast_id = self.session["broadcastId"]
        self.broadcast_label.setText(self._broadcast_label_text())

    def _pick_region(self, slot: SlotRow):
        self._active_selector = RegionSelector()
        self._active_selector.region_picked.connect(lambda r: self._region_picked(slot, r))
        self._active_selector.showFullScreen()

    def _region_picked(self, slot: SlotRow, region):
        slot.set_region(region)
        self._save_layout()

    def _quick_setup(self):
        existing = {(t, p): row.region for (t, p), row in self.slots.items() if row.region}
        self._active_quick_setup = QuickRegionSetup(existing)
        self._active_quick_setup.setup_complete.connect(self._quick_setup_complete)
        self._active_quick_setup.showFullScreen()

    def _quick_setup_complete(self, regions: dict):
        for key, region in regions.items():
            self.slots[key].set_region(region)
        self._save_layout()

    def _save_layout(self):
        data = {}
        for (t, p), row in self.slots.items():
            if not row.region:
                continue
            region = dict(row.region)
            monitor = monitor_for_region(self.sct, region)
            region["monitor"] = monitor_signature(monitor) if monitor else None
            data[f"{t}-{p}"] = region
        LAYOUTS_FILE.write_text(json.dumps(data, indent=2))

    def _load_layout(self):
        if not LAYOUTS_FILE.exists():
            return
        try:
            data = json.loads(LAYOUTS_FILE.read_text())
        except Exception:
            return
        current_signatures = {monitor_signature(m) for m in list_monitors(self.sct)}
        for key, region in data.items():
            t, p = map(int, key.split("-"))
            if (t, p) not in self.slots:
                continue
            slot = self.slots[(t, p)]
            slot.set_region(region)
            saved_sig = region.get("monitor")
            if saved_sig and saved_sig not in current_signatures:
                slot.flag_monitor_missing()

    # ── Live correction logging ──────────────────────────────────────
    def _log_correction(self, slot: SlotRow, label: str):
        """Fired when the operator presses Alive/Low/Dead on a row
        because status_label is showing the wrong thing right now. Grabs
        a fresh frame from that slot's saved region and logs it via
        calibrate.py's log_sample() with the pressed label as ground
        truth — same log file `python calibrate.py summarize` reads."""
        if not slot.region:
            self.status_bar_label.setText(f"P{slot.player_index + 1}: no region set — can't log a correction.")
            return

        rgb = grab_region(self.sct, slot.region)
        signal = analyse_frame(rgb, self.templates)
        log_sample(slot.team_index, slot.player_index, label, signal)

        self.status_bar_label.setText(
            f"Logged '{label}' for Team {slot.team_index + 1} P{slot.player_index + 1} "
            f"(brightness={signal['brightness']:.0f}, was shown as '{slot.status_label.text()}')"
        )
        QTimer.singleShot(3000, lambda: self.status_bar_label.setText(""))

    def _toggle_capture(self):
        self.running = not self.running
        self.start_btn.setText("Stop capture" if self.running else "Start capture")
        if self.running:
            layout_summary = {f"{t}-{p}": row.region for (t, p), row in self.slots.items() if row.region}
            monitors = list_monitors(self.sct)
            monitor_info = ", ".join(monitor_signature(m) for m in monitors)
            self.logger.start(monitor_info, layout_summary)
            self.timer.start()
        else:
            self.timer.stop()
            self.logger.stop()

    def _tick(self):
        changed = False
        for (team, player), slot in self.slots.items():
            if not slot.region:
                continue
            state = self.player_states[(team, player)]
            if state.in_cooldown():
                continue

            rgb = grab_region(self.sct, slot.region)
            slot.set_thumbnail(rgb)
            signal = analyse_frame(rgb, self.templates)
            old_status = "dead" if state.is_dead else "alive"
            flipped, status = evaluate(state, signal)
            slot.set_status(status, signal)

            if flipped:
                self.team_alive[team][player] = not state.is_dead
                changed = True
                self.logger.state_change(team, player, old_status, status, signal)

        if changed and self.broadcast_id:
            ok, info = post_alive_status(self.broadcast_id, self.team_alive[0], self.team_alive[1])
            self.status_bar_label.setText(f"{'✓ posted' if ok else '✗ post failed'} — {info}")
            if not ok:
                self.logger.error("poster", info)
            if self.overlay_window:
                self.overlay_window.update_state(self.team_alive[0], self.team_alive[1])
        elif changed:
            self.status_bar_label.setText("State changed, but no overlay connected — not posted.")
            self.logger.error("poster", "state changed but no overlay connected")

    def _reset_all(self):
        for state in self.player_states.values():
            state.is_dead = False
            state.cooldown_until = 0
            state.samples = []
            state.consecutive_dead = 0
            state.consecutive_alive = 0
        self.team_alive = {0: [True] * PLAYERS_PER_TEAM, 1: [True] * PLAYERS_PER_TEAM}
        for slot in self.slots.values():
            slot.set_status("—")

    def _set_all_alive(self):
        for state in self.player_states.values():
            state.is_dead = False
            state.cooldown_until = 0
            state.consecutive_dead = 0
            state.consecutive_alive = 0
        self.team_alive = {0: [True] * PLAYERS_PER_TEAM, 1: [True] * PLAYERS_PER_TEAM}
        if self.broadcast_id:
            post_alive_status(self.broadcast_id, self.team_alive[0], self.team_alive[1])
        if self.overlay_window:
            self.overlay_window.update_state(self.team_alive[0], self.team_alive[1])

    def _toggle_overlay_window(self):
        if self.overlay_window:
            self.overlay_window.close()
            self.overlay_window = None
        else:
            self.overlay_window = OverlayWindow()
            self.overlay_window.show()

    def closeEvent(self, event):
        if self.running:
            self.logger.stop()
        event.accept()