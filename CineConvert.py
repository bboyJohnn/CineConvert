import os
import sys
import json
import math
import subprocess
import platform
import zipfile
import tempfile
import urllib.request
import ctypes
import shutil
import re
import ssl
import time
try:
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox,
        QMainWindow, QWidget, QHBoxLayout, QGridLayout, QTabWidget,
        QGroupBox, QLineEdit, QComboBox, QTextEdit, QScrollArea, QFileDialog,
        QCheckBox, QStyle, QSizePolicy, QToolButton, QSlider, QFrame, QColorDialog
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QRectF, QSize, QPointF, QLineF
    from PyQt6.QtGui import (QFont, QPixmap, QPainter, QPainterPath, QColor,
                             QLinearGradient, QIcon, QPen)
    PYQT_VERSION = 6
except ModuleNotFoundError:
    from PyQt5.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox,
        QMainWindow, QWidget, QHBoxLayout, QGridLayout, QTabWidget,
        QGroupBox, QLineEdit, QComboBox, QTextEdit, QScrollArea, QFileDialog,
        QCheckBox, QStyle, QSizePolicy, QToolButton, QSlider, QFrame, QColorDialog
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QRectF, QSize, QPointF, QLineF
    from PyQt5.QtGui import (QFont, QPixmap, QPainter, QPainterPath, QColor,
                             QLinearGradient, QIcon, QPen)
    PYQT_VERSION = 5

# --- Слой совместимости PyQt5/PyQt6 ------------------------------------------
if PYQT_VERSION == 5:
    for _enum_name in (
        'WindowType', 'AlignmentFlag', 'AspectRatioMode', 'TransformationMode',
        'PenStyle', 'GlobalColor', 'ArrowType', 'ToolButtonStyle', 'Orientation',
        'CursorShape', 'PenCapStyle', 'PenJoinStyle',
    ):
        if not hasattr(Qt, _enum_name):
            setattr(Qt, _enum_name, Qt)


def _enum(cls, member):
    """Достаёт член перечисления и в scoped- (Qt6), и в flat-стиле (PyQt5)."""
    for holder in (getattr(cls, 'StandardPixmap', None),
                   getattr(cls, 'StandardButton', None), cls):
        if holder is not None and hasattr(holder, member):
            return getattr(holder, member)
    return getattr(cls, member)


if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

RESOURCE_DIR = getattr(sys, '_MEIPASS', APP_DIR)
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

# Иконка приложения: из распакованных ресурсов (_MEIPASS) или рядом с программой
APP_ICON = next((p for p in (os.path.join(RESOURCE_DIR, "app.ico"),
                             os.path.join(APP_DIR, "app.ico")) if os.path.exists(p)), None)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
_EXE = ".exe" if sys.platform == 'win32' else ""


def run_hidden(cmd, **kwargs):
    """subprocess.run без чёрного консольного окна и с устойчивым UTF-8."""
    kwargs.setdefault('creationflags', _NO_WINDOW)
    if kwargs.get('text') or kwargs.get('capture_output'):
        kwargs.setdefault('encoding', 'utf-8')
        kwargs.setdefault('errors', 'replace')
    return subprocess.run(cmd, **kwargs)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_config(**changes):
    cfg = load_config()
    cfg.update(changes)
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        os.replace(tmp, CONFIG_FILE)
    except Exception:
        return False
    return True


def open_in_os(path):
    try:
        if platform.system() == 'Windows':
            os.startfile(path)  # noqa: P204
        elif platform.system() == 'Darwin':
            subprocess.call(('open', path))
        else:
            subprocess.call(('xdg-open', path))
    except Exception:
        pass


def find_ffmpeg():
    """Портативный поиск ffmpeg/ffprobe: встроенная ./ffmpeg/bin → config → PATH."""
    local_bin = os.path.join(APP_DIR, "ffmpeg", "bin")
    ff = os.path.join(local_bin, "ffmpeg" + _EXE)
    fp = os.path.join(local_bin, "ffprobe" + _EXE)
    if os.path.exists(ff):
        return ff, (fp if os.path.exists(fp) else ff)

    cfg = load_config()
    ff = cfg.get("ffmpeg_path", "")
    if ff and os.path.exists(ff):
        fp = cfg.get("ffprobe_path", "")
        if not fp or not os.path.exists(fp):
            guess = ff.replace("ffmpeg" + _EXE, "ffprobe" + _EXE)
            fp = guess if os.path.exists(guess) else ff
        return ff, fp

    ff = shutil.which("ffmpeg")
    if ff:
        return ff, (shutil.which("ffprobe") or ff)
    return None, None


_BITRATE_RE = re.compile(r'^\d+(?:\.\d+)?[kKmMgG]?$')


# ============================================================================
#  Тема оформления (перенесена из проекта Download Internet Video — OKLCH)
# ============================================================================
DEFAULT_HUE = 258          # синий — классический цвет приложения
DEFAULT_SATURATION = 100   # проценты; больше = насыщеннее


class _Theme:
    """Держатель текущих цветов и стилей (перестраивается set_theme)."""
    CURRENT_HUE = DEFAULT_HUE
    CURRENT_SATURATION = DEFAULT_SATURATION
    CURRENT_DARK = False


T = _Theme()


def is_system_dark():
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
        except Exception:
            pass
    return False


def _oklch(L, C, H):
    """oklch -> #rrggbb (та же цветовая модель, что и в референсном сайте)."""
    h = math.radians(H)
    a, b = C * math.cos(h), C * math.sin(h)
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = +4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_

    def srgb(c):
        c = max(0.0, min(1.0, c))
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(max(0.0, min(1.0, c)) * 255)

    return '#%02x%02x%02x' % (srgb(r), srgb(g), srgb(bl))


def _rainbow_stops():
    return ', '.join(f'stop:{i / 12:.4f} {_oklch(.8, .1, i * 30)}' for i in range(13))


def srgb_to_oklch(r, g, b):
    def linear(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = linear(r), linear(g), linear(b)
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.sqrt(a * a + bb * bb)
    H = math.degrees(math.atan2(bb, a)) % 360
    return L, C, H


def set_theme(hue=None, saturation=None, dark=None):
    """Перестраивает всю палитру и стили. None-аргументы не меняются."""
    if hue is not None:
        T.CURRENT_HUE = max(0, min(360, int(hue)))
    if saturation is not None:
        T.CURRENT_SATURATION = max(50, min(160, int(saturation)))
    if dark is not None:
        T.CURRENT_DARK = bool(dark)

    h = T.CURRENT_HUE
    s = T.CURRENT_SATURATION / 100.0

    def c(base):
        return base * s

    if T.CURRENT_DARK:
        T.COLOR_PRIMARY = _oklch(.75, c(.14), h)
        T.COLOR_PRIMARY_HOVER = _oklch(.70, c(.14), h)
        T.COLOR_PRIMARY_ACTIVE = _oklch(.65, c(.13), h)
        T.COLOR_PAGE_BG = _oklch(.16, c(.014), h)
        T.COLOR_PAGE_BG_DEEP = _oklch(.10, c(.014), h)
        T.COLOR_CARD_BG = _oklch(.23, c(.015), h)
        T.COLOR_CARD_BORDER = _oklch(.33, c(.02), h)
        T.COLOR_INPUT_BG = _oklch(.19, c(.012), h)
        T.COLOR_BTN_BG = _oklch(.33, c(.035), h)
        T.COLOR_BTN_BG_HOVER = _oklch(.38, c(.04), h)
        T.COLOR_BTN_BG_ACTIVE = _oklch(.43, c(.045), h)
        T.COLOR_BTN_TEXT = _oklch(.80, c(.10), h)
        T.COLOR_TEXT = _oklch(.93, c(.01), h)
        T.COLOR_TEXT_MUTED = _oklch(.68, c(.02), h)
        T.COLOR_TRACK = _oklch(.34, c(.02), h)
        T.COLOR_THUMB_BG = _oklch(.30, c(.015), h)
        T.COLOR_GREEN = _oklch(.75, .13, 150)
        T.COLOR_RED = _oklch(.72, .16, 25)
        chip_red_bg, chip_red_bg_hover = _oklch(.30, .06, 25), _oklch(.35, .07, 25)
        chip_red_text = _oklch(.80, .13, 25)
    else:
        T.COLOR_PRIMARY = _oklch(.70, c(.14), h)
        T.COLOR_PRIMARY_HOVER = _oklch(.63, c(.13), h)
        T.COLOR_PRIMARY_ACTIVE = _oklch(.58, c(.12), h)
        T.COLOR_PAGE_BG = _oklch(.95, c(.01), h)
        T.COLOR_PAGE_BG_DEEP = _oklch(.86, c(.03), h)
        T.COLOR_CARD_BG = "#ffffff"
        T.COLOR_CARD_BORDER = _oklch(.90, c(.012), h)
        T.COLOR_INPUT_BG = "#ffffff"
        T.COLOR_BTN_BG = _oklch(.95, c(.025), h)
        T.COLOR_BTN_BG_HOVER = _oklch(.90, c(.05), h)
        T.COLOR_BTN_BG_ACTIVE = _oklch(.85, c(.08), h)
        T.COLOR_BTN_TEXT = _oklch(.55, c(.12), h)
        T.COLOR_TEXT = _oklch(.25, c(.02), h)
        T.COLOR_TEXT_MUTED = _oklch(.55, c(.02), h)
        T.COLOR_TRACK = _oklch(.92, c(.02), h)
        T.COLOR_THUMB_BG = _oklch(.93, c(.015), h)
        T.COLOR_GREEN = _oklch(.62, .14, 150)
        T.COLOR_RED = _oklch(.55, .19, 25)
        chip_red_bg, chip_red_bg_hover = _oklch(.95, .03, 25), _oklch(.91, .05, 25)
        chip_red_text = _oklch(.55, .18, 25)

    T.STYLESHEET_MAIN = f"""
        QMainWindow {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {T.COLOR_PAGE_BG}, stop:0.35 {T.COLOR_PAGE_BG},
                stop:1 {T.COLOR_PAGE_BG_DEEP});
        }}
        QDialog {{ background-color: {T.COLOR_PAGE_BG}; }}
        QWidget {{ font-family: 'Segoe UI', Arial, sans-serif; }}
        QLabel {{ font-size: 9pt; color: {T.COLOR_TEXT}; background: transparent; }}
        QLabel#fieldLabel {{ color: {T.COLOR_TEXT_MUTED}; font-size: 8.5pt; font-weight: 600; }}
        QLabel#infoKey {{ color: {T.COLOR_TEXT_MUTED}; font-size: 8.5pt; }}
        QLabel#infoVal {{ color: {T.COLOR_BTN_TEXT}; font-size: 8.5pt; font-weight: 600; }}
        QLabel#previewLabel {{
            border: 1px dashed {T.COLOR_CARD_BORDER}; border-radius: 8px;
            color: {T.COLOR_TEXT_MUTED}; background: {T.COLOR_INPUT_BG}; font-size: 8pt;
        }}
        QFrame#infoCard {{
            background-color: {T.COLOR_CARD_BG}; border: 1px solid {T.COLOR_CARD_BORDER};
            border-radius: 12px;
        }}
        QLabel#batchStatus {{ color: {T.COLOR_BTN_TEXT}; font-size: 9pt; font-weight: 600; }}
        QLabel#statsLabel {{ color: {T.COLOR_TEXT_MUTED}; font-size: 8.5pt; }}
        QLineEdit, QComboBox {{
            border: 1px solid {T.COLOR_CARD_BORDER}; border-radius: 8px;
            padding: 6px 10px; background-color: {T.COLOR_INPUT_BG};
            font-size: 9pt; color: {T.COLOR_TEXT};
            selection-background-color: {T.COLOR_BTN_BG_HOVER}; selection-color: {T.COLOR_TEXT};
        }}
        QLineEdit:focus, QComboBox:focus {{ border: 1px solid {T.COLOR_PRIMARY}; }}
        QLineEdit:read-only {{ color: {T.COLOR_TEXT_MUTED}; }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QComboBox QAbstractItemView {{
            background: {T.COLOR_INPUT_BG}; border: 1px solid {T.COLOR_CARD_BORDER};
            border-radius: 8px; color: {T.COLOR_TEXT};
            selection-background-color: {T.COLOR_BTN_BG}; selection-color: {T.COLOR_BTN_TEXT};
            outline: none;
        }}
        QPushButton {{
            background-color: {T.COLOR_BTN_BG}; color: {T.COLOR_BTN_TEXT}; border: none;
            border-radius: 8px; padding: 7px 14px; font-size: 9pt; font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {T.COLOR_BTN_BG_HOVER}; }}
        QPushButton:pressed {{ background-color: {T.COLOR_BTN_BG_ACTIVE}; }}
        QPushButton:disabled {{ background-color: {T.COLOR_PAGE_BG}; color: {T.COLOR_TEXT_MUTED}; }}
        QTabWidget::pane {{ border: none; background: transparent; }}
        QTabBar::tab {{
            background: transparent; color: {T.COLOR_TEXT_MUTED};
            padding: 7px 16px; margin: 0 6px 8px 0; border-radius: 8px;
            font-size: 9pt; font-weight: 600;
        }}
        QTabBar::tab:selected {{ background: {T.COLOR_PRIMARY}; color: white; }}
        QTabBar::tab:hover:!selected {{ background: {T.COLOR_BTN_BG_HOVER}; color: {T.COLOR_BTN_TEXT}; }}
        QTextEdit {{
            border: 1px solid {T.COLOR_CARD_BORDER}; border-radius: 10px;
            font-family: Consolas, monospace; font-size: 8.5pt;
            background: {T.COLOR_INPUT_BG}; color: {T.COLOR_TEXT};
        }}
        QCheckBox {{ font-size: 9pt; color: {T.COLOR_TEXT}; spacing: 8px; background: transparent; }}
        QProgressBar {{
            border: none; border-radius: 4px; background: {T.COLOR_TRACK};
            text-align: center; color: {T.COLOR_TEXT}; height: 16px; font-size: 8.5pt;
        }}
        QProgressBar::chunk {{ background-color: {T.COLOR_PRIMARY}; border-radius: 4px; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{ border: none; background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {T.COLOR_CARD_BORDER}; border-radius: 4px; min-height: 30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QMessageBox, QMessageBox QLabel {{ background-color: {T.COLOR_CARD_BG}; color: {T.COLOR_TEXT}; }}
        QToolTip {{ background-color: {T.COLOR_CARD_BG}; color: {T.COLOR_TEXT};
            border: 1px solid {T.COLOR_CARD_BORDER}; }}
    """

    T.STYLESHEET_GROUPBOX = f"""
        QGroupBox {{
            border: 1px solid {T.COLOR_CARD_BORDER}; border-radius: 12px;
            margin-top: 12px; padding-top: 14px; font-weight: 600;
            background-color: {T.COLOR_CARD_BG}; font-size: 9pt; color: {T.COLOR_BTN_TEXT};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; left: 14px; top: 2px;
            padding: 0 4px; background: transparent;
        }}
    """

    T.STYLESHEET_PROGRESS_BAR = f"""
        QProgressBar {{ border: none; border-radius: 4px; background: {T.COLOR_TRACK};
            text-align: center; color: {T.COLOR_TEXT}; height: 16px; font-size: 8.5pt; }}
        QProgressBar::chunk {{ background-color: {T.COLOR_PRIMARY}; border-radius: 4px; }}
    """

    T.STYLESHEET_BUTTON_PRIMARY = f"""
        QPushButton {{ background-color: {T.COLOR_PRIMARY}; color: white; border: none;
            border-radius: 8px; padding: 7px 16px; font-size: 9.5pt; font-weight: 600; }}
        QPushButton:hover {{ background-color: {T.COLOR_PRIMARY_HOVER}; }}
        QPushButton:pressed {{ background-color: {T.COLOR_PRIMARY_ACTIVE}; }}
        QPushButton:disabled {{ background-color: {T.COLOR_BTN_BG}; color: {T.COLOR_TEXT_MUTED}; }}
    """

    T.STYLESHEET_BUTTON_DANGER = f"""
        QPushButton {{ background-color: {chip_red_bg}; color: {chip_red_text}; border: none;
            border-radius: 8px; padding: 7px 14px; font-size: 9pt; font-weight: 600; }}
        QPushButton:hover {{ background-color: {chip_red_bg_hover}; }}
    """

    T.STYLESHEET_BUTTON_LINK = f"""
        QPushButton {{ background: transparent; color: {T.COLOR_TEXT_MUTED}; border: none;
            padding: 4px 10px; font-size: 9pt; font-weight: 600; }}
        QPushButton:hover {{ color: {T.COLOR_BTN_TEXT}; text-decoration: underline; }}
    """

    T.STYLESHEET_HUE_SLIDER = f"""
        QSlider::groove:horizontal {{ height: 10px; border-radius: 5px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {_rainbow_stops()}); }}
        QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -5px 0;
            border-radius: 10px; background: {T.COLOR_CARD_BG}; border: 3px solid {T.COLOR_PRIMARY}; }}
        QSlider::add-page:horizontal, QSlider::sub-page:horizontal {{ background: transparent; }}
    """

    T.STYLESHEET_SAT_SLIDER = f"""
        QSlider::groove:horizontal {{ height: 10px; border-radius: 5px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {_oklch(.7, .01, h)}, stop:1 {_oklch(.7, .24, h)}); }}
        QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -5px 0;
            border-radius: 10px; background: {T.COLOR_CARD_BG}; border: 3px solid {T.COLOR_PRIMARY}; }}
        QSlider::add-page:horizontal, QSlider::sub-page:horizontal {{ background: transparent; }}
    """

    T.FIELD_LABEL_STYLE = (f"color: {T.COLOR_TEXT_MUTED}; font-size: 8.5pt; "
                           f"font-weight: 600; background: transparent;")


set_theme()  # построить палитру по умолчанию при импорте


# ============================================================================
#  Иконки — чистые флэт-глифы, рисуются в цвет темы (без эмодзи)
# ============================================================================
def make_icon(kind, color, px=44):
    """Возвращает QIcon с плоским линейным глифом заданного цвета."""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    col = QColor(color)
    pen = QPen(col)
    pen.setWidthF(px * 0.088)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    def line(x1, y1, x2, y2):
        p.drawLine(QLineF(x1 * px, y1 * px, x2 * px, y2 * px))

    def rrect(x, y, w, h, r):
        p.drawRoundedRect(QRectF(x * px, y * px, w * px, h * px), r * px, r * px)

    def poly(points, fill):
        path = QPainterPath()
        path.moveTo(QPointF(points[0][0] * px, points[0][1] * px))
        for xx, yy in points[1:]:
            path.lineTo(QPointF(xx * px, yy * px))
        if fill:
            path.closeSubpath()
            p.fillPath(path, col)
        else:
            p.drawPath(path)

    def dot(cx, cy, r):
        p.setBrush(col)
        p.drawEllipse(QPointF(cx * px, cy * px), r * px, r * px)
        p.setBrush(Qt.GlobalColor.transparent)

    if kind == 'video':
        rrect(0.16, 0.24, 0.68, 0.52, 0.16)
        poly([(0.42, 0.37), (0.42, 0.63), (0.62, 0.50)], True)
    elif kind == 'audio':
        for x, h in ((0.24, 0.28), (0.38, 0.60), (0.52, 0.42), (0.66, 0.70), (0.80, 0.34)):
            line(x, 0.5 - h / 2, x, 0.5 + h / 2)
    elif kind == 'logs':
        line(0.24, 0.32, 0.76, 0.32)
        line(0.24, 0.50, 0.76, 0.50)
        line(0.24, 0.68, 0.60, 0.68)
    elif kind == 'settings':
        line(0.20, 0.36, 0.80, 0.36)
        line(0.20, 0.64, 0.80, 0.64)
        dot(0.62, 0.36, 0.09)
        dot(0.38, 0.64, 0.09)
    elif kind == 'folder':
        rrect(0.15, 0.26, 0.30, 0.14, 0.06)
        rrect(0.15, 0.34, 0.70, 0.42, 0.08)
    elif kind == 'close':
        line(0.30, 0.30, 0.70, 0.70)
        line(0.70, 0.30, 0.30, 0.70)
    elif kind == 'play':
        poly([(0.34, 0.26), (0.34, 0.74), (0.74, 0.50)], True)
    elif kind == 'download':
        line(0.50, 0.22, 0.50, 0.58)
        poly([(0.37, 0.46), (0.50, 0.62), (0.63, 0.46)], True)
        line(0.28, 0.74, 0.72, 0.74)
    elif kind == 'check':
        poly([(0.27, 0.52), (0.43, 0.67), (0.73, 0.33)], False)
    elif kind == 'refresh':
        r = 0.27
        rect = QRectF((0.5 - r) * px, (0.5 - r) * px, 2 * r * px, 2 * r * px)
        path = QPainterPath()
        path.arcMoveTo(rect, 70)
        path.arcTo(rect, 70, 250)
        p.drawPath(path)
        end = math.radians(70 + 250)
        ex, ey = 0.5 + r * math.cos(end), 0.5 - r * math.sin(end)
        poly([(ex - 0.02, ey - 0.13), (ex, ey), (ex + 0.13, ey - 0.02)], True)
    elif kind == 'info':
        p.drawEllipse(QPointF(0.5 * px, 0.5 * px), 0.30 * px, 0.30 * px)
        dot(0.5, 0.37, 0.045)
        line(0.5, 0.47, 0.5, 0.66)
    elif kind == 'prev':
        line(0.60, 0.26, 0.40, 0.50)
        line(0.40, 0.50, 0.60, 0.74)
    elif kind == 'next':
        line(0.42, 0.26, 0.62, 0.50)
        line(0.62, 0.50, 0.42, 0.74)
    elif kind == 'add':
        line(0.50, 0.28, 0.50, 0.72)
        line(0.28, 0.50, 0.72, 0.50)
    elif kind == 'copy':
        rrect(0.24, 0.24, 0.36, 0.36, 0.08)
        rrect(0.40, 0.40, 0.36, 0.36, 0.08)
    elif kind == 'trash':
        line(0.22, 0.33, 0.78, 0.33)
        rrect(0.41, 0.25, 0.18, 0.08, 0.03)
        rrect(0.30, 0.33, 0.40, 0.45, 0.07)
        line(0.43, 0.44, 0.43, 0.68)
        line(0.57, 0.44, 0.57, 0.68)
    p.end()
    return QIcon(pm)


# ============================================================================
#  Виджеты дизайн-системы (перенесены из Download Internet Video)
# ============================================================================
class ShadowGroupBox(QGroupBox):
    """Карточка-группа в современном стиле."""
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setStyleSheet(T.STYLESHEET_GROUPBOX)


class BannerWidget(QWidget):
    """Заголовок в стиле сайта: название на цветной «картинке» с плывущими
    волнами вдоль нижнего края (цвет волн = фон страницы)."""
    def __init__(self, title, parent=None, height=104):
        super().__init__(parent)
        self._title = title
        self.setFixedHeight(height)
        self._t = 0.0
        self._boost = 0.0
        self._animated = True
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def setTitle(self, title):
        self._title = title
        self.update()

    def set_animated(self, animated):
        self._animated = bool(animated)
        if self._animated:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._boost = 0.0
            self.update()

    def splash(self):
        if self._animated:
            self._boost = 1.0

    def _tick(self):
        self._t += 0.04 * (1.0 + 2.0 * self._boost)
        self._boost = self._boost * 0.94 if self._boost > 0.01 else 0.0
        self.update()

    @staticmethod
    def _gentle_wave_path():
        path = QPainterPath()
        path.moveTo(-160, 44)
        path.cubicTo(-130, 44, -102, 26, -72, 26)
        path.cubicTo(-42, 26, -14, 44, 16, 44)
        path.cubicTo(46, 44, 74, 26, 104, 26)
        path.cubicTo(134, 26, 162, 44, 192, 44)
        path.lineTo(192, 92)
        path.lineTo(-160, 92)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), float(self.height())
        if w <= 0 or h <= 0:
            return
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 12, 12)
        painter.setClipPath(clip)

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor(T.COLOR_PRIMARY_ACTIVE))
        grad.setColorAt(0.55, QColor(T.COLOR_PRIMARY))
        grad.setColorAt(1.0, QColor(T.COLOR_BTN_BG_ACTIVE))
        painter.fillPath(clip, grad)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 26))
        painter.drawEllipse(QRectF(w * 0.62, -h * 0.7, h * 1.7, h * 1.7))
        painter.drawEllipse(QRectF(w * 0.06, h * 0.35, h * 1.1, h * 1.1))

        painter.setPen(QColor(255, 255, 255))
        title_font = QFont("Segoe UI", 17)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(0, 0, w, h - 26), Qt.AlignmentFlag.AlignCenter, self._title)

        wave_h = 30.0 * (1.0 + 0.22 * self._boost)
        sx = w / 150.0
        sy = wave_h / 32.0
        top = h - wave_h
        base_path = self._gentle_wave_path()
        page = QColor(T.COLOR_PAGE_BG)
        for y_off, opacity, duration in ((0, 0.25, 7.0), (3, 0.50, 10.0),
                                         (5, 0.75, 13.0), (7, 1.00, 20.0)):
            phase = (self._t / duration) % 1.0
            x_units = 48.0 - 90.0 + phase * 175.0
            color = QColor(page)
            color.setAlphaF(opacity)
            painter.save()
            painter.translate(0, top - 20.0 * sy)
            painter.scale(sx, sy)
            painter.translate(x_units, y_off)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(base_path)
            painter.restore()
        painter.end()


class CollapsibleBox(QWidget):
    """Карточка настроек со сворачиваемым содержимым по клику на заголовок."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("collapsibleBox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True) if hasattr(
            Qt, 'WidgetAttribute') else self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 8)
        outer.setSpacing(2)
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self._on_toggled)
        outer.addWidget(self.toggle_button)
        self.content = QWidget()
        outer.addWidget(self.content)
        self.apply_theme()

    def _on_toggled(self):
        expanded = self.toggle_button.isChecked()
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)

    def set_expanded(self, expanded):
        self.toggle_button.setChecked(bool(expanded))
        self._on_toggled()

    def setContentLayout(self, layout):
        self.content.setLayout(layout)

    def apply_theme(self):
        self.setStyleSheet(
            f"#collapsibleBox {{ background-color: {T.COLOR_CARD_BG}; "
            f"border: 1px solid {T.COLOR_CARD_BORDER}; border-radius: 12px; }}")
        self.toggle_button.setStyleSheet(
            f"QToolButton {{ border: none; background: transparent; "
            f"color: {T.COLOR_BTN_TEXT}; font-weight: 600; font-size: 9pt; padding: 4px 2px; }}")


# ============================================================================
#  FFmpeg: скачивание, проверка версий и обновление (подход из Download
#  Internet Video: certifi-фолбэк, сверка версий, атомарная замена с откатом)
# ============================================================================
FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_VERSION_URL = "https://www.gyan.dev/ffmpeg/builds/release-version"


def _net_urlopen(url, timeout=30):
    """urlopen с UA и запасными SSL-контекстами: системный → certifi → без
    проверки. Как в DIV (сначала certifi, не отключая проверку), плюс последний
    фолбэк без верификации — на случай перекоса часов/старых корневых серт."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    contexts = [None]
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    contexts.append(unverified)
    last_err = None
    for ctx in contexts:
        try:
            if ctx is None:
                return urllib.request.urlopen(req, timeout=timeout)
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except Exception as e:
            last_err = e
    raise last_err


def _version_tuple(v):
    """'8.1.2' / 'v2.9.1' -> сравнимый кортеж чисел."""
    return tuple(int(x) for x in re.findall(r'\d+', v or '')) or (0,)


def ffmpeg_local_version(ffmpeg_path):
    """Версия локального ffmpeg (`ffmpeg -version`) или None."""
    try:
        r = run_hidden([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=10)
        m = re.search(r'ffmpeg version (\S+)', r.stdout or "")
        return m.group(1).split('-')[0] if m else None
    except Exception:
        return None


def ffmpeg_latest_version():
    """Последняя версия сборки FFmpeg с gyan.dev или None."""
    try:
        with _net_urlopen(FFMPEG_VERSION_URL, timeout=15) as r:
            return r.read().decode('utf-8', 'replace').strip() or None
    except Exception:
        return None


def _rmtree_retry(path, attempts=5, delay=0.4):
    """Удаляет папку, повторяя при блокировках (OneDrive/антивирус)."""
    for i in range(attempts):
        if not os.path.exists(path):
            return True
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(delay * (i + 1))
    return not os.path.exists(path)


class FFmpegSetupThread(QThread):
    progress = pyqtSignal(object)   # int (проценты) или str (статус)
    log = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, mode="install", force=False, parent=None):
        super().__init__(parent)
        self.mode = mode            # "install" | "update"
        self.force = force
        self._cancel = False

    def stop(self):
        self._cancel = True

    def _download(self, url, dst):
        """Атомарная стриминговая загрузка через .part с прогрессом."""
        tmp = dst + ".part"
        try:
            with _net_urlopen(url, timeout=60) as resp, open(tmp, 'wb') as out_f:
                total = resp.getheader('Content-Length')
                total = int(total) if total and total.isdigit() else None
                downloaded = 0
                while True:
                    if self._cancel:
                        raise RuntimeError("Отменено пользователем")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        self.progress.emit(int(downloaded * 100 / total))
            if total is not None and downloaded < total:
                raise RuntimeError(f"Неполная загрузка: {downloaded}/{total} байт")
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _extract_new(self, zip_path, new_dir):
        """Распаковывает архив и собирает new_dir/bin с бинарниками ffmpeg."""
        extract = new_dir + ".extract"
        _rmtree_retry(new_dir)
        _rmtree_retry(extract)
        os.makedirs(extract, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract)
        inner_bin = None
        for root, _dirs, files in os.walk(extract):
            if os.path.basename(root) == "bin" and any(
                    f.lower().startswith("ffmpeg") for f in files):
                inner_bin = root
                break
        if not inner_bin:
            _rmtree_retry(extract)
            raise RuntimeError("В архиве не найдена папка bin с ffmpeg")
        new_bin = os.path.join(new_dir, "bin")
        os.makedirs(new_bin, exist_ok=True)
        for fname in os.listdir(inner_bin):
            shutil.copy2(os.path.join(inner_bin, fname), os.path.join(new_bin, fname))
        _rmtree_retry(extract)
        return new_bin

    @staticmethod
    def _swap(new_dir, target_dir):
        """Атомарно заменяет target_dir на new_dir с бэкапом .old и откатом."""
        backup = target_dir + ".old"
        _rmtree_retry(backup)
        had_old = os.path.exists(target_dir)
        if had_old:
            os.rename(target_dir, backup)
        try:
            os.rename(new_dir, target_dir)
        except OSError:
            if had_old and os.path.exists(backup):
                os.rename(backup, target_dir)
            raise
        _rmtree_retry(backup)

    def run(self):
        app_dir = APP_DIR
        target = os.path.join(app_dir, "ffmpeg")
        target_bin = os.path.join(target, "bin")
        zip_path = os.path.join(app_dir, "ffmpeg.zip")
        new_dir = os.path.join(app_dir, "ffmpeg.new")
        # Чистим «хвосты» от прерванных установок
        for n in ("ffmpeg.new", "ffmpeg.new.extract", "ffmpeg.old"):
            _rmtree_retry(os.path.join(app_dir, n), attempts=2)
        for n in ("ffmpeg.zip", "ffmpeg.zip.part"):
            p = os.path.join(app_dir, n)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        try:
            cur = ffmpeg_local_version(os.path.join(target_bin, "ffmpeg" + _EXE))
            if self.mode == "update":
                self.progress.emit("Проверка версии…")
                latest = ffmpeg_latest_version()
                self.log.emit(f"Установлено: {cur or '—'}  ·  Последняя: {latest or 'неизвестно'}")
                if (cur and latest and not self.force
                        and _version_tuple(cur) >= _version_tuple(latest)):
                    self.done.emit(True, f"Уже актуально — FFmpeg {cur}.")
                    return

            self.progress.emit("Скачивание FFmpeg…")
            self._download(FFMPEG_DOWNLOAD_URL, zip_path)
            if self._cancel:
                self.done.emit(False, "Отменено.")
                return

            self.progress.emit("Распаковка…")
            new_bin = self._extract_new(zip_path, new_dir)
            new_ver = ffmpeg_local_version(os.path.join(new_bin, "ffmpeg" + _EXE))
            if not new_ver:
                raise RuntimeError("Скачанный ffmpeg не прошёл проверку запуска")

            self.progress.emit("Установка…")
            self._swap(new_dir, target)
            fp = os.path.join(target_bin, "ffprobe" + _EXE)
            save_config(ffmpeg_installed=True,
                        ffmpeg_path=os.path.join(target_bin, "ffmpeg" + _EXE),
                        ffprobe_path=fp if os.path.exists(fp) else os.path.join(target_bin, "ffmpeg" + _EXE))
            self.log.emit(f"Готово: FFmpeg {new_ver}")
            self.progress.emit("Готово!")
            self.done.emit(True, f"FFmpeg {new_ver} установлен.")
        except Exception as e:
            self.log.emit(f"Ошибка: {e}")
            self.done.emit(False, str(e))
        finally:
            _rmtree_retry(new_dir, attempts=2)
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass


class FFmpegSetupDialog(QDialog):
    """Установка (авто) или обновление FFmpeg — с логом и прогрессом (как в DIV)."""

    def __init__(self, mode="install", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.success = False
        self.thread = None
        self.setWindowTitle("Установка FFmpeg" if mode == "install" else "Обновление FFmpeg")
        self.setStyleSheet(T.STYLESHEET_MAIN)
        if parent is not None:
            try:
                self.setWindowIcon(parent.windowIcon())
            except Exception:
                pass
        self.setMinimumSize(520, 400)
        if mode == "install":
            self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.label = QLabel("Проверка FFmpeg…" if mode == "install"
                            else "Нажмите «Проверить и обновить», чтобы сравнить "
                                 "версию FFmpeg с последней.")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        layout.addWidget(self.log_view, 1)

        self.chk_force = QCheckBox("Переустановить, даже если версия актуальна")
        self.chk_force.setVisible(mode == "update")
        layout.addWidget(self.chk_force)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_action = QPushButton("Проверить и обновить")
        self.btn_action.setStyleSheet(T.STYLESHEET_BUTTON_PRIMARY)
        self.btn_action.setVisible(mode == "update")
        self.btn_action.clicked.connect(lambda: self._start(self.chk_force.isChecked()))
        row.addWidget(self.btn_action)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self._close_or_cancel)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        if mode == "install":
            self.btn_close.setEnabled(False)
            self._start(force=False)

    def _start(self, force):
        self.btn_action.setEnabled(False)
        self.chk_force.setEnabled(False)
        self.btn_close.setText("Отмена")
        self.btn_close.setEnabled(True)   # отмена доступна и при автоустановке
        self.progress.setValue(0)
        self.thread = FFmpegSetupThread(self.mode, force)
        self.thread.progress.connect(self._on_progress)
        self.thread.log.connect(self.log_view.append)
        self.thread.done.connect(self._on_done)
        self.thread.start()

    def _on_progress(self, message):
        if isinstance(message, int):
            self.progress.setValue(message)
            self.label.setText(f"Скачивание… {message}%")
        else:
            self.label.setText(str(message))
            self.log_view.append(str(message))

    def _on_done(self, ok, msg):
        self.success = ok
        self.label.setText(msg)
        self.log_view.append(msg)
        if ok:
            self.progress.setValue(100)
        self.btn_action.setEnabled(True)
        self.chk_force.setEnabled(True)
        self.btn_close.setText("Закрыть")
        self.btn_close.setEnabled(True)
        if self.mode == "install" and ok:
            QTimer.singleShot(800, self.accept)

    def _close_or_cancel(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()
            self.log_view.append("Отмена…")
            self.btn_close.setEnabled(False)
        else:
            self.accept()

    def _shutdown(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(15000)

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)

    def reject(self):
        self._shutdown()
        super().reject()


class NotificationDialog(QDialog):
    def __init__(self, output_file, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Готово")
        self.setStyleSheet(T.STYLESHEET_MAIN)
        if parent is not None:
            try:
                self.setWindowIcon(parent.windowIcon())
            except Exception:
                pass
        self.setMinimumSize(380, 150)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        msg = QLabel("✅  Готово! Файл создан успешно.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"font-size: 11pt; font-weight: 600; color: {T.COLOR_TEXT};")
        layout.addWidget(msg)
        row = QHBoxLayout()
        self.btn_play = QPushButton("Открыть файл")
        self.btn_play.setStyleSheet(T.STYLESHEET_BUTTON_PRIMARY)
        self.btn_play.setIcon(make_icon('play', "#ffffff"))
        self.btn_play.setIconSize(QSize(16, 16))
        self.btn_play.clicked.connect(lambda: self._act(output_file, False))
        row.addWidget(self.btn_play)
        self.btn_folder = QPushButton("Открыть папку")
        self.btn_folder.setIcon(make_icon('folder', T.COLOR_BTN_TEXT))
        self.btn_folder.setIconSize(QSize(16, 16))
        self.btn_folder.clicked.connect(lambda: self._act(output_file, True))
        row.addWidget(self.btn_folder)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.setStyleSheet(T.STYLESHEET_BUTTON_DANGER)
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

    def _act(self, file_path, folder):
        target = os.path.dirname(file_path) if folder else file_path
        if target and os.path.exists(target):
            open_in_os(target)
        self.accept()


class VideoInfoDialog(QDialog):
    """Отдельное окно с полной информацией о видео (все потоки, все поля)."""

    def __init__(self, video_info, file_path, preview_pixmap=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подробная информация")
        self.setStyleSheet(T.STYLESHEET_MAIN)
        if parent is not None:
            try:
                self.setWindowIcon(parent.windowIcon())
            except Exception:
                pass
        self.resize(560, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)
        if preview_pixmap is not None and not preview_pixmap.isNull():
            pv = QLabel()
            pv.setObjectName("previewLabel")
            pv.setFixedSize(176, 99)
            pv.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pv.setPixmap(preview_pixmap.scaled(
                176, 99, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            header.addWidget(pv, 0)
        name = QLabel(os.path.basename(file_path) if file_path else "")
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size: 10pt; font-weight: 600; color: {T.COLOR_TEXT};")
        header.addWidget(name, 1)
        layout.addLayout(header)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setHtml(self._build_html(video_info))
        layout.addWidget(self.text, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_copy = QPushButton("Копировать")
        self.btn_copy.setIcon(make_icon('copy', T.COLOR_BTN_TEXT))
        self.btn_copy.setIconSize(QSize(16, 16))
        self.btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        row.addWidget(self.btn_copy)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.setStyleSheet(T.STYLESHEET_BUTTON_PRIMARY)
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

    # ---- форматирование значений ----
    @staticmethod
    def _dur(v):
        try:
            s = int(float(v))
        except (TypeError, ValueError):
            return None
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    @staticmethod
    def _size(v):
        try:
            b = int(v)
        except (TypeError, ValueError):
            return None
        return f"{b / (1024*1024):.2f} MB ({b:,} байт)"

    @staticmethod
    def _kbps(v):
        try:
            return f"{int(v)//1000} kbps"
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _hz(v):
        try:
            return f"{int(v)/1000:.1f} kHz"
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fps(v):
        try:
            num, den = map(float, str(v).split('/'))
            return f"{num/den:.3f}".rstrip('0').rstrip('.') if den else None
        except Exception:
            return None

    def _build_html(self, info):
        muted, accent, text = T.COLOR_TEXT_MUTED, T.COLOR_BTN_TEXT, T.COLOR_TEXT

        def esc(x):
            return str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        def section(title):
            return (f'<div style="margin-top:12px;margin-bottom:3px;color:{accent};'
                    f'font-weight:700;font-size:10pt;">{esc(title)}</div>')

        def table(pairs):
            out = '<table cellspacing="0" cellpadding="2" style="font-size:9pt;">'
            any_row = False
            for k, val in pairs:
                if val in (None, '', 'N/A'):
                    continue
                any_row = True
                out += (f'<tr><td style="color:{muted};padding-right:16px;white-space:nowrap;'
                        f'vertical-align:top;">{esc(k)}</td>'
                        f'<td style="color:{text};">{esc(val)}</td></tr>')
            out += '</table>'
            return out if any_row else ''

        fmt = info.get('format', {}) or {}
        streams = info.get('streams', []) or []
        html = [f'<div style="font-family:Segoe UI;color:{text};">']

        html.append(section("Контейнер"))
        html.append(table([
            ("Формат", fmt.get('format_long_name') or fmt.get('format_name')),
            ("Расширения", fmt.get('format_name')),
            ("Длительность", self._dur(fmt.get('duration'))),
            ("Размер", self._size(fmt.get('size'))),
            ("Общий битрейт", self._kbps(fmt.get('bit_rate'))),
            ("Потоков", fmt.get('nb_streams')),
        ]))
        ftags = fmt.get('tags') or {}
        if ftags:
            html.append(table([(f"tag · {k}", v) for k, v in ftags.items()]))

        vi = ai = si = 0
        for s in streams:
            ctype = s.get('codec_type')
            tags = s.get('tags') or {}
            if ctype == 'video':
                vi += 1
                w, h = s.get('width'), s.get('height')
                html.append(section(f"Видео поток #{vi}"))
                html.append(table([
                    ("Кодек", s.get('codec_name')),
                    ("Полное имя", s.get('codec_long_name')),
                    ("Профиль", s.get('profile')),
                    ("Уровень", s.get('level')),
                    ("Разрешение", f"{w}x{h}" if w and h else None),
                    ("Соотношение сторон", s.get('display_aspect_ratio')),
                    ("Пиксельный формат", s.get('pix_fmt')),
                    ("Частота кадров", self._fps(s.get('avg_frame_rate'))),
                    ("Битрейт", self._kbps(s.get('bit_rate'))),
                    ("Кадров", s.get('nb_frames')),
                    ("Цвет. пространство", s.get('color_space')),
                    ("Порядок полей", s.get('field_order')),
                    ("Язык", tags.get('language')),
                    ("Название", tags.get('title')),
                ]))
            elif ctype == 'audio':
                ai += 1
                ch = s.get('channels')
                layout_s = s.get('channel_layout')
                html.append(section(f"Аудио поток #{ai}"))
                html.append(table([
                    ("Кодек", s.get('codec_name')),
                    ("Полное имя", s.get('codec_long_name')),
                    ("Профиль", s.get('profile')),
                    ("Частота дискретизации", self._hz(s.get('sample_rate'))),
                    ("Каналы", f"{ch} ({layout_s})" if ch and layout_s else ch),
                    ("Битрейт", self._kbps(s.get('bit_rate'))),
                    ("Язык", tags.get('language')),
                    ("Название", tags.get('title')),
                ]))
            else:
                si += 1
                html.append(section(f"{(ctype or 'поток').capitalize()} #{si}"))
                html.append(table([
                    ("Кодек", s.get('codec_name')),
                    ("Язык", tags.get('language')),
                    ("Название", tags.get('title')),
                ]))
        html.append('</div>')
        return ''.join(html)


# ============================================================================
#  Основное окно
# ============================================================================
class VideoConverter(QMainWindow):
    VIDEO_EXTS = ('.mp4', '.mkv', '.mov', '.avi', '.flv', '.webm', '.wmv',
                  '.m4v', '.mpg', '.mpeg', '.ts')
    KNOWN_CONTAINERS = {"mp4", "mkv", "mov", "avi", "flv", "webm", "wmv", "m4v",
                        "mpg", "mpeg", "ts"}
    SOFTWARE_VCODECS = ("libx264", "libx265", "libvpx-vp9")
    VIDEO_ENCODER_MAP = {
        'vp9': 'libvpx-vp9', 'av1': 'libaom-av1',
        'h264': 'libx264', 'h265': 'libx265', 'hevc': 'libx265',
    }
    TAB_EMOJI = ["🎬", "🎧", "🧾", "⚙️"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cine Convert")
        if APP_ICON:
            self.setWindowIcon(QIcon(APP_ICON))
        self.setGeometry(100, 100, 960, 830)
        self.setMinimumSize(760, 600)
        self.setAcceptDrops(True)

        cfg = load_config()
        # Восстанавливаем сохранённый размер окна
        try:
            ww, wh = cfg.get("win_size") or (0, 0)
            if int(ww) >= 760 and int(wh) >= 600:
                self.resize(int(ww), int(wh))
        except Exception:
            pass
        self.settings = {
            "show_video_notifications": cfg.get("show_video_notifications", True),
            "show_audio_notifications": cfg.get("show_audio_notifications", True),
            "open_folder_when_done": cfg.get("open_folder_when_done", False),
            "sound_notifications": cfg.get("sound_notifications", True),
        }
        self.last_dir = cfg.get("last_dir", "") or ""
        self.output_dir = cfg.get("output_dir", "") or ""
        if self.output_dir and not os.path.isdir(self.output_dir):
            self.output_dir = ""

        self.input_file = ""
        self.output_file = ""
        self.video_info = {}
        self.input_files = []
        self._current_files = []   # все выбранные файлы (для листания инфо)
        self._info_index = 0
        self._info_file = ""
        self._probe_cache = {}     # (path, mtime) -> ffprobe json — листание без подтормаживаний
        self._preview_cache = {}   # (path, mtime) -> QPixmap
        self._busy = False
        self._batch_cancelled = False
        self._encoders_cache = None
        self.ffmpeg_path = "ffmpeg"
        self.ffprobe_path = "ffprobe"
        self.translations = {}
        self.locales_map = {}
        self._sections = []
        self._primary_buttons = []
        self._danger_buttons = []
        self._icon_widgets = []   # (кнопка, kind, role) для перекраски при смене темы

        self.setup_ui()
        self._setup_icons()
        self._apply_theme()

        self.chk_video_notify.setChecked(self.settings["show_video_notifications"])
        self.chk_audio_notify.setChecked(self.settings["show_audio_notifications"])
        self.chk_open_folder.setChecked(self.settings["open_folder_when_done"])
        self.chk_sound.setChecked(self.settings["sound_notifications"])
        self.restore_render_settings(cfg)

        try:
            self.load_locales()
            lang = cfg.get('language')
            if lang:
                idx = self.locale_combo.findData(lang)
                if idx >= 0:
                    self.locale_combo.setCurrentIndex(idx)
                self.apply_locale(lang)
        except Exception:
            pass

        # Настройки применяются и сохраняются сразу (кнопки «Сохранить» нет)
        self._wire_autosave()
        self._ui_ready = True

    # ---------------------------------------------------------------- UI ----
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 8)

        # Баннер с волнами
        self.banner = BannerWidget("Cine Convert")
        self.banner.set_animated(load_config().get("wave_anim", True))
        root.addWidget(self.banner)

        # Источник
        src_group = ShadowGroupBox("Источник")
        src_group.setObjectName("group_source")
        src_layout = QGridLayout(src_group)
        src_layout.setSpacing(8)
        src_layout.setContentsMargins(14, 18, 14, 14)
        src_layout.setColumnStretch(0, 1)
        self.input_path = QLineEdit()
        self.input_path.setObjectName("input_path")
        self.input_path.setReadOnly(True)
        self.input_path.setPlaceholderText("Перетащите видео сюда или нажмите «Обзор…»")
        src_layout.addWidget(self.input_path, 0, 0)
        self.btn_browse_input = QPushButton("Обзор…")
        self.btn_browse_input.setObjectName("btn_browse_input")
        self.btn_browse_input.setToolTip("Выберите один или несколько видеофайлов")
        self.btn_browse_input.clicked.connect(self.select_input_files)
        src_layout.addWidget(self.btn_browse_input, 0, 1)
        self.btn_clear_input = QPushButton("")
        self.btn_clear_input.setToolTip("Очистить выбор")
        self.btn_clear_input.setFixedWidth(40)
        self.btn_clear_input.clicked.connect(self.clear_inputs)
        self._danger_buttons.append(self.btn_clear_input)
        src_layout.addWidget(self.btn_clear_input, 0, 2)
        root.addWidget(src_group)

        # Вкладки (сразу под источником)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("main_tabs")
        self.tabs.currentChanged.connect(self.banner.splash)
        root.addWidget(self.tabs)
        self.setup_video_tab()
        self.setup_audio_tab()
        self.setup_log_tab()
        self.setup_settings_tab()

        # Информация о видео — тонкая компактная карточка (превью + основное +
        # «Подробнее»). Прячется вместе с прогрессом на вкладках Логи/Настройки,
        # чтобы те занимали всю высоту.
        self.info_card = QFrame()
        self.info_card.setObjectName("infoCard")
        self.info_card.setMinimumHeight(192)   # ~2× прежней высоты
        info_row = QHBoxLayout(self.info_card)
        info_row.setContentsMargins(14, 12, 14, 12)
        info_row.setSpacing(16)

        self.preview_label = QLabel("нет кадра")
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setFixedSize(240, 135)
        info_row.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.info_container = QWidget()
        self.info_grid = QGridLayout(self.info_container)
        self.info_grid.setHorizontalSpacing(12)
        self.info_grid.setVerticalSpacing(6)
        self.info_grid.setContentsMargins(0, 0, 0, 0)
        for _c in (1, 3, 5):
            self.info_grid.setColumnStretch(_c, 1)
        info_row.addWidget(self.info_container, 1, Qt.AlignmentFlag.AlignVCenter)
        self._set_info_placeholder()

        # Правая колонка: листание файлов (мини-кнопки) + «Подробнее»
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addStretch(1)
        nav_row = QHBoxLayout()
        nav_row.setSpacing(4)
        self.btn_info_prev = QPushButton("")
        self.btn_info_prev.setFixedSize(26, 26)
        self.btn_info_prev.setStyleSheet("QPushButton { padding: 2px; }")
        self.btn_info_prev.setToolTip("Предыдущее видео")
        self.btn_info_prev.clicked.connect(lambda: self._show_info_at(self._info_index - 1))
        nav_row.addWidget(self.btn_info_prev)
        self.info_nav_label = QLabel("1/1")
        self.info_nav_label.setObjectName("statsLabel")
        self.info_nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_nav_label.setMinimumWidth(36)
        nav_row.addWidget(self.info_nav_label)
        self.btn_info_next = QPushButton("")
        self.btn_info_next.setFixedSize(26, 26)
        self.btn_info_next.setStyleSheet("QPushButton { padding: 2px; }")
        self.btn_info_next.setToolTip("Следующее видео")
        self.btn_info_next.clicked.connect(lambda: self._show_info_at(self._info_index + 1))
        nav_row.addWidget(self.btn_info_next)
        right_col.addLayout(nav_row)
        self.btn_details = QPushButton("Подробнее")
        self.btn_details.setToolTip("Полная информация о видео в отдельном окне")
        self.btn_details.setEnabled(False)
        self.btn_details.clicked.connect(self._show_video_details)
        right_col.addWidget(self.btn_details)
        right_col.addStretch(1)
        info_row.addLayout(right_col, 0)
        self._set_info_nav_visible(False)

        root.addWidget(self.info_card)

        # Прогресс
        self.batch_status_label = QLabel("")
        self.batch_status_label.setObjectName("batchStatus")
        self.batch_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.batch_status_label.setMinimumHeight(18)
        root.addWidget(self.batch_status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.progress_bar)
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("statsLabel")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setMinimumHeight(16)
        root.addWidget(self.stats_label)

        # На Логах/Настройках прячем инфо+прогресс (вкладка занимает всё место)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabs.currentIndex())

    def _on_tab_changed(self, index):
        """Видео/Аудио — показываем инфо о видео и прогресс; Логи/Настройки —
        прячем их, чтобы вкладка занимала всю высоту окна."""
        show = index in (0, 1)
        for w in (self.info_card, self.batch_status_label,
                  self.progress_bar, self.stats_label):
            w.setVisible(show)

    def _field_column(self, label, widget, obj_name):
        label.setObjectName("fieldLabel")
        widget.setObjectName(obj_name)
        label.setMinimumHeight(16)
        widget.setMinimumHeight(32)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(label)
        col.addWidget(widget)
        return col

    def setup_video_tab(self):
        tab = QWidget()
        tab_outer = QVBoxLayout(tab)
        tab_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        tab_outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(4, 10, 4, 4)
        outer.setSpacing(10)

        group = ShadowGroupBox("Настройки видео")
        group.setObjectName("group_video_settings")
        row = QHBoxLayout(group)
        row.setContentsMargins(16, 20, 16, 16)
        row.setSpacing(12)

        self.lbl_resolution = QLabel("Разрешение")
        self.resolution = QComboBox()
        for text, data in [
            ("Без изменений", None), ("4K (3840x2160)", "3840:2160"),
            ("1440p (2560x1440)", "2560:1440"), ("1080p (1920x1080)", "1920:1080"),
            ("720p (1280x720)", "1280:720"), ("480p (854x480)", "854:480"),
            ("360p (640x360)", "640:360"), ("240p (426x240)", "426:240"),
            ("144p (256x144)", "256:144"), ("128p (256x128)", "256:128"),
        ]:
            self.resolution.addItem(text, data)
        row.addLayout(self._field_column(self.lbl_resolution, self.resolution, "resolution"), 1)

        self.lbl_codec = QLabel("Кодек")
        self.video_codec = QComboBox()
        for text, data in [
            ("Без изменений", None), ("libx264", "libx264"), ("libx265", "libx265"),
            ("h264_nvenc", "h264_nvenc"), ("hevc_nvenc", "hevc_nvenc"),
            ("vp9", "vp9"), ("av1", "av1"),
        ]:
            self.video_codec.addItem(text, data)
        row.addLayout(self._field_column(self.lbl_codec, self.video_codec, "video_codec"), 1)

        self.lbl_bitrate = QLabel("Битрейт")
        self.bitrate = QComboBox()
        self.bitrate.setEditable(True)
        self.bitrate.addItems(["Без изменений", "500k", "1M", "2M", "5M", "10M", "20M"])
        self.bitrate.setToolTip("Целевой битрейт видео (напр. 2M). «Без изменений» — не задавать.")
        row.addLayout(self._field_column(self.lbl_bitrate, self.bitrate, "bitrate"), 1)

        self.lbl_format = QLabel("Формат")
        self.format = QComboBox()
        for text, data in [
            ("Без изменений", None), ("mp4", "mp4"), ("mkv", "mkv"), ("mov", "mov"),
            ("avi", "avi"), ("flv", "flv"), ("webm", "webm"),
        ]:
            self.format.addItem(text, data)
        self.format.setToolTip("Контейнер выходного файла. «Без изменений» — оставить исходный.")
        row.addLayout(self._field_column(self.lbl_format, self.format, "format"), 1)

        self.btn_render = QPushButton("Рендер")
        self.btn_render.setStyleSheet(T.STYLESHEET_BUTTON_PRIMARY)
        self.btn_render.setMinimumHeight(52)
        self.btn_render.clicked.connect(self.start_video_render)
        self._primary_buttons.append(self.btn_render)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setMinimumHeight(52)
        self.btn_cancel.clicked.connect(self.cancel_current)
        self.btn_cancel.setVisible(False)
        self._danger_buttons.append(self.btn_cancel)
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        sp = QLabel(" ")
        sp.setObjectName("fieldLabel")
        sp.setMinimumHeight(16)
        btn_col.addWidget(sp)
        btn_col.addWidget(self.btn_render)
        btn_col.addWidget(self.btn_cancel)
        row.addLayout(btn_col, 1)
        outer.addWidget(group)

        # Аудио при конвертации видео (перенесено сюда, под настройки видео)
        conv_group = ShadowGroupBox("Аудио при конвертации видео")
        conv_group.setObjectName("group_audio_settings")
        conv_group.setMinimumHeight(104)
        crow = QHBoxLayout(conv_group)
        crow.setContentsMargins(16, 20, 16, 16)
        crow.setSpacing(12)

        self.lbl_acodec = QLabel("Аудио кодек")
        self.audio_codec = QComboBox()
        for text, data in [
            ("Без изменений", None), ("Копировать (copy)", "copy"),
            ("aac", "aac"), ("mp3", "mp3"), ("flac", "flac"),
            ("opus", "opus"), ("ac3", "ac3"),
        ]:
            self.audio_codec.addItem(text, data)
        crow.addLayout(self._field_column(self.lbl_acodec, self.audio_codec, "audio_codec"), 1)

        self.lbl_abitrate = QLabel("Битрейт аудио")
        self.audio_bitrate = QComboBox()
        self.audio_bitrate.setEditable(True)
        self.audio_bitrate.addItems(["Без изменений", "64k", "128k", "192k", "256k", "320k"])
        crow.addLayout(self._field_column(self.lbl_abitrate, self.audio_bitrate, "audio_bitrate"), 1)

        self.lbl_achannels = QLabel("Каналы")
        self.audio_channels = QComboBox()
        for text, data in [
            ("Без изменений", None), ("1 (моно)", "1"), ("2 (стерео)", "2"),
            ("5.1", "6"), ("7.1", "8"),
        ]:
            self.audio_channels.addItem(text, data)
        crow.addLayout(self._field_column(self.lbl_achannels, self.audio_channels, "audio_channels"), 1)
        outer.addWidget(conv_group)

        outer.addStretch(1)
        self.tabs.addTab(tab, "Видео")

    def setup_audio_tab(self):
        """Вкладка «Аудио» — только извлечение звуковой дорожки в файл."""
        tab = QWidget()
        tab_outer = QVBoxLayout(tab)
        tab_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        tab_outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(4, 10, 4, 4)
        outer.setSpacing(10)

        extract_group = ShadowGroupBox("Извлечение аудио")
        extract_group.setObjectName("group_audio_extract")
        extract_group.setMinimumHeight(112)
        erow = QHBoxLayout(extract_group)
        erow.setContentsMargins(16, 20, 16, 16)
        erow.setSpacing(12)
        self.lbl_aformat = QLabel("Формат аудио")
        self.audio_format = QComboBox()
        for fmt in ["mp3", "aac", "flac", "wav", "ogg", "ac3"]:
            self.audio_format.addItem(fmt, fmt)
        erow.addLayout(self._field_column(self.lbl_aformat, self.audio_format, "audio_format"), 1)
        self.btn_extract = QPushButton("Извлечь аудио")
        self.btn_extract.setObjectName("btn_extract")
        self.btn_extract.setStyleSheet(T.STYLESHEET_BUTTON_PRIMARY)
        self.btn_extract.setMinimumHeight(52)
        self.btn_extract.clicked.connect(self.extract_audio)
        self._primary_buttons.append(self.btn_extract)
        ecol = QVBoxLayout()
        ecol.setSpacing(4)
        esp = QLabel(" ")
        esp.setObjectName("fieldLabel")
        esp.setMinimumHeight(16)
        ecol.addWidget(esp)
        ecol.addWidget(self.btn_extract)
        erow.addLayout(ecol, 2)
        outer.addWidget(extract_group)
        outer.addStretch(1)
        self.tabs.addTab(tab, "Аудио")

    def setup_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(8)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_clear_log = QPushButton("Очистить")
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        btns.addWidget(self.btn_clear_log)
        self.btn_copy_log = QPushButton("Копировать")
        self.btn_copy_log.clicked.connect(self._copy_log)
        btns.addWidget(self.btn_copy_log)
        layout.addLayout(btns)
        self.tabs.addTab(tab, "Логи")

    def _copy_log(self):
        QApplication.clipboard().setText(self.log_text.toPlainText())

    def _make_section(self, title):
        box = CollapsibleBox(title)
        self._sections.append(box)
        return box

    def setup_settings_tab(self):
        tab = QWidget()
        tab_outer = QVBoxLayout(tab)
        tab_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame if hasattr(QFrame, 'Shape') else QFrame.NoFrame)
        tab_outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(10)
        layout.setContentsMargins(6, 10, 6, 10)

        # Папка сохранения
        self.dir_group = self._make_section("📁  Папка сохранения")
        dl = QGridLayout()
        dl.setContentsMargins(6, 4, 6, 6)
        dl.setSpacing(8)
        dl.setColumnStretch(0, 1)
        self.output_dir_input = QLineEdit(self.output_dir)
        self.output_dir_input.setReadOnly(True)
        self.output_dir_input.setPlaceholderText("Рядом с исходным файлом")
        dl.addWidget(self.output_dir_input, 0, 0)
        self.btn_choose_output = QPushButton("Выбрать…")
        self.btn_choose_output.clicked.connect(self._choose_output_dir)
        dl.addWidget(self.btn_choose_output, 0, 1)
        self.btn_reset_output = QPushButton("Рядом с исходным")
        self.btn_reset_output.clicked.connect(self._reset_output_dir)
        self._danger_buttons.append(self.btn_reset_output)
        dl.addWidget(self.btn_reset_output, 0, 2)
        hint = QLabel("Перед каждым рендером спросим, куда сохранить (папка по умолчанию — отсюда).")
        hint.setObjectName("statsLabel")
        hint.setWordWrap(True)
        dl.addWidget(hint, 1, 0, 1, 3)
        self.dir_group.setContentLayout(dl)
        layout.addWidget(self.dir_group)

        # Уведомления
        self.notif_group = self._make_section("🔔  Уведомления")
        nl = QVBoxLayout()
        nl.setContentsMargins(6, 4, 6, 6)
        self.chk_video_notify = QCheckBox("Показывать уведомление после рендеринга видео")
        self.chk_video_notify.setObjectName("chk_video_notify")
        self.chk_audio_notify = QCheckBox("Показывать уведомление после извлечения аудио")
        self.chk_audio_notify.setObjectName("chk_audio_notify")
        self.chk_open_folder = QCheckBox("Открывать папку с результатом по завершении")
        self.chk_open_folder.setObjectName("chk_open_folder")
        self.chk_sound = QCheckBox("Звуковой сигнал при уведомлении")
        self.chk_sound.setObjectName("chk_sound")
        for cbx in (self.chk_video_notify, self.chk_audio_notify, self.chk_open_folder, self.chk_sound):
            nl.addWidget(cbx)
        self.notif_group.setContentLayout(nl)
        layout.addWidget(self.notif_group)

        # Язык
        self.lang_group = self._make_section("🌐  Язык интерфейса")
        ll = QHBoxLayout()
        ll.setContentsMargins(6, 4, 6, 6)
        ll.setSpacing(8)
        self.locale_combo = QComboBox()
        self.locale_combo.setToolTip("Язык применяется сразу при выборе")
        self.locale_combo.currentIndexChanged.connect(self._on_locale_changed)
        ll.addWidget(self.locale_combo, 1)
        self.btn_refresh_locales = QPushButton("Обновить")
        self.btn_refresh_locales.setObjectName("btn_refresh_locales")
        self.btn_refresh_locales.clicked.connect(self.load_locales)
        ll.addWidget(self.btn_refresh_locales)
        self.btn_open_locales = QPushButton("Папка")
        self.btn_open_locales.setObjectName("btn_open_locales")
        self.btn_open_locales.clicked.connect(self.open_locales_folder)
        ll.addWidget(self.btn_open_locales)
        self.lang_group.setContentLayout(ll)
        layout.addWidget(self.lang_group)

        # Внешний вид (тема)
        self.theme_group = self._make_section("🎨  Внешний вид")
        tl = QGridLayout()
        tl.setContentsMargins(6, 4, 6, 6)
        tl.setHorizontalSpacing(12)
        tl.setVerticalSpacing(10)
        tl.setColumnStretch(1, 1)

        self.lbl_color = QLabel("Цвет")
        tl.addWidget(self.lbl_color, 0, 0)
        hue_row = QHBoxLayout()
        hue_row.setSpacing(10)
        self.hue_slider = QSlider(Qt.Orientation.Horizontal)
        self.hue_slider.setRange(0, 360)
        self.hue_slider.setValue(T.CURRENT_HUE)
        self.hue_slider.valueChanged.connect(self._on_hue_changed)
        self.hue_slider.sliderReleased.connect(lambda: save_config(hue=self.hue_slider.value()))
        hue_row.addWidget(self.hue_slider, 1)
        self.hue_swatch = QLabel()
        self.hue_swatch.setFixedSize(22, 22)
        hue_row.addWidget(self.hue_swatch)
        self.color_pick_btn = QPushButton("🎨")
        self.color_pick_btn.setFixedSize(34, 28)
        self.color_pick_btn.setToolTip("Выбрать цвет…")
        self.color_pick_btn.clicked.connect(self._pick_color)
        hue_row.addWidget(self.color_pick_btn)
        tl.addLayout(hue_row, 0, 1)

        self.lbl_saturation = QLabel("Насыщенность")
        tl.addWidget(self.lbl_saturation, 1, 0)
        sat_row = QHBoxLayout()
        sat_row.setSpacing(10)
        self.sat_slider = QSlider(Qt.Orientation.Horizontal)
        self.sat_slider.setRange(50, 160)
        self.sat_slider.setValue(T.CURRENT_SATURATION)
        self.sat_slider.valueChanged.connect(self._on_sat_changed)
        self.sat_slider.sliderReleased.connect(lambda: save_config(saturation=self.sat_slider.value()))
        sat_row.addWidget(self.sat_slider, 1)
        self.sat_value = QLabel(f"{T.CURRENT_SATURATION}%")
        self.sat_value.setFixedWidth(46)
        self.sat_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sat_row.addWidget(self.sat_value)
        tl.addLayout(sat_row, 1, 1)

        self.lbl_mode = QLabel("Режим")
        tl.addWidget(self.lbl_mode, 2, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Светлая", "light")
        self.mode_combo.addItem("Тёмная", "dark")
        self.mode_combo.addItem("Системная", "system")
        cfg = load_config()
        mi = self.mode_combo.findData(cfg.get("theme_mode", "light"))
        if mi >= 0:
            self.mode_combo.setCurrentIndex(mi)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        tl.addWidget(self.mode_combo, 2, 1)

        self.chk_wave = QCheckBox("Анимированные волны в шапке")
        self.chk_wave.setChecked(cfg.get("wave_anim", True))
        self.chk_wave.stateChanged.connect(self._on_wave_toggled)
        tl.addWidget(self.chk_wave, 3, 1)
        self.theme_group.setContentLayout(tl)
        layout.addWidget(self.theme_group)

        # FFmpeg / обновление библиотек
        self.tools_group = self._make_section("🔧  FFmpeg (обновление)")
        fl = QVBoxLayout()
        fl.setContentsMargins(6, 4, 6, 6)
        fl.setSpacing(8)
        self.ffmpeg_version_label = QLabel("FFmpeg: проверка…")
        self.ffmpeg_version_label.setObjectName("statsLabel")
        self.ffmpeg_version_label.setWordWrap(True)
        fl.addWidget(self.ffmpeg_version_label)
        frow = QHBoxLayout()
        frow.setSpacing(8)
        self.btn_update_ffmpeg = QPushButton("Обновить FFmpeg до последней версии")
        self.btn_update_ffmpeg.setStyleSheet(T.STYLESHEET_BUTTON_PRIMARY)
        self.btn_update_ffmpeg.clicked.connect(self._update_ffmpeg)
        self._primary_buttons.append(self.btn_update_ffmpeg)
        frow.addWidget(self.btn_update_ffmpeg, 1)
        self.btn_ffmpeg_folder = QPushButton("Папка")
        self.btn_ffmpeg_folder.clicked.connect(
            lambda: open_in_os(os.path.join(APP_DIR, "ffmpeg", "bin")))
        frow.addWidget(self.btn_ffmpeg_folder)
        fl.addLayout(frow)
        fhint = QLabel("Скачивает свежую сборку FFmpeg (gyan.dev, release-essentials) "
                       "в папку рядом с программой. Нужен интернет.")
        fhint.setObjectName("statsLabel")
        fhint.setWordWrap(True)
        fl.addWidget(fhint)
        self.tools_group.setContentLayout(fl)
        layout.addWidget(self.tools_group)

        layout.addStretch(1)
        self.tabs.addTab(tab, "Настройки")

    # ------------------------------------------------------------- Тема ----
    def _apply_theme(self):
        self.setStyleSheet(T.STYLESHEET_MAIN)
        for gb in self.findChildren(ShadowGroupBox):
            gb.setStyleSheet(T.STYLESHEET_GROUPBOX)
        for b in self._primary_buttons:
            b.setStyleSheet(T.STYLESHEET_BUTTON_PRIMARY)
        for b in self._danger_buttons:
            b.setStyleSheet(T.STYLESHEET_BUTTON_DANGER)
        if hasattr(self, 'hue_slider'):
            self.hue_slider.setStyleSheet(T.STYLESHEET_HUE_SLIDER)
            self.sat_slider.setStyleSheet(T.STYLESHEET_SAT_SLIDER)
            self.hue_swatch.setStyleSheet(f"background: {T.COLOR_PRIMARY}; border-radius: 11px;")
            self.sat_value.setText(f"{T.CURRENT_SATURATION}%")
        for box in self._sections:
            box.apply_theme()
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setStyleSheet(T.STYLESHEET_PROGRESS_BAR)
        if hasattr(self, 'banner'):
            self.banner.update()
        self._rebuild_icons()

    # --------------------------------------------------------- Иконки ------
    ICON_SIZE = 16

    def _reg_icon(self, widget, kind, role):
        widget.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
        self._icon_widgets.append((widget, kind, role))

    @staticmethod
    def _icon_color(role):
        if role == 'primary':
            return "#ffffff"
        if role == 'danger':
            return T.COLOR_RED
        return T.COLOR_BTN_TEXT

    def _rebuild_icons(self):
        for widget, kind, role in self._icon_widgets:
            widget.setIcon(make_icon(kind, self._icon_color(role)))
        self._update_tab_icons()

    def _update_tab_icons(self):
        kinds = ['video', 'audio', 'logs', 'settings']
        cur = self.tabs.currentIndex()
        for i, k in enumerate(kinds):
            if i < self.tabs.count():
                color = "#ffffff" if i == cur else T.COLOR_TEXT_MUTED
                self.tabs.setTabIcon(i, make_icon(k, color))

    def _setup_icons(self):
        self.tabs.setIconSize(QSize(17, 17))
        self.tabs.currentChanged.connect(self._update_tab_icons)
        for w, kind, role in (
            (self.btn_render, 'play', 'primary'),
            (self.btn_extract, 'download', 'primary'),
            (self.btn_update_ffmpeg, 'refresh', 'primary'),
            (self.btn_clear_input, 'close', 'danger'),
            (self.btn_cancel, 'close', 'danger'),
            (self.btn_reset_output, 'close', 'danger'),
            (self.btn_details, 'info', 'secondary'),
            (self.btn_info_prev, 'prev', 'secondary'),
            (self.btn_info_next, 'next', 'secondary'),
            (self.btn_browse_input, 'folder', 'secondary'),
            (self.btn_choose_output, 'folder', 'secondary'),
            (self.btn_ffmpeg_folder, 'folder', 'secondary'),
            (self.btn_open_locales, 'folder', 'secondary'),
            (self.btn_clear_log, 'trash', 'secondary'),
            (self.btn_copy_log, 'copy', 'secondary'),
            (self.btn_refresh_locales, 'refresh', 'secondary'),
        ):
            self._reg_icon(w, kind, role)

    def _on_hue_changed(self, value):
        set_theme(hue=value)
        self._apply_theme()

    def _on_sat_changed(self, value):
        set_theme(saturation=value)
        self._apply_theme()

    def _on_mode_changed(self):
        mode = self.mode_combo.currentData() or "light"
        set_theme(dark=is_system_dark() if mode == "system" else (mode == "dark"))
        save_config(theme_mode=mode)
        self._apply_theme()

    def _on_wave_toggled(self):
        on = self.chk_wave.isChecked()
        save_config(wave_anim=on)
        self.banner.set_animated(on)

    def _pick_color(self):
        dlg = QColorDialog(self)
        try:
            dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        except Exception:
            pass
        dlg.setCurrentColor(QColor(T.COLOR_PRIMARY))
        dlg.setWindowTitle("Выбор цвета")
        if dlg.exec():
            col = dlg.currentColor()
            _, C, H = srgb_to_oklch(col.red(), col.green(), col.blue())
            self.hue_slider.setValue(int(round(H)))
            self.sat_slider.setValue(max(50, min(160, int(round(C / 0.14 * 100)))))
            save_config(hue=T.CURRENT_HUE, saturation=T.CURRENT_SATURATION)

    # ---------------------------------------------- Папка сохранения -------
    def _choose_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для сохранения",
                                             self.output_dir or self.last_dir or "")
        if d:
            self.output_dir = d
            self.output_dir_input.setText(d)
            save_config(output_dir=d)

    def _reset_output_dir(self):
        self.output_dir = ""
        self.output_dir_input.clear()
        save_config(output_dir="")

    # ---------------------------------------------- Обновление FFmpeg ------
    def _ffmpeg_version_text(self):
        try:
            r = run_hidden([getattr(self, "ffmpeg_path", "ffmpeg"), "-version"],
                           capture_output=True, text=True, timeout=8)
            first = (r.stdout or "").splitlines()[0] if r.stdout else ""
            return first.strip() or "FFmpeg: версия неизвестна"
        except Exception:
            return "FFmpeg: не найден"

    def refresh_ffmpeg_label(self):
        if hasattr(self, "ffmpeg_version_label"):
            self.ffmpeg_version_label.setText(self._ffmpeg_version_text())

    def _update_ffmpeg(self):
        if self._busy:
            QMessageBox.information(self, "Занято", "Дождитесь завершения текущей операции.")
            return
        FFmpegSetupDialog("update", self).exec()
        ff, fp = find_ffmpeg()
        if ff:
            self.ffmpeg_path = ff
            self.ffprobe_path = fp or ff
            self._encoders_cache = None
            self.refresh_ffmpeg_label()

    # ------------------------------------------------- Значения комбо ------
    @staticmethod
    def _combo_editable_value(combo):
        txt = combo.currentText().strip()
        if not txt:
            return None
        token = txt.split()[0]
        return token if _BITRATE_RE.match(token) else None

    def current_render_settings(self):
        return {
            "resolution": self.resolution.currentData(),
            "video_codec": self.video_codec.currentData(),
            "bitrate": self._combo_editable_value(self.bitrate),
            "format": self.format.currentData(),
            "audio_codec": self.audio_codec.currentData(),
            "audio_bitrate": self._combo_editable_value(self.audio_bitrate),
            "audio_channels": self.audio_channels.currentData(),
            "audio_format": self.audio_format.currentData(),
        }

    @staticmethod
    def _restore_combo(combo, value, editable=False):
        if value is None:
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
        if editable:
            i = combo.findText(str(value))
            if i >= 0:
                combo.setCurrentIndex(i)
            else:
                combo.setEditText(str(value))

    def restore_render_settings(self, cfg):
        saved = cfg.get("render_settings") or {}
        if not isinstance(saved, dict):
            return
        self._restore_combo(self.resolution, saved.get("resolution"))
        self._restore_combo(self.video_codec, saved.get("video_codec"))
        self._restore_combo(self.bitrate, saved.get("bitrate"), editable=True)
        self._restore_combo(self.format, saved.get("format"))
        self._restore_combo(self.audio_codec, saved.get("audio_codec"))
        self._restore_combo(self.audio_bitrate, saved.get("audio_bitrate"), editable=True)
        self._restore_combo(self.audio_channels, saved.get("audio_channels"))
        if saved.get("audio_format"):
            self._restore_combo(self.audio_format, saved.get("audio_format"))

    # ----------------------------------------------- Автосохранение --------
    def _save_setting(self, key, value):
        """Чекбоксы настроек: применяются и пишутся в config сразу."""
        self.settings[key] = bool(value)
        if getattr(self, '_ui_ready', False):
            save_config(**{key: bool(value)})

    def _save_render_settings(self, *_args):
        """Комбобоксы кодирования: сохраняются при каждом изменении."""
        if getattr(self, '_ui_ready', False):
            save_config(render_settings=self.current_render_settings())

    def _on_locale_changed(self):
        if not getattr(self, '_ui_ready', False):
            return
        code = self.locale_combo.currentData()
        if code:
            self.apply_locale(code)
            save_config(language=code)

    def _wire_autosave(self):
        for chk, key in ((self.chk_video_notify, 'show_video_notifications'),
                         (self.chk_audio_notify, 'show_audio_notifications'),
                         (self.chk_open_folder, 'open_folder_when_done'),
                         (self.chk_sound, 'sound_notifications')):
            chk.toggled.connect(lambda v, k=key: self._save_setting(k, v))
        for combo in (self.resolution, self.video_codec, self.bitrate, self.format,
                      self.audio_codec, self.audio_bitrate, self.audio_channels,
                      self.audio_format):
            combo.currentIndexChanged.connect(self._save_render_settings)
            if combo.isEditable():
                combo.editTextChanged.connect(self._save_render_settings)

    def tr_or(self, text):
        try:
            v = self.translations.get(text)
            return v if isinstance(v, str) else text
        except Exception:
            return text

    # ------------------------------------------------------- Локализация ---
    def load_locales(self):
        locales_dir = (os.path.join(RESOURCE_DIR, 'locales')
                       if os.path.exists(os.path.join(RESOURCE_DIR, 'locales'))
                       else os.path.join(APP_DIR, 'locales'))
        try:
            os.makedirs(locales_dir, exist_ok=True)
        except Exception:
            pass
        current = self.locale_combo.currentData()
        self.locales_map = {}
        self.locale_combo.blockSignals(True)
        self.locale_combo.clear()
        try:
            for fname in sorted(f for f in os.listdir(locales_dir) if f.lower().endswith('.json')):
                code = os.path.splitext(fname)[0]
                path = os.path.join(locales_dir, fname)
                display = code
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, dict) and data.get('name'):
                            display = f"{data.get('name')} ({code})"
                except Exception:
                    pass
                self.locales_map[code] = path
                self.locale_combo.addItem(display, code)
        except Exception:
            pass
        if current:
            idx = self.locale_combo.findData(current)
            if idx >= 0:
                self.locale_combo.setCurrentIndex(idx)
        self.locale_combo.blockSignals(False)

    def open_locales_folder(self):
        open_in_os(os.path.join(APP_DIR, 'locales'))

    def apply_locale(self, code):
        path = self.locales_map.get(code)
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        self.translations = t = data
        if t.get('window_title'):
            self.setWindowTitle(t['window_title'])

        tab_keys = ['tab_video', 'tab_audio', 'tab_logs', 'tab_settings']
        for i, key in enumerate(tab_keys):
            if i < self.tabs.count():
                val = t.get(key) or (t.get('tab_audio_settings') if key == 'tab_audio' else None)
                if isinstance(val, str):
                    self.tabs.setTabText(i, val)

        def apply_widget(w):
            obj = w.objectName()
            if not obj or obj not in t or not isinstance(t[obj], str):
                return
            txt = t[obj]
            if isinstance(w, QPushButton):
                w.setText(txt)
            elif isinstance(w, QCheckBox):
                w.setText(txt)
            elif isinstance(w, QGroupBox):
                w.setTitle(txt)
            elif isinstance(w, QLineEdit):
                w.setPlaceholderText(txt)
            elif isinstance(w, QLabel):
                w.setText(txt)

        for w in self.findChildren(QWidget):
            try:
                apply_widget(w)
                if isinstance(w, QComboBox):
                    for i in range(w.count()):
                        it = w.itemText(i)
                        if it in t and isinstance(t[it], str):
                            w.setItemText(i, t[it])
            except Exception:
                continue

    # --------------------------------------------------- Загрузка файлов ---
    def _load_inputs(self, files):
        files = [f for f in files if f]
        if not files:
            return
        self.input_files = files if len(files) > 1 else []
        self.input_file = files[0]
        if len(files) > 1:
            self.input_path.setText(f"▤  Выбрано файлов: {len(files)}")
            self.input_path.setToolTip("\n".join(files))
        else:
            self.input_path.setText(files[0])
            self.input_path.setToolTip(files[0])
        self.output_file = ""
        self.last_dir = os.path.dirname(files[0])
        save_config(last_dir=self.last_dir)
        self._current_files = files
        self._show_info_at(0)

    def clear_inputs(self):
        self.input_files = []
        self.input_file = ""
        self.output_file = ""
        self._current_files = []
        self._info_index = 0
        self._info_file = ""
        self.input_path.clear()
        self.input_path.setToolTip("")
        self.video_info = {}
        self._set_info_placeholder()
        self.btn_details.setEnabled(False)
        self._set_info_nav_visible(False)
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("нет кадра")

    # ---- листание информации по выбранным файлам ----
    def _set_info_nav_visible(self, visible):
        for wdg in (self.btn_info_prev, self.info_nav_label, self.btn_info_next):
            wdg.setVisible(visible)

    def _show_info_at(self, index):
        files = self._current_files
        if not files:
            return
        index = max(0, min(index, len(files) - 1))
        self._info_index = index
        self._info_file = files[index]
        self.load_video_info(self._info_file)
        self.show_video_preview(self._info_file)
        self.info_nav_label.setText(f"{index + 1}/{len(files)}")
        self.info_nav_label.setToolTip(os.path.basename(self._info_file))
        self.btn_info_prev.setEnabled(index > 0)
        self.btn_info_next.setEnabled(index < len(files) - 1)
        self._set_info_nav_visible(len(files) > 1)

    def select_input_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите видеофайлы (один или несколько)", self.last_dir,
            "Видеофайлы (*.mp4 *.mkv *.mov *.avi *.flv *.webm *.wmv *.m4v *.mpg *.mpeg *.ts);;Все файлы (*.*)")
        if files:
            self._load_inputs(files)

    def dragEnterEvent(self, event):
        try:
            md = event.mimeData()
            if md.hasUrls() and any(
                    u.toLocalFile().lower().endswith(self.VIDEO_EXTS) for u in md.urls()):
                event.acceptProposedAction()
                return
        except Exception:
            pass
        event.ignore()

    def dropEvent(self, event):
        try:
            paths = [u.toLocalFile() for u in event.mimeData().urls()]
            paths = [p for p in paths if p.lower().endswith(self.VIDEO_EXTS) and os.path.isfile(p)]
            if paths:
                self._load_inputs(paths)
                event.acceptProposedAction()
        except Exception:
            pass

    # ------------------------------------------------- Информация о видео --
    def _clear_info(self):
        while self.info_grid.count():
            item = self.info_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _set_info_placeholder(self):
        self._clear_info()
        lbl = QLabel("Выберите видео, чтобы увидеть информацию о нём")
        lbl.setObjectName("infoKey")
        lbl.setWordWrap(True)
        self.info_grid.addWidget(lbl, 0, 0, 1, 4)

    def _set_info_pairs(self, pairs):
        self._clear_info()
        row = col = 0
        for key, val in pairs:
            k = QLabel(str(key))
            k.setObjectName("infoKey")
            v = QLabel(str(val))
            v.setObjectName("infoVal")
            self.info_grid.addWidget(k, row, col * 2)
            self.info_grid.addWidget(v, row, col * 2 + 1)
            col += 1
            if col > 2:   # 3 пары в ряд → компактно в 2 строки
                col = 0
                row += 1

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _cache_key(path):
        try:
            return (path, os.path.getmtime(path))
        except OSError:
            return (path, 0)

    def load_video_info(self, file_path):
        try:
            key = self._cache_key(file_path)
            info = self._probe_cache.get(key)
            if info is None:
                cmd = [getattr(self, "ffprobe_path", "ffprobe"), '-v', 'error',
                       '-show_format', '-show_streams', '-of', 'json', file_path]
                result = run_hidden(cmd, capture_output=True, text=True, check=True, timeout=30)
                info = json.loads(result.stdout)
                if len(self._probe_cache) > 64:
                    self._probe_cache.clear()
                self._probe_cache[key] = info
            self.video_info = info
            streams = info.get('streams', [])
            fmt = info.get('format', {})
            vstreams = [s for s in streams if s.get('codec_type') == 'video']
            astreams = [s for s in streams if s.get('codec_type') == 'audio']
            v = vstreams[0] if vstreams else {}
            a = astreams[0] if astreams else {}

            def short(val, n=22):
                s = str(val)
                return s if len(s) <= n else s[:n - 1] + '…'

            # Расширенный основной набор: 12 фактов, 4 ряда × 3 колонки.
            # Значения укорачиваются, чтобы ничего не вылезало из карточки.
            pairs = []
            w, h = v.get('width'), v.get('height')
            pairs.append(("Разрешение:", f"{w}x{h}" if w and h else "—"))
            dur = self._safe_float(fmt.get('duration')) or self._safe_float(v.get('duration'))
            if dur:
                m, sec = divmod(int(dur), 60)
                hh, m = divmod(m, 60)
                dtext = f"{hh}:{m:02d}:{sec:02d}" if hh else f"{m}:{sec:02d}"
            else:
                dtext = "—"
            pairs.append(("Длительность:", dtext))
            size = self._safe_int(fmt.get('size'))
            pairs.append(("Размер:", f"{size / (1024 * 1024):.1f} MB" if size else "—"))

            pairs.append(("Видео:", short(v.get('codec_name') or "—", 16)))
            fps = "—"
            try:
                num, den = map(float, str(v.get('avg_frame_rate', '0/0')).split('/'))
                if den:
                    fps = f"{num / den:.2f}".rstrip('0').rstrip('.')
            except Exception:
                pass
            pairs.append(("FPS:", fps))
            vbr = self._safe_int(v.get('bit_rate'))
            pairs.append(("Битрейт видео:", f"{vbr // 1000} kbps" if vbr else "—"))

            pairs.append(("Аудио:", short(a.get('codec_name') or "—", 16)))
            ch = a.get('channels')
            lay = a.get('channel_layout')
            pairs.append(("Каналы:", short(f"{ch} ({lay})" if ch and lay else (ch or "—"), 16)))
            sr = self._safe_int(a.get('sample_rate'))
            pairs.append(("Частота:", f"{sr / 1000:.1f} kHz" if sr else "—"))

            pairs.append(("Контейнер:", short((fmt.get('format_name') or "—").split(',')[0], 16)))
            tbr = self._safe_int(fmt.get('bit_rate'))
            pairs.append(("Общий битрейт:", f"{tbr // 1000} kbps" if tbr else "—"))
            pairs.append(("Пикс. формат:", short(v.get('pix_fmt') or "—", 16)))

            self._set_info_pairs(pairs)
            self.btn_details.setEnabled(True)
        except Exception as e:
            self._clear_info()
            err = QLabel(f"Ошибка получения информации: {e}")
            err.setObjectName("infoKey")
            err.setWordWrap(True)
            self.info_grid.addWidget(err, 0, 0, 1, 4)
            self.btn_details.setEnabled(False)

    def _show_video_details(self):
        if not self.video_info:
            return
        VideoInfoDialog(self.video_info, self._info_file or self.input_file,
                        self.preview_label.pixmap(), self).exec()

    def show_video_preview(self, file_path):
        key = self._cache_key(file_path)
        cached = self._preview_cache.get(key)
        if cached is not None and not cached.isNull():
            self.preview_label.setPixmap(cached)
            return
        preview_path = os.path.join(tempfile.gettempdir(), f"cineconvert_preview_{os.getpid()}.jpg")
        try:
            ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
            if os.path.isabs(ffmpeg_cmd):
                if not os.path.exists(ffmpeg_cmd):
                    raise FileNotFoundError(ffmpeg_cmd)
            elif shutil.which(ffmpeg_cmd) is None:
                raise FileNotFoundError(ffmpeg_cmd)
            ss = "00:00:01"
            dur = self._safe_float(self.video_info.get('format', {}).get('duration'))
            if dur and dur < 2:
                ss = f"00:00:{max(0, dur / 2):05.2f}"
            cmd = [ffmpeg_cmd, '-y', '-ss', ss, '-i', file_path,
                   '-vframes', '1', '-q:v', '2', preview_path]
            run_hidden(cmd, check=True, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pixmap = QPixmap(preview_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(self.preview_label.width(), self.preview_label.height(),
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                if len(self._preview_cache) > 64:
                    self._preview_cache.clear()
                self._preview_cache[key] = pixmap
                self.preview_label.setPixmap(pixmap)
            else:
                self.preview_label.setText("не удалось загрузить превью")
        except Exception as e:
            self.log_text.append(f"Ошибка создания превью: {e}")
            self.preview_label.setText("не удалось загрузить превью")
        finally:
            try:
                if os.path.exists(preview_path):
                    os.remove(preview_path)
            except Exception:
                pass

    # ------------------------------------------------ Подбор энкодеров -----
    def _available_encoders(self, ffmpeg_cmd):
        if self._encoders_cache is None:
            out = ''
            try:
                proc = run_hidden([ffmpeg_cmd, '-hide_banner', '-encoders'],
                                  capture_output=True, text=True, timeout=10)
                out = (proc.stdout or '') + (proc.stderr or '')
            except Exception:
                out = ''
            self._encoders_cache = out
        return self._encoders_cache

    @staticmethod
    def _encoder_listed(out, name):
        if not name:
            return False
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == name:
                return True
        return False

    def check_codec_available(self, ffmpeg_cmd, codec_name, container=None):
        name = (codec_name or '').strip()
        real = self.VIDEO_ENCODER_MAP.get(name.lower(), name)
        fallback = 'libvpx-vp9' if (container or '').lower() == 'webm' else 'libx264'
        try:
            if 'nvenc' in real.lower() and platform.system() == 'Windows':
                try:
                    ctypes.WinDLL('nvcuda.dll')
                except Exception:
                    return fallback
            out = self._available_encoders(ffmpeg_cmd)
            if not out:
                return real
            if self._encoder_listed(out, real):
                return real
        except Exception:
            pass
        return fallback

    def map_audio_codec(self, ffmpeg_cmd, codec_name):
        if not codec_name:
            return 'aac'
        name = str(codec_name).lower()
        if name == 'copy':
            return 'copy'
        mapping = {'opus': 'libopus', 'mp3': 'libmp3lame', 'aac': 'aac',
                   'flac': 'flac', 'vorbis': 'libvorbis', 'ogg': 'libvorbis',
                   'ac3': 'ac3', 'wav': 'pcm_s16le', 'wma': 'wmav2'}
        mapped = mapping.get(name, name)
        out = self._available_encoders(ffmpeg_cmd)
        try:
            if not out or self._encoder_listed(out, mapped):
                return mapped
        except Exception:
            pass
        for candidate in ('aac', 'libopus', 'libvorbis', 'libmp3lame'):
            if self._encoder_listed(out, candidate):
                return candidate
        return mapped

    # ------------------------------------------------ Занятость / отмена ---
    def _set_busy(self, busy):
        self._busy = busy
        self.btn_render.setEnabled(not busy)
        self.btn_extract.setEnabled(not busy)
        self.btn_cancel.setVisible(busy)
        self.btn_cancel.setEnabled(busy)

    def cancel_current(self):
        self._batch_cancelled = True
        w = getattr(self, "worker", None)
        if w is not None:
            try:
                w.stop()
            except Exception:
                pass
        self.batch_status_label.setText("Отменено пользователем")
        self.stats_label.setText("")
        self._set_busy(False)

    def _open_output_folder(self, file_path):
        try:
            folder = os.path.dirname(file_path)
            if folder and os.path.isdir(folder):
                open_in_os(folder)
        except Exception:
            pass

    def _play_sound(self):
        if not self.settings.get("sound_notifications"):
            return
        try:
            if sys.platform == "win32":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    # ------------------------------------------- Выбор папки перед рендером
    def _ask_destination(self):
        """Спрашивает, куда сохранить. Возвращает путь папки, '' (рядом с
        исходным) или None (отмена). Папка по умолчанию — из Настроек."""
        box = QMessageBox(self)
        box.setWindowTitle("Сохранение")
        box.setIcon(QMessageBox.Icon.Question if hasattr(QMessageBox, 'Icon')
                    else QMessageBox.Question)
        box.setText("Куда сохранить результат?")
        ActionRole = _enum(QMessageBox, 'ActionRole')
        RejectRole = _enum(QMessageBox, 'RejectRole')
        btn_default = None
        if self.output_dir and os.path.isdir(self.output_dir):
            box.setInformativeText(f"Папка по умолчанию:\n{self.output_dir}")
            btn_default = box.addButton("📁  В папку по умолчанию", ActionRole)
        btn_source = box.addButton("📄  Рядом с исходным", ActionRole)
        btn_choose = box.addButton("📂  Выбрать папку…", ActionRole)
        box.addButton("Отмена", RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_default:
            return self.output_dir
        if clicked is btn_source:
            return ""
        if clicked is btn_choose:
            d = QFileDialog.getExistingDirectory(self, "Выберите папку",
                                                 self.output_dir or self.last_dir or "")
            return d if d else None
        return None

    def _dest_for(self, input_file, ext, dest_dir):
        directory = dest_dir if dest_dir else os.path.dirname(input_file)
        try:
            os.makedirs(directory, exist_ok=True)   # папку могли удалить
        except OSError:
            pass
        base = os.path.splitext(os.path.basename(input_file))[0]
        candidate = os.path.join(directory, base + ext)
        i = 1
        while os.path.exists(candidate) or os.path.abspath(candidate) == os.path.abspath(input_file):
            candidate = os.path.join(directory, f"{base}_{i}{ext}")
            i += 1
        return candidate

    def _output_extension(self, settings, input_file):
        token = (settings.get("format") or "").strip().lower()
        if token in self.KNOWN_CONTAINERS:
            return "." + token
        return os.path.splitext(input_file)[1] or ".mp4"

    def _build_video_command(self, input_file, output_file, settings, ffmpeg_cmd):
        notes = []
        container = os.path.splitext(output_file)[1].lstrip(".").lower()
        cmd = [ffmpeg_cmd, '-y', '-i', input_file]
        vcodec = settings.get("video_codec")
        scale = settings.get("resolution")
        bitrate = settings.get("bitrate")
        acodec = settings.get("audio_codec")
        abitrate = settings.get("audio_bitrate")
        channels = settings.get("audio_channels")
        # Копирование потока безопасно при том же контейнере или mkv (принимает всё)
        in_ext = os.path.splitext(input_file)[1].lstrip(".").lower()
        copy_ok = container in (in_ext, "mkv")

        if vcodec:
            safe = self.check_codec_available(ffmpeg_cmd, vcodec, container=container)
            if safe != vcodec:
                notes.append(f"⚠ Кодек {vcodec} недоступен — используем {safe}.")
            cmd.extend(['-c:v', safe])
        elif not scale and not bitrate and copy_ok:
            # Параметры видео не меняются — копируем без перекодирования
            # (мгновенно и без потерь качества вместо дефолтного пережатия)
            cmd.extend(['-c:v', 'copy'])
            notes.append("⚡ Видео копируется без перекодирования.")
        filters = []
        if scale:
            filters.append(f"scale={scale}:force_original_aspect_ratio=decrease")
            filters.append(f"pad={scale}:(ow-iw)/2:(oh-ih)/2")
        if filters:
            cmd.extend(['-vf', ",".join(filters)])
        if bitrate:
            cmd.extend(['-b:v', bitrate])

        is_copy = acodec == 'copy'
        if acodec:
            cmd.extend(['-c:a', 'copy' if is_copy else self.map_audio_codec(ffmpeg_cmd, acodec)])
        elif not abitrate and not channels and copy_ok:
            cmd.extend(['-c:a', 'copy'])
            is_copy = True
            notes.append("⚡ Аудио копируется без перекодирования.")
        if abitrate and not is_copy and abitrate.endswith('k'):
            n = self._safe_int(abitrate[:-1])
            if n and n > 0:
                cmd.extend(['-b:a', f"{n}k"])
        if channels and not is_copy:
            cmd.extend(['-ac', channels])
        cmd.append(output_file)
        return cmd, notes

    def _known_duration(self):
        try:
            return float(self.video_info.get('format', {}).get('duration', 0)) or None
        except Exception:
            return None

    # ---------------------------------------------- Рендеринг (пакет) ------
    def start_video_render(self):
        if self._busy:
            return
        files = self.input_files if self.input_files else ([self.input_file] if self.input_file else [])
        files = [f for f in files if f]
        if not files or not all(os.path.exists(f) for f in files):
            QMessageBox.warning(self, "Ошибка", "Выберите существующие видеофайлы!")
            return
        dest = self._ask_destination()
        if dest is None:
            return
        self.batch_files = files
        self.batch_index = 0
        self.batch_total = len(files)
        self.batch_settings = self.current_render_settings()
        self._batch_dir = dest
        self._batch_cancelled = False
        save_config(render_settings=self.batch_settings)
        self._set_busy(True)
        self.stats_label.setText("")
        self.render_next_in_batch()

    def render_next_in_batch(self):
        if self._batch_cancelled:
            return
        if self.batch_index >= self.batch_total:
            self.batch_status_label.setText("Пакетное перекодирование завершено!")
            self.progress_bar.setValue(100)
            self._set_busy(False)
            return
        input_file = self.batch_files[self.batch_index]
        if self.batch_total > 1:
            self.batch_status_label.setText(
                f"Видео {self.batch_index + 1} из {self.batch_total}: {os.path.basename(input_file)}")
        else:
            self.batch_status_label.setText(f"Обработка: {os.path.basename(input_file)}")
        settings = self.batch_settings
        ext = self._output_extension(settings, input_file)
        output_file = self._dest_for(input_file, ext, self._batch_dir)
        self.output_file = output_file
        ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
        cmd, notes = self._build_video_command(input_file, output_file, settings, ffmpeg_cmd)
        self.log_text.clear()
        self.log_text.append(
            f"Начато перекодирование видео {self.batch_index + 1}/{self.batch_total}..."
            if self.batch_total > 1 else "Начато перекодирование видео...")
        for note in notes:
            self.log_text.append(note)
        self.log_text.append("Сохранение: " + output_file)
        self.log_text.append("Команда: " + " ".join(cmd))
        self.progress_bar.setValue(0)
        known = self._known_duration() if self.batch_total == 1 else None
        self.worker = FFmpegWorker(cmd, total_duration=known)
        self.worker.progressUpdated.connect(self.update_progress)
        self.worker.statsUpdated.connect(self.stats_label.setText)
        self.worker.outputReceived.connect(self.log_text.append)
        self.worker.resultReady.connect(self.batch_render_finished)
        self.worker.start()

    def batch_render_finished(self, success):
        if self._batch_cancelled:
            self.log_text.append("Операция отменена.")
            self._set_busy(False)
            return
        if success:
            self.log_text.append(
                f"Видео {self.batch_index + 1} успешно перекодировано!"
                if self.batch_total > 1 else "Перекодирование видео успешно завершено!")
        else:
            self.log_text.append(f"Ошибка при перекодировании видео {self.batch_index + 1}!")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при обработке видео {self.batch_index + 1}")
        self.batch_index += 1
        if self.batch_index < self.batch_total and not self._batch_cancelled:
            self.render_next_in_batch()
            return
        self.batch_status_label.setText(
            "Пакетное перекодирование завершено!" if self.batch_total > 1 else "Готово!")
        self.stats_label.setText("")
        self.progress_bar.setValue(100)
        self._set_busy(False)
        if success:
            if self.settings.get("open_folder_when_done"):
                self._open_output_folder(self.output_file)
            if self.settings["show_video_notifications"]:
                self._play_sound()
                NotificationDialog(self.output_file, self).exec()

    # ----------------------------------------------- Извлечение аудио ------
    def extract_audio(self):
        if self._busy:
            return
        if not self.input_file or not os.path.exists(self.input_file):
            QMessageBox.warning(self, "Ошибка", "Выберите видеофайл!")
            return
        dest = self._ask_destination()
        if dest is None:
            return
        audio_format = self.audio_format.currentData() or self.audio_format.currentText()
        output_file = self._dest_for(self.input_file, "." + audio_format, dest)
        ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
        chosen = self.map_audio_codec(ffmpeg_cmd, audio_format.lower())
        cmd = [ffmpeg_cmd, '-y', '-i', self.input_file, '-vn',
               '-acodec', 'copy' if chosen == 'copy' else chosen, output_file]
        self._extract_output = output_file
        self.log_text.clear()
        self.log_text.append("Начато извлечение аудио...")
        self.log_text.append("Сохранение: " + output_file)
        self.log_text.append("Команда: " + " ".join(cmd))
        self.progress_bar.setValue(0)
        self._batch_cancelled = False
        self._set_busy(True)
        self.worker = FFmpegWorker(cmd, total_duration=self._known_duration())
        self.worker.progressUpdated.connect(self.update_progress)
        self.worker.statsUpdated.connect(self.stats_label.setText)
        self.worker.outputReceived.connect(self.log_text.append)
        self.worker.resultReady.connect(self.audio_extraction_finished)
        self.worker.start()

    def audio_extraction_finished(self, success):
        self._set_busy(False)
        self.stats_label.setText("")
        if self._batch_cancelled:
            self.log_text.append("Извлечение отменено.")
            return
        if success:
            self.log_text.append("Аудио успешно извлечено!")
            output_file = getattr(self, "_extract_output", "")
            if output_file:
                self.batch_status_label.setText("Готово!")
                if self.settings.get("open_folder_when_done"):
                    self._open_output_folder(output_file)
                if self.settings["show_audio_notifications"]:
                    self._play_sound()
                    NotificationDialog(output_file, self).exec()
        else:
            self.log_text.append("Ошибка при извлечении аудио!")
            QMessageBox.critical(self, "Ошибка", "Произошла ошибка при извлечении аудио")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def closeEvent(self, event):
        save_config(win_size=[self.width(), self.height()])
        w = getattr(self, "worker", None)
        if w is not None and w.isRunning():
            try:
                w.stop()
                w.wait(3000)
            except Exception:
                pass
        super().closeEvent(event)


# ============================================================================
#  Рабочий поток ffmpeg
# ============================================================================
class FFmpegWorker(QThread):
    progressUpdated = pyqtSignal(int)
    statsUpdated = pyqtSignal(str)
    outputReceived = pyqtSignal(str)
    resultReady = pyqtSignal(bool)

    def __init__(self, command, total_duration=None):
        super().__init__()
        self.command = command
        self.total_duration = total_duration
        self.process = None
        self._cancelled = False

    def stop(self):
        self._cancelled = True
        p = self.process
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    @staticmethod
    def _parse_time(value):
        try:
            h, m, s = value.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            return None

    @staticmethod
    def _fmt_eta(seconds):
        try:
            seconds = int(seconds)
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        except Exception:
            return "?"

    def run(self):
        try:
            exe = self.command[0] if self.command else None
            if exe:
                if os.path.isabs(exe) and not os.path.exists(exe):
                    self.outputReceived.emit(f"Ошибка: исполняемый файл не найден: {exe}")
                    self.resultReady.emit(False)
                    return
                if not os.path.isabs(exe) and shutil.which(exe) is None:
                    self.outputReceived.emit(f"Ошибка: команда не найдена в PATH: {exe}")
                    self.resultReady.emit(False)
                    return
            self.process = subprocess.Popen(
                self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, encoding='utf-8', errors='replace',
                bufsize=1, creationflags=_NO_WINDOW)
            total_duration = self.total_duration
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                self.outputReceived.emit(line.strip())
                if total_duration is None and "Duration:" in line:
                    part = line.split("Duration:")[1].split(",")[0].strip()
                    if part and part.upper() != "N/A":
                        d = self._parse_time(part)
                        if d:
                            total_duration = d
                if "time=" in line:
                    time_str = line.split("time=")[1].split()[0]
                    current_time = self._parse_time(time_str) if time_str.upper() != "N/A" else None
                    if current_time is not None and total_duration and total_duration > 0:
                        progress = int((current_time / total_duration) * 100)
                        self.progressUpdated.emit(max(0, min(progress, 100)))
                        speed = None
                        if "speed=" in line:
                            try:
                                speed = float(line.split("speed=")[1].split()[0].rstrip('x'))
                            except Exception:
                                speed = None
                        if speed and speed > 0:
                            eta = max(0.0, (total_duration - current_time)) / speed
                            self.statsUpdated.emit(
                                f"Осталось ~{self._fmt_eta(eta)}   ·   скорость {speed:g}x")
            self.process.wait()
            self.resultReady.emit(False if self._cancelled else self.process.returncode == 0)
        except Exception as e:
            self.outputReceived.emit(f"Ошибка: {e}")
            self.resultReady.emit(False)


# ============================================================================
#  Запуск
# ============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if APP_ICON:
        app.setWindowIcon(QIcon(APP_ICON))

    cfg = load_config()
    mode = cfg.get("theme_mode", "light")
    set_theme(hue=cfg.get("hue", DEFAULT_HUE),
              saturation=cfg.get("saturation", DEFAULT_SATURATION),
              dark=is_system_dark() if mode == "system" else (mode == "dark"))
    app.setStyleSheet(T.STYLESHEET_MAIN)

    ffmpeg_path, ffprobe_path = find_ffmpeg()
    if not ffmpeg_path:
        FFmpegSetupDialog().exec()
        ffmpeg_path, ffprobe_path = find_ffmpeg()

    if ffmpeg_path:
        save_config(ffmpeg_installed=True, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
        window = VideoConverter()
        window.ffmpeg_path = ffmpeg_path
        window.ffprobe_path = ffprobe_path or ffmpeg_path
        window.refresh_ffmpeg_label()
        window.show()
        sys.exit(app.exec())
    else:
        QMessageBox.critical(None, "Ошибка", "Не удалось найти или установить FFmpeg.")
        sys.exit(1)
