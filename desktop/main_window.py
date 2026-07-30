import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QMessageBox,
)
import mss

from config import LAYOUTS_FILE, POLL_INTERVAL_MS, NUM_TEAMS, PLAYERS_PER_TEAM
from analysis import Templates, analyse_frame
from state import PlayerState, evaluate
from capture import grab_region
from poster import post_alive_status
from region_selector import RegionSelector
from overlay_window import OverlayWindow
import auth


class SlotRow(QWidget):
    def __init__(self, team_index: int, player_index: int, on_pick_region):
        super().__init__()
        self.team_index = team_index
        self.player_index = player_index
        self.region = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.name_label = QLabel(f"P{player_index + 1}")
        self.name_label.setFixedWidth(30)

        self.region_label = QLabel("no region")
        self.region_label.setFixedWidth(150)
        self.region_label.setStyleSheet("color: #888;")

        self.pick_btn = QPushButton("Pick region")
        self.pick_btn.clicked.connect(lambda: on_pick_region(self))

        self.status_label = QLabel("—")
        self.status_label.setFixedWidth(70)

        self.brightness_label = QLabel("")
        self.brightness_label.setFixedWidth(50)
        self.brightness_label.setStyleSheet("color: #666; font-size: 10px;")

        layout.addWidget(self.name_label)
        layout.addWidget(self.pick_btn)
        layout.addWidget(self.region_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.brightness_label)

    def set_region(self, region):
        self.region = region
        self.region_label.setText(
            f"{region['width']}×{region['height']} @ {region['left']},{region['top']}" if region else "no region"
        )

    def set_status(self, status: str, brightness=None):
        colors = {"alive": "#4ade80", "dead": "#f87171", "low": "#fbbf24", "warming": "#94a3b8", "—": "#666"}
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {colors.get(status, '#888')}; font-weight: bold;")
        if brightness is not None:
            self.brightness_label.setText(f"{brightness:.0f}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Health Capture")
        self.resize(720, 560)

        self.identity = auth.load_cached_identity()
        self.broadcast_id = auth.compute_broadcast_id(self.identity) if self.identity else None

        self.templates = Templates()
        self.sct = mss.mss()
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

        auth_row = QHBoxLayout()
        self.auth_label = QLabel(self._auth_label_text())
        self.auth_btn = QPushButton("Sign in" if not self.identity else "Switch account")
        self.auth_btn.clicked.connect(self._handle_sign_in)
        auth_row.addWidget(self.auth_label)
        auth_row.addStretch()
        auth_row.addWidget(self.auth_btn)
        root.addLayout(auth_row)

        grid = QGridLayout()
        for team in range(NUM_TEAMS):
            header = QLabel(f"Team {team + 1}")
            header.setStyleSheet("font-weight: bold; margin-top: 6px;")
            grid.addWidget(header, 0, team)
            for player in range(PLAYERS_PER_TEAM):
                row = SlotRow(team, player, self._pick_region)
                self.slots[(team, player)] = row
                grid.addWidget(row, player + 1, team)
        root.addLayout(grid)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start capture")
        self.start_btn.clicked.connect(self._toggle_capture)
        reset_btn = QPushButton("Reset all")
        reset_btn.clicked.connect(self._reset_all)
        alive_btn = QPushButton("Set all alive")
        alive_btn.clicked.connect(self._set_all_alive)
        overlay_btn = QPushButton("Toggle overlay window")
        overlay_btn.clicked.connect(self._toggle_overlay_window)
        controls.addWidget(self.start_btn)
        controls.addWidget(reset_btn)
        controls.addWidget(alive_btn)
        controls.addWidget(overlay_btn)
        root.addLayout(controls)

        self.status_bar_label = QLabel("")
        root.addWidget(self.status_bar_label)

        self.setCentralWidget(central)

    def _auth_label_text(self) -> str:
        if not self.identity:
            return "Not signed in"
        return f"Signed in as {self.identity.get('userId', 'unknown')} · broadcast: {self.broadcast_id}"

    def _handle_sign_in(self):
        try:
            self.identity = auth.sign_in()
        except Exception as e:
            QMessageBox.warning(self, "Sign-in failed", str(e))
            return
        self.broadcast_id = auth.compute_broadcast_id(self.identity)
        self.auth_label.setText(self._auth_label_text())
        self.auth_btn.setText("Switch account")

    def _pick_region(self, slot: SlotRow):
        self._active_selector = RegionSelector()
        self._active_selector.region_picked.connect(lambda r: self._region_picked(slot, r))
        self._active_selector.showFullScreen()

    def _region_picked(self, slot: SlotRow, region):
        slot.set_region(region)
        self._save_layout()

    def _save_layout(self):
        data = {f"{t}-{p}": row.region for (t, p), row in self.slots.items() if row.region}
        LAYOUTS_FILE.write_text(json.dumps(data, indent=2))

    def _load_layout(self):
        if not LAYOUTS_FILE.exists():
            return
        try:
            data = json.loads(LAYOUTS_FILE.read_text())
        except Exception:
            return
        for key, region in data.items():
            t, p = map(int, key.split("-"))
            if (t, p) in self.slots:
                self.slots[(t, p)].set_region(region)

    def _toggle_capture(self):
        self.running = not self.running
        self.start_btn.setText("Stop capture" if self.running else "Start capture")
        (self.timer.start if self.running else self.timer.stop)()

    def _tick(self):
        changed = False
        for (team, player), slot in self.slots.items():
            if not slot.region:
                continue
            state = self.player_states[(team, player)]
            if state.in_cooldown():
                continue

            rgb = grab_region(self.sct, slot.region)
            signal = analyse_frame(rgb, self.templates)
            flipped, status = evaluate(state, signal)
            slot.set_status(status, signal["brightness"])

            if flipped:
                self.team_alive[team][player] = not state.is_dead
                changed = True

        if changed and self.broadcast_id:
            ok, info = post_alive_status(self.broadcast_id, self.team_alive[0], self.team_alive[1])
            self.status_bar_label.setText(f"{'✓ posted' if ok else '✗ post failed'} — {info}")
            if self.overlay_window:
                self.overlay_window.update_state(self.team_alive[0], self.team_alive[1])
        elif changed:
            self.status_bar_label.setText("State changed, but not signed in — not posted.")

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