import json
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QMessageBox, QLineEdit, QFrame, QCheckBox,
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
import auth


STYLESHEET = """
QWidget {
    background-color: #12141a;
    color: #e5e7eb;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QGroupBox {
    background-color: #1a1d26;
    border: 1px solid #2a2e3a;
    border-radius: 8px;
    margin-top: 16px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
    font-size: 13px;
    color: #9ca3af;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #d1d5db;
}
QPushButton {
    background-color: #232838;
    border: 1px solid #363c4d;
    border-radius: 6px;
    padding: 6px 14px;
    color: #e5e7eb;
}
QPushButton:hover {
    background-color: #2d3444;
    border-color: #4b5563;
}
QPushButton:pressed {
    background-color: #1a1d26;
}
QLineEdit {
    background-color: #1a1d26;
    border: 1px solid #2a2e3a;
    border-radius: 6px;
    padding: 6px 8px;
}
QLineEdit:focus {
    border: 1px solid #3b82f6;
}
QCheckBox {
    color: #9ca3af;
}
#primaryButton {
    background-color: #16532d;
    border: 1px solid #22c55e;
    color: #dcfce7;
    font-weight: 600;
    font-size: 14px;
    padding: 10px 20px;
}
#primaryButton:hover { background-color: #1a6636; }
#stopButton {
    background-color: #5c1a1a;
    border: 1px solid #f87171;
    color: #fee2e2;
    font-weight: 600;
    font-size: 14px;
    padding: 10px 20px;
}
#stopButton:hover { background-color: #6e1f1f; }
#topBar, #healthBar {
    background-color: #1a1d26;
    border: 1px solid #2a2e3a;
    border-radius: 8px;
}
#warningBanner {
    background-color: #3a1414;
    border: 1px solid #f87171;
    border-radius: 6px;
    color: #fecaca;
    font-weight: 600;
    padding: 8px 12px;
}
"""


def _rgb_to_pixmap(rgb: np.ndarray) -> QPixmap:
    h, w, _ = rgb.shape
    contiguous = np.ascontiguousarray(rgb)
    qimg = QImage(contiguous.data, w, h, w * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _pill(label: QLabel, text: str, ok: bool | None):
    """ok=True → green, ok=False → red, ok=None → neutral grey."""
    fg, bg = {"ok": ("#4ade80", "#0f2b18"), "bad": ("#f87171", "#2b0f0f"),
              "neutral": ("#9ca3af", "#20242e")}[
        "ok" if ok is True else "bad" if ok is False else "neutral"]
    label.setText(text)
    label.setStyleSheet(
        f"color: {fg}; background-color: {bg}; border-radius: 5px; "
        f"font-weight: 600; padding: 3px 10px;")


class SlotRow(QWidget):
    def __init__(self, team_index: int, player_index: int, on_pick_region):
        super().__init__()
        self.team_index = team_index
        self.player_index = player_index
        self.region = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(8)

        self.name_label = QLabel(f"P{player_index + 1}")
        self.name_label.setFixedWidth(26)
        self.name_label.setStyleSheet("color: #9ca3af; font-weight: 600;")

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(48, 30)
        self.thumb_label.setStyleSheet(
            "background: #0a0b0e; border: 1px solid #2a2e3a; border-radius: 4px;")

        self.region_label = QLabel("no region")
        self.region_label.setFixedWidth(150)
        self.region_label.setStyleSheet("color: #6b7280;")

        self.pick_btn = QPushButton("Pick")
        self.pick_btn.setFixedWidth(52)
        self.pick_btn.clicked.connect(lambda: on_pick_region(self))

        self.status_label = QLabel("—")
        self.status_label.setFixedWidth(64)
        self.status_label.setAlignment(Qt.AlignCenter)

        self.signal_label = QLabel("")
        self.signal_label.setStyleSheet("color: #6b7280; font-size: 10px; font-family: Consolas, monospace;")

        layout.addWidget(self.name_label)
        layout.addWidget(self.thumb_label)
        layout.addWidget(self.pick_btn)
        layout.addWidget(self.region_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.signal_label)
        layout.addStretch()

        self.set_status("—")

    def set_region(self, region):
        self.region = region
        if region:
            self.region_label.setText(f"{region['width']}×{region['height']} @ {region['left']},{region['top']}")
            self.region_label.setStyleSheet("color: #6b7280;")
        else:
            self.region_label.setText("no region")

    def flag_monitor_missing(self):
        self.region_label.setText((self.region_label.text() or "") + "  ⚠")
        self.region_label.setStyleSheet("color: #f87171; font-weight: 600;")

    def set_status(self, status: str, signal: dict | None = None):
        styles = {
            "alive": ("#4ade80", "#0f2b18"), "dead": ("#f87171", "#2b0f0f"),
            "low": ("#fbbf24", "#2b2410"), "warming": ("#94a3b8", "#1a1d26"),
            "—": ("#6b7280", "#1a1d26"),
        }
        fg, bg = styles.get(status, ("#9ca3af", "#1a1d26"))
        self.status_label.setText(status)
        self.status_label.setStyleSheet(
            f"color: {fg}; background-color: {bg}; border-radius: 5px; "
            f"font-weight: 600; padding: 2px 8px;")
        if signal:
            self.signal_label.setText(
                f"b={signal.get('brightness', 0):.0f}  d={signal.get('dead_sim', 0):.2f}  "
                f"a={signal.get('alive_sim', 0):.2f}  v={signal.get('pixel_votes', 0)}")

    def set_thumbnail(self, rgb: np.ndarray):
        pix = _rgb_to_pixmap(rgb).scaled(self.thumb_label.width(), self.thumb_label.height())
        self.thumb_label.setPixmap(pix)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Realtime CODM HUD")
        self.resize(900, 640)
        self.setStyleSheet(STYLESHEET)

        self.session = auth.load_cached_session()
        self.broadcast_id = self.session.get("broadcastId") if self.session else None

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
        self.consecutive_push_failures = 0
        self.last_push_ok = None  # None = never posted yet

        self._build_ui()
        self._load_layout()
        self._update_health_bar()

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)

        # ── Fast recovery shortcuts — no mouse required mid-broadcast ──
        QShortcut(QKeySequence("F9"), self, activated=self._toggle_capture)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.broadcast_input.setFocus())
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=self._quick_setup)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ── Warning banner — hidden unless something needs attention ──
        self.warning_banner = QLabel("")
        self.warning_banner.setObjectName("warningBanner")
        self.warning_banner.setWordWrap(True)
        self.warning_banner.hide()
        root.addWidget(self.warning_banner)

        # ── System health strip — always visible, at a glance ──
        health_bar = QFrame()
        health_bar.setObjectName("healthBar")
        health_layout = QHBoxLayout(health_bar)
        health_layout.setContentsMargins(12, 8, 12, 8)
        health_layout.setSpacing(10)
        self.health_overlay = QLabel()
        self.health_capture = QLabel()
        self.health_monitors = QLabel()
        self.health_push = QLabel()
        for lbl in (self.health_overlay, self.health_capture, self.health_monitors, self.health_push):
            health_layout.addWidget(lbl)
        health_layout.addStretch()
        always_on_top_cb = QCheckBox("Always on top")
        always_on_top_cb.toggled.connect(self._toggle_always_on_top)
        health_layout.addWidget(always_on_top_cb)
        root.addWidget(health_bar)

        # ── Overlay connect + monitor info ──
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QVBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 10, 12, 10)
        top_layout.setSpacing(8)

        broadcast_row = QHBoxLayout()
        self.broadcast_input = QLineEdit()
        self.broadcast_input.setPlaceholderText("Paste the Scoreboard overlay link or token from Studio (Ctrl+L)")
        connect_btn = QPushButton("Connect overlay")
        connect_btn.clicked.connect(self._handle_connect_overlay)
        broadcast_row.addWidget(self.broadcast_input)
        broadcast_row.addWidget(connect_btn)
        top_layout.addLayout(broadcast_row)

        self.monitor_label = QLabel(self._monitor_label_text())
        self.monitor_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        top_layout.addWidget(self.monitor_label)
        root.addWidget(top_bar)

        # ── Teams ──
        teams_row = QHBoxLayout()
        teams_row.setSpacing(12)
        for team in range(NUM_TEAMS):
            box = QGroupBox(f"Team {team + 1}")
            box_layout = QVBoxLayout(box)
            box_layout.setSpacing(4)
            for player in range(PLAYERS_PER_TEAM):
                row = SlotRow(team, player, self._pick_region)
                self.slots[(team, player)] = row
                box_layout.addWidget(row)
            teams_row.addWidget(box)
        root.addLayout(teams_row)

        # ── Primary action ──
        primary_row = QHBoxLayout()
        self.start_btn = QPushButton("Start capture  (F9)")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._toggle_capture)
        primary_row.addWidget(self.start_btn)
        root.addLayout(primary_row)

        # ── Secondary controls ──
        controls = QHBoxLayout()
        controls.setSpacing(8)
        quick_setup_btn = QPushButton("Quick setup (10 boxes)")
        quick_setup_btn.clicked.connect(self._quick_setup)
        reset_btn = QPushButton("Reset all")
        reset_btn.clicked.connect(self._reset_all)
        alive_btn = QPushButton("Set all alive")
        alive_btn.clicked.connect(self._set_all_alive)
        overlay_btn = QPushButton("Toggle overlay window")
        overlay_btn.clicked.connect(self._toggle_overlay_window)
        controls.addWidget(quick_setup_btn)
        controls.addWidget(reset_btn)
        controls.addWidget(alive_btn)
        controls.addWidget(overlay_btn)
        root.addLayout(controls)

        self.status_bar_label = QLabel("")
        self.status_bar_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        root.addWidget(self.status_bar_label)

        self.setCentralWidget(central)

    # ── Health bar / warning banner ──────────────────────────────────
    def _update_health_bar(self):
        _pill(self.health_overlay,
              "Overlay: connected" if self.broadcast_id else "Overlay: not connected",
              True if self.broadcast_id else False)
        _pill(self.health_capture,
              "Capture: running" if self.running else "Capture: stopped",
              True if self.running else None)

        current_sigs = {monitor_signature(m) for m in list_monitors(self.sct)}
        missing = any(
            row.region and row.region.get("monitor") and row.region["monitor"] not in current_sigs
            for row in self.slots.values()
        )
        _pill(self.health_monitors, "Monitors: missing one" if missing else "Monitors: ok",
              False if missing else True)

        if self.last_push_ok is None:
            _pill(self.health_push, "Last push: —", None)
        else:
            _pill(self.health_push, "Last push: ok" if self.last_push_ok else "Last push: failed",
                  self.last_push_ok)

        self._update_warning_banner(missing)

    def _update_warning_banner(self, monitor_missing: bool):
        problems = []
        if self.running and not self.broadcast_id:
            problems.append("Capture is running but no overlay is connected — nothing is being pushed.")
        if monitor_missing:
            problems.append("A saved region's monitor is no longer detected — reselect it before going live.")
        if self.consecutive_push_failures >= 3:
            problems.append(f"Last {self.consecutive_push_failures} pushes to the broadcast platform failed.")

        if problems:
            self.warning_banner.setText("⚠ " + "   ·   ".join(problems))
            self.warning_banner.show()
        else:
            self.warning_banner.hide()

    def _toggle_always_on_top(self, checked: bool):
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()  # re-apply flags — Qt requires a re-show after changing them

    def _monitor_label_text(self) -> str:
        monitors = list_monitors(self.sct)
        return f"{len(monitors)} monitor(s) detected: " + ", ".join(
            f"{m['width']}×{m['height']} @ {m['left']},{m['top']}" for m in monitors)

    def _handle_connect_overlay(self):
        raw = self.broadcast_input.text().strip()
        if not raw:
            return
        token = parse_qs(urlparse(raw).query).get("token", [raw])[0]
        try:
            self.session = auth.resolve_broadcast_id(token)
        except Exception as e:
            QMessageBox.warning(self, "Couldn't connect overlay", str(e))
            self._update_health_bar()
            return
        self.broadcast_id = self.session["broadcastId"]
        self._update_health_bar()

    def _pick_region(self, slot: SlotRow):
        self._active_selector = RegionSelector()
        self._active_selector.region_picked.connect(lambda r: self._region_picked(slot, r))
        self._active_selector.showFullScreen()

    def _region_picked(self, slot: SlotRow, region):
        slot.set_region(region)
        self._save_layout()
        self._update_health_bar()

    def _quick_setup(self):
        existing = {(t, p): row.region for (t, p), row in self.slots.items() if row.region}
        self._active_quick_setup = QuickRegionSetup(existing)
        self._active_quick_setup.setup_complete.connect(self._quick_setup_complete)
        self._active_quick_setup.showFullScreen()

    def _quick_setup_complete(self, regions: dict):
        for key, region in regions.items():
            self.slots[key].set_region(region)
        self._save_layout()
        self._update_health_bar()

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

    def _toggle_capture(self):
        self.running = not self.running
        self.start_btn.setText("Stop capture  (F9)" if self.running else "Start capture  (F9)")
        self.start_btn.setObjectName("stopButton" if self.running else "primaryButton")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        (self.timer.start if self.running else self.timer.stop)()
        self._update_health_bar()

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
            flipped, status = evaluate(state, signal)
            slot.set_status(status, signal)

            if flipped:
                self.team_alive[team][player] = not state.is_dead
                changed = True

        if changed and self.broadcast_id:
            ok, info = post_alive_status(self.broadcast_id, self.team_alive[0], self.team_alive[1])
            self.last_push_ok = ok
            self.consecutive_push_failures = 0 if ok else self.consecutive_push_failures + 1
            self.status_bar_label.setText(f"{'✓ posted' if ok else '✗ post failed'} — {info}")
            if self.overlay_window:
                self.overlay_window.update_state(self.team_alive[0], self.team_alive[1])
            self._update_health_bar()
        elif changed:
            self.status_bar_label.setText("State changed, but no overlay connected — not posted.")
            self._update_health_bar()

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
            ok, _ = post_alive_status(self.broadcast_id, self.team_alive[0], self.team_alive[1])
            self.last_push_ok = ok
            self.consecutive_push_failures = 0 if ok else self.consecutive_push_failures + 1
        if self.overlay_window:
            self.overlay_window.update_state(self.team_alive[0], self.team_alive[1])
        self._update_health_bar()

    def _toggle_overlay_window(self):
        if self.overlay_window:
            self.overlay_window.close()
            self.overlay_window = None
        else:
            self.overlay_window = OverlayWindow()
            self.overlay_window.show()