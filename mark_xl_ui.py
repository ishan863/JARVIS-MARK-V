from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from memory.memory_manager import MEMORY_PATH, load_memory, update_memory
from core.security import security


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE = CONFIG_DIR / "api_keys.json"
SETTINGS_FILE = CONFIG_DIR / "mark_xl_settings.json"

DEFAULT_W, DEFAULT_H = 1360, 860
MIN_W, MIN_H = 1120, 720
SIDEBAR_W = 220
RIGHT_RAIL_W = 356
OS_NAME = platform.system()


class C:
    BG = "#030712"
    BG_2 = "#050b16"
    PANEL = "#07101c"
    PANEL_2 = "#081423"
    PANEL_3 = "#0a1728"
    BORDER = "#1c304d"
    BORDER_2 = "#28527d"
    TEXT = "#f4fbff"
    MUTED = "#91a0b5"
    DIM = "#66748a"
    BLUE = "#28d6ff"
    BLUE_2 = "#2f8cff"
    GREEN = "#28e88a"
    YELLOW = "#ffc533"
    PINK = "#ff4f87"
    PURPLE = "#9a66ff"
    RED = "#ff4d68"
    ORANGE = "#ff9d3b"


def qcol(hex_color: str, alpha: int = 255) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def style_panel(radius: int = 16, bg: str = C.PANEL, border: str = C.BORDER) -> str:
    return f"""
        QFrame {{
            background: {bg};
            border: 1px solid {border};
            border-radius: {radius}px;
        }}
        QLabel {{
            background: transparent;
            border: none;
        }}
        QPushButton {{
            border-radius: 10px;
        }}
    """


def button_style(accent: str = C.BLUE, active: bool = False) -> str:
    bg = "#0b2442" if active else C.PANEL_2
    return f"""
        QPushButton {{
            background: {bg};
            color: {C.TEXT};
            border: 1px solid {accent if active else C.BORDER};
            border-radius: 12px;
            padding: 8px 14px;
            text-align: left;
        }}
        QPushButton:hover {{
            background: #0d2036;
            border: 1px solid {accent};
            color: white;
        }}
        QPushButton:pressed {{
            background: #102b4d;
        }}
    """


class SysMetrics:
    def __init__(self):
        self.cpu = 0.0
        self.mem = 0.0
        self.net = 0.0
        self.gpu = -1.0
        self.tmp = -1.0
        self.disk = 0.0
        self.battery = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage(str(Path.home().anchor or Path.home())).percent

        nc = psutil.net_io_counters()
        now = time.time()
        dt = max(0.001, now - self._last_net_t)
        net = ((nc.bytes_sent - self._last_net.bytes_sent) + (nc.bytes_recv - self._last_net.bytes_recv)) / dt
        net = net / (1024 * 1024)
        self._last_net = nc
        self._last_net_t = now

        battery = -1.0
        try:
            b = psutil.sensors_battery()
            if b:
                battery = float(b.percent)
        except Exception:
            pass

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = self._gpu_usage()
            self.tmp = self._temperature()
            self.disk = disk
            self.battery = battery

    def _gpu_usage(self) -> float:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                values = [float(v.strip()) for v in result.stdout.splitlines() if v.strip()]
                if values:
                    return sum(values) / len(values)
        except Exception:
            pass
        return -1.0

    def _temperature(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            for entries in temps.values():
                if entries:
                    return float(entries[0].current)
        except Exception:
            pass
        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
                "disk": self.disk,
                "battery": self.battery,
            }


_metrics = SysMetrics()


class RingMeter(QWidget):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.label = label
        self.color = color
        self.value = 0.0
        self.text = "--"
        self.setFixedSize(92, 58)

    def set_value(self, value: float, text: str):
        self.value = max(0.0, min(100.0, float(value)))
        self.text = text
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(qcol(C.PANEL_2)))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 18, 18)

        rect = QRectF(10, 10, 36, 36)
        painter.setPen(QPen(qcol("#15243b"), 5))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(qcol(self.color), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * (self.value / 100)))

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.setPen(qcol(C.MUTED))
        painter.drawText(QRectF(52, 10, 36, 14), Qt.AlignmentFlag.AlignLeft, self.label)
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        painter.setPen(qcol(C.TEXT))
        painter.drawText(QRectF(52, 27, 38, 20), Qt.AlignmentFlag.AlignLeft, self.text)


class NavButton(QPushButton):
    def __init__(self, label: str, badge: str, parent=None):
        super().__init__(f"{badge}   {label}", parent)
        self.label = label
        self.badge = badge
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.refresh(False)

    def refresh(self, active: bool):
        self.setChecked(active)
        self.setStyleSheet(button_style(C.BLUE_2 if active else C.BORDER, active))


class Panel(QFrame):
    def __init__(self, title: str, subtitle: str | None = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(style_panel())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(12)
        header = QHBoxLayout()
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        title_lbl.setStyleSheet(f"color: {C.TEXT};")
        text_col.addWidget(title_lbl)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setFont(QFont("Segoe UI", 9))
            sub.setStyleSheet(f"color: {C.MUTED};")
            text_col.addWidget(sub)
        header.addLayout(text_col)
        header.addStretch()
        self.layout.addLayout(header)


class StatLine(QWidget):
    def __init__(self, name: str, value: str, color: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(10)
        dot = QLabel()
        dot.setFixedSize(9, 9)
        dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        name_lbl.setStyleSheet(f"color: {C.TEXT};")
        value_lbl = QLabel(value)
        value_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        value_lbl.setStyleSheet(f"color: {color};")
        row.addWidget(dot)
        row.addWidget(name_lbl, stretch=1)
        row.addWidget(value_lbl)


class OrbWidget(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.state = "INITIALISING"
        self.speaking = False
        self.muted = False
        self._tick = 0
        self._rings = [0.0, 120.0, 240.0]
        self._face = self._load_face(face_path)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(16)

    def _load_face(self, path: str) -> QPixmap | None:
        p = Path(path)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.exists():
            px = QPixmap(str(p))
            if not px.isNull():
                return px
        return None

    def _step(self):
        self._tick += 1
        speeds = [1.4, -0.9, 0.55] if self.speaking else [0.45, -0.28, 0.25]
        for index, speed in enumerate(speeds):
            self._rings[index] = (self._rings[index] + speed) % 360
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG_2))

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 - 8
        size = min(w, h)
        orb_r = size * 0.22
        accent = C.RED if self.muted else (C.ORANGE if self.speaking else C.BLUE)

        for i in range(5):
            radius = orb_r * (2.1 - i * 0.23)
            alpha = max(10, 80 - i * 13)
            p.setPen(QPen(qcol(accent, alpha), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        for i, angle in enumerate(self._rings):
            radius = orb_r * (1.75 - i * 0.22)
            p.setPen(QPen(qcol([C.BLUE_2, C.PURPLE, C.BLUE][i], 190), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2), int(angle * 16), int((90 - i * 12) * 16))

        gradient = QRadialGradient(QPointF(cx, cy), orb_r * 1.05)
        gradient.setColorAt(0.0, qcol("#07172a"))
        gradient.setColorAt(0.55, qcol("#0d3b7a"))
        gradient.setColorAt(1.0, qcol(accent))
        p.setPen(QPen(qcol(accent, 230), 3))
        p.setBrush(QBrush(gradient))
        p.drawEllipse(QRectF(cx - orb_r, cy - orb_r, orb_r * 2, orb_r * 2))

        inner = orb_r * 0.64
        p.setPen(QPen(qcol("#8cc9ff", 210), 2))
        p.setBrush(QBrush(qcol(C.BG, 245)))
        p.drawEllipse(QRectF(cx - inner, cy - inner, inner * 2, inner * 2))

        if self._face and not self._face.isNull():
            face_size = int(inner * 1.5)
            scaled = self._face.scaled(face_size, face_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            path = QPainterPath()
            path.addEllipse(QRectF(cx - face_size / 2, cy - face_size / 2, face_size, face_size))
            p.setClipPath(path)
            p.drawPixmap(int(cx - face_size / 2), int(cy - face_size / 2), scaled)
            p.setClipping(False)
        else:
            p.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
            p.setPen(qcol(C.BLUE))
            p.drawText(QRectF(cx - inner, cy - 18, inner * 2, 36), Qt.AlignmentFlag.AlignCenter, "XL")

        wave_y = cy + orb_r * 1.48
        bars = 40
        bar_w = 5
        start_x = cx - (bars * bar_w) / 2
        for i in range(bars):
            if self.muted:
                bar_h = 3
                color = C.RED
            elif self.speaking:
                bar_h = 6 + abs(math.sin(self._tick * 0.18 + i * 0.7)) * 24
                color = C.BLUE if i % 3 else C.PURPLE
            else:
                bar_h = 4 + abs(math.sin(self._tick * 0.06 + i * 0.45)) * 10
                color = C.BLUE_2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcol(color, 210))
            p.drawRoundedRect(QRectF(start_x + i * bar_w, wave_y - bar_h / 2, 3, bar_h), 2, 2)

        state = "Muted" if self.muted else ("Speaking" if self.speaking else self.state.title())
        p.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        p.setPen(qcol(accent))
        p.drawText(QRectF(0, wave_y + 18, w, 26), Qt.AlignmentFlag.AlignCenter, state)


class LogWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {C.MUTED};
                border: none;
                selection-background-color: #103a66;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_2};
                border-radius: 4px;
                min-height: 24px;
            }}
        """)

    def append_log(self, text: str):
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lower = text.lower()
        if lower.startswith("you:"):
            color = C.TEXT
        elif lower.startswith("jarvis:") or lower.startswith("mark"):
            color = C.BLUE
        elif lower.startswith("file:"):
            color = C.GREEN
        elif "err" in lower or "failed" in lower:
            color = C.RED
        else:
            color = C.MUTED
        self.append(f"<span style='color:{color};'>{escaped}</span>")
        self.ensureCursorVisible()


FILE_TYPES = {
    "image": {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"},
    "pdf": {"pdf"},
    "word": {"doc", "docx"},
    "excel": {"xls", "xlsx", "csv", "ods"},
    "code": {"py", "js", "ts", "tsx", "jsx", "html", "css", "json", "md", "sql"},
    "archive": {"zip", "rar", "7z", "tar", "gz"},
    "media": {"mp3", "wav", "mp4", "mov", "mkv"},
}


def _file_category(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    for name, values in FILE_TYPES.items():
        if ext in values:
            return name
    return "file"


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    return f"{size / 1024**3:.1f} GB"


class FileDropZone(QFrame):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(116)
        self._current_file: str | None = None
        self.setStyleSheet(f"""
            QFrame {{
                background: #071423;
                border: 1px dashed {C.BORDER_2};
                border-radius: 14px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self._title = QLabel("Drop files here")
        self._title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {C.TEXT};")
        self._detail = QLabel("PDF, Excel, Word, images, code, CSV")
        self._detail.setFont(QFont("Segoe UI", 9))
        self._detail.setStyleSheet(f"color: {C.MUTED};")
        self._detail.setWordWrap(True)
        layout.addWidget(self._title)
        layout.addWidget(self._detail)
        layout.addStretch()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None
        self._title.setText("Drop files here")
        self._detail.setText("PDF, Excel, Word, images, code, CSV")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if Path(path).is_file():
            self._set_file(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "Select a file for MARK XL", str(Path.home()), "All files (*.*)")
            if path:
                self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        p = Path(path)
        size = _fmt_size(p.stat().st_size)
        cat = _file_category(p).upper()
        self._title.setText(p.name)
        self._detail.setText(f"{cat} - {size} - ready for document intelligence")
        self.file_selected.emit(path)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(3, 7, 18, 246);
                border: 1px solid {C.BORDER_2};
                border-radius: 18px;
            }}
        """)
        self._sel_os = {"Darwin": "mac", "Windows": "windows"}.get(OS_NAME, "linux")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(12)

        title = QLabel("MARK XL INITIALISATION")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        layout.addWidget(title)

        sub = QLabel("Configure the existing Gemini live voice connection.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Segoe UI", 10))
        sub.setStyleSheet(f"color: {C.MUTED}; background: transparent;")
        layout.addWidget(sub)

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("Gemini API key")
        self._key_input.setFixedHeight(42)
        self._key_input.setFont(QFont("Segoe UI", 10))
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 12px;
                padding: 0 14px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.BLUE}; }}
        """)
        layout.addWidget(self._key_input)

        os_row = QHBoxLayout()
        self._os_buttons: dict[str, QPushButton] = {}
        for key, label in [("windows", "Windows"), ("mac", "macOS"), ("linux", "Linux")]:
            btn = QPushButton(label)
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._select_os(k))
            os_row.addWidget(btn)
            self._os_buttons[key] = btn
        layout.addLayout(os_row)
        self._select_os(self._sel_os)

        start = QPushButton("Initialise MARK XL")
        start.setFixedHeight(42)
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        start.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        start.setStyleSheet(button_style(C.BLUE, True))
        start.clicked.connect(self._submit)
        layout.addWidget(start)

    def _select_os(self, key: str):
        self._sel_os = key
        for btn_key, btn in self._os_buttons.items():
            btn.setStyleSheet(button_style(C.GREEN if btn_key == key else C.BORDER, btn_key == key))

    def _submit(self):
        key = self._key_input.text().strip()
        if not (key.startswith("AIzaSy") or key.startswith("AQ.")):
            self._key_input.setStyleSheet(self._key_input.styleSheet() + f"QLineEdit {{ border: 1px solid {C.RED}; }}")
            return
        self.done.emit(key, self._sel_os)


class CommandPalette(QDialog):
    command = pyqtSignal(str)
    navigate = pyqtSignal(str)

    COMMANDS = [
        ("Open browser", "Open Browser"),
        ("Analyze my screen", "Analyze Screen"),
        ("Take a screenshot", "Take Screenshot"),
        ("Start a research workflow", "Research Workflow"),
        ("Summarize the selected file", "File Summary"),
        ("Show memory dashboard", "Memory"),
        ("Show automation dashboard", "Automation"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(False)
        self.setStyleSheet(f"""
            QDialog {{
                background: {C.BG_2};
                border: 1px solid {C.BORDER_2};
                border-radius: 18px;
            }}
            QLabel {{
                color: {C.MUTED};
                background: transparent;
            }}
        """)
        self.setFixedSize(520, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("AI Command Palette")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search commands, apps, workflows...")
        self._input.setFixedHeight(42)
        self._input.setFont(QFont("Segoe UI", 10))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 12px;
                padding: 0 14px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.BLUE}; }}
        """)
        self._input.returnPressed.connect(self._submit_custom)
        layout.addWidget(self._input)

        for command, label in self.COMMANDS:
            btn = QPushButton(label)
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(button_style(C.BLUE))
            btn.clicked.connect(lambda _, c=command, l=label: self._activate(c, l))
            layout.addWidget(btn)
        layout.addStretch()

        hint = QLabel("Shortcut: Ctrl + Space or Ctrl + K")
        hint.setFont(QFont("Segoe UI", 9))
        layout.addWidget(hint)

    def open_at_center(self):
        if self.parent():
            parent = self.parent()
            self.move(
                parent.x() + (parent.width() - self.width()) // 2,
                parent.y() + 92,
            )
        self._input.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def _activate(self, command: str, label: str):
        if label in {"Memory", "Automation"}:
            self.navigate.emit(label)
        else:
            self.command.emit(command)
        self.hide()

    def _submit_custom(self):
        text = self._input.text().strip()
        if text:
            self.command.emit(text)
            self.hide()


class MainWindow(QMainWindow):
    _log_sig = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _input_sig = pyqtSignal(str)
    _output_sig = pyqtSignal(str)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("MARK XL - AI Operating Assistant")
        self.setMinimumSize(MIN_W, MIN_H)
        self.resize(DEFAULT_W, DEFAULT_H)

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - DEFAULT_W) // 2, (geo.height() - DEFAULT_H) // 2)

        self.on_text_command = None
        self._muted = False
        self._ready = self._check_config()
        self._current_file: str | None = None
        self._nav_buttons: dict[str, NavButton] = {}
        self._metric_widgets: dict[str, RingMeter] = {}
        self._activity_count = 0
        self._assistant_command_count = 0
        self._workflow_count = 0
        self._memory_write_count = 0
        self._browser_action_count = 0
        self._vision_action_count = 0
        self._chat_sessions: list[dict] = []
        self._active_chat_index = 0
        self._scheduled_items: list[dict] = []
        self._workflow_history: list[str] = []
        self._settings = self._load_settings()
        self._agent_status_widgets: dict[str, QLabel] = {}
        self._task_widgets: list[dict] = []
        self._memory_timeline_widgets: list[dict] = []
        self._reminder_widgets: list[dict] = []

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar(), stretch=0)
        body.addWidget(self._build_center(), stretch=1)
        body.addWidget(self._build_right_rail(), stretch=0)
        root.addLayout(body, stretch=1)
        root.addWidget(self._build_voice_strip())
        root.addWidget(self._build_command_bar())

        self._palette = CommandPalette(self)
        self._palette.command.connect(lambda text: self._dispatch_command(text, True))
        self._palette.navigate.connect(self._navigate)

        self._log_sig.connect(self._handle_log)
        self._state_sig.connect(self._apply_state)
        self._input_sig.connect(self._update_voice_input)
        self._output_sig.connect(self._update_voice_output)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

        self._metric_timer = QTimer(self)
        self._metric_timer.timeout.connect(self._update_metrics)
        self._metric_timer.start(2000)
        self._update_metrics()
        self._dashboard_timer = QTimer(self)
        self._dashboard_timer.timeout.connect(self._refresh_dashboard_data)
        self._dashboard_timer.start(2500)

        QShortcut(QKeySequence("F4"), self).activated.connect(self._toggle_mute)
        QShortcut(QKeySequence("F11"), self).activated.connect(self._toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+Space"), self).activated.connect(self._palette.open_at_center)
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._palette.open_at_center)

        self._overlay: SetupOverlay | None = None
        if not self._ready:
            self._show_setup()
        else:
            self._apply_state("LISTENING")
            self._handle_log("SYS: MARK XL interface online. Voice pipeline unchanged.")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(76)
        header.setStyleSheet(f"background: {C.BG_2}; border-bottom: 1px solid {C.BORDER};")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(18)

        logo = QLabel("XL")
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        logo.setStyleSheet(f"background: #0b2752; color: {C.BLUE}; border: 1px solid {C.BLUE_2}; border-radius: 22px;")
        layout.addWidget(logo)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("MARK XL")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        sub = QLabel("AI Operating Assistant")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet(f"color: {C.MUTED}; background: transparent;")
        brand.addWidget(title)
        brand.addWidget(sub)
        layout.addLayout(brand)
        layout.addStretch(1)

        search = QLineEdit()
        search.setPlaceholderText("Search anything...")
        search.setFixedSize(330, 38)
        search.setFont(QFont("Segoe UI", 10))
        search.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 19px;
                padding: 0 18px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.BLUE}; }}
        """)
        search.returnPressed.connect(lambda: self._dispatch_command(search.text(), True))
        layout.addWidget(search)

        shortcut = QLabel("Ctrl + K")
        shortcut.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shortcut.setFixedSize(72, 28)
        shortcut.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        shortcut.setStyleSheet(f"color: {C.MUTED}; border: 1px solid {C.BORDER}; border-radius: 12px; background: {C.PANEL};")
        layout.addWidget(shortcut)

        self._state_lbl = QLabel("INITIALISING")
        self._state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_lbl.setFixedSize(118, 30)
        self._state_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self._state_lbl.setStyleSheet(f"color: {C.YELLOW}; background: #111722; border: 1px solid {C.BORDER}; border-radius: 14px;")
        layout.addWidget(self._state_lbl)

        self._clock_lbl = QLabel("00:00")
        self._clock_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        layout.addWidget(self._clock_lbl)
        return header

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setFixedWidth(SIDEBAR_W)
        side.setStyleSheet(f"background: {C.BG_2}; border-right: 1px solid {C.BORDER};")
        layout = QVBoxLayout(side)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(8)

        nav = [
            ("Home", "HM"),
            ("Chats", "CH"),
            ("Agents", "AG"),
            ("Automation", "AU"),
            ("Browser", "BR"),
            ("Files", "FD"),
            ("Memory", "ME"),
            ("Vision", "VI"),
            ("Workflows", "WF"),
            ("Analytics", "AN"),
            ("Remote", "RC"),
            ("Settings", "ST"),
        ]
        for name, badge in nav:
            btn = NavButton(name, badge)
            btn.clicked.connect(lambda _, n=name: self._navigate(n))
            self._nav_buttons[name] = btn
            layout.addWidget(btn)
        layout.addStretch()

        pro = QFrame()
        pro.setStyleSheet(style_panel(14, "#071423", "#132d4e"))
        pro_lay = QVBoxLayout(pro)
        pro_lay.setContentsMargins(16, 14, 16, 14)
        pro_lay.setSpacing(4)
        pro_title = QLabel("MARK XL PRO")
        pro_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        pro_title.setStyleSheet(f"color: {C.TEXT};")
        pro_sub = QLabel("Ultimate Edition\nv2.0.0")
        pro_sub.setFont(QFont("Segoe UI", 9))
        pro_sub.setStyleSheet(f"color: {C.BLUE};")
        pro_lay.addWidget(pro_title)
        pro_lay.addWidget(pro_sub)
        layout.addWidget(pro)

        user = QFrame()
        user.setStyleSheet(style_panel(14))
        user_lay = QHBoxLayout(user)
        user_lay.setContentsMargins(14, 12, 14, 12)
        avatar = QLabel("F")
        avatar.setFixedSize(42, 42)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(f"background: #17333b; color: {C.GREEN}; border-radius: 21px;")
        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        name = QLabel("FATIH")
        name.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        name.setStyleSheet(f"color: {C.TEXT};")
        role = QLabel("Pro User")
        role.setFont(QFont("Segoe UI", 9))
        role.setStyleSheet(f"color: {C.MUTED};")
        name_col.addWidget(name)
        name_col.addWidget(role)
        user_lay.addWidget(avatar)
        user_lay.addLayout(name_col)
        layout.addWidget(user)
        return side

    def _build_center(self) -> QWidget:
        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        self._pages["Home"] = self._home_page()
        self._pages["Chats"] = self._chats_page()
        self._pages["Agents"] = self._agents_page()
        self._pages["Automation"] = self._automation_page()
        self._pages["Browser"] = self._browser_page()
        self._pages["Files"] = self._files_page()
        self._pages["Memory"] = self._memory_page()
        self._pages["Vision"] = self._vision_page()
        self._pages["Workflows"] = self._workflows_page()
        self._pages["Analytics"] = self._analytics_page()
        self._pages["Remote"] = self._remote_page()
        self._pages["Settings"] = self._settings_page()
        for page in self._pages.values():
            self._stack.addWidget(page)
        self._navigate("Home")
        return self._stack

    def _home_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(16)

        top = QHBoxLayout()
        greet_col = QVBoxLayout()
        greet_col.setSpacing(4)
        self._greeting_lbl = QLabel("Good Evening, Fatih")
        self._greeting_lbl.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        self._greeting_lbl.setStyleSheet(f"color: {C.TEXT};")
        prompt = QLabel("I'm MARK XL, your AI operating assistant. How can I help you today?")
        prompt.setFont(QFont("Segoe UI", 11))
        prompt.setStyleSheet(f"color: {C.MUTED};")
        greet_col.addWidget(self._greeting_lbl)
        greet_col.addWidget(prompt)
        top.addLayout(greet_col)
        top.addStretch()
        for key, color in [("CPU", C.BLUE), ("RAM", C.GREEN), ("GPU", C.PURPLE), ("DISK", C.YELLOW)]:
            meter = RingMeter(key, color)
            self._metric_widgets[key] = meter
            top.addWidget(meter)
        layout.addLayout(top)

        action_row = QHBoxLayout()
        for label, command, accent in [
            ("New Chat", "Start a new chat", C.BLUE),
            ("Screenshot", "Take a screenshot", C.PURPLE),
            ("Voice Command", "Listen for my voice command", C.BLUE_2),
            ("Run Workflow", "Run my default workflow", C.PURPLE),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            btn.setStyleSheet(button_style(accent))
            btn.clicked.connect(lambda _, c=command: self._dispatch_command(c, True))
            action_row.addWidget(btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(self._agents_panel(), 0, 0)
        grid.addWidget(self._tasks_panel(), 0, 1)
        grid.addWidget(self._system_panel(), 0, 2)
        grid.addWidget(self._memory_panel(), 1, 0)
        grid.addWidget(self._orb_panel(), 1, 1)
        grid.addWidget(self._quick_actions_panel(), 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _agents_panel(self) -> Panel:
        panel = Panel("AI Agents")
        self._agent_status_widgets = {}
        for name, state, color in [
            ("Main Assistant", "Online", C.GREEN),
            ("Vision Agent", "Online", C.GREEN),
            ("Browser Agent", "Working", C.YELLOW),
            ("Automation Agent", "Working", C.YELLOW),
            ("Memory Agent", "Online", C.GREEN),
            ("File Agent", "Idle", C.DIM),
            ("Coding Agent", "Idle", C.DIM),
        ]:
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            name_lbl.setStyleSheet(f"color: {C.TEXT};")
            status_lbl = QLabel(state)
            status_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            status_lbl.setStyleSheet(f"color: {color};")
            row.addWidget(dot)
            row.addWidget(name_lbl, stretch=1)
            row.addWidget(status_lbl)
            panel.layout.addLayout(row)
            self._agent_status_widgets[name] = status_lbl
        return panel

    def _tasks_panel(self) -> Panel:
        panel = Panel("Today's Overview", "5 tasks")
        self._task_widgets = []
        for name, state, color, time_text in [
            ("Morning Briefing", "Completed", C.GREEN, "08:00"),
            ("DPR Daily Report", "Completed", C.GREEN, "10:30"),
            ("Outage Data Analysis", "In Progress", C.YELLOW, "14:15"),
            ("Email Summary", "Pending", C.PINK, "16:00"),
            ("Research: AI Agents", "Pending", C.PINK, "18:00"),
        ]:
            row = QHBoxLayout()
            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            name_lbl.setStyleSheet(f"color: {C.TEXT};")
            state_lbl = QLabel(state)
            state_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            state_lbl.setStyleSheet(f"color: {color};")
            time_lbl = QLabel(time_text)
            time_lbl.setFont(QFont("Segoe UI", 9))
            time_lbl.setStyleSheet(f"color: {C.MUTED};")
            row.addWidget(name_lbl, stretch=1)
            row.addWidget(state_lbl)
            row.addWidget(time_lbl)
            panel.layout.addLayout(row)
            self._task_widgets.append(
                {"name": name, "name_lbl": name_lbl, "state_lbl": state_lbl, "time_lbl": time_lbl}
            )
        return panel

    def _system_panel(self) -> Panel:
        panel = Panel("System Monitor")
        self._health_value = QLabel("87%")
        self._health_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._health_value.setFont(QFont("Segoe UI", 34, QFont.Weight.Bold))
        self._health_value.setStyleSheet(f"color: {C.TEXT}; background: #081423; border: 1px solid {C.BORDER_2}; border-radius: 64px;")
        self._health_value.setFixedSize(128, 128)
        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(self._health_value)
        center.addStretch()
        panel.layout.addLayout(center)
        self._health_caption = QLabel("Everything is running smooth.")
        self._health_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._health_caption.setFont(QFont("Segoe UI", 10))
        self._health_caption.setStyleSheet(f"color: {C.MUTED};")
        panel.layout.addWidget(self._health_caption)
        return panel

    def _memory_panel(self) -> Panel:
        panel = Panel("Memory Timeline")
        self._memory_timeline_widgets = []
        for title, detail, color in [
            ("Preference stored", "Dark theme enabled", C.BLUE),
            ("Project memory updated", "DPR System Automation", C.YELLOW),
            ("Important context stored", "Outage report structure", C.PINK),
            ("New conversation summary", "Voice conversation saved", C.PURPLE),
        ]:
            block = QVBoxLayout()
            head = QLabel(title)
            head.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            head.setStyleSheet(f"color: {color};")
            sub = QLabel(detail)
            sub.setFont(QFont("Segoe UI", 9))
            sub.setStyleSheet(f"color: {C.MUTED};")
            block.addWidget(head)
            block.addWidget(sub)
            panel.layout.addLayout(block)
            self._memory_timeline_widgets.append({"head": head, "sub": sub, "base_color": color})
        return panel

    def _orb_panel(self) -> Panel:
        panel = Panel("Voice Core", "Existing voice pipeline preserved")
        panel.layout.setSpacing(10)
        self.hud = OrbWidget("face.png")
        self.hud.setMinimumHeight(360)
        panel.layout.addWidget(self.hud, stretch=1)
        dock = QFrame()
        dock.setStyleSheet(style_panel(22, C.PANEL_2, C.BORDER))
        row = QHBoxLayout(dock)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        for label, command in [
            ("Keyboard", "Open keyboard command mode"),
            ("Globe", "Open browser"),
            ("Mute", "Toggle microphone"),
            ("Close", "Stop current task"),
        ]:
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(button_style(C.BLUE))
            if label == "Mute":
                b.clicked.connect(self._toggle_mute)
            else:
                b.clicked.connect(lambda _, c=command: self._dispatch_command(c, True))
            row.addWidget(b)
        panel.layout.addWidget(dock)
        return panel

    def _quick_actions_panel(self) -> Panel:
        panel = Panel("Quick Actions")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        actions = [
            ("Open Browser", "Open browser"),
            ("Screenshot", "Take a screenshot"),
            ("Analyze Screen", "Analyze my screen"),
            ("Clipboard", "Read clipboard"),
            ("Smart Search", "Search the web"),
            ("Workflow", "Run my default workflow"),
        ]
        for index, (label, command) in enumerate(actions):
            btn = QPushButton(label)
            btn.setMinimumHeight(64)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            btn.setStyleSheet(button_style(C.BLUE if index % 2 == 0 else C.PURPLE))
            btn.clicked.connect(lambda _, c=command: self._dispatch_command(c, True))
            grid.addWidget(btn, index // 2, index % 2)
        panel.layout.addLayout(grid)
        return panel

    def _chats_page(self) -> QScrollArea:
        self._seed_chats()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Multi Chat Workspace")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        row = QHBoxLayout()
        left = Panel("Conversations", "Pinned, folders, and agent lanes")
        self._chat_search = QLineEdit()
        self._chat_search.setPlaceholderText("Search chat title or agent...")
        self._chat_search.setFixedHeight(36)
        self._chat_search.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 10px; padding: 0 10px; }}")
        self._chat_search.textChanged.connect(self._refresh_chat_list)
        left.layout.addWidget(self._chat_search)

        self._chat_list = QListWidget()
        self._chat_list.setStyleSheet(f"""
            QListWidget {{
                background: {C.PANEL_2};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 12px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px 6px;
                border-bottom: 1px solid #14233a;
            }}
            QListWidget::item:selected {{
                background: #123258;
                color: {C.TEXT};
                border-radius: 8px;
            }}
        """)
        self._chat_list.currentRowChanged.connect(self._on_chat_changed)
        left.layout.addWidget(self._chat_list, stretch=1)

        controls = QHBoxLayout()
        for label, cb in [
            ("New", self._create_chat_session),
            ("Pin", self._toggle_pin_chat),
            ("Delete", self._delete_chat_session),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(button_style(C.BLUE))
            btn.clicked.connect(cb)
            controls.addWidget(btn)
        left.layout.addLayout(controls)
        row.addWidget(left, stretch=1)

        right = Panel("Chat Thread", "Agent-specific context is preserved per session")
        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        self._chat_view.setFont(QFont("Consolas", 10))
        self._chat_view.setStyleSheet(f"QTextEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 12px; padding: 8px; }}")
        right.layout.addWidget(self._chat_view, stretch=1)

        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("Send message to active chat...")
        self._chat_input.setFixedHeight(38)
        self._chat_input.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 10px; padding: 0 12px; }}")
        self._chat_input.returnPressed.connect(self._send_chat_message)
        right.layout.addWidget(self._chat_input)

        send = QPushButton("Send To Assistant")
        send.setFixedHeight(36)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(button_style(C.BLUE, True))
        send.clicked.connect(self._send_chat_message)
        right.layout.addWidget(send)
        row.addWidget(right, stretch=2)
        layout.addLayout(row)

        self._refresh_chat_list()
        scroll.setWidget(page)
        return scroll

    def _seed_chats(self):
        if self._chat_sessions:
            return
        self._chat_sessions = [
            {"title": "MARK XL Core", "agent": "Main", "pinned": True, "messages": ["System: Main assistant planning lane online."]},
            {"title": "Vision Debug", "agent": "Vision", "pinned": False, "messages": ["System: Vision OCR and screenshot lane ready."]},
            {"title": "Browser Tasks", "agent": "Browser", "pinned": False, "messages": ["System: Browser automation lane ready."]},
        ]
        self._active_chat_index = 0

    def _refresh_chat_list(self):
        if not hasattr(self, "_chat_list"):
            return
        query = self._chat_search.text().strip().lower() if hasattr(self, "_chat_search") else ""
        items: list[tuple[int, dict]] = list(enumerate(self._chat_sessions))
        items.sort(key=lambda x: (not x[1]["pinned"], x[1]["title"].lower()))
        self._chat_list.clear()
        self._chat_visible_index_map: list[int] = []
        for real_idx, item in items:
            if query and query not in item["title"].lower() and query not in item["agent"].lower():
                continue
            star = "[PIN]" if item["pinned"] else "     "
            lw = QListWidgetItem(f"{star} {item['title']} ({item['agent']})")
            self._chat_list.addItem(lw)
            self._chat_visible_index_map.append(real_idx)
        if self._chat_visible_index_map:
            target = 0
            for idx, real_idx in enumerate(self._chat_visible_index_map):
                if real_idx == self._active_chat_index:
                    target = idx
                    break
            self._chat_list.setCurrentRow(target)
        else:
            self._chat_view.setPlainText("No chats match the current search.")

    def _on_chat_changed(self, row: int):
        if row < 0 or not hasattr(self, "_chat_visible_index_map") or row >= len(self._chat_visible_index_map):
            return
        self._active_chat_index = self._chat_visible_index_map[row]
        self._render_active_chat()

    def _render_active_chat(self):
        if not self._chat_sessions:
            self._chat_view.setPlainText("No active chat.")
            return
        session = self._chat_sessions[self._active_chat_index]
        text = [f"{session['title']} [{session['agent']}]"]
        text.append("-" * 40)
        text.extend(session["messages"][-80:])
        self._chat_view.setPlainText("\n".join(text))
        self._chat_view.verticalScrollBar().setValue(self._chat_view.verticalScrollBar().maximum())

    def _create_chat_session(self):
        count = len(self._chat_sessions) + 1
        self._chat_sessions.append(
            {"title": f"Chat {count}", "agent": "Main", "pinned": False, "messages": ["System: New chat created."]}
        )
        self._active_chat_index = len(self._chat_sessions) - 1
        self._refresh_chat_list()
        self._handle_log("SYS: New chat workspace created.")

    def _toggle_pin_chat(self):
        if not self._chat_sessions:
            return
        session = self._chat_sessions[self._active_chat_index]
        session["pinned"] = not session["pinned"]
        self._refresh_chat_list()
        self._handle_log(f"SYS: {'Pinned' if session['pinned'] else 'Unpinned'} '{session['title']}'.")

    def _delete_chat_session(self):
        if len(self._chat_sessions) <= 1:
            self._handle_log("SYS: At least one chat must remain.")
            return
        removed = self._chat_sessions.pop(self._active_chat_index)
        self._active_chat_index = max(0, self._active_chat_index - 1)
        self._refresh_chat_list()
        self._handle_log(f"SYS: Deleted chat '{removed['title']}'.")

    def _send_chat_message(self):
        text = self._chat_input.text().strip()
        if not text or not self._chat_sessions:
            return
        self._chat_input.clear()
        session = self._chat_sessions[self._active_chat_index]
        session["messages"].append(f"You: {text}")
        wrapped = f"[CHAT:{session['title']}|AGENT:{session['agent']}] {text}"
        self._dispatch_command(wrapped, False)
        session["messages"].append("System: Sent to assistant command router.")
        self._render_active_chat()

    def _agents_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Agent Command Center")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        panel = Panel("Live Agent Controls", "Launch direct tasks through the existing tool router")
        self._agent_status_labels: dict[str, QLabel] = {}
        for name, desc, cmd in [
            ("Main Assistant", "Conversation, planning, and routing", "Summarize current goals and next actions"),
            ("Vision Agent", "Screen and webcam understanding", "Analyze my screen and explain key UI elements"),
            ("Browser Agent", "Navigation, forms, and extraction", "Open browser and search project dashboard health"),
            ("Coding Agent", "Code generation and debugging", "Inspect current codebase and suggest one improvement"),
            ("File Agent", "Document understanding and extraction", "Check loaded file and summarize actionable data"),
            ("Memory Agent", "Long-term and project memory", "Remember this project as MARK XL upgrade"),
            ("Automation Agent", "Workflow execution and scheduling", "Create a morning briefing workflow"),
            ("Research Agent", "Web search and synthesis", "Research best practices for desktop AI assistants"),
        ]:
            row = QHBoxLayout()
            left = QVBoxLayout()
            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            name_lbl.setStyleSheet(f"color: {C.TEXT};")
            desc_lbl = QLabel(desc)
            desc_lbl.setFont(QFont("Segoe UI", 9))
            desc_lbl.setStyleSheet(f"color: {C.MUTED};")
            left.addWidget(name_lbl)
            left.addWidget(desc_lbl)
            row.addLayout(left, stretch=1)
            status = QLabel("Ready")
            status.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            status.setStyleSheet(f"color: {C.GREEN};")
            self._agent_status_labels[name] = status
            row.addWidget(status)
            run = QPushButton("Run")
            run.setFixedHeight(32)
            run.setCursor(Qt.CursorShape.PointingHandCursor)
            run.setStyleSheet(button_style(C.BLUE))
            run.clicked.connect(lambda _, n=name, c=cmd: self._run_agent_action(n, c))
            row.addWidget(run)
            panel.layout.addLayout(row)
        layout.addWidget(panel)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _run_agent_action(self, agent_name: str, command: str):
        self._agent_status_labels[agent_name].setText("Working")
        self._agent_status_labels[agent_name].setStyleSheet(f"color: {C.YELLOW};")
        self._dispatch_command(f"[AGENT:{agent_name}] {command}", True)
        QTimer.singleShot(900, lambda: self._mark_agent_ready(agent_name))

    def _mark_agent_ready(self, agent_name: str):
        if agent_name not in self._agent_status_labels:
            return
        self._agent_status_labels[agent_name].setText("Ready")
        self._agent_status_labels[agent_name].setStyleSheet(f"color: {C.GREEN};")

    def _automation_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Automation Ecosystem")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        templates = Panel("Run Workflow Templates")
        for wf_name, wf_cmd in [
            ("Morning Briefing", "Prepare morning briefing with weather, tasks, and news"),
            ("DPR Daily Report", "Generate DPR daily report summary"),
            ("Attendance Automation", "Compile attendance status and export report"),
            ("Research Workflow", "Research requested topic and save concise notes"),
        ]:
            row = QHBoxLayout()
            label = QLabel(wf_name)
            label.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            label.setStyleSheet(f"color: {C.TEXT};")
            row.addWidget(label, stretch=1)
            run = QPushButton("Run Now")
            run.setFixedHeight(32)
            run.setCursor(Qt.CursorShape.PointingHandCursor)
            run.setStyleSheet(button_style(C.BLUE))
            run.clicked.connect(lambda _, n=wf_name, c=wf_cmd: self._run_workflow_template(n, c))
            row.addWidget(run)
            templates.layout.addLayout(row)
        layout.addWidget(templates)

        scheduler = Panel("Schedule Workflow")
        form = QHBoxLayout()
        self._sched_workflow_name = QLineEdit()
        self._sched_workflow_name.setPlaceholderText("Workflow name")
        self._sched_workflow_name.setFixedHeight(34)
        self._sched_workflow_name.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        form.addWidget(self._sched_workflow_name, stretch=2)
        self._sched_delay_min = QSpinBox()
        self._sched_delay_min.setRange(1, 240)
        self._sched_delay_min.setValue(10)
        self._sched_delay_min.setFixedHeight(34)
        self._sched_delay_min.setStyleSheet(f"QSpinBox {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 8px; }}")
        form.addWidget(self._sched_delay_min)
        add_btn = QPushButton("Schedule")
        add_btn.setFixedHeight(34)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(button_style(C.PURPLE))
        add_btn.clicked.connect(self._schedule_workflow)
        form.addWidget(add_btn)
        scheduler.layout.addLayout(form)
        self._sched_list = QListWidget()
        self._sched_list.setStyleSheet(f"QListWidget {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 10px; }}")
        scheduler.layout.addWidget(self._sched_list)
        layout.addWidget(scheduler)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _run_workflow_template(self, name: str, command: str):
        self._workflow_history.append(f"{time.strftime('%H:%M:%S')} - {name}")
        self._dispatch_command(f"[WORKFLOW:{name}] {command}", True)

    def _schedule_workflow(self):
        name = self._sched_workflow_name.text().strip() or "Custom Workflow"
        minutes = int(self._sched_delay_min.value())
        self._sched_workflow_name.clear()
        run_at = time.time() + (minutes * 60)
        item = {"name": name, "minutes": minutes, "run_at": run_at}
        self._scheduled_items.append(item)
        self._refresh_schedule_list()
        QTimer.singleShot(minutes * 60 * 1000, lambda data=item: self._run_scheduled_item(data))
        self._handle_log(f"SYS: Scheduled '{name}' in {minutes} minute(s).")

    def _refresh_schedule_list(self):
        if not hasattr(self, "_sched_list"):
            return
        self._sched_list.clear()
        now = time.time()
        for item in self._scheduled_items[-50:]:
            remaining = max(0, int((item["run_at"] - now) / 60))
            self._sched_list.addItem(f"{item['name']} - starts in ~{remaining} min")

    def _run_scheduled_item(self, item: dict):
        self._run_workflow_template(item["name"], f"Run scheduled workflow: {item['name']}")
        self._scheduled_items = [x for x in self._scheduled_items if x is not item]
        self._refresh_schedule_list()

    def _browser_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Browser Intelligence")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        panel = Panel("AI Browser Mode")
        row1 = QHBoxLayout()
        self._browser_url = QLineEdit()
        self._browser_url.setPlaceholderText("https://example.com")
        self._browser_url.setFixedHeight(36)
        self._browser_url.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        row1.addWidget(self._browser_url, stretch=2)
        go = QPushButton("Open URL")
        go.setFixedHeight(36)
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setStyleSheet(button_style(C.BLUE))
        go.clicked.connect(self._run_browser_open)
        row1.addWidget(go)
        panel.layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._browser_query = QLineEdit()
        self._browser_query.setPlaceholderText("Search query")
        self._browser_query.setFixedHeight(36)
        self._browser_query.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        row2.addWidget(self._browser_query, stretch=2)
        search = QPushButton("Search")
        search.setFixedHeight(36)
        search.setCursor(Qt.CursorShape.PointingHandCursor)
        search.setStyleSheet(button_style(C.PURPLE))
        search.clicked.connect(self._run_browser_search)
        row2.addWidget(search)
        panel.layout.addLayout(row2)

        action_row = QHBoxLayout()
        for label, command in [
            ("Summarize Page", "Summarize current browser page"),
            ("Extract Data", "Extract structured data from current page"),
            ("Take Browser Screenshot", "Take screenshot of current browser tab"),
            ("List Browser Sessions", "List active browser sessions"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(button_style(C.BLUE_2))
            btn.clicked.connect(lambda _, c=command: self._run_browser_command(c))
            action_row.addWidget(btn)
        panel.layout.addLayout(action_row)
        layout.addWidget(panel)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _run_browser_open(self):
        url = self._browser_url.text().strip()
        if not url:
            self._handle_log("SYS: Enter a URL first.")
            return
        self._run_browser_command(f"Open {url} in browser")

    def _run_browser_search(self):
        query = self._browser_query.text().strip()
        if not query:
            self._handle_log("SYS: Enter a search query first.")
            return
        self._run_browser_command(f"Search the web for: {query}")

    def _run_browser_command(self, command: str):
        self._dispatch_command(f"[BROWSER] {command}", True)

    def _memory_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Memory Engine")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        add_panel = Panel("Write Memory")
        form = QHBoxLayout()
        self._mem_category = QComboBox()
        self._mem_category.addItems(["identity", "preferences", "projects", "relationships", "wishes", "notes"])
        self._mem_category.setFixedHeight(34)
        self._mem_category.setStyleSheet(f"QComboBox {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        form.addWidget(self._mem_category)
        self._mem_key = QLineEdit()
        self._mem_key.setPlaceholderText("key")
        self._mem_key.setFixedHeight(34)
        self._mem_key.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        form.addWidget(self._mem_key)
        self._mem_value = QLineEdit()
        self._mem_value.setPlaceholderText("value")
        self._mem_value.setFixedHeight(34)
        self._mem_value.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        form.addWidget(self._mem_value, stretch=2)
        save = QPushButton("Save")
        save.setFixedHeight(34)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setStyleSheet(button_style(C.GREEN, True))
        save.clicked.connect(self._save_memory_entry)
        form.addWidget(save)
        add_panel.layout.addLayout(form)
        layout.addWidget(add_panel)

        list_panel = Panel("Memory Timeline", "Local memory store with semantic categories")
        self._mem_search = QLineEdit()
        self._mem_search.setPlaceholderText("Filter memory...")
        self._mem_search.setFixedHeight(34)
        self._mem_search.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        self._mem_search.textChanged.connect(self._refresh_memory_list)
        list_panel.layout.addWidget(self._mem_search)
        self._mem_list = QListWidget()
        self._mem_list.setStyleSheet(f"QListWidget {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 10px; }}")
        list_panel.layout.addWidget(self._mem_list)
        layout.addWidget(list_panel)
        layout.addStretch()
        self._refresh_memory_list()
        scroll.setWidget(page)
        return scroll

    def _refresh_memory_list(self):
        if not hasattr(self, "_mem_list"):
            return
        query = self._mem_search.text().strip().lower() if hasattr(self, "_mem_search") else ""
        data = load_memory()
        rows = []
        for cat, items in data.items():
            if not isinstance(items, dict):
                continue
            for key, entry in items.items():
                val = entry.get("value") if isinstance(entry, dict) else str(entry)
                updated = entry.get("updated", "--") if isinstance(entry, dict) else "--"
                rows.append((updated, f"{cat}/{key}", val))
        rows.sort(reverse=True)
        self._mem_list.clear()
        for updated, path, value in rows:
            text = f"{updated} | {path} -> {value}"
            if query and query not in text.lower():
                continue
            self._mem_list.addItem(text)

    def _save_memory_entry(self):
        category = self._mem_category.currentText().strip()
        key = self._mem_key.text().strip()
        value = self._mem_value.text().strip()
        if not key or not value:
            self._handle_log("SYS: Memory key and value are required.")
            return
        self._safe_update_memory(category, key, value)
        self._mem_key.clear()
        self._mem_value.clear()
        self._memory_write_count += 1
        self._refresh_memory_list()
        self._refresh_analytics_panel()
        self._handle_log(f"SYS: Memory saved at {category}/{key}.")

    def _safe_update_memory(self, category: str, key: str, value: str):
        try:
            update_memory({category: {key: {"value": value}}})
            return
        except UnicodeEncodeError:
            pass
        data = load_memory()
        if category not in data or not isinstance(data[category], dict):
            data[category] = {}
        data[category][key] = {"value": value, "updated": time.strftime("%Y-%m-%d")}
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _vision_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Vision System")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        panel = Panel("Vision Controls")
        for label, command in [
            ("Analyze Screen", "Analyze my screen and describe active windows"),
            ("Analyze Camera", "Analyze camera feed and describe scene"),
            ("OCR Current Screen", "Read text from screen and summarize"),
            ("Detect UI Elements", "Find buttons and key UI elements on screen"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(button_style(C.BLUE))
            btn.clicked.connect(lambda _, c=command: self._run_vision_command(c))
            panel.layout.addWidget(btn)
        layout.addWidget(panel)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _run_vision_command(self, command: str):
        self._dispatch_command(f"[VISION] {command}", True)

    def _workflows_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Workflow Studio")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        builder = Panel("Workflow Builder", "Create a quick flow and run it through the assistant")
        self._wf_name = QLineEdit()
        self._wf_name.setPlaceholderText("Workflow name")
        self._wf_name.setFixedHeight(34)
        self._wf_name.setStyleSheet(f"QLineEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; }}")
        builder.layout.addWidget(self._wf_name)
        self._wf_steps = QPlainTextEdit()
        self._wf_steps.setPlaceholderText("One step per line, e.g.\nsearch incident dashboard\nsummarize new failures\nwrite report")
        self._wf_steps.setFixedHeight(140)
        self._wf_steps.setStyleSheet(f"QPlainTextEdit {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 10px; padding: 8px; }}")
        builder.layout.addWidget(self._wf_steps)
        run = QPushButton("Run Workflow")
        run.setFixedHeight(36)
        run.setCursor(Qt.CursorShape.PointingHandCursor)
        run.setStyleSheet(button_style(C.PURPLE, True))
        run.clicked.connect(self._run_custom_workflow)
        builder.layout.addWidget(run)
        layout.addWidget(builder)

        history = Panel("Execution Log")
        self._workflow_list = QListWidget()
        self._workflow_list.setStyleSheet(f"QListWidget {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 10px; }}")
        history.layout.addWidget(self._workflow_list)
        layout.addWidget(history)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _run_custom_workflow(self):
        name = self._wf_name.text().strip() or "Custom Workflow"
        steps = [x.strip() for x in self._wf_steps.toPlainText().splitlines() if x.strip()]
        if not steps:
            self._handle_log("SYS: Add at least one workflow step.")
            return
        summary = f"{name}: " + " -> ".join(steps[:6])
        self._workflow_history.append(f"{time.strftime('%H:%M:%S')} - {summary}")
        self._workflow_list.insertItem(0, self._workflow_history[-1])
        self._dispatch_command(f"[WORKFLOW:{name}] Execute steps: {', '.join(steps)}", True)
        self._wf_name.clear()
        self._wf_steps.clear()

    def _analytics_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Analytics Dashboard")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        panel = Panel("Usage Telemetry", "Live counters from this desktop session")
        self._ana_labels: dict[str, QLabel] = {}
        self._ana_bars: dict[str, QProgressBar] = {}
        for key, display, color in [
            ("commands", "Assistant Commands", C.BLUE),
            ("workflow", "Workflow Runs", C.PURPLE),
            ("memory", "Memory Writes", C.GREEN),
            ("browser", "Browser Actions", C.YELLOW),
            ("vision", "Vision Actions", C.PINK),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(f"{display}: 0")
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            lbl.setStyleSheet(f"color: {C.TEXT};")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFixedHeight(12)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background: {C.PANEL_2};
                    border: 1px solid {C.BORDER};
                    border-radius: 6px;
                }}
                QProgressBar::chunk {{
                    background: {color};
                    border-radius: 6px;
                }}
            """)
            row.addWidget(lbl, stretch=1)
            row.addWidget(bar, stretch=1)
            panel.layout.addLayout(row)
            self._ana_labels[key] = lbl
            self._ana_bars[key] = bar
        layout.addWidget(panel)

        # Real-time system stats panel
        stats_panel = Panel("System Status", "Live metrics from orchestrator and model router")
        self._ana_stats_labels: dict[str, QLabel] = {}
        for key, display in [
            ("tools", "Registered Tools: —"),
            ("slowest", "Slowest Tool: —"),
            ("providers", "Providers: —"),
        ]:
            lbl = QLabel(display)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            lbl.setStyleSheet(f"color: {C.MUTED};")
            stats_panel.layout.addWidget(lbl)
            self._ana_stats_labels[key] = lbl
        layout.addWidget(stats_panel)

        layout.addStretch()
        scroll.setWidget(page)
        self._refresh_analytics_panel()
        return scroll

    def _refresh_analytics_panel(self):
        if not hasattr(self, "_ana_labels"):
            return
        # Pull real stats from orchestrator
        try:
            from core.orchestrator import orchestrator
            timing_stats = orchestrator.timing.get_stats()
            tool_count = len(orchestrator._registry)
        except Exception:
            timing_stats = {}
            tool_count = 0

        try:
            from core.model_router import router as model_router
            router_stats = model_router.get_stats()
        except Exception:
            router_stats = {}

        values = {
            "commands": self._assistant_command_count,
            "workflow": self._workflow_count,
            "memory": self._memory_write_count,
            "browser": self._browser_action_count,
            "vision": self._vision_action_count,
        }
        max_count = max(1, max(values.values()))
        for key, value in values.items():
            self._ana_labels[key].setText(f"{self._ana_labels[key].text().split(':')[0]}: {value}")
            pct = int((value / max_count) * 100)
            self._ana_bars[key].setValue(max(2 if value > 0 else 0, pct))

        # Update real-time stats labels if they exist
        if hasattr(self, "_ana_stats_labels"):
            self._ana_stats_labels["tools"].setText(f"Registered Tools: {tool_count}")
            top_tool = ""
            top_ms = 0
            for t_name, t_data in timing_stats.items():
                if t_data["avg_ms"] > top_ms:
                    top_ms = t_data["avg_ms"]
                    top_tool = t_name
            self._ana_stats_labels["slowest"].setText(f"Slowest Tool: {top_tool} ({top_ms:.0f}ms)" if top_tool else "Slowest Tool: —")

            providers = ""
            for p_name, p_data in router_stats.items():
                providers += f"{p_name}: {p_data['calls']} calls, {p_data['avg_latency_ms']}ms avg  "
            self._ana_stats_labels["providers"].setText(f"Providers: {providers}" if providers else "Providers: —")

    # ------------------------------------------------------------------ #
    #  Remote Connect Tab
    # ------------------------------------------------------------------ #

    def _remote_page(self) -> QScrollArea:
        from core.remote_manager import remote_manager as _rm
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(16)

        title = QLabel("📱 Remote Connect")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        sub = QLabel("Control JARVIS from your iPhone over WiFi")
        sub.setFont(QFont("Segoe UI", 11))
        sub.setStyleSheet(f"color: {C.MUTED};")
        layout.addWidget(sub)

        # ── Server status panel ──
        srv_panel = Panel("Server Status", "Local WiFi connection")
        self._remote_status_lbl = QLabel("🔴 Server stopped")
        self._remote_status_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self._remote_status_lbl.setStyleSheet(f"color: {C.MUTED};")
        srv_panel.layout.addWidget(self._remote_status_lbl)

        self._remote_url_lbl = QLabel("")
        self._remote_url_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self._remote_url_lbl.setStyleSheet(f"color: {C.BLUE};")
        self._remote_url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        srv_panel.layout.addWidget(self._remote_url_lbl)

        btn_row = QHBoxLayout()
        self._remote_start_btn = QPushButton("▶  Start Server")
        self._remote_start_btn.setFixedHeight(38)
        self._remote_start_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._remote_start_btn.setStyleSheet(button_style(C.GREEN))
        self._remote_start_btn.clicked.connect(self._start_remote_server)
        btn_row.addWidget(self._remote_start_btn)

        self._remote_stop_btn = QPushButton("■  Stop")
        self._remote_stop_btn.setFixedHeight(38)
        self._remote_stop_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._remote_stop_btn.setStyleSheet(button_style(C.MUTED))
        self._remote_stop_btn.clicked.connect(self._stop_remote_server)
        self._remote_stop_btn.setEnabled(False)
        btn_row.addWidget(self._remote_stop_btn)
        srv_panel.layout.addLayout(btn_row)
        layout.addWidget(srv_panel)

        # ── Pairing panel ──
        pair_panel = Panel("Pair Your iPhone", "Open Safari → type the URL → enter PIN")
        pair_row = QHBoxLayout()

        # QR code
        self._remote_qr_lbl = QLabel()
        self._remote_qr_lbl.setFixedSize(160, 160)
        self._remote_qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._remote_qr_lbl.setStyleSheet(f"background: {C.PANEL_2}; border: 1px solid {C.BORDER}; border-radius: 8px;")
        self._remote_qr_lbl.setText("QR code\nappears here\nafter start")
        pair_row.addWidget(self._remote_qr_lbl)

        pin_col = QVBoxLayout()
        pin_col.setSpacing(8)
        pin_lbl = QLabel("PIN Code")
        pin_lbl.setFont(QFont("Segoe UI", 10))
        pin_lbl.setStyleSheet(f"color: {C.MUTED};")
        self._remote_pin_lbl = QLabel("----")
        self._remote_pin_lbl.setFont(QFont("Segoe UI", 36, QFont.Weight.Bold))
        self._remote_pin_lbl.setStyleSheet(f"color: {C.BLUE}; letter-spacing: 8px;")
        pin_col.addWidget(pin_lbl)
        pin_col.addWidget(self._remote_pin_lbl)
        pin_col.addStretch()
        pair_row.addLayout(pin_col)
        pair_panel.layout.addLayout(pair_row)
        layout.addWidget(pair_panel)

        # ── Connected devices ──
        dev_panel = Panel("Connected Devices", "Devices currently paired")
        self._remote_devices_lbl = QLabel("No devices connected")
        self._remote_devices_lbl.setFont(QFont("Segoe UI", 10))
        self._remote_devices_lbl.setStyleSheet(f"color: {C.MUTED};")
        dev_panel.layout.addWidget(self._remote_devices_lbl)
        layout.addWidget(dev_panel)

        layout.addStretch()
        scroll.setWidget(page)

        # Refresh timer
        self._remote_refresh_timer = QTimer(self)
        self._remote_refresh_timer.timeout.connect(self._refresh_remote_status)
        self._remote_refresh_timer.start(2000)

        return scroll

    def _start_remote_server(self):
        from core.remote_manager import remote_manager as _rm
        url = _rm.start()
        self._remote_start_btn.setEnabled(False)
        self._remote_stop_btn.setEnabled(True)
        self.write_log(f"SYS: Remote server started → {url}  PIN={_rm.pin}")
        self._refresh_remote_status()

    def _stop_remote_server(self):
        from core.remote_manager import remote_manager as _rm
        _rm.stop()
        self._remote_start_btn.setEnabled(True)
        self._remote_stop_btn.setEnabled(False)
        self._refresh_remote_status()

    def _refresh_remote_status(self):
        try:
            from core.remote_manager import remote_manager as _rm
            status = _rm.get_status()
            if status["running"]:
                self._remote_status_lbl.setText(f"🟢 Running on {status['ip']}:{status['port']}")
                self._remote_status_lbl.setStyleSheet(f"color: #3fb950;")
                self._remote_url_lbl.setText(status["url"])
                self._remote_pin_lbl.setText(status["pin"])
                # Update QR
                pm = _rm.get_qr_pixmap()
                if pm:
                    self._remote_qr_lbl.setPixmap(pm.scaled(
                        156, 156,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    ))
                    self._remote_qr_lbl.setText("")
                # Devices
                devs = status.get("devices", [])
                if devs:
                    names = ", ".join(d["name"] for d in devs if d.get("paired"))
                    self._remote_devices_lbl.setText(f"📱 {names}" if names else "No paired devices")
                    self._remote_devices_lbl.setStyleSheet(f"color: {C.GREEN};")
                else:
                    self._remote_devices_lbl.setText("No devices connected")
                    self._remote_devices_lbl.setStyleSheet(f"color: {C.MUTED};")
            else:
                self._remote_status_lbl.setText("🔴 Server stopped")
                self._remote_status_lbl.setStyleSheet(f"color: {C.MUTED};")
                self._remote_url_lbl.setText("")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Settings Page
    # ------------------------------------------------------------------ #

    def _settings_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(14)

        title = QLabel("Settings Panel")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        panel = Panel("MARK XL Configuration", "Saved locally in config/mark_xl_settings.json")
        combo_style = f"QComboBox {{ background: {C.PANEL_2}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 8px; padding: 0 10px; min-height: 34px; }}"

        self._set_model_chat = QComboBox()
        self._set_model_chat.addItems(["gemini-2.5-flash", "gemini-2.0-flash", "deepseek-chat", "llama-3.1-8b (Groq)", "mixtral-8x7b (Groq)"])
        self._set_model_chat.setCurrentText(self._settings.get("chat_model", "gemini-2.5-flash"))
        self._set_model_chat.setStyleSheet(combo_style)
        chat_lbl = QLabel("Chat Model")
        chat_lbl.setStyleSheet(f"color: {C.MUTED};")
        panel.layout.addWidget(chat_lbl)
        panel.layout.addWidget(self._set_model_chat)

        self._set_model_vision = QComboBox()
        self._set_model_vision.addItems(["gemini-2.5-flash", "gemini-2.0-flash"])
        self._set_model_vision.setCurrentText(self._settings.get("vision_model", "gemini-2.5-flash"))
        self._set_model_vision.setStyleSheet(combo_style)
        vision_lbl = QLabel("Vision Model")
        vision_lbl.setStyleSheet(f"color: {C.MUTED};")
        panel.layout.addWidget(vision_lbl)
        panel.layout.addWidget(self._set_model_vision)

        self._set_theme = QComboBox()
        self._set_theme.addItems(["Dark Futuristic", "Neon Blue", "Iron Red", "Minimal White", "Cyberpunk"])
        self._set_theme.setCurrentText(self._settings.get("theme", "Dark Futuristic"))
        self._set_theme.setStyleSheet(combo_style)
        theme_lbl = QLabel("Theme")
        theme_lbl.setStyleSheet(f"color: {C.MUTED};")
        panel.layout.addWidget(theme_lbl)
        panel.layout.addWidget(self._set_theme)

        self._set_auto = QCheckBox("Enable autonomous workflow execution")
        self._set_auto.setChecked(bool(self._settings.get("autonomous", False)))
        self._set_auto.setStyleSheet(f"color: {C.TEXT};")
        panel.layout.addWidget(self._set_auto)

        self._set_notifications = QCheckBox("Enable desktop notifications")
        self._set_notifications.setChecked(bool(self._settings.get("notifications", True)))
        self._set_notifications.setStyleSheet(f"color: {C.TEXT};")
        panel.layout.addWidget(self._set_notifications)

        save_btn = QPushButton("Save Settings")
        save_btn.setFixedHeight(38)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(button_style(C.GREEN, True))
        save_btn.clicked.connect(self._save_settings_from_ui)
        panel.layout.addWidget(save_btn)
        layout.addWidget(panel)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _load_settings(self) -> dict:
        if SETTINGS_FILE.exists():
            try:
                return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_settings_from_ui(self):
        self._settings = {
            "chat_model": self._set_model_chat.currentText(),
            "vision_model": self._set_model_vision.currentText(),
            "theme": self._set_theme.currentText(),
            "autonomous": bool(self._set_auto.isChecked()),
            "notifications": bool(self._set_notifications.isChecked()),
        }
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")
        self._handle_log("SYS: Settings saved.")

    def _feature_page(self, title: str, cards: list[tuple[str, str]]) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(16)

        header = QLabel(title)
        header.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(header)

        sub = QLabel("Production-ready surface scaffolded for MARK XL. Commands still route through the existing assistant tools.")
        sub.setFont(QFont("Segoe UI", 11))
        sub.setStyleSheet(f"color: {C.MUTED};")
        layout.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        for index, (name, detail) in enumerate(cards):
            card = Panel(name)
            desc = QLabel(detail)
            desc.setWordWrap(True)
            desc.setFont(QFont("Segoe UI", 10))
            desc.setStyleSheet(f"color: {C.MUTED};")
            card.layout.addWidget(desc)
            launch = QPushButton("Run via Assistant")
            launch.setFixedHeight(36)
            launch.setCursor(Qt.CursorShape.PointingHandCursor)
            launch.setStyleSheet(button_style(C.BLUE))
            launch.clicked.connect(lambda _, n=name: self._dispatch_command(f"Open {n}", True))
            card.layout.addWidget(launch)
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _files_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 18, 24)
        layout.setSpacing(16)
        title = QLabel("Smart File Intelligence")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT};")
        layout.addWidget(title)

        drop_panel = Panel("Document Intake", "Drag a file here, then ask MARK XL what to do with it.")
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        drop_panel.layout.addWidget(self._drop_zone)
        self._file_hint = QLabel("No file loaded.")
        self._file_hint.setFont(QFont("Segoe UI", 10))
        self._file_hint.setStyleSheet(f"color: {C.MUTED};")
        drop_panel.layout.addWidget(self._file_hint)
        layout.addWidget(drop_panel)

        tools_grid = QGridLayout()
        tools_grid.setHorizontalSpacing(14)
        tools_grid.setVerticalSpacing(14)
        for index, (name, detail) in enumerate([
            ("PDF Understanding", "Summarize, answer questions, extract tables"),
            ("Excel Intelligence", "Analyze sheets, generate charts, answer queries"),
            ("OCR Pipeline", "Extract screenshots, scanned documents, handwritten notes"),
            ("Code Files", "Explain, debug, edit, and run code files"),
        ]):
            card = Panel(name)
            desc = QLabel(detail)
            desc.setWordWrap(True)
            desc.setFont(QFont("Segoe UI", 10))
            desc.setStyleSheet(f"color: {C.MUTED};")
            card.layout.addWidget(desc)
            tools_grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(tools_grid)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _build_right_rail(self) -> QWidget:
        rail = QWidget()
        rail.setFixedWidth(RIGHT_RAIL_W)
        rail.setStyleSheet(f"background: {C.BG}; border-left: 1px solid {C.BORDER};")
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(14, 18, 16, 18)
        layout.setSpacing(14)

        activity = Panel("Live Activity Feed")
        self._log = LogWidget()
        activity.layout.addWidget(self._log, stretch=1)
        layout.addWidget(activity, stretch=2)

        reminders = Panel("Upcoming Reminders")
        self._reminder_widgets = []
        for title, time_text, color in [
            ("Open Standup Report", "Tomorrow, 09:00", C.YELLOW),
            ("Check DPR Systems", "Tomorrow, 11:30", C.PINK),
            ("Team Meeting", "Tomorrow, 16:00", C.BLUE),
        ]:
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
            title_lbl = QLabel(title)
            title_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            title_lbl.setStyleSheet(f"color: {C.TEXT};")
            time_lbl = QLabel(time_text)
            time_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            time_lbl.setStyleSheet(f"color: {color};")
            row.addWidget(dot)
            row.addWidget(title_lbl, stretch=1)
            row.addWidget(time_lbl)
            reminders.layout.addLayout(row)
            self._reminder_widgets.append({"title": title_lbl, "time": time_lbl, "color": color})
        layout.addWidget(reminders, stretch=1)

        player = Panel("Media")
        now = QLabel("Not Playing\nMARK XL Player")
        now.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        now.setStyleSheet(f"color: {C.MUTED};")
        player.layout.addWidget(now)
        controls = QHBoxLayout()
        for label in ["Prev", "Play", "Next"]:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(button_style(C.BLUE))
            controls.addWidget(btn)
        player.layout.addLayout(controls)
        layout.addWidget(player, stretch=0)
        return rail

    def _build_voice_strip(self) -> QWidget:
        """Live voice transcript strip — shows real-time speech-to-text."""
        strip = QWidget()
        strip.setFixedHeight(42)
        strip.setStyleSheet(f"""
            QWidget {{
                background: {C.BG_2};
                border-top: 1px solid {C.BORDER};
            }}
            QLabel {{
                background: transparent;
            }}
        """)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(248, 4, 24, 4)
        layout.setSpacing(10)

        self._voice_indicator = QLabel("🎤")
        self._voice_indicator.setFixedWidth(28)
        self._voice_indicator.setFont(QFont("Segoe UI", 14))
        layout.addWidget(self._voice_indicator)

        self._voice_live_label = QLabel("Waiting for voice input…")
        self._voice_live_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self._voice_live_label.setStyleSheet(f"color: {C.DIM};")
        layout.addWidget(self._voice_live_label, stretch=1)

        return strip

    def _build_command_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(84)
        bar.setStyleSheet(f"background: {C.BG}; border-top: 1px solid {C.BORDER};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(248, 12, 24, 14)
        layout.setSpacing(12)

        spark = QLabel("AI")
        spark.setFixedSize(44, 44)
        spark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spark.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        spark.setStyleSheet(f"background: #0b2752; color: {C.BLUE}; border: 1px solid {C.BLUE_2}; border-radius: 22px;")
        layout.addWidget(spark)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type your command or ask anything...")
        self._input.setFixedHeight(50)
        self._input.setFont(QFont("Segoe UI", 11))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 24px;
                padding: 0 18px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.BLUE}; }}
        """)
        self._input.returnPressed.connect(self._send)
        layout.addWidget(self._input, stretch=1)

        self._mute_btn = QPushButton("Mic Active")
        self._mute_btn.setFixedSize(110, 46)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        layout.addWidget(self._mute_btn)
        self._style_mute_btn()

        send = QPushButton("Send")
        send.setFixedSize(88, 46)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        send.setStyleSheet(button_style(C.BLUE, True))
        send.clicked.connect(self._send)
        layout.addWidget(send)
        return bar

    def _navigate(self, name: str):
        if name not in self._pages:
            return
        self._stack.setCurrentWidget(self._pages[name])
        for key, btn in self._nav_buttons.items():
            btn.refresh(key == name)
        if name == "Memory":
            self._refresh_memory_list()
        elif name == "Automation":
            self._refresh_schedule_list()
        elif name == "Analytics":
            self._refresh_analytics_panel()
        elif name == "Chats":
            self._refresh_chat_list()

    def _dispatch_command(self, text: str, echo: bool):
        text = text.strip()
        if not text:
            return
        self._assistant_command_count += 1
        lowered = text.lower()
        if "workflow" in lowered:
            self._workflow_count += 1
        if "browser" in lowered or "[browser]" in lowered:
            self._browser_action_count += 1
        if "vision" in lowered or "screen" in lowered or "camera" in lowered:
            self._vision_action_count += 1
        self._refresh_analytics_panel()
        if echo:
            self._handle_log(f"You: {text}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

    def _send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._dispatch_command(text, True)

    def _handle_log(self, text: str):
        self._log.append_log(text)
        self._activity_count += 1
        if self._chat_sessions:
            session = self._chat_sessions[self._active_chat_index]
            if text.startswith("You:") or text.startswith("Jarvis:") or text.startswith("SYS:") or text.startswith("FILE:"):
                session["messages"].append(text)
                if hasattr(self, "_chat_view") and self._stack.currentWidget() is self._pages.get("Chats"):
                    self._render_active_chat()

    def _on_file_selected(self, path: str):
        self._current_file = path
        p = Path(path)
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{p.name} - {size} - Ask MARK XL to summarize, extract, analyze, or convert it.")
        self._handle_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            message = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Tell the user the file is ready and ask what they want to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(message,), daemon=True).start()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._handle_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._handle_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("Mic Muted")
            self._mute_btn.setStyleSheet(button_style(C.RED, True))
        else:
            self._mute_btn.setText("Mic Active")
            self._mute_btn.setStyleSheet(button_style(C.GREEN, True))

    def _apply_state(self, state: str):
        state = state or "IDLE"
        self.hud.state = state
        self.hud.speaking = state.upper() == "SPEAKING"
        if state.upper() == "MUTED":
            color = C.RED
        elif state.upper() == "SPEAKING":
            color = C.ORANGE
        elif state.upper() == "LISTENING":
            color = C.GREEN
        elif state.upper() == "THINKING":
            color = C.YELLOW
        elif state.upper() == "WORKING":
            color = C.BLUE
        else:
            color = C.BLUE
        self._state_lbl.setText(state.upper())
        self._state_lbl.setStyleSheet(f"color: {color}; background: #111722; border: 1px solid {color}; border-radius: 14px;")

    def _update_voice_input(self, text: str):
        """Update the live voice strip with user's speech transcript."""
        if text:
            self._voice_indicator.setText("🎤")
            self._voice_live_label.setText(text)
            self._voice_live_label.setStyleSheet(f"color: {C.GREEN};")
        else:
            self._voice_indicator.setText("🎤")
            self._voice_live_label.setText("Listening for voice…")
            self._voice_live_label.setStyleSheet(f"color: {C.DIM};")

    def _update_voice_output(self, text: str):
        """Update the live voice strip with Jarvis's speech transcript."""
        if text:
            self._voice_indicator.setText("🤖")
            self._voice_live_label.setText(text)
            self._voice_live_label.setStyleSheet(f"color: {C.BLUE};")
        else:
            self._voice_indicator.setText("🎤")
            if not self._muted:
                self._voice_live_label.setText("Listening for voice…")
                self._voice_live_label.setStyleSheet(f"color: {C.DIM};")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M"))
        hour = int(time.strftime("%H"))
        if hour < 12:
            part = "Good Morning"
        elif hour < 18:
            part = "Good Afternoon"
        else:
            part = "Good Evening"
        self._greeting_lbl.setText(f"{part}, Fatih")

    def _update_metrics(self):
        snap = _metrics.snapshot()
        self._metric_widgets["CPU"].set_value(snap["cpu"], f"{snap['cpu']:.0f}%")
        self._metric_widgets["RAM"].set_value(snap["mem"], f"{snap['mem']:.0f}%")
        gpu = snap["gpu"]
        self._metric_widgets["GPU"].set_value(gpu if gpu >= 0 else 0, f"{gpu:.0f}%" if gpu >= 0 else "N/A")
        self._metric_widgets["DISK"].set_value(snap["disk"], f"{snap['disk']:.0f}%")
        health = max(0, min(100, 100 - ((snap["cpu"] * 0.25) + (snap["mem"] * 0.25) + (snap["disk"] * 0.12))))
        self._health_value.setText(f"{health:.0f}%")
        if health > 80:
            msg = "Everything is running smooth."
        elif health > 60:
            msg = "System load is moderate."
        else:
            msg = "System load is high."
        self._health_caption.setText(msg)
        self._refresh_dashboard_data()

    def _refresh_dashboard_data(self):
        self._refresh_agent_statuses()
        self._refresh_task_overview()
        self._refresh_memory_timeline_panel()
        self._refresh_reminders_panel()

    def _refresh_agent_statuses(self):
        if not self._agent_status_widgets:
            return
        queue_states = []
        try:
            from agent.task_queue import get_queue
            queue_states = get_queue().get_all_statuses()
        except Exception:
            queue_states = []

        running = sum(1 for x in queue_states if x.get("status") == "running")
        pending = sum(1 for x in queue_states if x.get("status") == "pending")
        failed = sum(1 for x in queue_states if x.get("status") == "failed")

        computed = {
            "Main Assistant": ("Online", C.GREEN),
            "Vision Agent": ("Working" if self._vision_action_count > 0 else "Online", C.YELLOW if self._vision_action_count > 0 else C.GREEN),
            "Browser Agent": ("Working" if self._browser_action_count > 0 else "Online", C.YELLOW if self._browser_action_count > 0 else C.GREEN),
            "Automation Agent": ("Working" if (running + pending) > 0 else "Online", C.YELLOW if (running + pending) > 0 else C.GREEN),
            "Memory Agent": ("Working" if self._memory_write_count > 0 else "Online", C.YELLOW if self._memory_write_count > 0 else C.GREEN),
            "File Agent": ("Working" if bool(self._current_file) else "Idle", C.YELLOW if self._current_file else C.DIM),
            "Coding Agent": ("Issue" if failed > 0 else ("Working" if running > 0 else "Idle"), C.RED if failed > 0 else (C.YELLOW if running > 0 else C.DIM)),
        }
        for name, label in self._agent_status_widgets.items():
            state, color = computed.get(name, ("Idle", C.DIM))
            label.setText(state)
            label.setStyleSheet(f"color: {color};")

    def _refresh_task_overview(self):
        if not self._task_widgets:
            return
        queue_states = []
        try:
            from agent.task_queue import get_queue
            queue_states = get_queue().get_all_statuses()
        except Exception:
            queue_states = []

        running = sum(1 for x in queue_states if x.get("status") == "running")
        pending = sum(1 for x in queue_states if x.get("status") == "pending")
        completed = sum(1 for x in queue_states if x.get("status") == "completed")
        failed = sum(1 for x in queue_states if x.get("status") == "failed")

        statuses = [
            ("Completed", C.GREEN, f"{completed} done"),
            ("Completed", C.GREEN, f"{len(self._workflow_history)} runs"),
            ("In Progress" if running > 0 else "Pending", C.YELLOW if running > 0 else C.PINK, f"{running} running"),
            ("Pending" if pending > 0 else "Completed", C.PINK if pending > 0 else C.GREEN, f"{pending} queued"),
            ("Failed" if failed > 0 else "Pending", C.RED if failed > 0 else C.PINK, f"{failed} failed"),
        ]
        now = time.strftime("%H:%M")
        for idx, row in enumerate(self._task_widgets):
            state, color, meta = statuses[idx] if idx < len(statuses) else ("Pending", C.PINK, "--")
            row["state_lbl"].setText(state)
            row["state_lbl"].setStyleSheet(f"color: {color};")
            row["time_lbl"].setText(meta if idx < 2 else now)
            row["time_lbl"].setStyleSheet(f"color: {C.MUTED};")

    def _refresh_memory_timeline_panel(self):
        if not self._memory_timeline_widgets:
            return
        entries = []
        try:
            mem = load_memory()
            for cat, items in mem.items():
                if not isinstance(items, dict):
                    continue
                for key, val in items.items():
                    if isinstance(val, dict):
                        text = str(val.get("value", "")).strip()
                        updated = val.get("updated", "--")
                    else:
                        text = str(val).strip()
                        updated = "--"
                    if text:
                        entries.append((updated, f"{cat}/{key}", text))
            entries.sort(reverse=True)
        except Exception:
            entries = []

        fallback = [
            ("No memory writes yet", "Use Memory tab to add data"),
            ("Project memory idle", "No new updates"),
            ("Context monitor ready", "Waiting for assistant saves"),
            ("Conversation summary idle", "No transcript summary yet"),
        ]
        for idx, widget in enumerate(self._memory_timeline_widgets):
            if idx < len(entries):
                updated, key, text = entries[idx]
                widget["head"].setText(f"{key} ({updated})")
                widget["sub"].setText(text[:80])
                widget["head"].setStyleSheet(f"color: {widget['base_color']};")
            else:
                widget["head"].setText(fallback[idx][0] if idx < len(fallback) else "No entry")
                widget["sub"].setText(fallback[idx][1] if idx < len(fallback) else "")
                widget["head"].setStyleSheet(f"color: {widget['base_color']};")

    def _refresh_reminders_panel(self):
        if not self._reminder_widgets:
            return
        if not self._scheduled_items:
            return
        now = time.time()
        active = sorted(self._scheduled_items, key=lambda x: x.get("run_at", now))[: len(self._reminder_widgets)]
        for idx, widget in enumerate(self._reminder_widgets):
            if idx < len(active):
                item = active[idx]
                mins = max(0, int((item.get("run_at", now) - now) / 60))
                widget["title"].setText(item.get("name", "Scheduled workflow"))
                widget["time"].setText(f"in {mins} min")
            else:
                # Keep existing fallback static text from initial render.
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            self._position_overlay()

    def _check_config(self) -> bool:
        data = {}
        try:
            dec = security.decrypt_keys()
            if isinstance(dec, dict) and dec:
                data = dec
        except Exception:
            data = {}
        if not data and API_FILE.exists():
            try:
                data = json.loads(API_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        try:
            key = data.get("gemini_api_key", "").strip()
            return (key.startswith("AIzaSy") or key.startswith("AQ.")) and bool(data.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        self._overlay = SetupOverlay(self.centralWidget())
        self._overlay.done.connect(self._on_setup_done)
        self._position_overlay()
        self._overlay.show()
        self._overlay.raise_()

    def _position_overlay(self):
        if not self._overlay:
            return
        cw = self.centralWidget()
        width, height = 470, 350
        self._overlay.setGeometry((cw.width() - width) // 2, (cw.height() - height) // 2, width, height)

    def _on_setup_done(self, key: str, os_name: str):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        existing = {}
        try:
            dec = security.decrypt_keys()
            if isinstance(dec, dict):
                existing = dec
        except Exception:
            existing = {}
        existing["gemini_api_key"] = key
        existing["os_system"] = os_name
        API_FILE.write_text(json.dumps(existing, indent=4), encoding="utf-8")
        try:
            security.encrypt_keys()
        except Exception:
            pass
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._handle_log(f"SYS: Initialised. OS={os_name.upper()}. MARK XL online.")


class RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, value: bool):
        if value != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._current_file

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def set_input_text(self, text: str):
        self._win._input_sig.emit(text)

    def set_output_text(self, text: str):
        self._win._output_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
