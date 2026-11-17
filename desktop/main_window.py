import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import QTimer, Qt, QRectF
from PySide6.QtGui import QImage, QPixmap, QKeySequence, QShortcut, QPainter, QColor, QPainterPath
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QMessageBox, QLineEdit, QFrame, QCheckBox, QSizePolicy,
)
import numpy as np
import mss

from config import LAYOUTS_FILE, POLL_INTERVAL_MS, NUM_TEAMS, PLAYERS_PER_TEAM
from analysis import read_bar
from state import PlayerState, evaluate
from capture import grab_region, list_monitors, monitor_for_region, monitor_signature
from poster import post_alive_status
from region_selector import RegionSelector, QuickRegionSetup
from overlay_window import OverlayWindow
import auth


# ── Look ──────────────────────────────────────────────────────────────────────
# Dark broadcast-desk palette; the two teams use the HUD's own colours
# (blue left, amber right) so a row reads at a glance.
BG       = "#0b0d12"
SURFACE  = "#12151d"
SURFACE2 = "#181c26"
BORDER   = "#232838"
TEXT     = "#e8eaf0"
MUTED    = "#8b93a7"
FAINT    = "#5b6275"
ACCENT   = "#ffc83d"
TEAM_COLORS = ["#3ba7ff", "#ffb020"]

STATUS_COLORS = {
    "alive":  ("#3ddc84", "#0e2a1b"),
    "low":    ("#ffb020", "#2d2210"),
    "dead":   ("#ff5c5c", "#2e1215"),
    "paused": ("#8b93a7", "#1c202b"),
    "—":      ("#5b6275", "#161a23"),
}

STYLESHEET = f"""
QMainWindow, #root {{ background: {BG}; }}
QWidget {{
    color: {TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}

#header {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
#brandMark {{
    background: {ACCENT}; color: #111; border-radius: 8px;
    font-weight: 900; font-size: 13px;
}}
#brandTitle {{ font-size: 17px; font-weight: 800; letter-spacing: 0.5px; }}
#brandSub {{ color: {MUTED}; font-size: 11px; letter-spacing: 1.5px; }}

#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#cardTitle {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1.6px; }}
#hint {{ color: {FAINT}; font-size: 12px; }}

QLineEdit {{
    background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 9px 12px; selection-background-color: {ACCENT}; selection-color: #111;
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QPushButton {{
    background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: #20253a; border-color: #343b52; }}
QPushButton:pressed {{ background: {SURFACE}; }}
#accentButton {{ background: {ACCENT}; color: #111; border: none; padding: 9px 18px; }}
#accentButton:hover {{ background: #ffd76b; }}
#ghostButton {{ background: transparent; border: 1px solid {BORDER}; color: {MUTED}; padding: 5px 10px; font-size: 12px; }}
#ghostButton:hover {{ color: {TEXT}; border-color: #3a4259; }}

#startButton {{
    background: #1ec46b; color: #04170c; border: none; border-radius: 10px;
    font-size: 15px; font-weight: 800; padding: 14px 26px; letter-spacing: 0.5px;
}}
#startButton:hover {{ background: #33d47c; }}
#stopButton {{
    background: #ff5c5c; color: #1d0405; border: none; border-radius: 10px;
    font-size: 15px; font-weight: 800; padding: 14px 26px; letter-spacing: 0.5px;
}}
#stopButton:hover {{ background: #ff7676; }}

#teamCount {{ font-size: 22px; font-weight: 800; }}
#teamCountSub {{ color: {MUTED}; font-size: 11px; letter-spacing: 1px; }}
#playerRow {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; }}
#detail {{ color: {FAINT}; font-size: 11px; font-family: 'Cascadia Mono', Consolas, monospace; }}
#region {{ color: {FAINT}; font-size: 11px; }}

#warningBanner {{
    background: #2e1215; border: 1px solid #ff5c5c; border-radius: 10px;
    color: #ffd0d0; font-weight: 600; padding: 10px 14px;
}}
#footer {{ color: {FAINT}; font-size: 12px; }}
QCheckBox {{ color: {MUTED}; spacing: 6px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3a4259; background: {SURFACE2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}
"""


def _rgba(hex_color: str, alpha: float) -> str:
    """'#3ba7ff', 0.15 → 'rgba(59, 167, 255, 38)'. Qt reads 8-digit hex as
    #AARRGGBB, so transparency is always written this way."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {round(alpha * 255)})"


def _rgb_to_pixmap(rgb: np.ndarray) -> QPixmap:
    h, w, _ = rgb.shape
    contiguous = np.ascontiguousarray(rgb)
    qimg = QImage(contiguous.data, w, h, w * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _pill(label: QLabel, text: str, ok: bool | None):
    """A status chip with a coloured dot. ok=True green, False red, None grey."""
    fg, bg = {True: ("#3ddc84", "#0e2a1b"), False: ("#ff5c5c", "#2e1215"),
              None: ("#8b93a7", "#1c202b")}[ok]
    label.setText(f"<span style='color:{fg}'>●</span>&nbsp; {text}")
    label.setStyleSheet(
        f"color: {TEXT if ok is not None else MUTED}; background: {bg}; border: 1px solid {_rgba(fg, 0.25)}; "
        f"border-radius: 13px; font-weight: 600; font-size: 12px; padding: 4px 12px;")


class HealthBar(QWidget):
    """Thin rounded bar showing a player's health, coloured by status."""

    def __init__(self):
        super().__init__()
        self.value = 0.0
        self.color = QColor(FAINT)
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: float, color: str):
        self.value = max(0.0, min(1.0, value))
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        track = QPainterPath()
        track.addRoundedRect(r, 3, 3)
        p.fillPath(track, QColor(BORDER))
        if self.value > 0:
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(r.x(), r.y(), r.width() * self.value, r.height()), 3, 3)
            p.fillPath(fill, self.color)


class SlotRow(QFrame):
    """One player: live thumbnail of their HUD card, status, health and the
    detector's reasons, with a button to pick the box by hand."""

    def __init__(self, team_index: int, player_index: int, on_pick_region):
        super().__init__()
        self.setObjectName("playerRow")
        self.team_index = team_index
        self.player_index = player_index
        self.region = None
        team_color = TEAM_COLORS[team_index % len(TEAM_COLORS)]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        self.name_label = QLabel(f"{'LR'[team_index] if team_index < 2 else 'T'}{player_index + 1}")
        self.name_label.setFixedSize(34, 34)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet(
            f"background: {_rgba(team_color, 0.14)}; color: {team_color}; border: 1px solid {_rgba(team_color, 0.45)}; "
            f"border-radius: 8px; font-weight: 800; font-size: 13px;")

        # Same shape as a HUD card (101 × 108 at 1080p)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(44, 47)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            f"background: {BG}; border: 1px solid {BORDER}; border-radius: 6px; color: {FAINT}; font-size: 10px;")

        middle = QVBoxLayout()
        middle.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_label = QLabel("—")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFixedWidth(70)
        self.health_text = QLabel("")
        self.health_text.setStyleSheet(f"color: {MUTED}; font-weight: 700; font-size: 12px;")
        top.addWidget(self.status_label)
        top.addWidget(self.health_text)
        top.addStretch()
        self.health_bar = HealthBar()
        self.signal_label = QLabel("")
        self.signal_label.setObjectName("detail")
        middle.addLayout(top)
        middle.addWidget(self.health_bar)
        middle.addWidget(self.signal_label)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.pick_btn = QPushButton("Pick box")
        self.pick_btn.setObjectName("ghostButton")
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.clicked.connect(lambda: on_pick_region(self))
        self.region_label = QLabel("no box")
        self.region_label.setObjectName("region")
        self.region_label.setAlignment(Qt.AlignRight)
        right.addWidget(self.pick_btn, alignment=Qt.AlignRight)
        right.addWidget(self.region_label)

        layout.addWidget(self.name_label)
        layout.addWidget(self.thumb_label)
        layout.addLayout(middle, 1)
        layout.addLayout(right)

        self.set_region(None)
        self.set_status("—")

    def set_region(self, region):
        self.region = region
        if region:
            self.region_label.setText(f"{region['width']}×{region['height']} at {region['left']},{region['top']}")
            self.region_label.setStyleSheet("")
            self.region_label.setToolTip("Where this player's card is captured from")
        else:
            self.region_label.setText("no box yet")
            self.thumb_label.setText("—")

    def flag_monitor_missing(self):
        self.region_label.setText("⚠ monitor missing")
        self.region_label.setStyleSheet("color: #ff5c5c; font-weight: 700;")

    def set_status(self, status: str, info: dict | None = None):
        fg, bg = STATUS_COLORS.get(status, STATUS_COLORS["—"])
        self.status_label.setText(status.upper() if status != "—" else "IDLE")
        self.status_label.setStyleSheet(
            f"color: {fg}; background: {bg}; border: 1px solid {_rgba(fg, 0.35)}; border-radius: 6px; "
            f"font-weight: 800; font-size: 11px; letter-spacing: 1px; padding: 3px 0;")
        health = (info or {}).get("health", 0.0) if status in ("alive", "low") else 0.0
        self.health_bar.set_value(health if status in ("alive", "low") else 0.0, fg)
        self.health_text.setText(f"{health:.0%} HP" if status in ("alive", "low") else "")
        if status == "paused":
            self.signal_label.setText("HUD hidden — holding")
        elif info:
            change = info.get("change")
            self.signal_label.setText(
                f"bar {info.get('run', 0)}px · portrait change {'—' if change is None else f'{change:.2f}'}")
        else:
            self.signal_label.setText("")

    def set_thumbnail(self, rgb: np.ndarray):
        pix = _rgb_to_pixmap(rgb).scaled(
            self.thumb_label.width() - 2, self.thumb_label.height() - 2,
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(pix)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Realtime CODM HUD")
        self.resize(1120, 760)
        self.setMinimumSize(980, 680)
        self.setStyleSheet(STYLESHEET)

        self.session = auth.load_cached_session()
        self.broadcast_id = self.session.get("broadcastId") if self.session else None

        self.sct = mss.mss()
        self.player_states = {
            (t, p): PlayerState(t, p)
            for t in range(NUM_TEAMS) for p in range(PLAYERS_PER_TEAM)
        }
        self.team_alive = {0: [True] * PLAYERS_PER_TEAM, 1: [True] * PLAYERS_PER_TEAM}
        self.slots = {}
        self.team_counts = {}
        self.overlay_window = None
        self.running = False
        self.consecutive_push_failures = 0
        self.last_push_ok = None  # None = never posted yet
        # Pushes run on a background thread, so a slow connection never
        # freezes capture. One at a time; a change made while one is in
        # flight is sent (with the latest state) as soon as it finishes.
        self._push_pool = ThreadPoolExecutor(max_workers=1)
        self._push_future = None
        self._push_again = False

        self._build_ui()
        self._load_layout()
        self._update_health_bar()
        self._update_team_counts()

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)

        self.push_timer = QTimer(self)
        self.push_timer.setInterval(100)
        self.push_timer.timeout.connect(self._collect_push)
        self.push_timer.start()

        # ── Fast recovery shortcuts — no mouse required mid-broadcast ──
        QShortcut(QKeySequence("F9"), self, activated=self._toggle_capture)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.broadcast_input.setFocus())
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=self._quick_setup)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("root")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header: brand on the left, system status chips on the right ──
        header = QFrame()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(12)
        mark = QLabel("RT")
        mark.setObjectName("brandMark")
        mark.setFixedSize(36, 36)
        mark.setAlignment(Qt.AlignCenter)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("CODM HUD")
        title.setObjectName("brandTitle")
        sub = QLabel("REALTIME PRODUCTION · LIVE DEATH TRACKER")
        sub.setObjectName("brandSub")
        brand.addWidget(title)
        brand.addWidget(sub)
        hl.addWidget(mark)
        hl.addLayout(brand)
        hl.addStretch()
        self.health_overlay = QLabel()
        self.health_capture = QLabel()
        self.health_monitors = QLabel()
        self.health_push = QLabel()
        for lbl in (self.health_overlay, self.health_capture, self.health_monitors, self.health_push):
            hl.addWidget(lbl)
        outer.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(14)
        outer.addLayout(body, 1)

        # ── Warning banner — hidden unless something needs attention ──
        self.warning_banner = QLabel("")
        self.warning_banner.setObjectName("warningBanner")
        self.warning_banner.setWordWrap(True)
        self.warning_banner.hide()
        body.addWidget(self.warning_banner)

        # ── Overlay connection ──
        connect_card = QFrame()
        connect_card.setObjectName("card")
        cl = QVBoxLayout(connect_card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(8)
        connect_title = QLabel("SCOREBOARD OVERLAY")
        connect_title.setObjectName("cardTitle")
        cl.addWidget(connect_title)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.broadcast_input = QLineEdit()
        self.broadcast_input.setPlaceholderText("Paste the Scoreboard overlay link from Studio  (Ctrl+L)")
        connect_btn = QPushButton("Connect")
        connect_btn.setObjectName("accentButton")
        connect_btn.setCursor(Qt.PointingHandCursor)
        connect_btn.clicked.connect(self._handle_connect_overlay)
        self.broadcast_input.returnPressed.connect(self._handle_connect_overlay)
        row.addWidget(self.broadcast_input, 1)
        row.addWidget(connect_btn)
        cl.addLayout(row)
        self.monitor_label = QLabel(self._monitor_label_text())
        self.monitor_label.setObjectName("hint")
        cl.addWidget(self.monitor_label)
        body.addWidget(connect_card)

        # ── Teams ──
        teams = QHBoxLayout()
        teams.setSpacing(14)
        for team in range(NUM_TEAMS):
            color = TEAM_COLORS[team % len(TEAM_COLORS)]
            card = QFrame()
            card.setObjectName("card")
            tl = QVBoxLayout(card)
            tl.setContentsMargins(14, 12, 14, 14)
            tl.setSpacing(8)

            head = QHBoxLayout()
            stripe = QFrame()
            stripe.setFixedSize(4, 30)
            stripe.setStyleSheet(f"background: {color}; border-radius: 2px;")
            names = QVBoxLayout()
            names.setSpacing(0)
            team_title = QLabel(f"TEAM {team + 1}")
            team_title.setObjectName("cardTitle")
            side = QLabel("Left side of the HUD" if team == 0 else "Right side of the HUD")
            side.setObjectName("hint")
            names.addWidget(team_title)
            names.addWidget(side)
            count = QLabel("5/5")
            count.setObjectName("teamCount")
            count.setStyleSheet(f"color: {color};")
            count_sub = QLabel("ALIVE")
            count_sub.setObjectName("teamCountSub")
            counts = QVBoxLayout()
            counts.setSpacing(0)
            counts.addWidget(count, alignment=Qt.AlignRight)
            counts.addWidget(count_sub, alignment=Qt.AlignRight)
            head.addWidget(stripe)
            head.addSpacing(6)
            head.addLayout(names)
            head.addStretch()
            head.addLayout(counts)
            tl.addLayout(head)
            self.team_counts[team] = count

            for player in range(PLAYERS_PER_TEAM):
                slot = SlotRow(team, player, self._pick_region)
                self.slots[(team, player)] = slot
                tl.addWidget(slot)
            teams.addWidget(card, 1)
        body.addLayout(teams, 1)

        # ── Actions ──
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_btn = QPushButton("▶  START CAPTURE   F9")
        self.start_btn.setObjectName("startButton")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._toggle_capture)
        actions.addWidget(self.start_btn, 2)
        for text, tip, handler in (
            ("Quick setup", "Place all 10 boxes on the HUD cards at once (Ctrl+Shift+R)", self._quick_setup),
            ("Reset all", "Everyone alive, readings cleared, overlay updated", self._reset_all),
            ("Set all alive", "Everyone alive and the overlay updated", self._set_all_alive),
            ("Mini window", "A small always-on-top strip of dots showing who is alive", self._toggle_overlay_window),
        ):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(48)
            b.clicked.connect(handler)
            actions.addWidget(b, 1)
        body.addLayout(actions)

        footer = QHBoxLayout()
        self.status_bar_label = QLabel("Ready. Connect the overlay, run Quick setup, then start capture.")
        self.status_bar_label.setObjectName("footer")
        always_on_top_cb = QCheckBox("Always on top")
        always_on_top_cb.toggled.connect(self._toggle_always_on_top)
        footer.addWidget(self.status_bar_label, 1)
        footer.addWidget(always_on_top_cb)
        body.addLayout(footer)

        self.setCentralWidget(central)

    def _update_team_counts(self):
        for team, label in self.team_counts.items():
            alive = sum(self.team_alive[team])
            label.setText(f"{alive}/{len(self.team_alive[team])}")

    # ── Health bar / warning banner ──────────────────────────────────
    def _update_health_bar(self):
        _pill(self.health_overlay,
              "Overlay connected" if self.broadcast_id else "Overlay not connected",
              True if self.broadcast_id else False)
        _pill(self.health_capture,
              "Capturing" if self.running else "Capture stopped",
              True if self.running else None)

        current_sigs = {monitor_signature(m) for m in list_monitors(self.sct)}
        missing = any(
            row.region and row.region.get("monitor") and row.region["monitor"] not in current_sigs
            for row in self.slots.values()
        )
        _pill(self.health_monitors, "Monitor missing" if missing else "Monitors OK",
              False if missing else True)

        if self.last_push_ok is None:
            _pill(self.health_push, "No pushes yet", None)
        else:
            _pill(self.health_push, "Last push OK" if self.last_push_ok else "Last push failed",
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
        self.player_states[(slot.team_index, slot.player_index)].reset(forget_box=True)
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
            self.player_states[key].reset(forget_box=True)
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
        self.start_btn.setText("■  STOP CAPTURE   F9" if self.running else "▶  START CAPTURE   F9")
        self.start_btn.setObjectName("stopButton" if self.running else "startButton")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        (self.timer.start if self.running else self.timer.stop)()
        self._update_health_bar()

    def _tick(self):
        changed = False
        frames = {}
        for key, slot in self.slots.items():
            if slot.region:
                rgb = grab_region(self.sct, slot.region)
                slot.set_thumbnail(rgb)
                frames[key] = (rgb, read_bar(rgb))
        # No card shows a bar: the HUD is hidden, so nobody changes
        hud_visible = any(bar.present for _, bar in frames.values())
        for (team, player), (rgb, bar) in frames.items():
            slot = self.slots[(team, player)]
            state = self.player_states[(team, player)]
            flipped, status, info = evaluate(state, rgb, bar, hud_visible)
            slot.set_status(status, info)
            if flipped:
                self.team_alive[team][player] = not state.is_dead
                changed = True
        if changed:
            self._state_changed()

    # ── Sending who is alive ─────────────────────────────────────────
    def _state_changed(self):
        self._update_team_counts()
        if self.overlay_window:
            self.overlay_window.update_state(self.team_alive[0], self.team_alive[1])
        if self.broadcast_id:
            self._push()
        else:
            self.status_bar_label.setText("State changed, but no overlay connected — not posted.")
            self._update_health_bar()

    def _push(self):
        if not self.broadcast_id or not self.session:
            return
        if self._push_future is not None:
            self._push_again = True
            return
        self._push_future = self._push_pool.submit(
            post_alive_status, self.broadcast_id, self.session["broadcastToken"],
            list(self.team_alive[0]), list(self.team_alive[1]))

    def _collect_push(self):
        future = self._push_future
        if future is None or not future.done():
            return
        self._push_future = None
        try:
            ok, info = future.result()
        except Exception as e:
            ok, info = False, str(e)
        self.last_push_ok = ok
        self.consecutive_push_failures = 0 if ok else self.consecutive_push_failures + 1
        self.status_bar_label.setText(f"{'✓ posted' if ok else '✗ post failed'} — {info}")
        self._update_health_bar()
        if self._push_again:
            self._push_again = False
            self._push()

    def _all_alive(self):
        for state in self.player_states.values():
            state.reset()
        self.team_alive = {0: [True] * PLAYERS_PER_TEAM, 1: [True] * PLAYERS_PER_TEAM}

    def _reset_all(self):
        """Everyone alive, readings cleared, and the overlay told."""
        self._all_alive()
        for slot in self.slots.values():
            slot.set_status("—")
        self._state_changed()

    def _set_all_alive(self):
        self._all_alive()
        self._state_changed()

    def closeEvent(self, event):
        self._push_pool.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def _toggle_overlay_window(self):
        if self.overlay_window:
            self.overlay_window.close()
            self.overlay_window = None
        else:
            self.overlay_window = OverlayWindow()
            self.overlay_window.show()