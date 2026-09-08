"""Lumi desktop avatar — pure-Python overlay (PySide6), no Live2D.

Frameless, transparent, always-on-top window in the bottom-right corner
that idles with a gentle wiggle, loops through a pose group's 3 art
variants (crossfading between each, on a randomized pace) for a lively,
breathing feel, jumps to a different pose group on a random timer (same
crossfade, always waiting for the current loop to finish first so it
never cuts a transition short), falls asleep (pose 8) after 20s with no
mouse/keyboard input and stays there until input resumes, and blinks on
the poses whose eyes have been calibrated for it.
"""

import ctypes
import math
import random
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

def _assets_dir() -> Path:
    # PyInstaller onefile builds extract bundled data next to sys._MEIPASS,
    # not next to __file__ (which points inside that same temp extraction
    # dir, but relying on _MEIPASS is the documented, stable way to find it).
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    return Path(__file__).parent / "assets"


ASSETS_DIR = _assets_dir()

# Set to a group number (e.g. 1) to restrict the rotation to just that
# pose's 3 variants and disable group-swapping entirely — useful for
# judging the variant-loop/crossfade in isolation. Set back to None for
# the normal full 8-group rotation.
TEST_ONLY_GROUP = None

# 8 poses x 3 art variants each, all regenerations of the same crop/
# framing at the same canvas size per group (the original 941x1672-canvas
# v1 art was dropped — different aspect ratio and shading from the other
# three, and re-cropping/color-matching it in place was more fragile than
# just not using it). Pixmaps are scaled to fit the window individually at
# paint time (see paintEvent).
if TEST_ONLY_GROUP is not None:
    POSES = [f"pose_{TEST_ONLY_GROUP:02d}_v{v}.png" for v in range(1, 4)]
else:
    POSES = [f"pose_{g:02d}_v{v}.png" for g in range(1, 9) for v in range(1, 4)]

# The default scale-to-fit-the-window logic (see _draw_pose) sizes each
# pose independently off its own canvas, which isn't the same as sizing
# Lumi's actual body consistently — a pose whose art has more empty
# canvas around the dog renders smaller than one cropped tight, even
# though she should look the same size. These multipliers correct that
# per pose group, derived by measuring each pose's dog silhouette height
# via its alpha channel (not canvas size) and scaling up to match a
# reference pose in the same group of poses (sitting: 1 and 3 scaled up
# to match 7's height). Verified the scaled-up canvas doesn't clip the
# visible dog against the window edges before committing these numbers.
GROUP_SCALE_MULTIPLIER = {
    1: 1.1796,
    3: 1.1865,
}

# Window is just a bounding box now; each pose is scaled to fit inside it
# (preserving its own aspect ratio) rather than stretched to fill it.
WINDOW_WIDTH = 142
WINDOW_HEIGHT = 252

WIGGLE_PERIOD_MS = 2400
WIGGLE_AMPLITUDE_DEG = 5.0
FRAME_INTERVAL_MS = 16  # ~60fps, also drives the crossfade progress

# How long a variant is held before starting the next crossfade — picked
# fresh each time from these three so the pacing doesn't feel metronomic
# — and how long that crossfade itself takes.
VARIANT_HOLD_CHOICES_MS = (500, 750, 1000)
TRANSITION_MS = 220

# Random interval before *requesting* a jump to a different pose group;
# the jump itself only happens once the current pose finishes its v3 (see
# _pending_group / _advance_variant) so it never cuts a loop short.
GROUP_SWAP_MIN_MS = 3500
GROUP_SWAP_MAX_MS = 7000

# Pose 8 (sleeping) is reserved for idle — never picked by the random
# group-swap above, only entered/left via _check_idle. While asleep the
# window itself grows to nearly fill the screen (still fit-to-aspect, never
# stretched/distorted) and recenters, instead of staying pinned small in
# the corner — swapped back the moment she wakes.
SLEEP_GROUP = 8
NORMAL_GROUPS = tuple(g for g in range(1, 9) if g != SLEEP_GROUP)
IDLE_POLL_MS = 1000
IDLE_THRESHOLD_MS = 20_000
# Fit-to-aspect within 100% of the screen (never distorted/stretched).
# 150% bigger was tried and rejected — the portrait art vs. landscape
# screen mismatch meant it overshot the screen edges top/bottom on any
# monitor, not just this sandbox's small one.
SLEEP_SCREEN_FRACTION = 1.0

BLINK_CYCLE_MS = 4000
BLINK_SHOW_AT_MS = 3760  # 94% into the cycle
BLINK_HIDE_AT_MS = 3880  # 97% into the cycle
EYE_COLOR = (75, 66, 65)

# The poses are genuinely different photos (standing, sitting, lying
# down, ...), not near-identical crops of one shot, so there's no single
# fixed eye position that works everywhere. Each entry here is a per-
# pose-group, hand-read (left, top, width, height) box in that group's
# native pixel space (read off a pixel grid overlaid on the art) — NOT a
# fraction, since groups don't share a canvas size; paintEvent scales it
# using the actual loaded pixmap size. Only pose 8 (sleeping, eyes drawn
# closed) has no entry. All 3 variants within a group share these
# coordinates: they're regenerations of the same crop/framing at the same
# canvas size, verified by rendering the overlay onto each one before
# committing to this table.
_EYES = {
    "01": {"left": (415, 295, 95, 75), "right": (665, 345, 88, 72)},
    "02": {"left": (430, 595, 95, 78), "right": (850, 660, 100, 82)},
    "03": {"left": (435, 240, 90, 68), "right": (625, 305, 90, 68)},
    "04": {"left": (335, 295, 90, 68), "right": (585, 375, 80, 68)},
    "05": {"left": (415, 385, 90, 68), "right": (695, 425, 90, 68)},
    "06": {"left": (390, 325, 90, 68), "right": (630, 390, 85, 68)},
    "07": {"left": (345, 345, 90, 68), "right": (605, 395, 80, 68)},
}
EYE_OVERLAYS = {}
for _group, _eyes in _EYES.items():
    for _v in (1, 2, 3):
        EYE_OVERLAYS[f"pose_{_group}_v{_v}.png"] = _eyes


def _parse_pose(name):
    # "pose_01_v2.png" -> (1, 2)
    _, group, variant = name[:-len(".png")].split("_")
    return int(group), int(variant[1:])


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _system_idle_ms():
    # Milliseconds since the last mouse OR keyboard input, system-wide —
    # not just input over this tiny window, which is rarely where the
    # cursor actually is. Standard Win32 API, no elevated permissions or
    # global hook needed.
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return ctypes.windll.kernel32.GetTickCount() - info.dwTime


class LumiWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self._place_bottom_right()

        self._pixmaps = {name: QPixmap(str(ASSETS_DIR / name)) for name in POSES}
        self._current_pose = POSES[0]
        self._angle = 0.0
        self._elapsed_ms = 0
        self._blink_visible = False
        self._wiggle_enabled = False
        self._drag_offset: QPoint | None = None

        # Crossfade state: while _transition_active, paintEvent draws
        # _transition_from at full opacity with _transition_to fading in
        # over it (opacity = _transition_progress, 0..1). _current_pose is
        # only updated once a transition finishes, so it's always the
        # single source of truth for "what pose are we settled on".
        self._transition_active = False
        self._transition_from = None
        self._transition_to = None
        self._transition_progress = 0.0

        # The group to land on once the current pose finishes its v3 —
        # set by _request_group_swap (normal random rotation) or
        # _check_idle (falling asleep / waking up), consumed in
        # _advance_variant. Never acted on mid-loop, which is what used to
        # cause a jarring instant-snap when a swap interrupted a fade.
        self._pending_group = None
        self._is_idle = False
        self._is_sleep_window = False

        # One continuous ~60fps timer drives both the wiggle angle and the
        # crossfade progress, independently of each other — kept separate
        # from the wiggle on/off toggle so disabling wiggle doesn't also
        # freeze pose transitions.
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)
        self._frame_timer.start(FRAME_INTERVAL_MS)

        self._variant_timer = QTimer(self)
        self._variant_timer.setSingleShot(True)
        self._variant_timer.timeout.connect(self._advance_variant)
        self._variant_timer.start(random.choice(VARIANT_HOLD_CHOICES_MS))

        self._group_swap_timer = QTimer(self)
        self._group_swap_timer.setSingleShot(True)
        self._group_swap_timer.timeout.connect(self._request_group_swap)

        self._idle_check_timer = QTimer(self)
        self._idle_check_timer.timeout.connect(self._check_idle)

        if TEST_ONLY_GROUP is None:
            self._schedule_group_swap()
            self._idle_check_timer.start(IDLE_POLL_MS)

        self._blink_cycle_timer = QTimer(self)
        self._blink_cycle_timer.timeout.connect(self._start_blink_cycle)
        self._blink_cycle_timer.start(BLINK_CYCLE_MS)
        self._start_blink_cycle()

    def _place_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - WINDOW_WIDTH
        y = screen.y() + screen.height() - WINDOW_HEIGHT
        self.move(x, y)

    def _set_sleep_window(self, enable):
        if enable == self._is_sleep_window:
            return
        self._is_sleep_window = enable
        if enable:
            screen = QApplication.primaryScreen().availableGeometry()
            max_w = screen.width() * SLEEP_SCREEN_FRACTION
            max_h = screen.height() * SLEEP_SCREEN_FRACTION
            # All 3 sleep-group variants share one canvas size, so any of
            # them gives the right aspect ratio to fit-to-screen with.
            pixmap = self._pixmaps[f"pose_{SLEEP_GROUP:02d}_v1.png"]
            scale = min(max_w / pixmap.width(), max_h / pixmap.height())
            w = round(pixmap.width() * scale)
            h = round(pixmap.height() * scale)
            self.setFixedSize(w, h)
            x = screen.x() + (screen.width() - w) // 2
            y = screen.y() + (screen.height() - h) // 2
            self.move(x, y)
        else:
            self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
            self._place_bottom_right()

    def _on_frame_tick(self):
        if self._wiggle_enabled:
            self._elapsed_ms = (self._elapsed_ms + FRAME_INTERVAL_MS) % WIGGLE_PERIOD_MS
            phase = self._elapsed_ms / WIGGLE_PERIOD_MS
            self._angle = WIGGLE_AMPLITUDE_DEG * math.sin(2 * math.pi * phase)
        if self._transition_active:
            self._transition_progress += FRAME_INTERVAL_MS / TRANSITION_MS
            if self._transition_progress >= 1.0:
                self._finish_transition()
        self.update()

    def _set_wiggle_enabled(self, enabled):
        self._wiggle_enabled = enabled
        if not enabled:
            self._angle = 0.0
            self._elapsed_ms = 0
            self.update()

    def _start_transition(self, target_pose):
        if target_pose == self._current_pose:
            return
        if self._transition_active:
            # A transition was already in flight (e.g. the group-swap timer
            # and the variant timer landed close together) — snap it to
            # its target instantly rather than blending three images.
            self._finish_transition()
            if target_pose == self._current_pose:
                return
        self._transition_from = self._current_pose
        self._transition_to = target_pose
        self._transition_progress = 0.0
        self._transition_active = True

    def _finish_transition(self):
        self._current_pose = self._transition_to
        self._transition_active = False
        self._transition_from = None
        self._transition_to = None
        self._transition_progress = 0.0
        # Grow to the big centered sleep window right as she settles into
        # pose 8 — not mid-fade, so the just-finished crossfade itself
        # always happens at one consistent window size.
        group, _variant = _parse_pose(self._current_pose)
        if group == SLEEP_GROUP:
            self._set_sleep_window(True)

    def _advance_variant(self):
        group, variant = _parse_pose(self._current_pose)
        # Only ever act on a pending group change once the current pose has
        # shown its last variant — never mid-loop.
        if variant == 3 and self._pending_group is not None:
            target_group = self._pending_group
            self._pending_group = None
            if target_group != SLEEP_GROUP:
                # Waking up (or a normal swap while already awake, a no-op
                # here) — shrink back to the small corner window *before*
                # the crossfade starts, so that fade never happens mid-resize.
                self._set_sleep_window(False)
            self._start_transition(f"pose_{target_group:02d}_v1.png")
        else:
            next_variant = variant % 3 + 1
            self._start_transition(f"pose_{group:02d}_v{next_variant}.png")
        self._variant_timer.start(random.choice(VARIANT_HOLD_CHOICES_MS))

    def _schedule_group_swap(self):
        self._group_swap_timer.start(random.randint(GROUP_SWAP_MIN_MS, GROUP_SWAP_MAX_MS))

    def _request_group_swap(self):
        # While asleep, the idle check owns _pending_group; ignore normal
        # rotation requests until she wakes up.
        if not self._is_idle:
            group, _variant = _parse_pose(self._current_pose)
            self._pending_group = random.choice([g for g in NORMAL_GROUPS if g != group])
        self._schedule_group_swap()

    def _check_idle(self):
        idle_ms = _system_idle_ms()
        if not self._is_idle and idle_ms >= IDLE_THRESHOLD_MS:
            self._is_idle = True
            self._pending_group = SLEEP_GROUP
        elif self._is_idle and idle_ms < IDLE_THRESHOLD_MS:
            self._is_idle = False
            self._pending_group = random.choice(NORMAL_GROUPS)

    def _start_blink_cycle(self):
        QTimer.singleShot(BLINK_SHOW_AT_MS, self._show_blink)
        QTimer.singleShot(BLINK_HIDE_AT_MS, self._hide_blink)

    def _show_blink(self):
        self._blink_visible = True
        self.update()

    def _hide_blink(self):
        self._blink_visible = False
        self.update()

    def _draw_pose(self, painter, pose_name, opacity):
        # Scale to fit inside the window preserving the pixmap's own aspect
        # ratio (variants aren't all the same aspect ratio), bottom-anchored
        # and centered so Lumi's feet stay on the same "ground line" and she
        # doesn't visibly jump sideways when the pose changes. GROUP_SCALE_
        # MULTIPLIER then corrects for poses whose art has more empty canvas
        # around the dog, so her actual body size stays consistent across
        # poses instead of just filling the window equally.
        pixmap = self._pixmaps[pose_name]
        group, _variant = _parse_pose(pose_name)
        scale = min(self.width() / pixmap.width(), self.height() / pixmap.height())
        scale *= GROUP_SCALE_MULTIPLIER.get(group, 1.0)
        draw_w = pixmap.width() * scale
        draw_h = pixmap.height() * scale
        draw_x = (self.width() - draw_w) / 2
        draw_y = self.height() - draw_h
        painter.setOpacity(opacity)
        painter.drawPixmap(QRectF(draw_x, draw_y, draw_w, draw_h), pixmap, QRectF(pixmap.rect()))
        painter.setOpacity(1.0)
        return scale, draw_x, draw_y

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)

        # Rotate around the bottom-center pivot, matching the CSS
        # transform-origin: 50% 100% wiggle in the original prototype.
        painter.translate(self.width() / 2, self.height())
        painter.rotate(self._angle)
        painter.translate(-self.width() / 2, -self.height())

        if self._transition_active:
            # Crossfade: draw the outgoing pose fully opaque, then the
            # incoming one on top with rising opacity — a standard dissolve.
            # No blink here; interpolating two different eye calibrations
            # mid-fade isn't worth the complexity for a ~0.2s transition.
            self._draw_pose(painter, self._transition_from, 1.0)
            self._draw_pose(painter, self._transition_to, self._transition_progress)
        else:
            scale, draw_x, draw_y = self._draw_pose(painter, self._current_pose, 1.0)
            eyes = EYE_OVERLAYS.get(self._current_pose)
            if eyes and self._blink_visible:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(*EYE_COLOR))
                for left, top, w, h in eyes.values():
                    painter.drawEllipse(QRectF(
                        draw_x + left * scale, draw_y + top * scale,
                        w * scale, h * scale,
                    ))

        painter.end()

    # Dragging: no titlebar, so the window is moved by dragging anywhere on it.
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        wiggle_action = QAction("Wiggle", self)
        wiggle_action.setCheckable(True)
        wiggle_action.setChecked(self._wiggle_enabled)
        wiggle_action.toggled.connect(self._set_wiggle_enabled)
        menu.addAction(wiggle_action)
        menu.addSeparator()
        quit_action = QAction("Quit Lumi", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        menu.exec(event.globalPos())


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    widget = LumiWidget()
    widget.show()

    # No titlebar/taskbar entry, so the tray icon is a second way to quit
    # (besides right-clicking Lumi herself) in case the window ever gets
    # dragged somewhere the user can't easily reach to right-click.
    tray_icon = QSystemTrayIcon(QIcon(str(ASSETS_DIR / POSES[0])), app)
    tray_icon.setToolTip("Lumi")
    menu = QMenu()
    quit_action = QAction("Quit Lumi")
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)
    tray_icon.setContextMenu(menu)
    tray_icon.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
