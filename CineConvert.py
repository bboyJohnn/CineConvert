"""
CineConvert — портативный видеоконвертер на FFmpeg (PyQt5 / PyQt6).

Интерфейс v3: боковая навигация, зона перетаскивания, общая панель действий
внизу, настройки в стиле карточек с переключателями. Шрифт — Inter (папка
fonts/, SIL OFL 1.1), иконки — Lucide (ISC), волны в шапке остались.
"""
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
        QMainWindow, QWidget, QHBoxLayout, QGridLayout, QStackedWidget, QButtonGroup,
        QComboBox, QTextEdit, QScrollArea, QFileDialog, QCheckBox, QSizePolicy, QSlider,
        QFrame, QColorDialog, QStyledItemDelegate
    )
    from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QTimer, QRectF, QSize, QPointF,
                              QByteArray, QVariantAnimation, QEasingCurve)
    from PyQt6.QtGui import (QFont, QPixmap, QPainter, QPainterPath, QColor, QLinearGradient,
                             QRadialGradient, QIcon, QPen, QPalette, QFontDatabase,
                             QKeySequence, QShortcut, QTransform)
    PYQT_VERSION = 6
except ImportError:   # нет PyQt6 или он не загружается (нет системных библиотек) → PyQt5
    from PyQt5.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox,
        QMainWindow, QWidget, QHBoxLayout, QGridLayout, QStackedWidget, QButtonGroup,
        QComboBox, QTextEdit, QScrollArea, QFileDialog, QCheckBox, QSizePolicy, QSlider,
        QFrame, QColorDialog, QStyledItemDelegate, QShortcut
    )
    from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QTimer, QRectF, QSize, QPointF,
                              QByteArray, QVariantAnimation, QEasingCurve)
    from PyQt5.QtGui import (QFont, QPixmap, QPainter, QPainterPath, QColor, QLinearGradient,
                             QRadialGradient, QIcon, QPen, QPalette, QFontDatabase,
                             QKeySequence, QTransform)
    PYQT_VERSION = 5
try:
    if PYQT_VERSION == 6:
        from PyQt6.QtSvg import QSvgRenderer
    else:
        from PyQt5.QtSvg import QSvgRenderer
except ImportError:      # без QtSvg кнопки просто останутся без иконок
    QSvgRenderer = None

APP_VERSION = "3.0"

# --- Слой совместимости PyQt5/PyQt6 ------------------------------------------
if PYQT_VERSION == 5:
    for _enum_name in (
        'WindowType', 'AlignmentFlag', 'AspectRatioMode', 'TransformationMode',
        'PenStyle', 'GlobalColor', 'ArrowType', 'ToolButtonStyle', 'Orientation',
        'CursorShape', 'PenCapStyle', 'PenJoinStyle', 'ScrollBarPolicy',
        'TextElideMode', 'WidgetAttribute', 'MouseButton', 'FocusPolicy',
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
#  Локализация: строки берутся из locales/*.json по ключу; ключ — имя
#  элемента (btn_render, tab_video…) или исходная русская строка. Чего нет в
#  файле — показывается по-русски, поэтому переключение языков не «залипает».
# ============================================================================
_TR = {}


def tr(key, default=None):
    """Перевод по ключу; если перевода нет — default (или сам ключ)."""
    value = _TR.get(key)
    if isinstance(value, str) and value:
        return value
    return key if default is None else default


def preload_locale(code):
    """Загружает перевод до создания окон (чтобы и мастер установки FFmpeg был
    на выбранном языке). Окно потом применяет язык ещё раз через apply_locale."""
    for folder in (os.path.join(RESOURCE_DIR, "locales"), os.path.join(APP_DIR, "locales")):
        path = os.path.join(folder, f"{code}.json")
        if code and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _TR.clear()
                    _TR.update(data)
            except Exception:
                pass
            return


def tr_fmt(key, default=None, **kw):
    """tr() + format(); кривой шаблон в переводе не роняет программу."""
    template = tr(key, default)
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return (default or key).format(**kw)


# ============================================================================
#  Шрифты: Inter (fonts/*.ttf) с запасными системными семействами
# ============================================================================
FONT_FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")
_FONT_FALLBACK = ["Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "Arial"]
# GDI в Windows регистрирует Medium/SemiBold как отдельные семейства, другие
# движки — как начертания «Inter». Список покрывает оба случая.
FONT_FAMILIES = {
    400: ["Inter"] + _FONT_FALLBACK,
    500: ["Inter Medium", "Inter"] + _FONT_FALLBACK,
    600: ["Inter SemiBold", "Inter"] + _FONT_FALLBACK,
    700: ["Inter"] + _FONT_FALLBACK,
}
MONO_FAMILIES = ["Cascadia Mono", "JetBrains Mono", "Consolas", "DejaVu Sans Mono", "Menlo"]


def load_fonts():
    """Регистрирует Inter из папки fonts (рядом с exe или из ресурсов)."""
    for folder in (os.path.join(RESOURCE_DIR, "fonts"), os.path.join(APP_DIR, "fonts")):
        if os.path.isdir(folder):
            for name in FONT_FILES:
                path = os.path.join(folder, name)
                if os.path.exists(path):
                    QFontDatabase.addApplicationFont(path)
            return


def _css_weight(weight):
    # Qt5 делит числовой CSS-вес на 8 (600 → Bold), поэтому подставляем эквивалент
    if PYQT_VERSION == 5:
        return {400: 400, 500: 456, 600: 504, 700: 600}.get(weight, 400)
    return weight


def css_font(weight=400):
    families = ", ".join(f'"{f}"' for f in FONT_FAMILIES[weight])
    return f"font-family: {families}; font-weight: {_css_weight(weight)};"


def ui_font(point_size=10.0, weight=400):
    font = QFont()
    try:
        font.setFamilies(FONT_FAMILIES[weight])
    except AttributeError:
        font.setFamily(FONT_FAMILIES[weight][0])
    font.setPointSizeF(point_size)
    if PYQT_VERSION == 5:
        font.setWeight({400: 50, 500: 57, 600: 63, 700: 75}.get(weight, 50))
    else:
        font.setWeight(QFont.Weight(weight))
    return font


# ============================================================================
#  Тема оформления (OKLCH): вся палитра считается из одного оттенка
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
        T.COLOR_PRIMARY = _oklch(.72, c(.15), h)
        T.COLOR_PRIMARY_HOVER = _oklch(.77, c(.14), h)
        T.COLOR_PRIMARY_ACTIVE = _oklch(.67, c(.14), h)
        T.COLOR_ON_PRIMARY = _oklch(.18, c(.03), h)
        T.COLOR_PAGE_BG = _oklch(.165, c(.012), h)
        T.COLOR_CARD_BG = _oklch(.205, c(.014), h)
        T.COLOR_CARD_BORDER = _oklch(.275, c(.016), h)
        T.COLOR_INPUT_BG = _oklch(.18, c(.012), h)
        T.COLOR_INPUT_BORDER = _oklch(.32, c(.018), h)
        T.COLOR_INPUT_BORDER_HOVER = _oklch(.42, c(.03), h)
        T.COLOR_BTN_BG = _oklch(.265, c(.02), h)
        T.COLOR_BTN_BG_HOVER = _oklch(.305, c(.025), h)
        T.COLOR_BTN_BG_ACTIVE = _oklch(.345, c(.03), h)
        T.COLOR_BTN_TEXT = _oklch(.90, c(.03), h)
        T.COLOR_HOVER = _oklch(.225, c(.016), h)
        T.COLOR_ACCENT_SOFT = _oklch(.29, c(.055), h)
        T.COLOR_ACCENT_TEXT = _oklch(.83, c(.11), h)
        T.COLOR_TEXT = _oklch(.95, c(.006), h)
        T.COLOR_TEXT_MUTED = _oklch(.72, c(.015), h)
        T.COLOR_TEXT_FAINT = _oklch(.56, c(.015), h)
        T.COLOR_TRACK = _oklch(.30, c(.018), h)
        T.COLOR_SWITCH_OFF = _oklch(.38, c(.02), h)
        T.COLOR_SEG_BG = _oklch(.175, c(.012), h)
        T.COLOR_SEG_ON = _oklch(.30, c(.028), h)
        T.COLOR_SCROLL = _oklch(.36, c(.02), h)
        T.COLOR_GREEN = _oklch(.80, .14, 155)
        T.COLOR_GREEN_SOFT = _oklch(.31, .055, 155)
        T.COLOR_RED = _oklch(.75, .15, 25)
        T.COLOR_RED_SOFT = _oklch(.30, .06, 25)
        T.COLOR_RED_SOFT_HOVER = _oklch(.35, .075, 25)
        T.BANNER_STOPS = (_oklch(.46, c(.15), h - 14), _oklch(.56, c(.16), h),
                          _oklch(.66, c(.13), h + 24))
    else:
        T.COLOR_PRIMARY = _oklch(.60, c(.17), h)
        T.COLOR_PRIMARY_HOVER = _oklch(.55, c(.165), h)
        T.COLOR_PRIMARY_ACTIVE = _oklch(.50, c(.15), h)
        T.COLOR_ON_PRIMARY = "#ffffff"
        T.COLOR_PAGE_BG = _oklch(.97, c(.008), h)
        T.COLOR_CARD_BG = "#ffffff"
        T.COLOR_CARD_BORDER = _oklch(.915, c(.012), h)
        T.COLOR_INPUT_BG = _oklch(.985, c(.004), h)
        T.COLOR_INPUT_BORDER = _oklch(.885, c(.014), h)
        T.COLOR_INPUT_BORDER_HOVER = _oklch(.78, c(.035), h)
        T.COLOR_BTN_BG = _oklch(.955, c(.016), h)
        T.COLOR_BTN_BG_HOVER = _oklch(.925, c(.026), h)
        T.COLOR_BTN_BG_ACTIVE = _oklch(.895, c(.035), h)
        T.COLOR_BTN_TEXT = _oklch(.32, c(.045), h)
        T.COLOR_HOVER = _oklch(.935, c(.016), h)
        T.COLOR_ACCENT_SOFT = _oklch(.935, c(.04), h)
        T.COLOR_ACCENT_TEXT = _oklch(.47, c(.16), h)
        T.COLOR_TEXT = _oklch(.22, c(.02), h)
        T.COLOR_TEXT_MUTED = _oklch(.50, c(.02), h)
        T.COLOR_TEXT_FAINT = _oklch(.66, c(.015), h)
        T.COLOR_TRACK = _oklch(.915, c(.016), h)
        T.COLOR_SWITCH_OFF = _oklch(.84, c(.02), h)
        T.COLOR_SEG_BG = _oklch(.955, c(.01), h)
        T.COLOR_SEG_ON = "#ffffff"
        T.COLOR_SCROLL = _oklch(.84, c(.015), h)
        T.COLOR_GREEN = _oklch(.56, .15, 155)
        T.COLOR_GREEN_SOFT = _oklch(.955, .04, 155)
        T.COLOR_RED = _oklch(.56, .19, 25)
        T.COLOR_RED_SOFT = _oklch(.96, .025, 25)
        T.COLOR_RED_SOFT_HOVER = _oklch(.93, .045, 25)
        T.BANNER_STOPS = (_oklch(.52, c(.16), h - 14), _oklch(.62, c(.16), h),
                          _oklch(.74, c(.12), h + 24))

    reg, med, semi = css_font(400), css_font(500), css_font(600)
    mono = ", ".join(f'"{f}"' for f in MONO_FAMILIES)

    T.STYLESHEET_MAIN = f"""
        QWidget {{ {reg} font-size: 10pt; color: {T.COLOR_TEXT}; }}
        QMainWindow, QDialog {{ background: {T.COLOR_PAGE_BG}; }}
        QWidget#transparent, QScrollArea, QScrollArea > QWidget > QWidget,
        QStackedWidget {{ background: transparent; border: none; }}
        QToolTip {{ {reg} font-size: 9pt; background: {T.COLOR_CARD_BG}; color: {T.COLOR_TEXT};
            border: 1px solid {T.COLOR_CARD_BORDER}; padding: 5px 8px; }}

        QLabel {{ background: transparent; }}
        QLabel[role="h1"] {{ {semi} font-size: 14pt; }}
        QLabel[role="title"] {{ {semi} font-size: 10.5pt; }}
        QLabel[role="rowTitle"] {{ {med} font-size: 10pt; }}
        QLabel[role="sub"] {{ color: {T.COLOR_TEXT_MUTED}; font-size: 9pt; }}
        QLabel[role="caption"] {{ color: {T.COLOR_TEXT_FAINT}; font-size: 8.5pt; }}
        QLabel[role="section"] {{ {semi} color: {T.COLOR_TEXT_MUTED}; font-size: 9pt;
            padding: 8px 4px 0 4px; }}
        QLabel[role="field"] {{ {med} color: {T.COLOR_TEXT_MUTED}; font-size: 9pt; }}
        QLabel[role="infoKey"] {{ color: {T.COLOR_TEXT_MUTED}; font-size: 9pt; }}
        QLabel[role="infoVal"] {{ {semi} font-size: 9pt; }}
        QLabel[role="fileTitle"] {{ {semi} font-size: 12pt; }}
        QLabel[role="status"] {{ {semi} font-size: 10pt; }}
        QLabel[role="percent"] {{ {semi} font-size: 10pt; color: {T.COLOR_ACCENT_TEXT}; }}
        QLabel[role="pill"] {{ {semi} font-size: 8.5pt; color: {T.COLOR_TEXT_MUTED};
            background: {T.COLOR_BTN_BG}; border-radius: 9px; padding: 2px 9px; }}
        QLabel[role="iconBadge"] {{ background: {T.COLOR_ACCENT_SOFT}; border-radius: 10px; }}
        QLabel[role="iconBadge"][state="done"] {{ background: {T.COLOR_GREEN_SOFT}; }}
        QLabel[role="iconBadge"][state="error"] {{ background: {T.COLOR_RED_SOFT}; }}
        QLabel[role="iconBadge"][state="cancelled"] {{ background: {T.COLOR_BTN_BG}; }}
        QLabel[role="swatch"] {{ background: {T.COLOR_PRIMARY}; border-radius: 12px;
            border: 3px solid {T.COLOR_ACCENT_SOFT}; }}

        QFrame#card {{ background: {T.COLOR_CARD_BG}; border: 1px solid {T.COLOR_CARD_BORDER};
            border-radius: 16px; }}
        QFrame#card[dragActive="true"] {{ border: 1px solid {T.COLOR_PRIMARY};
            background: {T.COLOR_ACCENT_SOFT}; }}
        QFrame#divider {{ background: {T.COLOR_CARD_BORDER}; border: none;
            min-height: 1px; max-height: 1px; }}
        QFrame#badge {{ background: {T.COLOR_GREEN_SOFT}; border-radius: 12px; }}
        QFrame#badge QLabel {{ {semi} color: {T.COLOR_GREEN}; font-size: 8.5pt; }}

        QPushButton {{ {semi} font-size: 9.5pt; background: {T.COLOR_BTN_BG};
            color: {T.COLOR_BTN_TEXT}; border: none; border-radius: 10px; padding: 8px 14px; }}
        QPushButton:hover {{ background: {T.COLOR_BTN_BG_HOVER}; }}
        QPushButton:pressed {{ background: {T.COLOR_BTN_BG_ACTIVE}; }}
        QPushButton:disabled {{ background: {T.COLOR_BTN_BG}; color: {T.COLOR_TEXT_FAINT}; }}
        QPushButton[variant="primary"] {{ {semi} font-size: 10.5pt; background: {T.COLOR_PRIMARY};
            color: {T.COLOR_ON_PRIMARY}; border-radius: 12px; padding: 10px 24px; }}
        QPushButton[variant="primary"]:hover {{ background: {T.COLOR_PRIMARY_HOVER}; }}
        QPushButton[variant="primary"]:pressed {{ background: {T.COLOR_PRIMARY_ACTIVE}; }}
        QPushButton[variant="primary"]:disabled {{ background: {T.COLOR_BTN_BG};
            color: {T.COLOR_TEXT_FAINT}; }}
        QPushButton[variant="danger"] {{ background: {T.COLOR_RED_SOFT}; color: {T.COLOR_RED}; }}
        QPushButton[variant="danger"]:hover {{ background: {T.COLOR_RED_SOFT_HOVER}; }}
        QPushButton[variant="danger"][size="lg"] {{ font-size: 10.5pt; border-radius: 12px;
            padding: 10px 18px; }}
        QPushButton[variant="ghost"] {{ background: transparent; color: {T.COLOR_TEXT_MUTED}; }}
        QPushButton[variant="ghost"]:hover {{ background: {T.COLOR_BTN_BG}; color: {T.COLOR_TEXT}; }}
        QPushButton[variant="ghost"]:disabled {{ background: transparent; color: {T.COLOR_TEXT_FAINT}; }}
        QPushButton[variant="ghostDanger"] {{ background: transparent; color: {T.COLOR_TEXT_MUTED}; }}
        QPushButton[variant="ghostDanger"]:hover {{ background: {T.COLOR_RED_SOFT}; color: {T.COLOR_RED}; }}
        QPushButton[variant="ghostDanger"]:disabled {{ background: transparent;
            color: {T.COLOR_TEXT_FAINT}; }}
        QPushButton[variant="icon"] {{ padding: 0; border-radius: 9px;
            min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; }}
        QPushButton[variant="icon"][flat="true"] {{ background: transparent; }}
        QPushButton[variant="icon"][flat="true"]:hover {{ background: {T.COLOR_BTN_BG}; }}
        QPushButton[variant="icon"][flat="true"]:disabled {{ background: transparent; }}

        QPushButton#navButton {{ {med} font-size: 10pt; text-align: left; background: transparent;
            color: {T.COLOR_TEXT_MUTED}; border-radius: 11px; padding: 10px 14px; }}
        QPushButton#navButton:hover {{ background: {T.COLOR_HOVER}; color: {T.COLOR_TEXT}; }}
        QPushButton#navButton:checked {{ {semi} background: {T.COLOR_ACCENT_SOFT};
            color: {T.COLOR_ACCENT_TEXT}; }}
        QPushButton#navButton[compact="true"] {{ text-align: center; padding: 10px 0; }}

        QFrame#segmented {{ background: {T.COLOR_SEG_BG}; border: 1px solid {T.COLOR_CARD_BORDER};
            border-radius: 11px; }}
        QPushButton#segment {{ {med} font-size: 9.5pt; background: transparent;
            color: {T.COLOR_TEXT_MUTED}; border: 1px solid transparent; border-radius: 8px;
            padding: 6px 10px; }}
        QPushButton#segment:hover {{ color: {T.COLOR_TEXT}; background: transparent; }}
        QPushButton#segment:checked {{ {semi} background: {T.COLOR_SEG_ON};
            color: {T.COLOR_ACCENT_TEXT}; border: 1px solid {T.COLOR_CARD_BORDER}; }}
        QPushButton#segment:disabled {{ color: {T.COLOR_TEXT_FAINT}; }}

        QPushButton#optionCard {{ background: {T.COLOR_CARD_BG}; border: 1px solid {T.COLOR_CARD_BORDER};
            border-radius: 12px; padding: 0; text-align: left; }}
        QPushButton#optionCard:hover, QPushButton#optionCard:focus {{
            background: {T.COLOR_ACCENT_SOFT}; border: 1px solid {T.COLOR_PRIMARY}; }}

        QLineEdit, QComboBox {{ background: {T.COLOR_INPUT_BG}; border: 1px solid {T.COLOR_INPUT_BORDER};
            border-radius: 10px; padding: 7px 11px; color: {T.COLOR_TEXT};
            selection-background-color: {T.COLOR_ACCENT_SOFT}; selection-color: {T.COLOR_ACCENT_TEXT}; }}
        QLineEdit:hover, QComboBox:hover {{ border: 1px solid {T.COLOR_INPUT_BORDER_HOVER}; }}
        QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border: 1px solid {T.COLOR_PRIMARY}; }}
        QLineEdit:read-only {{ color: {T.COLOR_TEXT_MUTED}; }}
        QComboBox {{ combobox-popup: 0; padding-right: 30px; }}
        QComboBox:disabled {{ color: {T.COLOR_TEXT_FAINT}; }}
        QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
            width: 30px; border: none; }}
        QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
        QComboBox QLineEdit, QComboBox QLineEdit:hover, QComboBox QLineEdit:focus {{
            background: transparent; border: none; padding: 0; color: {T.COLOR_TEXT}; }}
        QComboBox QAbstractItemView {{ background: {T.COLOR_CARD_BG}; color: {T.COLOR_TEXT};
            border: 1px solid {T.COLOR_CARD_BORDER}; padding: 4px; outline: 0;
            selection-background-color: {T.COLOR_ACCENT_SOFT}; selection-color: {T.COLOR_ACCENT_TEXT}; }}
        QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 10px; border-radius: 7px; }}
        QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
            background: {T.COLOR_ACCENT_SOFT}; color: {T.COLOR_ACCENT_TEXT}; }}

        QTextEdit {{ background: {T.COLOR_INPUT_BG}; border: 1px solid {T.COLOR_CARD_BORDER};
            border-radius: 12px; padding: 8px; color: {T.COLOR_TEXT};
            selection-background-color: {T.COLOR_ACCENT_SOFT}; selection-color: {T.COLOR_ACCENT_TEXT}; }}
        QTextEdit#logView {{ font-family: {mono}; font-size: 9pt; font-weight: 400; }}

        QProgressBar {{ background: {T.COLOR_TRACK}; border: none; border-radius: 4px;
            min-height: 8px; max-height: 8px; text-align: center; color: transparent; }}
        QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {T.COLOR_PRIMARY_ACTIVE}, stop:1 {T.COLOR_PRIMARY}); }}

        QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: {T.COLOR_TRACK}; }}
        QSlider::sub-page:horizontal {{ background: {T.COLOR_PRIMARY}; border-radius: 3px; }}
        QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -7px 0; border-radius: 10px;
            background: {T.COLOR_CARD_BG}; border: 3px solid {T.COLOR_PRIMARY}; }}

        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; border: none; }}
        QScrollBar::handle:vertical {{ background: {T.COLOR_SCROLL}; border-radius: 3px;
            min-height: 36px; margin: 0 2px; }}
        QScrollBar::handle:vertical:hover {{ background: {T.COLOR_TEXT_FAINT}; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; border: none; }}
        QScrollBar::handle:horizontal {{ background: {T.COLOR_SCROLL}; border-radius: 3px;
            min-width: 36px; margin: 2px 0; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        QMenu {{ background: {T.COLOR_CARD_BG}; border: 1px solid {T.COLOR_CARD_BORDER}; padding: 4px; }}
        QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; color: {T.COLOR_TEXT}; }}
        QMenu::item:selected {{ background: {T.COLOR_ACCENT_SOFT}; color: {T.COLOR_ACCENT_TEXT}; }}
        QMenu::item:disabled {{ color: {T.COLOR_TEXT_FAINT}; }}
        QMenu::separator {{ height: 1px; background: {T.COLOR_CARD_BORDER}; margin: 4px 6px; }}

        QCheckBox {{ spacing: 8px; background: transparent; }}
        QMessageBox {{ background: {T.COLOR_PAGE_BG}; }}
        QMessageBox QPushButton {{ min-width: 84px; }}
    """

    T.STYLESHEET_HUE_SLIDER = f"""
        QSlider::groove:horizontal {{ height: 10px; border-radius: 5px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {_rainbow_stops()}); }}
        QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0;
            border-radius: 10px; background: {T.COLOR_CARD_BG}; border: 3px solid {T.COLOR_PRIMARY}; }}
        QSlider::add-page:horizontal, QSlider::sub-page:horizontal {{ background: transparent; }}
    """

    T.STYLESHEET_SAT_SLIDER = f"""
        QSlider::groove:horizontal {{ height: 10px; border-radius: 5px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {_oklch(.7, .01, h)}, stop:1 {_oklch(.7, .24, h)}); }}
        QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0;
            border-radius: 10px; background: {T.COLOR_CARD_BG}; border: 3px solid {T.COLOR_PRIMARY}; }}
        QSlider::add-page:horizontal, QSlider::sub-page:horizontal {{ background: transparent; }}
    """


set_theme()  # построить палитру по умолчанию при импорте


def build_palette():
    """QPalette под текущую тему — для системных диалогов, меню и Fusion."""
    pal = QPalette()
    role = QPalette.ColorRole
    for r, col in ((role.Window, T.COLOR_PAGE_BG), (role.WindowText, T.COLOR_TEXT),
                   (role.Base, T.COLOR_INPUT_BG), (role.AlternateBase, T.COLOR_BTN_BG),
                   (role.Text, T.COLOR_TEXT), (role.Button, T.COLOR_BTN_BG),
                   (role.ButtonText, T.COLOR_BTN_TEXT), (role.Highlight, T.COLOR_PRIMARY),
                   (role.HighlightedText, T.COLOR_ON_PRIMARY), (role.ToolTipBase, T.COLOR_CARD_BG),
                   (role.ToolTipText, T.COLOR_TEXT), (role.Link, T.COLOR_ACCENT_TEXT),
                   (role.BrightText, T.COLOR_RED), (role.Light, T.COLOR_CARD_BG),
                   (role.Midlight, T.COLOR_CARD_BORDER), (role.Mid, T.COLOR_INPUT_BORDER),
                   (role.Dark, T.COLOR_INPUT_BORDER_HOVER), (role.Shadow, T.COLOR_TEXT_FAINT)):
        pal.setColor(r, QColor(col))
    if hasattr(role, 'PlaceholderText'):
        pal.setColor(role.PlaceholderText, QColor(T.COLOR_TEXT_FAINT))
    disabled = QPalette.ColorGroup.Disabled
    for r in (role.WindowText, role.Text, role.ButtonText):
        pal.setColor(disabled, r, QColor(T.COLOR_TEXT_FAINT))
    return pal


def apply_window_theme(widget):
    """Тёмный/светлый системный заголовок окна (Windows 10 20H1+ / 11)."""
    if sys.platform != 'win32':
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if T.CURRENT_DARK else 0)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (новый и старый номер)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def mix_color(a, b, t):
    """Линейное смешение двух цветов (t: 0 → a, 1 → b)."""
    a, b = QColor(a), QColor(b)
    t = max(0.0, min(1.0, float(t)))
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t),
                  round(a.alpha() + (b.alpha() - a.alpha()) * t))


def repolish(widget):
    """Переприменяет стиль после смены динамического свойства (role/state…)."""
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()



# Lucide icons (ISC License, https://lucide.dev): inner SVG of 24×24 stroke icons
LUCIDE = {
    'clapperboard': (
        '<path d="m12.296 3.464 3.02 3.956" />'
        '<path d="M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3z" />'
        '<path d="M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />'
        '<path d="m6.18 5.276 3.1 3.899" />'
    ),
    'film': (
        '<rect width="18" height="18" x="3" y="3" rx="2" />'
        '<path d="M7 3v18" />'
        '<path d="M3 7.5h4" />'
        '<path d="M3 12h18" />'
        '<path d="M3 16.5h4" />'
        '<path d="M17 3v18" />'
        '<path d="M17 7.5h4" />'
        '<path d="M17 16.5h4" />'
    ),
    'audio-lines': (
        '<path d="M2 10v3" />'
        '<path d="M6 6v11" />'
        '<path d="M10 3v18" />'
        '<path d="M14 8v7" />'
        '<path d="M18 5v13" />'
        '<path d="M22 10v3" />'
    ),
    'music': (
        '<path d="M9 18V5l12-2v13" />'
        '<circle cx="6" cy="18" r="3" />'
        '<circle cx="18" cy="16" r="3" />'
    ),
    'scroll-text': (
        '<path d="M15 12h-5" />'
        '<path d="M15 8h-5" />'
        '<path d="M19 17V5a2 2 0 0 0-2-2H4" />'
        '<path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" />'
    ),
    'settings': (
        '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" />'
        '<circle cx="12" cy="12" r="3" />'
    ),
    'folder-open': (
        '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />'
    ),
    'folder': (
        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />'
    ),
    'folder-output': (
        '<path d="M2 7.5V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-1.5" />'
        '<path d="M2 13h10" />'
        '<path d="m5 10-3 3 3 3" />'
    ),
    'play': (
        '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" />'
    ),
    'download': (
        '<path d="M12 15V3" />'
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />'
        '<path d="m7 10 5 5 5-5" />'
    ),
    'refresh-cw': (
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />'
        '<path d="M21 3v5h-5" />'
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />'
        '<path d="M8 16H3v5" />'
    ),
    'info': (
        '<circle cx="12" cy="12" r="10" />'
        '<path d="M12 16v-4" />'
        '<path d="M12 8h.01" />'
    ),
    'chevron-left': (
        '<path d="m15 18-6-6 6-6" />'
    ),
    'chevron-right': (
        '<path d="m9 18 6-6-6-6" />'
    ),
    'plus': (
        '<path d="M5 12h14" />'
        '<path d="M12 5v14" />'
    ),
    'copy': (
        '<rect width="14" height="14" x="8" y="8" rx="2" ry="2" />'
        '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />'
    ),
    'trash-2': (
        '<path d="M10 11v6" />'
        '<path d="M14 11v6" />'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />'
        '<path d="M3 6h18" />'
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />'
    ),
    'upload': (
        '<path d="M12 3v12" />'
        '<path d="m17 8-5-5-5 5" />'
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />'
    ),
    'sun': (
        '<circle cx="12" cy="12" r="4" />'
        '<path d="M12 2v2" />'
        '<path d="M12 20v2" />'
        '<path d="m4.93 4.93 1.41 1.41" />'
        '<path d="m17.66 17.66 1.41 1.41" />'
        '<path d="M2 12h2" />'
        '<path d="M20 12h2" />'
        '<path d="m6.34 17.66-1.41 1.41" />'
        '<path d="m19.07 4.93-1.41 1.41" />'
    ),
    'moon': (
        '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401" />'
    ),
    'sun-moon': (
        '<path d="M12 2v2" />'
        '<path d="M14.837 16.385a6 6 0 1 1-7.223-7.222c.624-.147.97.66.715 1.248a4 4 0 0 0 5.26 5.259c.589-.255 1.396.09 1.248.715" />'
        '<path d="M16 12a4 4 0 0 0-4-4" />'
        '<path d="m19 5-1.256 1.256" />'
        '<path d="M20 12h2" />'
    ),
    'monitor': (
        '<rect width="20" height="14" x="2" y="3" rx="2" />'
        '<line x1="8" x2="16" y1="21" y2="21" />'
        '<line x1="12" x2="12" y1="17" y2="21" />'
    ),
    'palette': (
        '<path d="M12 22a1 1 0 0 1 0-20 10 9 0 0 1 10 9 5 5 0 0 1-5 5h-2.25a1.75 1.75 0 0 0-1.4 2.8l.3.4a1.75 1.75 0 0 1-1.4 2.8z" />'
        '<circle cx="13.5" cy="6.5" r=".5" fill="currentColor" />'
        '<circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />'
        '<circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />'
        '<circle cx="8.5" cy="7.5" r=".5" fill="currentColor" />'
    ),
    'droplet': (
        '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z" />'
    ),
    'bell': (
        '<path d="M10.268 21a2 2 0 0 0 3.464 0" />'
        '<path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326" />'
    ),
    'globe': (
        '<circle cx="12" cy="12" r="10" />'
        '<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />'
        '<path d="M2 12h20" />'
    ),
    'cpu': (
        '<path d="M12 20v2" />'
        '<path d="M12 2v2" />'
        '<path d="M17 20v2" />'
        '<path d="M17 2v2" />'
        '<path d="M2 12h2" />'
        '<path d="M2 17h2" />'
        '<path d="M2 7h2" />'
        '<path d="M20 12h2" />'
        '<path d="M20 17h2" />'
        '<path d="M20 7h2" />'
        '<path d="M7 20v2" />'
        '<path d="M7 2v2" />'
        '<rect x="4" y="4" width="16" height="16" rx="2" />'
        '<rect x="8" y="8" width="8" height="8" rx="1" />'
    ),
    'circle-check': (
        '<circle cx="12" cy="12" r="10" />'
        '<path d="m16 9-5.5 5.5L8 12" />'
    ),
    'zap': (
        '<path d="M15.914 4a1.5 1.5 0 0 0 -2.474-1.561l-9 9A1.5 1.5 0 0 0 5.5 14h4.002a.5.5 0 0 1 .471.666L8.086 20a1.5 1.5 0 0 0 2.475 1.56l9-9A1.5 1.5 0 0 0 18.5 10h-3.997a.5.5 0 0 1 -.472-.667z" />'
    ),
    'circle-stop': (
        '<circle cx="12" cy="12" r="10" />'
        '<rect x="9" y="9" width="6" height="6" rx="1" />'
    ),
    'image': (
        '<rect width="18" height="18" x="3" y="3" rx="2" ry="2" />'
        '<circle cx="9" cy="9" r="2" />'
        '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />'
    ),
    'pipette': (
        '<path d="m12 9-8.414 8.414A2 2 0 0 0 3 18.828v1.344a2 2 0 0 1-.586 1.414A2 2 0 0 1 3.828 21h1.344a2 2 0 0 0 1.414-.586L15 12" />'
        '<path d="m18 9 .4.4a1 1 0 1 1-3 3l-3.8-3.8a1 1 0 1 1 3-3l.4.4 3.4-3.4a1 1 0 1 1 3 3z" />'
        '<path d="m2 22 .414-.414" />'
    ),
    'triangle-alert': (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />'
        '<path d="M12 9v4" />'
        '<path d="M12 17h.01" />'
    ),
    'circle-x': (
        '<circle cx="12" cy="12" r="10" />'
        '<path d="m15 9-6 6" />'
        '<path d="m9 9 6 6" />'
    ),
    'volume-2': (
        '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z" />'
        '<path d="M16 9a5 5 0 0 1 0 6" />'
        '<path d="M19.364 18.364a9 9 0 0 0 0-12.728" />'
    ),
    'waves': (
        '<path d="M2 12q2.5 2 5 0t5 0 5 0 5 0" />'
        '<path d="M2 19q2.5 2 5 0t5 0 5 0 5 0" />'
        '<path d="M2 5q2.5 2 5 0t5 0 5 0 5 0" />'
    ),
    'file-video': (
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" />'
        '<path d="M14 2v5a1 1 0 0 0 1 1h5" />'
        '<path d="M15.033 13.44a.647.647 0 0 1 0 1.12l-4.065 2.352a.645.645 0 0 1-.968-.56v-4.704a.645.645 0 0 1 .967-.56z" />'
    ),
    'loader-circle': (
        '<path d="M21 12a9 9 0 1 1-6.219-8.56" />'
    ),
    'sparkles': (
        '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z" />'
        '<path d="M20 2v4" />'
        '<path d="M22 4h-4" />'
        '<circle cx="4" cy="20" r="2" />'
    ),
    'rotate-ccw': (
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />'
        '<path d="M3 3v5h5" />'
    ),
}

# ============================================================================
#  Иконки — Lucide (https://lucide.dev, ISC), рисуются из SVG в цвет темы
# ============================================================================
_SVG_TEMPLATE = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
                 '<g fill="{fill}" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
                 'stroke-linejoin="round">{body}</g></svg>')
_FILLED_ICONS = {"play"}   # эти глифы рисуются залитыми (так «play» читается лучше)
_ICON_CACHE = {}


def icon_pixmap(kind, color, px=20, dpr=1.0, stroke=2.0):
    """Растр иконки kind цвета color размером px логических пикселей."""
    key = (kind, color, px, dpr, stroke)
    pm = _ICON_CACHE.get(key)
    if pm is not None:
        return pm
    size = max(1, int(round(px * dpr)))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    body = LUCIDE.get(kind, "")
    if body and QSvgRenderer is not None:
        svg = _SVG_TEMPLATE.format(color=color, stroke=stroke,
                                   fill=color if kind in _FILLED_ICONS else "none",
                                   body=body.replace("currentColor", color))
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
    pm.setDevicePixelRatio(dpr)
    if len(_ICON_CACHE) > 800:
        _ICON_CACHE.clear()
    _ICON_CACHE[key] = pm
    return pm


def make_icon(kind, color, on_color=None, px=20):
    """QIcon с растрами 1x/2x; on_color — цвет для отмеченного (checked) состояния."""
    icon = QIcon()
    for scale in (1, 2):
        size = px * scale
        icon.addPixmap(icon_pixmap(kind, color, size), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(icon_pixmap(kind, T.COLOR_TEXT_FAINT, size), QIcon.Mode.Disabled, QIcon.State.Off)
        if on_color:
            icon.addPixmap(icon_pixmap(kind, on_color, size), QIcon.Mode.Normal, QIcon.State.On)
            icon.addPixmap(icon_pixmap(kind, on_color, size), QIcon.Mode.Active, QIcon.State.On)
    return icon


# ============================================================================
#  Виджеты дизайн-системы
# ============================================================================
def _set_role(widget, role):
    widget.setProperty("role", role)
    return widget


class ElidedLabel(QLabel):
    """Подпись, которая сокращает длинный текст многоточием, не распирая макет."""

    def __init__(self, text="", parent=None, mode=Qt.TextElideMode.ElideMiddle):
        super().__init__(text, parent)
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self):
        return QSize(16, super().minimumSizeHint().height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), self._mode, rect.width())
        p.drawText(rect, self.alignment(), text)
        p.end()


class ComboBox(QComboBox):
    """Комбобокс со стрелкой-шевроном; колесо мыши не меняет значение без фокуса
    (страница прокручивается, а не настройки «случайно» перескакивают)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(QStyledItemDelegate(self))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMaxVisibleItems(12)
        self.setMinimumHeight(38)
        self._orig = []

    def add_items(self, items):
        """items: [(текст, data)]; исходный текст запоминается для переводов."""
        for text, data in items:
            self.addItem(text, data)
            self._orig.append(text)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(T.COLOR_TEXT_MUTED if self.isEnabled() else T.COLOR_TEXT_FAINT))
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 18.0, self.height() / 2.0
        path = QPainterPath()
        path.moveTo(cx - 4.5, cy - 2.0)
        path.lineTo(cx, cy + 2.5)
        path.lineTo(cx + 4.5, cy - 2.0)
        p.drawPath(path)
        p.end()


class Slider(QSlider):
    """Слайдер, который не перехватывает прокрутку страницы колесом мыши."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class SegmentedControl(QFrame):
    """Сегментированный переключатель (как вкладки-«таблетки»). Повторяет
    нужную часть API QComboBox, чтобы сохранение/восстановление настроек и
    переводы работали одинаково."""
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons, self._data, self._orig, self._icons = [], [], [], []
        self._index = -1

    def addItem(self, text, data=None, icon=None):
        b = QPushButton(text)
        b.setObjectName("segment")
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(32)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        idx = len(self._buttons)
        b.clicked.connect(lambda _checked=False, i=idx: self.setCurrentIndex(i))
        self._group.addButton(b)
        self._layout.addWidget(b, 1)
        self._buttons.append(b)
        self._data.append(data)
        self._orig.append(text)
        self._icons.append(icon)
        if icon:
            b.setIconSize(QSize(16, 16))
        if self._index < 0:
            self.setCurrentIndex(0)
        self.refresh_icons()

    def add_items(self, items):
        for item in items:
            self.addItem(*item)

    def refresh_icons(self):
        for b, kind in zip(self._buttons, self._icons):
            if kind:
                b.setIcon(make_icon(kind, T.COLOR_TEXT_MUTED, T.COLOR_ACCENT_TEXT, 16))

    def setCurrentIndex(self, index):
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setChecked(True)
        if index != self._index:
            self._index = index
            self.currentIndexChanged.emit(index)

    def currentIndex(self):
        return self._index

    def count(self):
        return len(self._buttons)

    def itemData(self, index):
        return self._data[index] if 0 <= index < len(self._data) else None

    def itemText(self, index):
        return self._buttons[index].text() if 0 <= index < len(self._buttons) else ""

    def setItemText(self, index, text):
        if 0 <= index < len(self._buttons):
            self._buttons[index].setText(text)

    def currentData(self):
        return self.itemData(self._index)

    def currentText(self):
        return self.itemText(self._index)

    def findData(self, data):
        return self._data.index(data) if data in self._data else -1

    def findText(self, text):
        for i, b in enumerate(self._buttons):
            if b.text() == text:
                return i
        return -1

    def isEditable(self):
        return False


class ToggleSwitch(QCheckBox):
    """Переключатель-«тумблер». Это QCheckBox: setChecked/isChecked/toggled
    работают как раньше, меняется только отрисовка."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._pos = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    def _on_anim(self, value):
        self._pos = float(value)
        self.update()

    def _animate(self, checked):
        self._anim.stop()
        if not self.isVisible():
            self._pos = 1.0 if checked else 0.0
            self.update()
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self):
        return QSize(46, 26)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(0.45)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        track = mix_color(T.COLOR_SWITCH_OFF, T.COLOR_PRIMARY, self._pos)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - 6 - d) * self._pos
        knob_rect = QRectF(x, r.top() + 3, d, d)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(knob_rect.translated(0, 1))
        on_knob = T.COLOR_ON_PRIMARY if T.CURRENT_DARK else "#ffffff"
        off_knob = "#ffffff" if not T.CURRENT_DARK else T.COLOR_TEXT_MUTED
        p.setBrush(mix_color(off_knob, on_knob, self._pos))
        p.drawEllipse(knob_rect)
        p.end()


class IconBadge(QLabel):
    """Иконка в мягкой цветной «плашке» (заголовки карточек, строки настроек)."""

    def __init__(self, kind, size=34, icon_px=18, color_attr="COLOR_ACCENT_TEXT", parent=None):
        super().__init__(parent)
        _set_role(self, "iconBadge")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if size != 34:
            radius = size // 2 if size >= 56 else round(size * 0.3)
            self.setStyleSheet(f"border-radius: {radius}px;")
        self._kind, self._px, self._color_attr = kind, icon_px, color_attr
        self.refresh()

    def set_icon(self, kind, color_attr=None):
        self._kind = kind
        if color_attr:
            self._color_attr = color_attr
        self.refresh()

    def refresh(self):
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        self.setPixmap(icon_pixmap(self._kind, getattr(T, self._color_attr), self._px, max(1.0, dpr)))


class Badge(QFrame):
    """Небольшой зелёный значок «⚡ Без перекодирования»."""

    def __init__(self, kind, text, parent=None):
        super().__init__(parent)
        self.setObjectName("badge")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 4, 11, 4)
        lay.setSpacing(5)
        self.icon = QLabel()
        self.icon.setFixedSize(14, 14)
        self.label = QLabel(text)
        lay.addWidget(self.icon)
        lay.addWidget(self.label)
        self._kind = kind
        self.refresh()

    def refresh(self):
        self.icon.setPixmap(icon_pixmap(self._kind, T.COLOR_GREEN, 14, 2.0))


class DropZone(QFrame):
    """Большая пунктирная зона «перетащите видео сюда» (клик = выбрать файлы)."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(184)
        self._hover = False
        self._active = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(4)
        lay.addStretch(1)
        self.icon = IconBadge("upload", 56, 26)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(8)
        self.title = _set_role(QLabel(), "title")
        self.subtitle = _set_role(QLabel(), "sub")
        self.formats = _set_role(QLabel("MP4 · MKV · MOV · AVI · WEBM · FLV · WMV · M4V · MPG · TS"), "caption")
        for lbl in (self.title, self.subtitle, self.formats):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        lay.addStretch(1)
        for w in (self.icon, self.title, self.subtitle, self.formats):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_active(self, active):
        self._active = bool(active)
        self.update()

    def refresh(self):
        self.icon.refresh()
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hot = self._hover or self._active
        if self._active:
            bg = QColor(T.COLOR_ACCENT_SOFT)
        elif self._hover:
            bg = mix_color(T.COLOR_CARD_BG, T.COLOR_ACCENT_SOFT, 0.55)
        else:
            bg = QColor(T.COLOR_CARD_BG)
        p.setBrush(bg)
        pen = QPen(QColor(T.COLOR_PRIMARY if hot else T.COLOR_INPUT_BORDER_HOVER))
        pen.setWidthF(1.6)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([4.0, 3.5])
        p.setPen(pen)
        p.drawRoundedRect(r, 16, 16)
        p.end()


class PreviewView(QWidget):
    """Кадр-превью со скруглёнными углами (или заглушка с иконкой)."""

    def __init__(self, w=240, h=135, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self._pm = None
        self._text = ""

    def setPixmap(self, pixmap):
        self._pm = pixmap if pixmap is not None and not pixmap.isNull() else None
        self.update()

    def pixmap(self):
        return self._pm

    def setText(self, text):
        self._text = text
        self._pm = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor("#0d0f14") if self._pm else QColor(T.COLOR_INPUT_BG))
        if self._pm is not None:
            p.save()
            p.setClipPath(path)
            pw, ph = self._pm.width(), self._pm.height()
            scale = min(r.width() / pw, r.height() / ph) if pw and ph else 1
            tw, th = pw * scale, ph * scale
            p.drawPixmap(QRectF(r.center().x() - tw / 2, r.center().y() - th / 2, tw, th),
                         self._pm, QRectF(0, 0, pw, ph))
            p.restore()
        else:
            icon = icon_pixmap("image", T.COLOR_TEXT_FAINT, 28, 2.0)
            p.drawPixmap(QPointF(r.center().x() - 14, r.center().y() - 26), icon)
            p.setPen(QColor(T.COLOR_TEXT_FAINT))
            p.setFont(ui_font(8.5, 500))
            p.drawText(QRectF(r.left() + 8, r.center().y() + 8, r.width() - 16, 22),
                       Qt.AlignmentFlag.AlignCenter, self._text)
        p.setPen(QPen(QColor(T.COLOR_CARD_BORDER), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


class BannerWidget(QWidget):
    """Шапка: логотип и название на градиенте с мягкими бликами и плывущими
    волнами вдоль нижнего края (цвет волн = фон страницы)."""

    def __init__(self, title, subtitle="", parent=None, height=110):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._badge = ""
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

    def setSubtitle(self, subtitle):
        self._subtitle = subtitle
        self.update()

    def setBadge(self, text):
        self._badge = text or ""
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
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), float(self.height())
        if w <= 0 or h <= 0:
            return
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 18, 18)
        painter.setClipPath(clip)

        a, b, c = T.BANNER_STOPS
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor(a))
        grad.setColorAt(0.55, QColor(b))
        grad.setColorAt(1.0, QColor(c))
        painter.fillPath(clip, grad)

        # Мягкие блики, медленно дрейфующие (эффект «aurora»)
        painter.setPen(Qt.PenStyle.NoPen)
        for cx, cy, rad, alpha, speed in ((0.80, 0.05, 1.45, 60, 0.33), (0.30, 0.95, 1.10, 38, 0.21),
                                          (0.58, 0.40, 0.75, 28, 0.47)):
            x = w * cx + math.sin(self._t * speed) * w * 0.05
            y = h * cy + math.cos(self._t * speed * 1.3) * h * 0.10
            radius = h * rad
            glow = QRadialGradient(QPointF(x, y), radius)
            glow.setColorAt(0.0, QColor(255, 255, 255, alpha))
            glow.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(x, y), radius, radius)

        # Логотип (как иконка приложения: кнопка «play» в скруглённом квадрате)
        wave_h = 30.0 * (1.0 + 0.22 * self._boost)
        content_h = h - 26
        mark = 46.0
        mx, my = 26.0, (content_h - mark) / 2 + 2
        painter.setBrush(QColor(255, 255, 255, 46))
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
        painter.drawRoundedRect(QRectF(mx, my, mark, mark), 13, 13)
        tri = QPainterPath()
        tri.moveTo(mx + mark * 0.40, my + mark * 0.30)
        tri.lineTo(mx + mark * 0.40, my + mark * 0.70)
        tri.lineTo(mx + mark * 0.72, my + mark * 0.50)
        tri.closeSubpath()
        painter.setPen(QPen(QColor(255, 255, 255), 3.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(tri)

        tx = mx + mark + 16
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(ui_font(19, 700))
        title_rect = QRectF(tx, my - 4, w - tx - 24, 32)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title)
        if self._subtitle:
            painter.setPen(QColor(255, 255, 255, 215))
            painter.setFont(ui_font(9.5, 500))
            painter.drawText(QRectF(tx, my + 28, w - tx - 24, 20),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._subtitle)

        if self._badge:
            font = ui_font(8.5, 600)
            painter.setFont(font)
            fm = painter.fontMetrics()
            bw = fm.horizontalAdvance(self._badge) + 26 if hasattr(fm, "horizontalAdvance") \
                else fm.width(self._badge) + 26
            bh = 24.0
            bx, by = w - bw - 22, (content_h - bh) / 2 + 2
            painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
            painter.setBrush(QColor(255, 255, 255, 40))
            painter.drawRoundedRect(QRectF(bx, by, bw, bh), bh / 2, bh / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#7ee2a8"))
            painter.drawEllipse(QPointF(bx + 12, by + bh / 2), 3.2, 3.2)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(bx + 18, by, bw - 22, bh), Qt.AlignmentFlag.AlignCenter, self._badge)

        # Волны — фирменный элемент (тот же рисунок, что и раньше)
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


def make_card():
    card = QFrame()
    card.setObjectName("card")
    return card


def make_divider(left=0, right=0):
    holder = QWidget()
    holder.setObjectName("transparent")
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(left, 0, right, 0)
    line = QFrame()
    line.setObjectName("divider")
    lay.addWidget(line)
    return holder


def style_button(button, variant=None, **props):
    """Назначает кнопке вариант оформления (primary/danger/ghost/icon…)."""
    if variant:
        button.setProperty("variant", variant)
    for k, v in props.items():
        button.setProperty(k, v)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


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
                self.progress.emit(tr("Проверка версии…"))
                latest = ffmpeg_latest_version()
                self.log.emit(tr_fmt("Установлено: {cur}  ·  Последняя: {latest}",
                                     cur=cur or '—', latest=latest or tr('неизвестно')))
                if (cur and latest and not self.force
                        and _version_tuple(cur) >= _version_tuple(latest)):
                    self.done.emit(True, tr_fmt("Уже актуально — FFmpeg {v}.", v=cur))
                    return

            self.progress.emit(tr("Скачивание FFmpeg…"))
            self._download(FFMPEG_DOWNLOAD_URL, zip_path)
            if self._cancel:
                self.done.emit(False, tr("Отменено."))
                return

            self.progress.emit(tr("Распаковка…"))
            new_bin = self._extract_new(zip_path, new_dir)
            new_ver = ffmpeg_local_version(os.path.join(new_bin, "ffmpeg" + _EXE))
            if not new_ver:
                raise RuntimeError("Скачанный ffmpeg не прошёл проверку запуска")

            self.progress.emit(tr("Установка…"))
            self._swap(new_dir, target)
            fp = os.path.join(target_bin, "ffprobe" + _EXE)
            save_config(ffmpeg_installed=True,
                        ffmpeg_path=os.path.join(target_bin, "ffmpeg" + _EXE),
                        ffprobe_path=fp if os.path.exists(fp) else os.path.join(target_bin, "ffmpeg" + _EXE))
            self.log.emit(tr_fmt("Готово: FFmpeg {v}", v=new_ver))
            self.progress.emit(tr("Готово!"))
            self.done.emit(True, tr_fmt("FFmpeg {v} установлен.", v=new_ver))
        except Exception as e:
            self.log.emit(tr_fmt("Ошибка: {e}", e=e))
            self.done.emit(False, str(e))
        finally:
            _rmtree_retry(new_dir, attempts=2)
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass



# ============================================================================
#  Диалоги
# ============================================================================
class ThemedDialog(QDialog):
    """Базовый диалог: иконка окна, без «?» в заголовке, тёмный заголовок в Windows."""

    def __init__(self, parent=None, title=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        try:
            self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        except Exception:
            pass
        icon = parent.windowIcon() if parent is not None else (QIcon(APP_ICON) if APP_ICON else None)
        if icon is not None:
            self.setWindowIcon(icon)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_theme(self)

    @staticmethod
    def header(kind, title, subtitle="", state=None):
        """Строка заголовка диалога: иконка в плашке + заголовок + подзаголовок."""
        row = QHBoxLayout()
        row.setSpacing(14)
        color = {"done": "COLOR_GREEN", "error": "COLOR_RED"}.get(state, "COLOR_ACCENT_TEXT")
        badge = IconBadge(kind, 44, 22, color)
        if state:
            badge.setProperty("state", state)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = _set_role(QLabel(title), "h1")
        col.addWidget(t)
        s = None
        if subtitle is not None:
            s = _set_role(QLabel(subtitle), "sub")
            s.setWordWrap(True)
            col.addWidget(s)
        row.addLayout(col, 1)
        return row, t, s


class FFmpegSetupDialog(ThemedDialog):
    """Установка (авто) или обновление FFmpeg — с логом и прогрессом (как в DIV)."""

    def __init__(self, mode="install", parent=None):
        super().__init__(parent, tr("Установка FFmpeg") if mode == "install"
                         else tr("Обновление FFmpeg"))
        self.mode = mode
        self.success = False
        self.thread = None
        self.setMinimumSize(560, 460)
        if mode == "install":
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        head, _title, self.label = self.header(
            "download" if mode == "install" else "refresh-cw",
            tr("Установка FFmpeg") if mode == "install" else tr("Обновление FFmpeg"),
            tr("Проверка FFmpeg…") if mode == "install"
            else tr("Нажмите «Проверить и обновить», чтобы сравнить версию FFmpeg с последней."))
        layout.addLayout(head)

        prow = QHBoxLayout()
        prow.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        prow.addWidget(self.progress, 1)
        self.percent = _set_role(QLabel("0%"), "percent")
        self.percent.setMinimumWidth(38)
        self.progress.valueChanged.connect(lambda v: self.percent.setText(f"{v}%"))
        prow.addWidget(self.percent)
        layout.addLayout(prow)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        layout.addWidget(self.log_view, 1)

        force_row = QHBoxLayout()
        force_row.setSpacing(10)
        self.chk_force = ToggleSwitch()
        force_lbl = _set_role(QLabel(tr("Переустановить, даже если версия актуальна")), "sub")
        force_row.addWidget(self.chk_force)
        force_row.addWidget(force_lbl, 1)
        self._force_widgets = (self.chk_force, force_lbl)
        for w in self._force_widgets:
            w.setVisible(mode == "update")
        layout.addLayout(force_row)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.btn_close = style_button(QPushButton(tr("Закрыть")), "ghost")
        self.btn_close.clicked.connect(self._close_or_cancel)
        row.addWidget(self.btn_close)
        self.btn_action = style_button(QPushButton(tr("Проверить и обновить")), "primary")
        self.btn_action.setIcon(make_icon("refresh-cw", T.COLOR_ON_PRIMARY, px=18))
        self.btn_action.setVisible(mode == "update")
        self.btn_action.clicked.connect(lambda: self._start(self.chk_force.isChecked()))
        row.addWidget(self.btn_action)
        layout.addLayout(row)

        if mode == "install":
            self.btn_close.setEnabled(False)
            self._start(force=False)

    def _start(self, force):
        self.btn_action.setEnabled(False)
        self.chk_force.setEnabled(False)
        self.btn_close.setText(tr("Отмена"))
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
            self.label.setText(tr_fmt("Скачивание… {p}%", p=message))
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
        self.btn_close.setText(tr("Закрыть"))
        self.btn_close.setEnabled(True)
        if self.mode == "install" and ok:
            QTimer.singleShot(800, self.accept)

    def _close_or_cancel(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()
            self.log_view.append(tr("Отмена…"))
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


class NotificationDialog(ThemedDialog):
    """Окно «Готово» с кнопками «Открыть файл» / «Открыть папку»."""

    def __init__(self, output_file, parent=None):
        super().__init__(parent, tr("Готово"))
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(6)

        badge = IconBadge("circle-check", 64, 32, "COLOR_GREEN")
        badge.setProperty("state", "done")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(8)
        title = _set_role(QLabel(tr("Готово!")), "h1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        sub = _set_role(QLabel(tr("Файл успешно создан")), "sub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)
        name = _set_role(ElidedLabel(os.path.basename(output_file)), "rowTitle")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setToolTip(output_file)
        layout.addWidget(name)
        layout.addSpacing(14)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_close = style_button(QPushButton(tr("Закрыть")), "ghost")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_close)
        row.addStretch(1)
        self.btn_folder = style_button(QPushButton(tr("Открыть папку")))
        self.btn_folder.setIcon(make_icon('folder-open', T.COLOR_BTN_TEXT, px=18))
        self.btn_folder.clicked.connect(lambda: self._act(output_file, True))
        row.addWidget(self.btn_folder)
        self.btn_play = style_button(QPushButton(tr("Открыть файл")), "primary")
        self.btn_play.setIcon(make_icon('play', T.COLOR_ON_PRIMARY, px=18))
        self.btn_play.clicked.connect(lambda: self._act(output_file, False))
        self.btn_play.setDefault(True)
        row.addWidget(self.btn_play)
        layout.addLayout(row)

    def _act(self, file_path, folder):
        target = os.path.dirname(file_path) if folder else file_path
        if target and os.path.exists(target):
            open_in_os(target)
        self.accept()


class DestinationDialog(ThemedDialog):
    """«Куда сохранить результат?» — карточки-варианты вместо системного окна."""

    def __init__(self, output_dir, start_dir, parent=None):
        super().__init__(parent, tr("Сохранение"))
        self.result_dir = None
        self._start_dir = start_dir
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        head, _t, _s = self.header("folder-output", tr("Куда сохранить результат?"),
                                   tr("Папку по умолчанию можно задать в настройках"))
        layout.addLayout(head)
        layout.addSpacing(6)
        first = None
        if output_dir and os.path.isdir(output_dir):
            first = self._option(layout, "folder", tr("В папку по умолчанию"), output_dir,
                                 lambda: self._finish(output_dir))
        b = self._option(layout, "file-video", tr("Рядом с исходным файлом"),
                         tr("В ту же папку, где лежит видео"), lambda: self._finish(""))
        first = first or b
        self._option(layout, "folder-open", tr("Выбрать папку…"),
                     tr("Указать другое место на диске"), self._choose)
        layout.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = style_button(QPushButton(tr("Отмена")), "ghost")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        layout.addLayout(row)
        first.setFocus()

    def _option(self, layout, kind, title, subtitle, callback):
        btn = QPushButton()
        btn.setObjectName("optionCard")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(64)
        row = QHBoxLayout(btn)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)
        badge = IconBadge(kind, 38, 20)
        row.addWidget(badge)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = _set_role(QLabel(title), "rowTitle")
        s = _set_role(ElidedLabel(subtitle), "sub")
        s.setToolTip(subtitle)
        col.addWidget(t)
        col.addWidget(s)
        row.addLayout(col, 1)
        chevron = QLabel()
        chevron.setPixmap(icon_pixmap("chevron-right", T.COLOR_TEXT_FAINT, 18, 2.0))
        row.addWidget(chevron)
        for w in (badge, t, s, chevron):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        btn.clicked.connect(callback)
        layout.addWidget(btn)
        return btn

    def _choose(self):
        d = QFileDialog.getExistingDirectory(self, tr("Выберите папку"), self._start_dir)
        if d:
            self._finish(d)

    def _finish(self, value):
        self.result_dir = value
        self.accept()


class VideoInfoDialog(ThemedDialog):
    """Отдельное окно с полной информацией о видео (все потоки, все поля)."""

    def __init__(self, video_info, file_path, preview_pixmap=None, parent=None):
        super().__init__(parent, tr("Подробная информация"))
        self.resize(600, 660)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        if preview_pixmap is not None and not preview_pixmap.isNull():
            pv = PreviewView(176, 99)
            pv.setPixmap(preview_pixmap)
            header.addWidget(pv, 0)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addStretch(1)
        name = _set_role(QLabel(os.path.basename(file_path) if file_path else ""), "title")
        name.setWordWrap(True)
        col.addWidget(name)
        folder = _set_role(ElidedLabel(os.path.dirname(file_path) if file_path else ""), "sub")
        folder.setToolTip(file_path or "")
        col.addWidget(folder)
        col.addStretch(1)
        header.addLayout(col, 1)
        layout.addLayout(header)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setHtml(self._build_html(video_info))
        layout.addWidget(self.text, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.btn_copy = style_button(QPushButton(tr("Копировать")))
        self.btn_copy.setIcon(make_icon('copy', T.COLOR_BTN_TEXT, px=18))
        self.btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        row.addWidget(self.btn_copy)
        self.btn_close = style_button(QPushButton(tr("Закрыть")), "primary")
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
        return f"{b / (1024*1024):.2f} MB ({b:,} {tr('байт')})"

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
        muted, accent, text = T.COLOR_TEXT_MUTED, T.COLOR_ACCENT_TEXT, T.COLOR_TEXT

        def esc(x):
            return str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        def section(title):
            return (f'<div style="margin-top:14px;margin-bottom:4px;color:{accent};'
                    f'font-weight:600;font-size:10.5pt;">{esc(title)}</div>')

        def table(pairs):
            out = '<table cellspacing="0" cellpadding="3" style="font-size:9.5pt;">'
            any_row = False
            for k, val in pairs:
                if val in (None, '', 'N/A'):
                    continue
                any_row = True
                out += (f'<tr><td style="color:{muted};padding-right:18px;white-space:nowrap;'
                        f'vertical-align:top;">{esc(tr(k))}</td>'
                        f'<td style="color:{text};">{esc(val)}</td></tr>')
            out += '</table>'
            return out if any_row else ''

        fmt = info.get('format', {}) or {}
        streams = info.get('streams', []) or []
        html = [f'<div style="color:{text};">']

        html.append(section(tr("Контейнер")))
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
                html.append(section(tr_fmt("Видеопоток #{n}", n=vi)))
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
                html.append(section(tr_fmt("Аудиопоток #{n}", n=ai)))
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
                html.append(section(f"{(ctype or tr('поток')).capitalize()} #{si}"))
                html.append(table([
                    ("Кодек", s.get('codec_name')),
                    ("Язык", tags.get('language')),
                    ("Название", tags.get('title')),
                ]))
        html.append('</div>')
        return ''.join(html)


# ============================================================================
#  Кодирование: профили качества и совместимость кодеков с контейнерами.
#  Значения — по встроенным пресетам HandBrake и вики FFmpeg: CRF/CQ вместо
#  «голого» кодека (у VP9/AV1/NVENC значения FFmpeg по умолчанию — это либо
#  2 Мбит/с, либо очень медленное кодирование).
# ============================================================================
QUALITY_LEVELS = ("high", "balanced", "small")

# (максимальное, баланс, меньший размер)
_VIDEO_PROFILES = {
    "libx264": {"crf": (18, 21, 25), "preset": ("slow", "medium", "medium")},
    "libx265": {"crf": (20, 23, 27), "preset": ("slow", "medium", "medium")},
    "libvpx-vp9": {"crf": (24, 31, 36), "cpu-used": (2, 3, 4)},
    "libsvtav1": {"crf": (26, 32, 38), "preset": (4, 6, 8)},
    "libaom-av1": {"crf": (26, 32, 38), "cpu-used": (4, 6, 6)},
    "h264_nvenc": {"cq": (19, 23, 27), "preset": ("p7", "p5", "p5")},
    "hevc_nvenc": {"cq": (22, 26, 30), "preset": ("p7", "p5", "p5")},
    "h264_qsv": {"gq": (20, 24, 28), "preset": ("slower", "medium", "medium")},
    "hevc_qsv": {"gq": (20, 24, 28), "preset": ("slower", "medium", "medium")},
    "h264_amf": {"qp": (18, 22, 26)},
    "hevc_amf": {"qp": (18, 22, 26)},
    "mpeg4": {"q": (2, 3, 5)},
    "mpeg2video": {"q": (2, 3, 5)},
    "wmv2": {"q": (2, 3, 5)},
}
_AUDIO_BITRATES = {"aac": (192, 160, 128), "libopus": (160, 128, 96), "ac3": (448, 384, 256),
                   "mp2": (256, 192, 160), "wmav2": (192, 160, 128)}
_MP3_VBR_Q = (0, 2, 4)        # libmp3lame -q:a (≈245 / 190 / 165 кбит/с)
_VORBIS_Q = (6, 5, 4)

ENCODER_CODEC = {
    "libx264": "h264", "h264_nvenc": "h264", "h264_qsv": "h264", "h264_amf": "h264",
    "libx265": "hevc", "hevc_nvenc": "hevc", "hevc_qsv": "hevc", "hevc_amf": "hevc",
    "libvpx-vp9": "vp9", "libsvtav1": "av1", "libaom-av1": "av1",
    "mpeg4": "mpeg4", "mpeg2video": "mpeg2video", "wmv2": "wmv2",
    "libopus": "opus", "libmp3lame": "mp3", "aac": "aac", "flac": "flac", "libvorbis": "vorbis",
    "ac3": "ac3", "pcm_s16le": "pcm_s16le", "wmav2": "wmav2", "mp2": "mp2",
}
HW_SUFFIXES = ("_nvenc", "_qsv", "_amf")

# Какие кодеки контейнер принимает (None — любые): по ним решаем, можно ли
# скопировать поток без перекодирования и подходит ли выбранный кодек.
CONTAINER_VIDEO = {
    "mp4": {"h264", "hevc", "mpeg4", "av1", "vp9"},
    "m4v": {"h264", "hevc", "mpeg4"},
    "mov": {"h264", "hevc", "mpeg4", "prores", "mjpeg"},
    "mkv": None,
    "webm": {"vp8", "vp9", "av1"},
    "avi": {"h264", "mpeg4", "msmpeg4v2", "msmpeg4v3", "mjpeg"},
    "flv": {"h264", "flv1"},
    "ts": {"h264", "hevc", "mpeg2video"},
    "mpg": {"mpeg1video", "mpeg2video"},
    "mpeg": {"mpeg1video", "mpeg2video"},
    "wmv": {"wmv1", "wmv2", "wmv3", "vc1"},
}
CONTAINER_AUDIO = {
    "mp4": {"aac", "mp3", "ac3", "eac3", "alac"},
    "m4v": {"aac", "mp3", "ac3", "eac3", "alac"},
    "mov": {"aac", "mp3", "ac3", "eac3", "alac", "pcm_s16le", "pcm_s24le", "pcm_s16be", "pcm_s24be"},
    "mkv": None,
    "webm": {"opus", "vorbis"},
    "avi": {"mp3", "ac3", "mp2", "pcm_s16le"},
    "flv": {"aac", "mp3"},
    "ts": {"aac", "mp3", "ac3", "eac3", "mp2"},
    "mpg": {"mp2", "mp3", "ac3"},
    "mpeg": {"mp2", "mp3", "ac3"},
    "wmv": {"wmav1", "wmav2", "wmapro", "mp3"},
}
CONTAINER_DEFAULT_VIDEO = {"webm": "vp9", "mpg": "mpeg2video", "mpeg": "mpeg2video", "wmv": "wmv2"}
CONTAINER_DEFAULT_AUDIO = {"webm": "libopus", "avi": "libmp3lame", "mpg": "mp2", "mpeg": "mp2",
                           "wmv": "wmav2"}
MKV_SUBTITLES = {"subrip", "ass", "ssa", "hdmv_pgs_subtitle", "dvd_subtitle", "webvtt", "text"}
TEXT_SUBTITLES = {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}


def parse_bitrate(token):
    """'2M' / '500k' / '192000' → бит/с (int) или None."""
    m = re.match(r'^(\d+(?:\.\d+)?)([kKmMgG]?)$', str(token or '').strip())
    if not m:
        return None
    value = int(float(m.group(1)) * {'': 1, 'k': 1e3, 'm': 1e6, 'g': 1e9}[m.group(2).lower()])
    return value if value > 0 else None


def _level_index(level):
    return QUALITY_LEVELS.index(level) if level in QUALITY_LEVELS else 1


def video_rate_args(encoder, level="balanced", bitrate=None, src10=False, container="", minimal=False):
    """Аргументы качества (CRF/CQ) или битрейта, скорости и формата пикселей.
    minimal=True — урезанный набор для старых GPU (без lookahead/AQ/tune)."""
    i = _level_index(level)
    prof = _VIDEO_PROFILES.get(encoder, {})
    br = parse_bitrate(bitrate) if bitrate else None
    capped = ["-b:v", str(br), "-maxrate", str(int(br * 1.5)), "-bufsize", str(br * 2)] if br else []
    args = []
    if encoder in ("libx264", "libx265"):
        args += ["-preset", prof["preset"][i]]
        args += capped or ["-crf", str(prof["crf"][i])]
        if encoder == "libx265":
            args += ["-pix_fmt", "yuv420p10le" if src10 else "yuv420p", "-x265-params", "log-level=error"]
        else:
            args += ["-pix_fmt", "yuv420p"]   # 4:2:0 8 бит — играется везде
    elif encoder == "libvpx-vp9":
        args += ["-deadline", "good", "-cpu-used", str(prof["cpu-used"][i]), "-row-mt", "1", "-g", "240"]
        args += ["-b:v", str(br)] if br else ["-crf", str(prof["crf"][i]), "-b:v", "0"]
        args += ["-pix_fmt", "yuv420p"]
    elif encoder == "libsvtav1":
        args += ["-preset", str(prof["preset"][i]), "-g", "240", "-pix_fmt", "yuv420p10le"]
        args += ["-b:v", str(br)] if br else ["-crf", str(prof["crf"][i])]
    elif encoder == "libaom-av1":
        args += ["-cpu-used", str(prof["cpu-used"][i]), "-row-mt", "1", "-tiles", "2x2", "-g", "240",
                 "-pix_fmt", "yuv420p10le" if src10 else "yuv420p"]
        args += ["-b:v", str(br)] if br else ["-crf", str(prof["crf"][i]), "-b:v", "0"]
    elif encoder.endswith("_nvenc"):
        args += ["-preset", prof["preset"][i], "-rc", "vbr"]
        if not minimal:
            args += ["-tune", "hq", "-rc-lookahead", "20", "-spatial-aq", "1"]
        args += capped or ["-cq", str(prof["cq"][i]), "-b:v", "0"]
        args += ["-pix_fmt", "p010le" if (src10 and encoder == "hevc_nvenc") else "yuv420p"]
    elif encoder.endswith("_qsv"):
        if not minimal:
            args += ["-preset", prof["preset"][i]]
        args += ["-b:v", str(br)] if br else ["-global_quality", str(prof["gq"][i])]
        if src10 and encoder == "hevc_qsv":
            args += ["-pix_fmt", "p010le"]
    elif encoder.endswith("_amf"):
        if not minimal:
            args += ["-usage", "transcoding", "-quality", "quality"]
        if br:
            args += ["-rc", "vbr_peak", "-b:v", str(br), "-maxrate", str(int(br * 1.5))]
        else:
            q = prof["qp"][i]
            args += ["-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q + 2)]
            if encoder == "h264_amf":
                args += ["-qp_b", str(q + 4)]
    elif encoder in ("mpeg4", "mpeg2video", "wmv2"):
        args += ["-b:v", str(br)] if br else ["-q:v", str(prof["q"][i])]
        args += ["-pix_fmt", "yuv420p"]
        if encoder == "mpeg4" and container == "avi":
            args += ["-tag:v", "XVID"]     # лучше узнаётся старыми плеерами
    elif br:
        args += ["-b:v", str(br)]
    if ENCODER_CODEC.get(encoder) == "hevc" and container in ("mp4", "mov", "m4v"):
        args += ["-tag:v", "hvc1"]         # иначе Apple-устройства не откроют HEVC
    return args


def audio_encode_args(encoder, level="balanced", bitrate=None, channels=None):
    """-c:a и битрейт/качество для аудиоэнкодера."""
    i = _level_index(level)
    args = ["-c:a", encoder]
    br = parse_bitrate(bitrate) if bitrate else None
    if br:
        args += ["-b:a", str(br)]
    elif encoder in _AUDIO_BITRATES:
        kbps = _AUDIO_BITRATES[encoder][i]
        multichannel = bool(channels and channels > 2)
        if multichannel and encoder in ("aac", "libopus"):
            kbps *= 2                      # 5.1/7.1 — вдвое больше, чем стерео
        elif encoder == "ac3" and not multichannel:
            kbps = (256, 192, 160)[i]      # 448 кбит/с имеют смысл только для 5.1
        args += ["-b:a", f"{kbps}k"]
    elif encoder == "libmp3lame":
        args += ["-q:a", str(_MP3_VBR_Q[i])]
    elif encoder == "libvorbis":
        args += ["-q:a", str(_VORBIS_Q[i])]
    return args


def scale_filter(target):
    """'1920:1080' → вписать кадр в рамку с учётом ориентации (вертикальное видео
    получает 1080×1920), без увеличения и без чёрных полос."""
    w, h = (int(x) for x in str(target).split(":"))
    big, small = max(w, h), min(w, h)
    return (f"scale=w='if(gte(iw,ih),min({big},iw),min({small},iw))'"
            f":h='if(gte(iw,ih),min({small},ih),min({big},ih))'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2"
            ":flags=lanczos+accurate_rnd")


# ============================================================================
#  Основное окно
# ============================================================================
class VideoConverter(QMainWindow):
    VIDEO_EXTS = ('.mp4', '.mkv', '.mov', '.avi', '.flv', '.webm', '.wmv',
                  '.m4v', '.mpg', '.mpeg', '.ts')
    KNOWN_CONTAINERS = {"mp4", "mkv", "mov", "avi", "flv", "webm", "wmv", "m4v",
                        "mpg", "mpeg", "ts"}
    VIDEO_ENCODER_MAP = {
        'vp9': 'libvpx-vp9', 'h264': 'libx264', 'h265': 'libx265', 'hevc': 'libx265',
    }
    QUALITY_NAMES = {None: "Как в исходнике", "high": "Максимальное", "balanced": "Баланс",
                     "small": "Меньший размер"}
    QUALITY_HINTS = {
        None: "Видео копируется без перекодирования, если формат это позволяет — мгновенно и без потерь",
        "high": "Визуально без потерь (как CRF 18 у x264) — файл крупнее",
        "balanced": "Качество почти неотличимо от исходника, файл заметно меньше — рекомендуем",
        "small": "Сильнее сжатие — для отправки и хранения, мелкие детали чуть мягче",
    }
    PAGE_VIDEO, PAGE_AUDIO, PAGE_LOGS, PAGE_SETTINGS = range(4)
    NAV_ITEMS = (("tab_video", "Видео", "clapperboard"), ("tab_audio", "Аудио", "audio-lines"),
                 ("tab_logs", "Логи", "scroll-text"), ("tab_settings", "Настройки", "settings"))
    AUDIO_FORMAT_HINTS = {
        "mp3": "MP3 — совместим со всем, сжатие с потерями",
        "aac": "AAC — компактный и качественный, отлично для телефонов",
        "flac": "FLAC — без потери качества, файл заметно больше",
        "wav": "WAV — несжатый PCM, максимальный размер",
        "ogg": "OGG Vorbis — открытый формат, сжатие с потерями",
        "ac3": "AC3 — Dolby Digital, подходит для 5.1",
    }
    MIN_W, MIN_H = 900, 620

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cine Convert")
        if APP_ICON:
            self.setWindowIcon(QIcon(APP_ICON))
        self.setAcceptDrops(True)

        cfg = load_config()
        self._init_geometry(cfg)
        self.settings = {
            "show_video_notifications": cfg.get("show_video_notifications", True),
            "show_audio_notifications": cfg.get("show_audio_notifications", True),
            "open_folder_when_done": cfg.get("open_folder_when_done", False),
            "sound_notifications": cfg.get("sound_notifications", True),
            "ask_destination": cfg.get("ask_destination", True),
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
        self._info_pairs = []
        self._info_cols = 3
        self._probe_cache = {}     # (path, mtime) -> ffprobe json — листание без подтормаживаний
        self._preview_cache = {}   # (path, mtime) -> QPixmap
        self._busy = False
        self._batch_cancelled = False
        self._batch_errors = 0
        self._encoders_cache = None
        self._hw_cache = {}        # результаты пробного кодирования NVENC/QSV/AMF
        self._retired_workers = []  # отменённые, но ещё не завершившиеся процессы
        self._page = self.PAGE_VIDEO
        self._status_sticky = False   # «Готово!»/«Отменено» держится до следующего действия
        self._spin_angle = 0
        self.ffmpeg_path = "ffmpeg"
        self.ffprobe_path = "ffprobe"
        self.translations = {}
        self.locales_map = {}
        self._i18n = []            # (виджет, ключ, текст по умолчанию, тип)
        self._i18n_items = []      # комбобоксы/сегменты с переводимыми пунктами
        self._icon_widgets = []    # (кнопка, kind, role) для перекраски при смене темы
        self._badges = []
        self._segments = []
        self._gap_buttons = set()
        self._compact = False

        self._theme_timer = QTimer(self)
        self._theme_timer.setSingleShot(True)
        self._theme_timer.setInterval(30)
        self._theme_timer.timeout.connect(self._apply_theme)
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(60)
        self._spin_timer.timeout.connect(self._spin_status_icon)

        self.setup_ui()
        self._setup_icons()
        self._apply_theme()

        self.chk_video_notify.setChecked(self.settings["show_video_notifications"])
        self.chk_audio_notify.setChecked(self.settings["show_audio_notifications"])
        self.chk_open_folder.setChecked(self.settings["open_folder_when_done"])
        self.chk_sound.setChecked(self.settings["sound_notifications"])
        self.chk_ask_dest.setChecked(self.settings["ask_destination"])
        self.restore_render_settings(cfg)
        self._update_audio_hint()
        self._update_quality_hint()

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
        self._setup_shortcuts()
        self._ui_ready = True
        self._go(self.PAGE_VIDEO, splash=False)

    def _init_geometry(self, cfg):
        w, h = 1140, 840
        try:
            ww, wh = cfg.get("win_size") or (0, 0)
            if int(ww) >= self.MIN_W and int(wh) >= self.MIN_H:
                w, h = int(ww), int(wh)
        except Exception:
            pass
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.setMinimumSize(min(self.MIN_W, avail.width() - 20), min(self.MIN_H, avail.height() - 20))
            w, h = min(w, avail.width() - 24), min(h, avail.height() - 24)
            self.resize(w, h)
            self.move(avail.x() + (avail.width() - self.width()) // 2,
                      avail.y() + max(0, (avail.height() - self.height()) // 2))
        else:
            self.setMinimumSize(self.MIN_W, self.MIN_H)
            self.resize(w, h)

    # ---------------------------------------------------------- i18n -------
    def _reg(self, widget, key, default, kind="text"):
        """Запоминает переводимый текст виджета (см. _retranslate)."""
        self._i18n.append((widget, key, default, kind))
        if kind == "text":
            widget.setText(tr(key, default))
        elif kind == "tip":
            widget.setToolTip(tr(key, default))
        return widget

    def _label(self, key, text, role):
        return self._reg(_set_role(QLabel(), role), key, text)

    def _combo(self, items, editable=False, tip=None):
        combo = ComboBox()
        combo.add_items(items)
        combo.setEditable(editable)
        if tip:
            combo.setToolTip(tip)
        self._i18n_items.append(combo)
        return combo

    def _segmented(self, items):
        seg = SegmentedControl()
        seg.add_items(items)
        self._i18n_items.append(seg)
        self._segments.append(seg)
        return seg

    def tr_or(self, text):
        return tr(text)

    # ---------------------------------------------------------------- UI ----
    def setup_ui(self):
        central = QWidget()
        central.setObjectName("transparent")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Шапка с волнами
        self.banner = BannerWidget("Cine Convert")
        self._reg(self.banner, "banner_subtitle", "Видеоконвертер на базе FFmpeg", kind="subtitle")
        self.banner.setSubtitle(tr("banner_subtitle", "Видеоконвертер на базе FFmpeg"))
        self.banner.set_animated(load_config().get("wave_anim", True))
        root.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)
        body.addWidget(self._build_sidebar())

        main = QVBoxLayout()
        main.setSpacing(12)
        body.addLayout(main, 1)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_media_page())     # Видео + Аудио (общий источник)
        self.pages.addWidget(self._build_logs_page())
        self.pages.addWidget(self._build_settings_page())
        main.addWidget(self.pages, 1)
        main.addWidget(self._build_action_bar())

    # ---- боковая навигация ----
    def _build_sidebar(self):
        side = QWidget()
        side.setObjectName("transparent")
        side.setFixedWidth(196)
        self.sidebar = side
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for idx, (key, text, _kind) in enumerate(self.NAV_ITEMS):
            b = QPushButton()
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(44)
            b.setIconSize(QSize(20, 20))
            b.setProperty("shortcut", f"Ctrl+{idx + 1}")
            b.clicked.connect(lambda _c=False, i=idx: self._go(i))
            self._i18n.append((b, key, text, "nav"))
            b.setText(" " + tr(key, text))
            b.setToolTip(f"{tr(key, text)}  ·  Ctrl+{idx + 1}")
            self.nav_group.addButton(b)
            self.nav_buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)

        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setObjectName("navButton")
        self.btn_theme_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme_toggle.setMinimumHeight(40)
        self.btn_theme_toggle.setIconSize(QSize(18, 18))
        self.btn_theme_toggle.clicked.connect(self._toggle_theme)
        lay.addWidget(self.btn_theme_toggle)
        self.version_label = _set_role(QLabel(f"Cine Convert {APP_VERSION}"), "caption")
        self.version_label.setContentsMargins(14, 2, 0, 0)
        lay.addWidget(self.version_label)
        return side

    def _scroll_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("transparent")
        scroll.setWidget(content)
        return scroll, content

    def _card(self, key, title, icon, sub_key=None, sub=None):
        """Карточка с заголовком: (рамка, тело-VBox, правый слот заголовка)."""
        card = make_card()
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(12)
        badge = IconBadge(icon)
        self._badges.append(badge)
        head.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(self._label(key, title, "title"))
        if sub:
            s = self._label(sub_key, sub, "sub")
            s.setWordWrap(True)
            col.addWidget(s)
        head.addLayout(col, 1)
        right = QHBoxLayout()
        right.setSpacing(8)
        head.addLayout(right)
        v.addLayout(head)
        return card, v, right

    def _field(self, grid, row, col, key, text, widget):
        grid.addWidget(self._label(key, text, "field"), row, col)
        grid.addWidget(widget, row + 1, col)

    # ---- страница «Видео/Аудио»: источник + параметры ----
    def _build_media_page(self):
        scroll, content = self._scroll_page()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(12)
        lay.addWidget(self._build_source())
        # Параметры видео и аудио — переключаются видимостью, а не QStackedWidget:
        # стек учитывает высоту скрытой страницы и даёт лишнюю прокрутку
        self.mode_pages = [self._build_video_settings(), self._build_audio_settings()]
        for page in self.mode_pages:
            lay.addWidget(page)
        lay.addStretch(1)
        return scroll

    def _build_source(self):
        self.source_stack = QStackedWidget()
        self.drop_zone = DropZone()
        self.drop_zone.clicked.connect(self.select_input_files)
        self._reg(self.drop_zone.title, "drop_title", "Перетащите видео сюда")
        self._reg(self.drop_zone.subtitle, "drop_subtitle",
                  "или нажмите, чтобы выбрать файлы — можно сразу несколько")
        self.source_stack.addWidget(self.drop_zone)

        self.media_card = make_card()
        h = QHBoxLayout(self.media_card)
        h.setContentsMargins(14, 14, 16, 14)
        h.setSpacing(18)
        self.preview_label = PreviewView(240, 135)
        h.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.file_title = _set_role(ElidedLabel(), "fileTitle")
        top.addWidget(self.file_title, 1)
        self.btn_info_prev = style_button(QPushButton(), "icon", flat=True)
        self._reg(self.btn_info_prev, "tip_prev", "Предыдущее видео", kind="tip")
        self.btn_info_prev.clicked.connect(lambda: self._show_info_at(self._info_index - 1))
        self.info_nav_label = _set_role(QLabel("1/1"), "pill")
        self.info_nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_info_next = style_button(QPushButton(), "icon", flat=True)
        self._reg(self.btn_info_next, "tip_next", "Следующее видео", kind="tip")
        self.btn_info_next.clicked.connect(lambda: self._show_info_at(self._info_index + 1))
        for w in (self.btn_info_prev, self.info_nav_label, self.btn_info_next):
            top.addWidget(w)
        col.addLayout(top)
        self.file_path_label = _set_role(ElidedLabel(), "sub")
        col.addWidget(self.file_path_label)
        col.addSpacing(8)

        self.info_container = QWidget()
        self.info_container.setObjectName("transparent")
        self.info_grid = QGridLayout(self.info_container)
        self.info_grid.setHorizontalSpacing(10)
        self.info_grid.setVerticalSpacing(5)
        self.info_grid.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self.info_container)
        col.addStretch(1)
        col.addSpacing(8)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_details = style_button(QPushButton())
        self._reg(self.btn_details, "btn_details", "Подробнее")
        self._reg(self.btn_details, "tip_details", "Полная информация о видео в отдельном окне", kind="tip")
        self.btn_details.setEnabled(False)
        self.btn_details.clicked.connect(self._show_video_details)
        self.btn_add_files = style_button(QPushButton())
        self._reg(self.btn_add_files, "btn_add_files", "Добавить ещё")
        self._reg(self.btn_add_files, "tip_add_files", "Добавить файлы к уже выбранным", kind="tip")
        self.btn_add_files.clicked.connect(lambda: self.select_input_files(append=True))
        self.btn_clear_input = style_button(QPushButton(), "ghostDanger")
        self._reg(self.btn_clear_input, "btn_clear_input", "Очистить")
        self._reg(self.btn_clear_input, "tip_clear_input", "Убрать все выбранные файлы", kind="tip")
        self.btn_clear_input.clicked.connect(self.clear_inputs)
        btns.addWidget(self.btn_details)
        btns.addWidget(self.btn_add_files)
        btns.addStretch(1)
        btns.addWidget(self.btn_clear_input)
        col.addLayout(btns)
        h.addLayout(col, 1)
        self.source_stack.addWidget(self.media_card)
        self._set_info_placeholder()
        self._set_info_nav_visible(False)
        return self.source_stack

    def _build_video_settings(self):
        page = QWidget()
        page.setObjectName("transparent")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        card, body, head_right = self._card(
            "card_video", "Видео", "film", "card_video_sub",
            "Оставьте «Без изменений» — и видео перепакуется мгновенно, без потери качества")
        self.lossless_badge = Badge("zap", "")
        self._reg(self.lossless_badge.label, "badge_lossless", "Без перекодирования")
        self._reg(self.lossless_badge, "tip_lossless",
                  "Видеопоток будет скопирован 1:1 — быстро и без потерь", kind="tip")
        self.lossless_badge.setVisible(False)
        head_right.addWidget(self.lossless_badge, 0, Qt.AlignmentFlag.AlignTop)

        body.addWidget(self._label("lbl_format", "Формат", "field"))
        self.format = self._segmented([
            ("Исходный", None), ("MP4", "mp4"), ("MKV", "mkv"), ("MOV", "mov"),
            ("AVI", "avi"), ("FLV", "flv"), ("WEBM", "webm"),
        ])
        self._reg(self.format, "tip_format",
                  "Контейнер выходного файла. «Исходный» — оставить как у исходника.", kind="tip")
        body.addWidget(self.format)

        body.addWidget(self._label("lbl_quality", "Качество", "field"))
        self.quality = self._segmented([(text, key) for key, text in self.QUALITY_NAMES.items()])
        self._reg(self.quality, "tip_quality",
                  "Качество при перекодировании (CRF/CQ, как в HandBrake). "
                  "«Как в исходнике» — без перекодирования, если возможно.", kind="tip")
        body.addWidget(self.quality)
        self.quality_hint = _set_role(QLabel(), "sub")
        self.quality_hint.setWordWrap(True)
        body.addWidget(self.quality_hint)
        self.quality.currentIndexChanged.connect(self._update_quality_hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        self.resolution = self._combo([
            ("Без изменений", None), ("4K (3840x2160)", "3840:2160"),
            ("1440p (2560x1440)", "2560:1440"), ("1080p (1920x1080)", "1920:1080"),
            ("720p (1280x720)", "1280:720"), ("480p (854x480)", "854:480"),
            ("360p (640x360)", "640:360"), ("240p (426x240)", "426:240"),
            ("144p (256x144)", "256:144"), ("128p (256x128)", "256:128"),
        ])
        self.video_codec = self._combo([
            ("Без изменений", None), ("H.264 · x264", "libx264"), ("H.265 · x265", "libx265"),
            ("AV1", "av1"), ("VP9", "vp9"),
            ("H.264 · NVIDIA", "h264_nvenc"), ("H.265 · NVIDIA", "hevc_nvenc"),
            ("H.264 · Intel QSV", "h264_qsv"), ("H.265 · Intel QSV", "hevc_qsv"),
            ("H.264 · AMD", "h264_amf"), ("H.265 · AMD", "hevc_amf"),
        ])
        self._reg(self.video_codec, "tip_codec",
                  "«Без изменений» — кодек исходника. Аппаратные кодеки (NVIDIA/Intel/AMD) "
                  "проверяются перед запуском; если не работают — берётся программный.", kind="tip")
        self.bitrate = self._combo([(t, None) for t in
                                    ("Без изменений", "500k", "1M", "2M", "5M", "10M", "20M")],
                                   editable=True)
        self._reg(self.bitrate, "tip_bitrate",
                  "Средний битрейт видео (напр. 2M) вместо качества. «Без изменений» — "
                  "управлять качеством (рекомендуется).", kind="tip")
        self._field(grid, 0, 0, "lbl_resolution", "Разрешение", self.resolution)
        self._field(grid, 0, 1, "lbl_codec", "Кодек", self.video_codec)
        self._field(grid, 0, 2, "lbl_bitrate", "Битрейт", self.bitrate)
        body.addLayout(grid)
        lay.addWidget(card)

        card2, body2, _r = self._card("card_vaudio", "Звук в видео", "audio-lines", "card_vaudio_sub",
                                      "Кодек, битрейт и каналы звуковой дорожки результата")
        grid2 = QGridLayout()
        grid2.setHorizontalSpacing(12)
        grid2.setVerticalSpacing(6)
        for c in range(3):
            grid2.setColumnStretch(c, 1)
        self.audio_codec = self._combo([
            ("Без изменений", None), ("Копировать (copy)", "copy"),
            ("aac", "aac"), ("mp3", "mp3"), ("flac", "flac"),
            ("opus", "opus"), ("ac3", "ac3"),
        ])
        self.audio_bitrate = self._combo([(t, None) for t in
                                          ("Без изменений", "64k", "128k", "192k", "256k", "320k")],
                                         editable=True)
        self.audio_channels = self._combo([
            ("Без изменений", None), ("1 (моно)", "1"), ("2 (стерео)", "2"),
            ("5.1", "6"), ("7.1", "8"),
        ])
        self._field(grid2, 0, 0, "lbl_acodec", "Кодек", self.audio_codec)
        self._field(grid2, 0, 1, "lbl_abitrate", "Битрейт", self.audio_bitrate)
        self._field(grid2, 0, 2, "lbl_achannels", "Каналы", self.audio_channels)
        body2.addLayout(grid2)
        lay.addWidget(card2)
        lay.addStretch(1)
        return page

    def _build_audio_settings(self):
        page = QWidget()
        page.setObjectName("transparent")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        card, body, _r = self._card("card_extract", "Извлечение аудио", "music", "card_extract_sub",
                                    "Сохраните звуковую дорожку видео в отдельный файл")
        body.addWidget(self._label("lbl_aformat", "Формат аудио", "field"))
        self.audio_format = self._segmented([(f.upper(), f) for f in
                                             ("mp3", "aac", "flac", "wav", "ogg", "ac3")])
        body.addWidget(self.audio_format)
        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        self.audio_hint_icon = QLabel()
        self.audio_hint_icon.setFixedSize(16, 16)
        hint_row.addWidget(self.audio_hint_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.audio_hint = _set_role(QLabel(), "sub")
        self.audio_hint.setWordWrap(True)
        hint_row.addWidget(self.audio_hint, 1)
        body.addLayout(hint_row)
        self.audio_format.currentIndexChanged.connect(self._update_audio_hint)
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _update_quality_hint(self, *_):
        level = self.quality.currentData()
        self.quality_hint.setText(tr(f"qhint_{level or 'source'}", self.QUALITY_HINTS.get(level, "")))

    def _update_audio_hint(self, *_):
        fmt = self.audio_format.currentData() or ""
        self.audio_hint.setText(tr(f"afmt_{fmt}", self.AUDIO_FORMAT_HINTS.get(fmt, "")))
        self.audio_hint_icon.setPixmap(icon_pixmap("info", T.COLOR_TEXT_MUTED, 16, 2.0))
        self._on_user_change()

    # ---- журнал ----
    def _build_logs_page(self):
        page = QWidget()
        page.setObjectName("transparent")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        card, body, right = self._card("card_logs", "Журнал FFmpeg", "scroll-text", "card_logs_sub",
                                       "Команда и вывод FFmpeg для последней операции")
        self.btn_copy_log = style_button(QPushButton(), "ghost")
        self._reg(self.btn_copy_log, "btn_copy_log", "Копировать")
        self.btn_copy_log.clicked.connect(self._copy_log)
        self.btn_clear_log = style_button(QPushButton(), "ghost")
        self._reg(self.btn_clear_log, "btn_clear_log", "Очистить")
        right.addWidget(self.btn_copy_log)
        right.addWidget(self.btn_clear_log)
        self.log_text = QTextEdit()
        self.log_text.setObjectName("logView")
        self.log_text.setReadOnly(True)
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        body.addWidget(self.log_text, 1)
        lay.addWidget(card, 1)
        return page

    def _copy_log(self):
        QApplication.clipboard().setText(self.log_text.toPlainText())

    # ---- настройки: секции из карточек со строками (как в Windows 11) ----
    def _setting_row(self, icon, key, title, sub_key=None, sub=None, elide_sub=False):
        row = QWidget()
        row.setObjectName("transparent")
        h = QHBoxLayout(row)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(14)
        badge = IconBadge(icon)
        self._badges.append(badge)
        h.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(self._label(key, title, "rowTitle"))
        s = None
        if sub is not None:
            s = _set_role(ElidedLabel(sub) if elide_sub else QLabel(sub), "sub")
            if not elide_sub:
                s.setWordWrap(True)
            if sub_key:
                self._reg(s, sub_key, sub)
            col.addWidget(s)
        h.addLayout(col, 1)
        right = QHBoxLayout()
        right.setSpacing(8)
        h.addLayout(right)
        return row, right, s

    def _settings_group(self, layout, key, title, rows):
        layout.addWidget(self._label(key, title, "section"))
        card = make_card()
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(0)
        for i, r in enumerate(rows):
            if i:
                v.addWidget(make_divider(64, 16))
            v.addWidget(r)
        layout.addWidget(card)

    def _build_settings_page(self):
        scroll, content = self._scroll_page()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 6, 8)
        lay.setSpacing(8)

        # Сохранение
        row_dir, r, self.output_dir_value = self._setting_row(
            "folder-output", "set_output_dir", "Папка по умолчанию", sub="", elide_sub=True)
        self.btn_choose_output = style_button(QPushButton())
        self._reg(self.btn_choose_output, "btn_choose_output", "Выбрать…")
        self.btn_choose_output.clicked.connect(self._choose_output_dir)
        self.btn_reset_output = style_button(QPushButton(), "ghost")
        self._reg(self.btn_reset_output, "btn_reset_output", "Сбросить")
        self._reg(self.btn_reset_output, "tip_reset_output", "Сохранять рядом с исходным файлом", kind="tip")
        self.btn_reset_output.clicked.connect(self._reset_output_dir)
        r.addWidget(self.btn_choose_output)
        r.addWidget(self.btn_reset_output)
        row_ask, r, _s = self._setting_row(
            "info", "chk_ask_dest", "Спрашивать, куда сохранить", "chk_ask_dest_sub",
            "Если выключено — файл сразу сохраняется в папку по умолчанию (или рядом с исходным)")
        self.chk_ask_dest = ToggleSwitch()
        r.addWidget(self.chk_ask_dest)
        self._settings_group(lay, "sec_output", "Сохранение", [row_dir, row_ask])

        # Уведомления
        self.chk_video_notify = ToggleSwitch()
        self.chk_audio_notify = ToggleSwitch()
        self.chk_open_folder = ToggleSwitch()
        self.chk_sound = ToggleSwitch()
        rows = []
        for icon, key, title, sub_key, sub, sw in (
            ("bell", "chk_video_notify", "Уведомление после рендера видео", "chk_video_notify_sub",
             "Окно с кнопками «Открыть файл» и «Открыть папку»", self.chk_video_notify),
            ("music", "chk_audio_notify", "Уведомление после извлечения аудио", "chk_audio_notify_sub",
             "То же окно, когда звуковая дорожка сохранена", self.chk_audio_notify),
            ("folder-open", "chk_open_folder", "Открывать папку с результатом", "chk_open_folder_sub",
             "Автоматически, когда обработка завершена", self.chk_open_folder),
            ("volume-2", "chk_sound", "Звуковой сигнал", "chk_sound_sub",
             "Короткий системный звук вместе с уведомлением", self.chk_sound),
        ):
            row, r, _s = self._setting_row(icon, key, title, sub_key, sub)
            r.addWidget(sw)
            rows.append(row)
        self._settings_group(lay, "sec_notify", "Уведомления", rows)

        # Внешний вид
        row_hue, r, _s = self._setting_row("palette", "set_accent", "Акцентный цвет", "set_accent_sub",
                                           "Вся палитра пересчитывается из одного оттенка")
        self.hue_slider = Slider(Qt.Orientation.Horizontal)
        self.hue_slider.setRange(0, 360)
        self.hue_slider.setValue(T.CURRENT_HUE)
        self.hue_slider.setMinimumWidth(230)
        self.hue_slider.valueChanged.connect(self._on_hue_changed)
        self.hue_slider.sliderReleased.connect(lambda: save_config(hue=self.hue_slider.value()))
        self.hue_swatch = _set_role(QLabel(), "swatch")
        self.hue_swatch.setFixedSize(24, 24)
        self.color_pick_btn = style_button(QPushButton(), "icon")
        self._reg(self.color_pick_btn, "tip_pick_color", "Выбрать цвет…", kind="tip")
        self.color_pick_btn.clicked.connect(self._pick_color)
        r.addWidget(self.hue_slider)
        r.addWidget(self.hue_swatch)
        r.addWidget(self.color_pick_btn)

        row_sat, r, _s = self._setting_row("droplet", "set_saturation", "Насыщенность")
        self.sat_slider = Slider(Qt.Orientation.Horizontal)
        self.sat_slider.setRange(50, 160)
        self.sat_slider.setValue(T.CURRENT_SATURATION)
        self.sat_slider.setMinimumWidth(230)
        self.sat_slider.valueChanged.connect(self._on_sat_changed)
        self.sat_slider.sliderReleased.connect(lambda: save_config(saturation=self.sat_slider.value()))
        self.sat_value = _set_role(QLabel(f"{T.CURRENT_SATURATION}%"), "pill")
        self.sat_value.setFixedWidth(56)
        self.sat_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r.addWidget(self.sat_slider)
        r.addWidget(self.sat_value)

        row_mode, r, _s = self._setting_row("sun-moon", "set_theme", "Тема")
        self.mode_combo = self._segmented([("Светлая", "light", "sun"), ("Тёмная", "dark", "moon"),
                                           ("Системная", "system", "monitor")])
        self.mode_combo.setMinimumWidth(330)
        mi = self.mode_combo.findData(load_config().get("theme_mode", "light"))
        if mi >= 0:
            self.mode_combo.setCurrentIndex(mi)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        r.addWidget(self.mode_combo)

        row_wave, r, _s = self._setting_row("waves", "chk_wave", "Анимированные волны в шапке",
                                            "chk_wave_sub", "Плавное движение и всплеск при смене раздела")
        self.chk_wave = ToggleSwitch()
        self.chk_wave.setChecked(load_config().get("wave_anim", True))
        self.chk_wave.toggled.connect(self._on_wave_toggled)
        r.addWidget(self.chk_wave)
        self._settings_group(lay, "sec_appearance", "Внешний вид", [row_hue, row_sat, row_mode, row_wave])

        # Язык
        row_lang, r, _s = self._setting_row("globe", "set_language", "Язык интерфейса", "set_language_sub",
                                            "Переводы — JSON-файлы в папке locales")
        self.locale_combo = ComboBox()
        self.locale_combo.setMinimumWidth(200)
        self._reg(self.locale_combo, "tip_language", "Язык применяется сразу при выборе", kind="tip")
        self.locale_combo.currentIndexChanged.connect(self._on_locale_changed)
        self.btn_refresh_locales = style_button(QPushButton(), "icon")
        self._reg(self.btn_refresh_locales, "btn_refresh_locales", "Обновить список", kind="tip")
        self.btn_refresh_locales.clicked.connect(self.load_locales)
        self.btn_open_locales = style_button(QPushButton(), "icon")
        self._reg(self.btn_open_locales, "btn_open_locales", "Открыть папку локалей", kind="tip")
        self.btn_open_locales.clicked.connect(self.open_locales_folder)
        r.addWidget(self.locale_combo)
        r.addWidget(self.btn_refresh_locales)
        r.addWidget(self.btn_open_locales)
        self._settings_group(lay, "sec_language", "Язык", [row_lang])

        # FFmpeg
        row_ff, r, self.ffmpeg_version_label = self._setting_row(
            "cpu", "set_ffmpeg", "FFmpeg", sub=tr("FFmpeg: проверка…"), elide_sub=True)
        self.btn_update_ffmpeg = style_button(QPushButton())
        self._reg(self.btn_update_ffmpeg, "btn_update_ffmpeg", "Обновить")
        self._reg(self.btn_update_ffmpeg, "tip_update_ffmpeg",
                  "Скачивает свежую сборку FFmpeg (gyan.dev, release-essentials) "
                  "в папку рядом с программой. Нужен интернет.", kind="tip")
        self.btn_update_ffmpeg.clicked.connect(self._update_ffmpeg)
        self.btn_ffmpeg_folder = style_button(QPushButton(), "icon")
        self._reg(self.btn_ffmpeg_folder, "tip_ffmpeg_folder", "Открыть папку FFmpeg", kind="tip")
        self.btn_ffmpeg_folder.clicked.connect(
            lambda: open_in_os(os.path.join(APP_DIR, "ffmpeg", "bin")))
        r.addWidget(self.btn_update_ffmpeg)
        r.addWidget(self.btn_ffmpeg_folder)
        self._settings_group(lay, "sec_ffmpeg", "FFmpeg", [row_ff])

        about = self._label("about_line", "Cine Convert · шрифт Inter (OFL) · иконки Lucide (ISC)", "caption")
        about.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(6)
        lay.addWidget(about)
        lay.addStretch(1)
        self._refresh_output_dir_label()
        return scroll

    # ---- нижняя панель действий (статус, прогресс, главная кнопка) ----
    def _build_action_bar(self):
        bar = make_card()
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 12, 12, 12)
        h.setSpacing(14)
        self.status_icon = IconBadge("sparkles", 42, 20)
        h.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.batch_status_label = _set_role(ElidedLabel(), "status")
        top.addWidget(self.batch_status_label, 1)
        self.percent_label = _set_role(QLabel(""), "percent")
        top.addWidget(self.percent_label)
        mid.addLayout(top)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.valueChanged.connect(self._on_progress_value)
        mid.addWidget(self.progress_bar)
        self.stats_label = _set_role(ElidedLabel(), "sub")
        mid.addWidget(self.stats_label)
        h.addLayout(mid, 1)

        self.btn_cancel = style_button(QPushButton(), "danger", size="lg")
        self._reg(self.btn_cancel, "btn_cancel", "Отмена")
        self.btn_cancel.setMinimumHeight(46)
        self.btn_cancel.clicked.connect(self.cancel_current)
        self.btn_cancel.setVisible(False)
        self.btn_render = style_button(QPushButton(), "primary")
        self._reg(self.btn_render, "btn_render", "Рендер")
        self._reg(self.btn_render, "tip_render", "Начать конвертацию (Ctrl+Enter)", kind="tip")
        self.btn_render.setMinimumSize(170, 46)
        self.btn_render.clicked.connect(self.start_video_render)
        self.btn_extract = style_button(QPushButton(), "primary")
        self._reg(self.btn_extract, "btn_extract", "Извлечь аудио")
        self._reg(self.btn_extract, "tip_extract", "Сохранить звуковую дорожку (Ctrl+Enter)", kind="tip")
        self.btn_extract.setMinimumSize(170, 46)
        self.btn_extract.clicked.connect(self.extract_audio)
        for b in (self.btn_cancel, self.btn_render, self.btn_extract):
            b.setIconSize(QSize(18, 18))
            h.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    # ------------------------------------------------------- Навигация -----
    def _go(self, index, splash=True):
        index = max(0, min(len(self.nav_buttons) - 1, int(index)))
        self._page = index
        self.nav_buttons[index].setChecked(True)
        if index in (self.PAGE_VIDEO, self.PAGE_AUDIO):
            self.pages.setCurrentIndex(0)
            for i, page in enumerate(self.mode_pages):
                page.setVisible(i == index)
        else:
            self.pages.setCurrentIndex(index - 1)
        self.btn_render.setVisible(index == self.PAGE_VIDEO)
        self.btn_extract.setVisible(index == self.PAGE_AUDIO)
        if splash:
            self.banner.splash()
        self._update_summary()

    def _setup_shortcuts(self):
        def bind(seq, fn):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(fn)
        bind("Ctrl+O", self.select_input_files)
        bind("Ctrl+Return", self._primary_action)
        bind("Ctrl+Enter", self._primary_action)
        for i in range(len(self.nav_buttons)):
            bind(f"Ctrl+{i + 1}", lambda i=i: self._go(i))

    def _primary_action(self):
        if self._busy:
            return
        if self._page == self.PAGE_VIDEO:
            self.start_video_render()
        elif self._page == self.PAGE_AUDIO:
            self.extract_audio()

    # ------------------------------------------------------------- Тема ----
    def _schedule_theme(self):
        self._theme_timer.start()

    def _apply_theme(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(build_palette())
            app.setStyleSheet(T.STYLESHEET_MAIN)
        self.hue_slider.setStyleSheet(T.STYLESHEET_HUE_SLIDER)
        self.sat_slider.setStyleSheet(T.STYLESHEET_SAT_SLIDER)
        self.sat_value.setText(f"{T.CURRENT_SATURATION}%")
        for badge in self._badges:
            badge.refresh()
        self.lossless_badge.refresh()
        self.drop_zone.refresh()
        self._rebuild_icons()
        self._refresh_status_icon()
        self._update_audio_hint_icon()
        self._refresh_theme_toggle()
        self.banner.update()
        apply_window_theme(self)

    # --------------------------------------------------------- Иконки ------
    def _reg_icon(self, widget, kind, role, px=18):
        widget.setIconSize(QSize(px, px))
        self._icon_widgets.append((widget, kind, role, px))
        if widget.text():
            # у QPushButton нет настройки отступа между иконкой и текстом
            self._gap_buttons.add(widget)
            widget.setText(" " + widget.text().lstrip())

    @staticmethod
    def _icon_colors(role):
        if role == 'primary':
            return T.COLOR_ON_PRIMARY, None
        if role == 'danger':
            return T.COLOR_RED, None
        if role == 'muted':
            return T.COLOR_TEXT_MUTED, None
        if role == 'nav':
            return T.COLOR_TEXT_MUTED, T.COLOR_ACCENT_TEXT
        return T.COLOR_BTN_TEXT, None

    def _rebuild_icons(self):
        for widget, kind, role, px in self._icon_widgets:
            color, on_color = self._icon_colors(role)
            widget.setIcon(make_icon(kind, color, on_color, px))
        for seg in self._segments:
            seg.refresh_icons()

    def _setup_icons(self):
        for b, (_k, _t, kind) in zip(self.nav_buttons, self.NAV_ITEMS):
            b.setIconSize(QSize(20, 20))
            self._icon_widgets.append((b, kind, 'nav', 20))
        for w, kind, role in (
            (self.btn_render, 'play', 'primary'),
            (self.btn_extract, 'download', 'primary'),
            (self.btn_cancel, 'circle-stop', 'danger'),
            (self.btn_details, 'info', 'secondary'),
            (self.btn_add_files, 'plus', 'secondary'),
            (self.btn_clear_input, 'trash-2', 'muted'),
            (self.btn_info_prev, 'chevron-left', 'muted'),
            (self.btn_info_next, 'chevron-right', 'muted'),
            (self.btn_choose_output, 'folder-open', 'secondary'),
            (self.btn_reset_output, 'rotate-ccw', 'muted'),
            (self.btn_update_ffmpeg, 'refresh-cw', 'secondary'),
            (self.btn_ffmpeg_folder, 'folder', 'secondary'),
            (self.btn_refresh_locales, 'refresh-cw', 'secondary'),
            (self.btn_open_locales, 'folder', 'secondary'),
            (self.btn_copy_log, 'copy', 'muted'),
            (self.btn_clear_log, 'trash-2', 'muted'),
            (self.color_pick_btn, 'pipette', 'secondary'),
        ):
            self._reg_icon(w, kind, role)

    def _update_audio_hint_icon(self):
        self.audio_hint_icon.setPixmap(icon_pixmap("info", T.COLOR_TEXT_MUTED, 16, 2.0))

    def _refresh_theme_toggle(self):
        dark = T.CURRENT_DARK
        text = tr("theme_to_light", "Светлая тема") if dark else tr("theme_to_dark", "Тёмная тема")
        self.btn_theme_toggle.setText("" if self._compact else " " + text)
        self.btn_theme_toggle.setToolTip(text)
        self.btn_theme_toggle.setIcon(make_icon("sun" if dark else "moon", T.COLOR_TEXT_MUTED, px=18))

    def _toggle_theme(self):
        idx = self.mode_combo.findData("light" if T.CURRENT_DARK else "dark")
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

    def _on_hue_changed(self, value):
        set_theme(hue=value)
        self._schedule_theme()

    def _on_sat_changed(self, value):
        set_theme(saturation=value)
        self.sat_value.setText(f"{T.CURRENT_SATURATION}%")
        self._schedule_theme()

    def _on_mode_changed(self, *_):
        mode = self.mode_combo.currentData() or "light"
        set_theme(dark=is_system_dark() if mode == "system" else (mode == "dark"))
        save_config(theme_mode=mode)
        self._apply_theme()

    def _on_wave_toggled(self, on):
        save_config(wave_anim=bool(on))
        self.banner.set_animated(on)

    def _pick_color(self):
        dlg = QColorDialog(self)
        try:
            dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        except Exception:
            pass
        dlg.setCurrentColor(QColor(T.COLOR_PRIMARY))
        dlg.setWindowTitle(tr("Выбор цвета"))
        if dlg.exec():
            col = dlg.currentColor()
            _, C, H = srgb_to_oklch(col.red(), col.green(), col.blue())
            self.hue_slider.setValue(int(round(H)))
            self.sat_slider.setValue(max(50, min(160, int(round(C / 0.14 * 100)))))
            save_config(hue=T.CURRENT_HUE, saturation=T.CURRENT_SATURATION)

    # ------------------------------------------------- Статус / сводка -----
    _STATUS_ICONS = {
        "idle": ("sparkles", "COLOR_ACCENT_TEXT"),
        "busy": ("loader-circle", "COLOR_ACCENT_TEXT"),
        "done": ("circle-check", "COLOR_GREEN"),
        "error": ("triangle-alert", "COLOR_RED"),
        "cancelled": ("circle-x", "COLOR_TEXT_MUTED"),
    }

    def _set_status(self, text, state="idle", sticky=False):
        self.batch_status_label.setText(text)
        self.batch_status_label.setToolTip(text)
        if self.status_icon.property("state") != state:
            self.status_icon.setProperty("state", state)
            repolish(self.status_icon)
        self._status_sticky = sticky
        self._refresh_status_icon()
        if state == "busy":
            if not self._spin_timer.isActive():
                self._spin_timer.start()
        else:
            self._spin_timer.stop()

    def _refresh_status_icon(self):
        state = self.status_icon.property("state") or "idle"
        kind, attr = self._STATUS_ICONS.get(state, self._STATUS_ICONS["idle"])
        self.status_icon.set_icon(kind, attr)
        if state == "busy":
            self._spin_status_icon(step=0)

    def _spin_status_icon(self, step=30):
        self._spin_angle = (self._spin_angle + step) % 360
        dpr = max(1.0, self.status_icon.devicePixelRatioF())
        base = icon_pixmap("loader-circle", T.COLOR_ACCENT_TEXT, 20, dpr)
        rotated = base.transformed(QTransform().rotate(self._spin_angle),
                                   Qt.TransformationMode.SmoothTransformation)
        # после поворота растр больше — обрезаем по центру до исходного размера
        size = base.width()
        x = (rotated.width() - size) // 2
        y = (rotated.height() - size) // 2
        frame = rotated.copy(x, y, size, size)
        frame.setDevicePixelRatio(dpr)
        self.status_icon.setPixmap(frame)

    def _on_progress_value(self, value):
        self.percent_label.setText(f"{value}%" if (self._busy or value > 0) else "")

    def _on_user_change(self, *_):
        """Любое действие пользователя сбрасывает «Готово!» и обновляет сводку."""
        if not getattr(self, '_ui_ready', False) or self._busy:
            return
        self._status_sticky = False
        self._update_summary()

    def _is_lossless(self):
        """Видео будет скопировано без перекодирования (как в _build_video_command)."""
        if not self._current_files:
            return False
        s = self.current_render_settings()
        if s["video_codec"] or s["resolution"] or s["bitrate"] or s["quality"]:
            return False
        fmt = (s["format"] or "").lower()
        for f in self._current_files:
            in_ext = os.path.splitext(f)[1].lstrip(".").lower()
            out_ext = fmt if fmt in self.KNOWN_CONTAINERS else (in_ext or "mp4")
            info = self._probe_cache.get(self._cache_key(f))
            vstreams = self._streams(info, 'video') if info else []
            if vstreams:   # точная проверка по кодеку исходника
                allowed = CONTAINER_VIDEO.get(out_ext)
                if allowed is not None and (vstreams[0].get('codec_name') or '') not in allowed:
                    return False
            elif out_ext not in (in_ext, "mkv"):
                return False
        return True

    def _video_summary(self):
        files = self._current_files
        s = self.current_render_settings()
        parts = [(s["format"] or "").upper() or tr("исходный формат")]
        if self._is_lossless():
            parts.append(tr("без перекодирования"))
        else:
            if s["video_codec"]:
                parts.append(self.video_codec.currentText())
            if s["resolution"]:
                parts.append(self.resolution.currentText().split(" ")[0])
            level = s["quality"] or "balanced"   # кодек выбран без качества → «Баланс»
            parts.append(s["bitrate"] or self.quality.itemText(self.quality.findData(level)))
        head = (tr_fmt("Файлов: {n}", n=len(files)) if len(files) > 1
                else os.path.basename(files[0]))
        return f"{head}  →  " + " · ".join(parts)

    def _update_summary(self, *_):
        if not hasattr(self, "lossless_badge"):
            return
        self.lossless_badge.setVisible(self._is_lossless())
        if self._busy or self._status_sticky:
            return
        files = self._current_files
        if not files:
            text = tr("Добавьте видео, чтобы начать")
        elif self._page == self.PAGE_AUDIO:
            text = tr_fmt("Звук из «{name}» → {fmt}",
                          name=os.path.basename(self._info_file or self.input_file),
                          fmt=(self.audio_format.currentData() or "").upper())
        else:
            text = self._video_summary()
        self._set_status(text, "idle")
        self.stats_label.setText(tr("Ctrl+O — открыть файлы  ·  Ctrl+Enter — старт"))
        self.progress_bar.setValue(0)

    # ---------------------------------------------- Папка сохранения -------
    def _refresh_output_dir_label(self):
        text = self.output_dir or tr("output_dir_none", "Рядом с исходным файлом")
        self.output_dir_value.setText(text)
        self.output_dir_value.setToolTip(self.output_dir or "")
        if hasattr(self, "btn_reset_output"):
            self.btn_reset_output.setEnabled(bool(self.output_dir))

    def _choose_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Папка для сохранения"),
                                             self.output_dir or self.last_dir or "")
        if d:
            self.output_dir = d
            save_config(output_dir=d)
            self._refresh_output_dir_label()

    def _reset_output_dir(self):
        self.output_dir = ""
        save_config(output_dir="")
        self._refresh_output_dir_label()

    # ---------------------------------------------- Обновление FFmpeg ------
    def _ffmpeg_version_text(self):
        try:
            r = run_hidden([getattr(self, "ffmpeg_path", "ffmpeg"), "-version"],
                           capture_output=True, text=True, timeout=8)
            first = (r.stdout or "").splitlines()[0] if r.stdout else ""
            return first.strip() or tr("FFmpeg: версия неизвестна")
        except Exception:
            return tr("FFmpeg: не найден")

    def refresh_ffmpeg_label(self):
        text = self._ffmpeg_version_text()
        self.ffmpeg_version_label.setText(text)
        self.ffmpeg_version_label.setToolTip(text)
        m = re.search(r'ffmpeg version (\S+)', text)
        short = m.group(1).split('-')[0] if m else ""
        self.banner.setBadge(f"FFmpeg {short}" if short else "")

    def _update_ffmpeg(self):
        if self._busy:
            QMessageBox.information(self, tr("Занято"), tr("Дождитесь завершения текущей операции."))
            return
        FFmpegSetupDialog("update", self).exec()
        ff, fp = find_ffmpeg()
        if ff:
            self.ffmpeg_path = ff
            self.ffprobe_path = fp or ff
            self._encoders_cache = None
            self._hw_cache.clear()
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
            "quality": self.quality.currentData(),
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
        self._restore_combo(self.quality, saved.get("quality"))
        self._restore_combo(self.audio_codec, saved.get("audio_codec"))
        self._restore_combo(self.audio_bitrate, saved.get("audio_bitrate"), editable=True)
        self._restore_combo(self.audio_channels, saved.get("audio_channels"))
        if saved.get("audio_format"):
            self._restore_combo(self.audio_format, saved.get("audio_format"))

    # ----------------------------------------------- Автосохранение --------
    def _save_setting(self, key, value):
        """Переключатели настроек: применяются и пишутся в config сразу."""
        self.settings[key] = bool(value)
        if getattr(self, '_ui_ready', False):
            save_config(**{key: bool(value)})

    def _save_render_settings(self, *_args):
        """Параметры кодирования: сохраняются при каждом изменении."""
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
                         (self.chk_sound, 'sound_notifications'),
                         (self.chk_ask_dest, 'ask_destination')):
            chk.toggled.connect(lambda v, k=key: self._save_setting(k, v))
        for combo in (self.resolution, self.video_codec, self.bitrate, self.format, self.quality,
                      self.audio_codec, self.audio_bitrate, self.audio_channels,
                      self.audio_format):
            combo.currentIndexChanged.connect(self._save_render_settings)
            combo.currentIndexChanged.connect(self._on_user_change)
            if combo.isEditable():
                combo.editTextChanged.connect(self._save_render_settings)
                combo.editTextChanged.connect(self._on_user_change)

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
        _TR.clear()
        _TR.update(data)
        self.translations = data
        self._retranslate()

    def _retranslate(self):
        self.setWindowTitle(tr("window_title", "Cine Convert"))
        for widget, key, default, kind in self._i18n:
            text = tr(key, default)
            try:
                if kind == "text":
                    if widget in self._gap_buttons:
                        text = " " + text
                    widget.setText(text)
                elif kind == "nav":
                    widget.setText("" if self._compact else " " + text)
                    widget.setToolTip(f"{text}  ·  {widget.property('shortcut')}")
                elif kind == "tip":
                    widget.setToolTip(text)
                elif kind == "subtitle":
                    widget.setSubtitle(text)
            except RuntimeError:      # виджет уже удалён
                continue
        for combo in self._i18n_items:
            custom = None
            if combo.isEditable():
                idx = combo.currentIndex()
                if idx < 0 or combo.itemText(idx) != combo.currentText():
                    custom = combo.currentText()   # введённое вручную значение не трогаем
            for i, orig in enumerate(getattr(combo, "_orig", [])):
                if i < combo.count():
                    combo.setItemText(i, tr(orig))
            if custom is not None:
                combo.setEditText(custom)
        self._refresh_output_dir_label()
        self._update_audio_hint()
        self._update_quality_hint()
        self._refresh_theme_toggle()
        if self._info_pairs:
            self._set_info_pairs(self._info_pairs)
        elif not self._current_files:
            self._set_info_placeholder()
        self._update_summary()

    # --------------------------------------------------- Загрузка файлов ---
    def _load_inputs(self, files, focus_index=0):
        files = [f for f in files if f]
        if not files:
            return
        self.input_files = files if len(files) > 1 else []
        self.input_file = files[0]
        self.output_file = ""
        self.last_dir = os.path.dirname(files[0])
        save_config(last_dir=self.last_dir)
        self._current_files = files
        self.source_stack.setCurrentIndex(1)
        self._status_sticky = False
        self._show_info_at(focus_index)
        if self._page not in (self.PAGE_VIDEO, self.PAGE_AUDIO):
            self._go(self.PAGE_VIDEO)

    def clear_inputs(self):
        if self._busy:
            return
        self.input_files = []
        self.input_file = ""
        self.output_file = ""
        self._current_files = []
        self._info_index = 0
        self._info_file = ""
        self._info_pairs = []
        self.video_info = {}
        self._set_info_placeholder()
        self.btn_details.setEnabled(False)
        self._set_info_nav_visible(False)
        self.preview_label.setText(tr("нет кадра"))
        self.file_title.setText("")
        self.file_path_label.setText("")
        self.source_stack.setCurrentIndex(0)
        self._on_user_change()

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
        self.file_title.setText(os.path.basename(self._info_file))
        self.file_title.setToolTip(self._info_file)
        folder = os.path.dirname(self._info_file)
        self.file_path_label.setText(folder)
        self.file_path_label.setToolTip(folder)
        self.load_video_info(self._info_file)
        self.show_video_preview(self._info_file)
        self.info_nav_label.setText(f"{index + 1}/{len(files)}")
        self.info_nav_label.setToolTip("\n".join(os.path.basename(f) for f in files))
        self.btn_info_prev.setEnabled(index > 0)
        self.btn_info_next.setEnabled(index < len(files) - 1)
        self._set_info_nav_visible(len(files) > 1)
        self._update_summary()

    def select_input_files(self, append=False):
        if self._busy:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("Выберите видеофайлы (один или несколько)"), self.last_dir,
            tr("Видеофайлы") + " (*.mp4 *.mkv *.mov *.avi *.flv *.webm *.wmv *.m4v *.mpg *.mpeg *.ts);;"
            + tr("Все файлы") + " (*.*)")
        if not files:
            return
        if append and self._current_files:
            known = {os.path.normcase(os.path.abspath(f)) for f in self._current_files}
            new = [f for f in files if os.path.normcase(os.path.abspath(f)) not in known]
            if new:
                self._load_inputs(self._current_files + new, focus_index=len(self._current_files))
        else:
            self._load_inputs(files)

    def _set_drag_active(self, active):
        self.drop_zone.set_active(active)
        if self.media_card.property("dragActive") != bool(active):
            self.media_card.setProperty("dragActive", bool(active))
            repolish(self.media_card)

    def dragEnterEvent(self, event):
        try:
            md = event.mimeData()
            if not self._busy and md.hasUrls() and any(
                    u.toLocalFile().lower().endswith(self.VIDEO_EXTS) for u in md.urls()):
                event.acceptProposedAction()
                self._set_drag_active(True)
                return
        except Exception:
            pass
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag_active(False)
        try:
            paths = [u.toLocalFile() for u in event.mimeData().urls()]
            paths = [p for p in paths if p.lower().endswith(self.VIDEO_EXTS) and os.path.isfile(p)]
            if paths and not self._busy:
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
                w.setParent(None)   # убрать с экрана сразу, а не после deleteLater
                w.deleteLater()

    def _set_info_placeholder(self):
        self._clear_info()
        lbl = _set_role(QLabel(tr("Выберите видео, чтобы увидеть информацию о нём")), "infoKey")
        lbl.setWordWrap(True)
        self.info_grid.addWidget(lbl, 0, 0, 1, 6)

    def _set_info_pairs(self, pairs):
        """pairs: [(ключ по-русски, значение)] — сетка «ключ: значение» в 2–3 колонки."""
        self._info_pairs = list(pairs)
        self._clear_info()
        cols = self._info_cols
        for c in range(6):
            self.info_grid.setColumnStretch(c, 0)
        for c in range(cols):
            self.info_grid.setColumnStretch(c * 2 + 1, 1)
        for i, (key, val) in enumerate(pairs):
            row, col = divmod(i, cols)
            k = _set_role(QLabel(tr(key)), "infoKey")
            v = _set_role(QLabel(str(val)), "infoVal")
            v.setToolTip(str(val))
            self.info_grid.addWidget(k, row, col * 2)
            self.info_grid.addWidget(v, row, col * 2 + 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_compact(self.width() < 1020)
        QTimer.singleShot(0, self._relayout_info)

    def _set_compact(self, compact):
        """На узком окне боковая панель сворачивается до иконок."""
        if compact == self._compact or not hasattr(self, "sidebar"):
            return
        self._compact = compact
        self.sidebar.setFixedWidth(60 if compact else 196)
        for b, (key, text, _kind) in zip(self.nav_buttons, self.NAV_ITEMS):
            b.setText("" if compact else " " + tr(key, text))
        for b in self.nav_buttons + [self.btn_theme_toggle]:
            b.setProperty("compact", compact)
            repolish(b)
        self.version_label.setVisible(not compact)
        self._refresh_theme_toggle()

    def _relayout_info(self):
        cols = 3 if self.info_container.width() >= 540 else 2
        if cols != self._info_cols:
            self._info_cols = cols
            if self._info_pairs:
                self._set_info_pairs(self._info_pairs)

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

            # Основной набор: 12 фактов (4 ряда × 3 или 6 × 2 колонки).
            pairs = []
            w, h = v.get('width'), v.get('height')
            pairs.append(("Разрешение", f"{w}x{h}" if w and h else "—"))
            dur = self._safe_float(fmt.get('duration')) or self._safe_float(v.get('duration'))
            if dur:
                m, sec = divmod(int(dur), 60)
                hh, m = divmod(m, 60)
                dtext = f"{hh}:{m:02d}:{sec:02d}" if hh else f"{m}:{sec:02d}"
            else:
                dtext = "—"
            pairs.append(("Длительность", dtext))
            size = self._safe_int(fmt.get('size'))
            pairs.append(("Размер", f"{size / (1024 * 1024):.1f} MB" if size else "—"))

            pairs.append(("Видео", short(v.get('codec_name') or "—", 16)))
            fps = "—"
            try:
                num, den = map(float, str(v.get('avg_frame_rate', '0/0')).split('/'))
                if den:
                    fps = f"{num / den:.2f}".rstrip('0').rstrip('.')
            except Exception:
                pass
            pairs.append(("FPS", fps))
            vbr = self._safe_int(v.get('bit_rate'))
            pairs.append(("Битрейт видео", f"{vbr // 1000} kbps" if vbr else "—"))

            pairs.append(("Аудио", short(a.get('codec_name') or "—", 16)))
            ch = a.get('channels')
            lay = a.get('channel_layout')
            pairs.append(("Каналы", short(f"{ch} ({lay})" if ch and lay else (ch or "—"), 16)))
            sr = self._safe_int(a.get('sample_rate'))
            pairs.append(("Частота", f"{sr / 1000:.1f} kHz" if sr else "—"))

            # ffprobe отдаёт «mov,mp4,m4a,…» — показываем имя, совпадающее с расширением
            names = (fmt.get('format_name') or "").split(',')
            ext = os.path.splitext(file_path)[1].lstrip('.').lower()
            pairs.append(("Контейнер", short(ext if ext in names else (names[0] or "—"), 16)))
            tbr = self._safe_int(fmt.get('bit_rate'))
            pairs.append(("Общий битрейт", f"{tbr // 1000} kbps" if tbr else "—"))
            pairs.append(("Пикс. формат", short(v.get('pix_fmt') or "—", 16)))

            self._set_info_pairs(pairs)
            self.btn_details.setEnabled(True)
        except Exception as e:
            self.video_info = {}
            self._info_pairs = []
            self._clear_info()
            err = _set_role(QLabel(tr_fmt("Ошибка получения информации: {e}", e=e)), "infoKey")
            err.setWordWrap(True)
            self.info_grid.addWidget(err, 0, 0, 1, 6)
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
                # храним кадр в 2× размере — чётко и на HiDPI-экранах
                pixmap = pixmap.scaled(self.preview_label.width() * 2, self.preview_label.height() * 2,
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                if len(self._preview_cache) > 64:
                    self._preview_cache.clear()
                self._preview_cache[key] = pixmap
                self.preview_label.setPixmap(pixmap)
            else:
                self.preview_label.setText(tr("не удалось загрузить превью"))
        except Exception as e:
            self.log_text.append(tr_fmt("Ошибка создания превью: {e}", e=e))
            self.preview_label.setText(tr("не удалось загрузить превью"))
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

    def _has_encoder(self, ffmpeg_cmd, name):
        out = self._available_encoders(ffmpeg_cmd)
        return not out or self._encoder_listed(out, name)   # список не получили — не мешаем

    def _hw_encoder_works(self, ffmpeg_cmd, encoder, args):
        """Пробное кодирование 5 кадров: -encoders показывает NVENC/QSV/AMF на любом
        ПК, а реально они работают только при подходящей видеокарте и драйвере."""
        key = (ffmpeg_cmd, encoder, tuple(args))
        if key not in self._hw_cache:
            cmd = [ffmpeg_cmd, '-hide_banner', '-v', 'error', '-f', 'lavfi',
                   '-i', 'color=c=black:s=640x360:r=30', '-frames:v', '5',
                   '-c:v', encoder] + list(args) + ['-f', 'null', '-']
            try:
                ok = run_hidden(cmd, capture_output=True, text=True, timeout=25).returncode == 0
            except Exception:
                ok = False
            self._hw_cache[key] = ok
        return self._hw_cache[key]

    def _software_encoder(self, ffmpeg_cmd, family):
        if family == "av1":
            for enc in ("libsvtav1", "libaom-av1"):   # SVT-AV1 в разы быстрее libaom
                if self._has_encoder(ffmpeg_cmd, enc):
                    return enc
            return None
        enc = {"h264": "libx264", "hevc": "libx265", "vp9": "libvpx-vp9", "mpeg4": "mpeg4",
               "mpeg2video": "mpeg2video", "wmv2": "wmv2"}.get(family)
        return enc if enc and self._has_encoder(ffmpeg_cmd, enc) else None

    def _plan_video(self, ffmpeg_cmd, choice, container, src_codec, level, bitrate, src10, notes):
        """Выбирает видеоэнкодер и его аргументы → (энкодер, [аргументы])."""
        allowed = CONTAINER_VIDEO.get(container)
        fallback_family = CONTAINER_DEFAULT_VIDEO.get(container, "h264")

        def fits(family):
            return allowed is None or family in allowed

        def fallback():
            return (self._software_encoder(ffmpeg_cmd, fallback_family)
                    or self._software_encoder(ffmpeg_cmd, "h264") or "libx264")

        if choice:
            name = choice.lower()
            if name == "av1":
                enc = self._software_encoder(ffmpeg_cmd, "av1") or "libaom-av1"
            else:
                enc = self.VIDEO_ENCODER_MAP.get(name, name)
            family = ENCODER_CODEC.get(enc, name)
            if not fits(family):
                new = fallback()
                notes.append(tr_fmt("⚠ {a} не поддерживается в {c} — используем {b}.",
                                    a=enc, c=container.upper(), b=new))
                enc = new
        else:
            # «Без изменений»: сохраняем семейство кодека исходника, если контейнер его принимает
            enc = ((self._software_encoder(ffmpeg_cmd, src_codec) if src_codec and fits(src_codec) else None)
                   or fallback())

        args = video_rate_args(enc, level, bitrate, src10, container)
        if enc.endswith(HW_SUFFIXES):
            if not self._hw_encoder_works(ffmpeg_cmd, enc, args):
                minimal = video_rate_args(enc, level, bitrate, src10, container, minimal=True)
                if self._hw_encoder_works(ffmpeg_cmd, enc, minimal):
                    args = minimal
                else:
                    soft = (self._software_encoder(ffmpeg_cmd, ENCODER_CODEC.get(enc, "h264"))
                            or fallback())
                    notes.append(tr_fmt("⚠ {a} недоступен на этом компьютере — используем {b}.",
                                        a=enc, b=soft))
                    enc = soft
                    args = video_rate_args(enc, level, bitrate, src10, container)
        elif not self._has_encoder(ffmpeg_cmd, enc):
            soft = fallback()
            notes.append(tr_fmt("⚠ Кодек {a} недоступен — используем {b}.", a=enc, b=soft))
            enc = soft
            args = video_rate_args(enc, level, bitrate, src10, container)
        return enc, args

    AUDIO_ENCODERS = {'opus': 'libopus', 'mp3': 'libmp3lame', 'aac': 'aac', 'flac': 'flac',
                      'vorbis': 'libvorbis', 'ogg': 'libvorbis', 'ac3': 'ac3',
                      'wav': 'pcm_s16le', 'wma': 'wmav2', 'mp2': 'mp2'}

    def _plan_audio(self, ffmpeg_cmd, choice, container, src_codec, src_channels,
                    level, bitrate, channels, notes):
        """Аргументы для звука: копия, если можно, иначе подходящий энкодер."""
        allowed = CONTAINER_AUDIO.get(container)
        default_enc = CONTAINER_DEFAULT_AUDIO.get(container, "aac")

        def fits(codec):
            return allowed is None or codec in allowed

        untouched = not choice and not bitrate and not channels
        if choice == 'copy' or untouched:
            if src_codec and fits(src_codec):
                if untouched:
                    notes.append(tr("⚡ Аудио копируется без перекодирования."))
                return ['-c:a', 'copy']
            if choice == 'copy' and src_codec:
                notes.append(tr_fmt("⚠ Звук {a} нельзя скопировать в {c} — перекодируем.",
                                    a=src_codec, c=container.upper()))
            enc = default_enc
        elif choice:
            enc = self.AUDIO_ENCODERS.get(choice.lower(), choice.lower())
            if not fits(ENCODER_CODEC.get(enc, enc)):
                notes.append(tr_fmt("⚠ {a} не поддерживается в {c} — используем {b}.",
                                    a=choice, c=container.upper(), b=default_enc))
                enc = default_enc
        else:
            enc = default_enc
        if not self._has_encoder(ffmpeg_cmd, enc):
            enc = next((e for e in ('aac', 'libopus', 'libvorbis', 'libmp3lame')
                        if self._has_encoder(ffmpeg_cmd, e) and fits(ENCODER_CODEC[e])), 'aac')
        out_channels = self._safe_int(channels) or src_channels
        args = audio_encode_args(enc, level, bitrate, out_channels)
        if channels:
            args += ['-ac', str(channels)]
        elif enc == 'libmp3lame' and (src_channels or 0) > 2:
            args += ['-ac', '2']           # MP3 — только моно/стерео
        elif enc == 'libopus' and (src_channels or 0) > 2:
            args += ['-af', 'aformat=channel_layouts=7.1|5.1|stereo|mono']
        return args

    def map_audio_codec(self, ffmpeg_cmd, codec_name):
        """Имя кодека из интерфейса → доступный аудиоэнкодер FFmpeg."""
        if not codec_name:
            return 'aac'
        name = str(codec_name).lower()
        if name == 'copy':
            return 'copy'
        mapped = self.AUDIO_ENCODERS.get(name, name)
        if self._has_encoder(ffmpeg_cmd, mapped):
            return mapped
        for candidate in ('aac', 'libopus', 'libvorbis', 'libmp3lame'):
            if self._has_encoder(ffmpeg_cmd, candidate):
                return candidate
        return mapped

    # ------------------------------------------------ Анализ исходника -----
    def _probe(self, path):
        """ffprobe с кэшем; при ошибке — пустой словарь (команда соберётся по-старому)."""
        key = self._cache_key(path)
        info = self._probe_cache.get(key)
        if info is None:
            try:
                r = run_hidden([getattr(self, "ffprobe_path", "ffprobe"), '-v', 'error',
                                '-show_format', '-show_streams', '-of', 'json', path],
                               capture_output=True, text=True, timeout=30)
                info = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
            except Exception:
                info = {}
            if info:
                if len(self._probe_cache) > 64:
                    self._probe_cache.clear()
                self._probe_cache[key] = info
        return info or {}

    @staticmethod
    def _streams(info, kind):
        out = [s for s in (info.get('streams') or []) if s.get('codec_type') == kind]
        if kind == 'video':   # обложки (attached_pic) — не видео
            out = [s for s in out if not (s.get('disposition') or {}).get('attached_pic')]
        return out

    @staticmethod
    def _is_10bit(stream):
        pix = (stream or {}).get('pix_fmt') or ''
        return any(t in pix for t in ('10', '12', 'p016'))

    # ------------------------------------------------ Занятость / отмена ---
    def _set_busy(self, busy):
        self._busy = busy
        self.btn_render.setEnabled(not busy)
        self.btn_extract.setEnabled(not busy)
        self.btn_cancel.setVisible(busy)
        self.btn_cancel.setEnabled(busy)
        for w in (self.btn_add_files, self.btn_clear_input, self.drop_zone, self.btn_update_ffmpeg):
            w.setEnabled(not busy)
        if busy:
            self.stats_label.setText("")

    def cancel_current(self):
        self._batch_cancelled = True
        w = getattr(self, "worker", None)
        if w is not None and w.isRunning():
            # Отвязываем отменённый процесс от интерфейса: его поздний сигнал не должен
            # попасть в новую операцию. Недописанный файл удалим, когда FFmpeg выйдет.
            for sig in (w.resultReady, w.progressUpdated, w.statsUpdated):
                try:
                    sig.disconnect()
                except (TypeError, RuntimeError):
                    pass
            partial = getattr(self, "_running_output", "")
            w.resultReady.connect(lambda _ok, p=partial: self._remove_partial(p))
            self._retired_workers.append(w)
            w.finished.connect(lambda w=w: self._retired_workers.remove(w)
                               if w in self._retired_workers else None)
            try:
                w.stop()
            except Exception:
                pass
        self.log_text.append(tr("Операция отменена."))
        self._set_busy(False)
        self._set_status(tr("Отменено пользователем"), "cancelled", sticky=True)
        self.stats_label.setText("")

    def _remove_partial(self, path):
        """Удаляет недописанный файл после ошибки или отмены."""
        try:
            if path and os.path.isfile(path):
                os.remove(path)
                self.log_text.append(tr("Незавершённый файл удалён: ") + path)
        except OSError:
            pass

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
        if not self.settings.get("ask_destination", True):
            return self.output_dir if self.output_dir and os.path.isdir(self.output_dir) else ""
        dlg = DestinationDialog(self.output_dir, self.output_dir or self.last_dir or "", self)
        if dlg.exec():
            return dlg.result_dir
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
        in_ext = os.path.splitext(input_file)[1].lstrip(".").lower()
        vcodec = settings.get("video_codec")
        scale = settings.get("resolution")
        bitrate = settings.get("bitrate")
        level = settings.get("quality")
        acodec = settings.get("audio_codec")
        abitrate = settings.get("audio_bitrate")
        channels = settings.get("audio_channels")

        info = self._probe(input_file)
        vstreams, astreams = self._streams(info, 'video'), self._streams(info, 'audio')
        sstreams = self._streams(info, 'subtitle')
        v0 = vstreams[0] if vstreams else {}
        a0 = astreams[0] if astreams else {}
        src_v = (v0.get('codec_name') or '').lower()
        src_a = (a0.get('codec_name') or '').lower()
        src_ch = self._safe_int(a0.get('channels')) or 0

        cmd = [ffmpeg_cmd, '-hide_banner', '-nostdin', '-y', '-i', input_file]

        # --- какие потоки берём: в MKV — все дорожки звука и субтитры, иначе
        #     основное видео и первую дорожку (субтитры MP4/AVI часто ломают запись)
        if info:
            cmd += ['-map', '0:V:0?']
            cmd += ['-map', '0:a?'] if container == 'mkv' else ['-map', '0:a:0?']
            if container == 'mkv' and sstreams:
                codecs = {(s.get('codec_name') or '').lower() for s in sstreams}
                if codecs <= MKV_SUBTITLES:
                    cmd += ['-map', '0:s?', '-c:s', 'copy']
                elif codecs <= TEXT_SUBTITLES:
                    cmd += ['-map', '0:s?', '-c:s', 'srt']
                if in_ext == 'mkv':
                    cmd += ['-map', '0:t?', '-c:t', 'copy']   # встроенные шрифты субтитров
        elif container != 'mkv':
            cmd.append('-sn')

        # --- видео
        untouched = not vcodec and not scale and not bitrate and not level
        allowed = CONTAINER_VIDEO.get(container)
        if info:
            copy_video = untouched and bool(src_v) and (allowed is None or src_v in allowed)
        else:
            copy_video = untouched and container in (in_ext, "mkv")
        if copy_video:
            # Ничего не меняется — копируем без перекодирования: мгновенно и без потерь
            cmd += ['-c:v', 'copy']
            if src_v == 'hevc' and container in ('mp4', 'mov', 'm4v'):
                cmd += ['-tag:v', 'hvc1']
            elif src_v == 'h264' and container == 'avi' and in_ext not in ('avi', 'ts', 'mpg', 'mpeg'):
                # AVI хранит H.264 только в Annex B и узнаёт его по FourCC «H264»
                cmd += ['-bsf:v', 'h264_mp4toannexb', '-tag:v', 'H264']
            notes.append(tr("⚡ Видео копируется без перекодирования."))
        else:
            quality = level or "balanced"
            enc, args = self._plan_video(ffmpeg_cmd, vcodec, container, src_v, quality,
                                         bitrate, self._is_10bit(v0), notes)
            cmd += ['-c:v', enc] + args
            if scale:
                cmd += ['-vf', scale_filter(scale)]
                w, h = self._safe_int(v0.get('width')), self._safe_int(v0.get('height'))
                tw, th = (int(x) for x in scale.split(':'))
                if w and h and max(w, h) <= max(tw, th) and min(w, h) <= min(tw, th):
                    notes.append(tr("ℹ Исходник не больше выбранного разрешения — кадр не увеличивается."))
            how = bitrate if bitrate else tr(self.QUALITY_NAMES.get(quality, quality))
            notes.append(tr_fmt("🎬 Видео: {enc} · {how}", enc=enc, how=how))

        # --- звук
        if astreams or not info:
            cmd += self._plan_audio(ffmpeg_cmd, acodec, container, src_a, src_ch,
                                    level or "balanced", abitrate, channels, notes)

        if container in ('mp4', 'mov', 'm4v'):
            cmd += ['-movflags', '+faststart']   # быстрый старт при просмотре по сети
        cmd.append(output_file)
        return cmd, notes

    EXTRACT_FORMATS = {   # формат файла → (кодек, при котором можно копировать; энкодер)
        "mp3": ("mp3", "libmp3lame"), "aac": ("aac", "aac"), "flac": ("flac", "flac"),
        "wav": ("pcm_s16le", "pcm_s16le"), "ogg": ("vorbis", "libvorbis"), "ac3": ("ac3", "ac3"),
    }

    def _build_extract_command(self, source, output_file, fmt, ffmpeg_cmd):
        """Команда извлечения звука; None — в файле нет звуковой дорожки."""
        notes = []
        info = self._probe(source)
        astreams = self._streams(info, 'audio')
        if info and not astreams:
            return None, notes
        a0 = astreams[0] if astreams else {}
        src = (a0.get('codec_name') or '').lower()
        ch = self._safe_int(a0.get('channels')) or 0
        copy_codec, enc = self.EXTRACT_FORMATS.get(fmt, (None, self.map_audio_codec(ffmpeg_cmd, fmt)))
        cmd = [ffmpeg_cmd, '-hide_banner', '-nostdin', '-y', '-i', source,
               '-map', '0:a:0', '-vn', '-sn', '-dn']
        if src and (src == copy_codec or (fmt == "ogg" and src in ("vorbis", "opus"))):
            cmd += ['-c:a', 'copy']           # дорожка уже в нужном формате — без потерь
            notes.append(tr("⚡ Звук копируется без перекодирования."))
        else:
            if not self._has_encoder(ffmpeg_cmd, enc):
                enc = self.map_audio_codec(ffmpeg_cmd, fmt)
            cmd += audio_encode_args(enc, "high", None, ch)
            if enc == 'libmp3lame' and ch > 2:
                cmd += ['-ac', '2']
        cmd.append(output_file)
        return cmd, notes

    def _known_duration(self, info=None):
        try:
            info = self.video_info if info is None else info
            return float(info.get('format', {}).get('duration', 0)) or None
        except Exception:
            return None

    def _start_worker(self, cmd, duration, on_finished):
        self.progress_bar.setValue(0)
        self._running_output = cmd[-1]
        self.worker = FFmpegWorker(cmd, total_duration=duration,
                                   stats_template=tr("Осталось ~{eta}  ·  скорость {speed}x"))
        self.worker.progressUpdated.connect(self.update_progress)
        self.worker.statsUpdated.connect(self.stats_label.setText)
        self.worker.outputReceived.connect(self.log_text.append)
        self.worker.resultReady.connect(on_finished)
        self.worker.start()

    # ---------------------------------------------- Рендеринг (пакет) ------
    def start_video_render(self):
        if self._busy:
            return
        files = self.input_files if self.input_files else ([self.input_file] if self.input_file else [])
        files = [f for f in files if f]
        if not files or not all(os.path.exists(f) for f in files):
            QMessageBox.warning(self, tr("Ошибка"), tr("Выберите существующие видеофайлы!"))
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
        self._batch_errors = 0
        save_config(render_settings=self.batch_settings)
        self._set_busy(True)
        self.render_next_in_batch()

    def render_next_in_batch(self):
        if self._batch_cancelled:
            return
        input_file = self.batch_files[self.batch_index]
        if self.batch_total > 1:
            status = tr_fmt("Видео {i} из {n}: {name}", i=self.batch_index + 1,
                            n=self.batch_total, name=os.path.basename(input_file))
        else:
            status = tr_fmt("Обработка: {name}", name=os.path.basename(input_file))
        self._set_status(status, "busy")
        settings = self.batch_settings
        ext = self._output_extension(settings, input_file)
        output_file = self._dest_for(input_file, ext, self._batch_dir)
        self.output_file = output_file
        ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
        cmd, notes = self._build_video_command(input_file, output_file, settings, ffmpeg_cmd)
        self.log_text.clear()
        self.log_text.append(
            tr_fmt("Начато перекодирование видео {i}/{n}...", i=self.batch_index + 1, n=self.batch_total)
            if self.batch_total > 1 else tr("Начато перекодирование видео..."))
        for note in notes:
            self.log_text.append(note)
        self.log_text.append(tr("Сохранение: ") + output_file)
        self.log_text.append(tr("Команда: ") + " ".join(cmd))
        info = self._probe_cache.get(self._cache_key(input_file))
        self._start_worker(cmd, self._known_duration(info) if info else None,
                           self.batch_render_finished)

    def batch_render_finished(self, success):
        if not success:
            self._remove_partial(self.output_file)
        if self._batch_cancelled:
            self.log_text.append(tr("Операция отменена."))
            self._set_busy(False)
            return
        if success:
            self.log_text.append(
                tr_fmt("Видео {i} успешно перекодировано!", i=self.batch_index + 1)
                if self.batch_total > 1 else tr("Перекодирование видео успешно завершено!"))
        else:
            self._batch_errors += 1
            self.log_text.append(tr_fmt("Ошибка при перекодировании видео {i}!", i=self.batch_index + 1))
            QMessageBox.critical(self, tr("Ошибка"),
                                 tr_fmt("Ошибка при обработке видео {i}", i=self.batch_index + 1))
        self.batch_index += 1
        if self.batch_index < self.batch_total and not self._batch_cancelled:
            self.render_next_in_batch()
            return
        self._set_busy(False)
        self.stats_label.setText(os.path.dirname(self.output_file) if self.output_file else "")
        if self._batch_errors:
            self._set_status(tr_fmt("Завершено, ошибок: {n}", n=self._batch_errors), "error", sticky=True)
        else:
            self.progress_bar.setValue(100)
            self._set_status(tr("Пакетное перекодирование завершено!") if self.batch_total > 1
                             else tr("Готово!"), "done", sticky=True)
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
        source = self._info_file or self.input_file   # то видео, что сейчас на экране
        if not source or not os.path.exists(source):
            QMessageBox.warning(self, tr("Ошибка"), tr("Выберите видеофайл!"))
            return
        dest = self._ask_destination()
        if dest is None:
            return
        audio_format = (self.audio_format.currentData() or self.audio_format.currentText()).lower()
        ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
        output_file = self._dest_for(source, "." + audio_format, dest)
        cmd, notes = self._build_extract_command(source, output_file, audio_format, ffmpeg_cmd)
        if cmd is None:
            QMessageBox.warning(self, tr("Ошибка"), tr("В этом видео нет звуковой дорожки."))
            return
        self._extract_output = output_file
        self.log_text.clear()
        self.log_text.append(tr("Начато извлечение аудио..."))
        for note in notes:
            self.log_text.append(note)
        self.log_text.append(tr("Сохранение: ") + output_file)
        self.log_text.append(tr("Команда: ") + " ".join(cmd))
        self._batch_cancelled = False
        self._set_busy(True)
        self._set_status(tr_fmt("Извлечение звука: {name}", name=os.path.basename(source)), "busy")
        info = self._probe_cache.get(self._cache_key(source))
        self._start_worker(cmd, self._known_duration(info) if info else None,
                           self.audio_extraction_finished)

    def audio_extraction_finished(self, success):
        self._set_busy(False)
        if not success:
            self._remove_partial(getattr(self, "_extract_output", ""))
        if self._batch_cancelled:
            self.log_text.append(tr("Извлечение отменено."))
            return
        if success:
            self.log_text.append(tr("Аудио успешно извлечено!"))
            output_file = getattr(self, "_extract_output", "")
            self.progress_bar.setValue(100)
            self.stats_label.setText(os.path.dirname(output_file) if output_file else "")
            self._set_status(tr("Готово!"), "done", sticky=True)
            if output_file:
                if self.settings.get("open_folder_when_done"):
                    self._open_output_folder(output_file)
                if self.settings["show_audio_notifications"]:
                    self._play_sound()
                    NotificationDialog(output_file, self).exec()
        else:
            self.log_text.append(tr("Ошибка при извлечении аудио!"))
            self._set_status(tr("Ошибка при извлечении аудио!"), "error", sticky=True)
            QMessageBox.critical(self, tr("Ошибка"), tr("Произошла ошибка при извлечении аудио"))

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def closeEvent(self, event):
        save_config(win_size=[self.width(), self.height()])
        for w in [getattr(self, "worker", None)] + list(self._retired_workers):
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

    def __init__(self, command, total_duration=None, stats_template=None):
        super().__init__()
        self.command = command
        self.total_duration = total_duration
        self.stats_template = stats_template or "Осталось ~{eta}  ·  скорость {speed}x"
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
                self.command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
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
                            try:
                                stats = self.stats_template.format(
                                    eta=self._fmt_eta(eta), speed=f"{speed:g}")
                            except (KeyError, IndexError, ValueError):
                                stats = f"~{self._fmt_eta(eta)} · {speed:g}x"
                            self.statsUpdated.emit(stats)
            self.process.wait()
            self.resultReady.emit(False if self._cancelled else self.process.returncode == 0)
        except Exception as e:
            self.outputReceived.emit(f"Ошибка: {e}")
            self.resultReady.emit(False)



# ============================================================================
#  Запуск
# ============================================================================
def main():
    if PYQT_VERSION == 5:
        # Чёткий интерфейс на экранах 125–200 % (в Qt6 включено по умолчанию)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if APP_ICON:
        app.setWindowIcon(QIcon(APP_ICON))
    load_fonts()
    app.setFont(ui_font(10, 400))

    cfg = load_config()
    preload_locale(cfg.get("language"))
    mode = cfg.get("theme_mode", "light")
    set_theme(hue=cfg.get("hue", DEFAULT_HUE),
              saturation=cfg.get("saturation", DEFAULT_SATURATION),
              dark=is_system_dark() if mode == "system" else (mode == "dark"))
    app.setPalette(build_palette())
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
        QMessageBox.critical(None, tr("Ошибка"), tr("Не удалось найти или установить FFmpeg."))
        sys.exit(1)


if __name__ == "__main__":
    main()
