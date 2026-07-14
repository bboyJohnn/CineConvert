import os
import sys
import json
import subprocess
import platform
import zipfile
import urllib.request
import ctypes
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox,
    QMainWindow, QWidget, QHBoxLayout, QGridLayout, QTabWidget,
    QGroupBox, QLineEdit, QComboBox, QTextEdit, QScrollArea, QFileDialog,
    QCheckBox, QFormLayout, QStyle, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPixmap

# При упаковке в один exe (PyInstaller --onefile) файл будет запущен из временной папки.
# Для устойчивого хранения конфигурации и поиска ресурсов используем папку рядом с исполняемым файлом.
if getattr(sys, 'frozen', False):
    # APP_DIR - папка рядом с exe (где находится файл .exe)
    APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# RESOURCE_DIR - папка с распакованными ресурсами (PyInstaller _MEIPASS) или APP_DIR
RESOURCE_DIR = getattr(sys, '_MEIPASS', APP_DIR)

# config.json хранится рядом с exe (APP_DIR) чтобы приложение было портативным
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

# ========== FFmpeg Автоматическая проверка и установка ==========
class FFmpegSetupThread(QThread):
    # progress can be a status string or an int (percent)
    progress = pyqtSignal(object)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            app_dir = APP_DIR
            ffmpeg_dir = os.path.join(app_dir, "ffmpeg")
            ffmpeg_bin = os.path.join(ffmpeg_dir, "bin")

            if not os.path.exists(ffmpeg_bin):
                os.makedirs(ffmpeg_bin, exist_ok=True)

            zip_path = os.path.join(app_dir, "ffmpeg.zip")
            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

            self.progress.emit("📥 Скачивание FFmpeg...")
            # Streaming download with progress reporting
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req) as resp:
                    total = resp.getheader('Content-Length')
                    total = int(total) if total and total.isdigit() else None
                    downloaded = 0
                    chunk_size = 8192
                    with open(zip_path, 'wb') as out_f:
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            out_f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                percent = int(downloaded * 100 / total)
                                # emit numeric progress
                                self.progress.emit(percent)
            except Exception as e:
                # fallback to urlretrieve if streaming fails
                try:
                    urllib.request.urlretrieve(url, zip_path)
                except Exception as e2:
                    self.progress.emit(f"❌ Ошибка загрузки: {e2}")
                    self.finished.emit(False, "")
                    return

            self.progress.emit("📦 Распаковка...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(app_dir)

            # Удаляем временный ZIP
            if os.path.exists(zip_path):
                os.remove(zip_path)

            # Ищем папку с распакованным ffmpeg
            extracted_dir = None
            for item in os.listdir(app_dir):
                if item.startswith("ffmpeg-") and os.path.isdir(os.path.join(app_dir, item)):
                    extracted_dir = os.path.join(app_dir, item)
                    break

            if extracted_dir:
                inner_bin = os.path.join(extracted_dir, "bin")
                import shutil
                # Если внутри есть папка bin — перемещаем файлы оттуда
                if os.path.exists(inner_bin):
                    for file in os.listdir(inner_bin):
                        src = os.path.join(inner_bin, file)
                        dst = os.path.join(ffmpeg_bin, file)
                        try:
                            # Пытаемся переместить, если не удалось — копируем
                            os.replace(src, dst)
                        except Exception:
                            try:
                                shutil.copy2(src, dst)
                            except Exception:
                                pass
                    shutil.rmtree(extracted_dir, ignore_errors=True)
                else:
                    # Если bin отсутствует, ищем бинарники по дереву и копируем
                    for root, dirs, files in os.walk(extracted_dir):
                        for fname in files:
                            if fname.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                                src = os.path.join(root, fname)
                                dst = os.path.join(ffmpeg_bin, fname)
                                try:
                                    shutil.copy2(src, dst)
                                except Exception:
                                    pass
                    shutil.rmtree(extracted_dir, ignore_errors=True)

            ffmpeg_path = os.path.join(ffmpeg_bin, "ffmpeg.exe")
            ffprobe_path = os.path.join(ffmpeg_bin, "ffprobe.exe")

            if os.path.exists(ffmpeg_path) and os.path.exists(ffprobe_path):
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "ffmpeg_installed": True,
                        "ffmpeg_path": ffmpeg_path,
                        "ffprobe_path": ffprobe_path
                    }, f, indent=4, ensure_ascii=False)
                self.progress.emit("✅ Установка завершена!")
                self.finished.emit(True, ffmpeg_path)
            else:
                self.progress.emit("❌ Ошибка: FFmpeg не найден после установки.")
                self.finished.emit(False, "")
        except Exception as e:
            self.progress.emit(f"❌ Ошибка: {e}")
            self.finished.emit(False, "")

class FFmpegSetupDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Установка FFmpeg")
        self.setFixedSize(420, 200)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        self.layout = QVBoxLayout(self)
        self.label = QLabel("Проверка FFmpeg...", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_close = QPushButton("Закрыть", self)
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)

        self.layout.addWidget(self.label)
        # прогресс-бар для загрузки (0..100)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.layout.addWidget(self.progress)
        self.layout.addWidget(self.btn_close)

        self.thread = FFmpegSetupThread()
        self.thread.progress.connect(self.update_status)
        self.thread.finished.connect(self.finish)
        self.thread.start()

    def update_status(self, message):
        # message can be int (percent) or str (status)
        try:
            if isinstance(message, int):
                self.progress.setValue(message)
                self.label.setText(f"📥 Скачивание... {message}%")
            else:
                self.label.setText(str(message))
                # If message contains an emoji or 'Установка завершена', set progress to 100
                if isinstance(message, str) and ("Установка завершена" in message or "✅" in message):
                    self.progress.setValue(100)
        except Exception:
            # Fallback: set label
            self.label.setText(str(message))

    def finish(self, success, ffmpeg_path):
        self.progress.setRange(0, 1)
        if success:
            self.label.setText("FFmpeg успешно установлен!")
        else:
            self.label.setText("Ошибка при установке FFmpeg.")
        self.btn_close.setEnabled(True)

# ========== Основной интерфейс ==========
class NotificationDialog(QDialog):
    def __init__(self, output_file, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Рендеринг завершен")
        if parent is not None:
            try:
                self.setWindowIcon(parent.windowIcon())
            except:
                pass
        self.setFixedSize(350, 150)
        
        layout = QVBoxLayout()
        
        message = QLabel("Рендеринг завершен успешно!")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(message)
        
        # Кнопки действий
        btn_layout = QHBoxLayout()
        
        self.btn_play = QPushButton("Включить видео")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_play.clicked.connect(lambda: self.play_video(output_file))
        btn_layout.addWidget(self.btn_play)
        
        self.btn_open_folder = QPushButton("Открыть папку")
        self.btn_open_folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.btn_open_folder.clicked.connect(lambda: self.open_folder(output_file))
        btn_layout.addWidget(self.btn_open_folder)
        
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
        # Настройка стилей
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
            }
            QPushButton {
                padding: 8px 12px;
                font-size: 12px;
            }
        """)
    
    def play_video(self, file_path):
        if os.path.exists(file_path):
            if platform.system() == 'Windows':
                os.startfile(file_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.call(('open', file_path))
            else:  # linux
                subprocess.call(('xdg-open', file_path))
        self.accept()
    
    def open_folder(self, file_path):
        folder_path = os.path.dirname(file_path)
        if os.path.exists(folder_path):
            if platform.system() == 'Windows':
                os.startfile(folder_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.call(('open', folder_path))
            else:  # linux
                subprocess.call(('xdg-open', folder_path))
        self.accept()

class VideoConverter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cine Convert")
        self.setGeometry(100, 100, 1000, 700)
        self.settings = {  # <-- Сначала инициализируем настройки!
            "show_video_notifications": True,
            "show_audio_notifications": True
        }
        # Локализации
        self.translations = {}
        self.locales_map = {}
        self.setup_ui()
        self.setup_styles()
        self.input_file = ""
        self.output_file = ""
        self.video_info = {}
        self.input_files = []  # Для пакетной обработки
        # Пути к FFmpeg/FFprobe будут установлены из главного блока
        self.ffmpeg_path = "ffmpeg"
        self.ffprobe_path = "ffprobe"
        # Загрузка доступных локалей и применение сохранённой
        try:
            self.load_locales()
            # Попробуем загрузить выбранный язык из конфига
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                        lang = cfg.get('language')
                        if lang:
                            self.apply_locale(lang)
                except Exception:
                    pass
        except Exception:
            pass

    def setup_ui(self):
        # Центральный виджет и основной слой
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Группа исходного видео
        source_group = QGroupBox("Исходное видео")
        source_group.setObjectName("group_source")
        source_layout = QHBoxLayout(source_group)
        self.input_path = QLineEdit()
        self.input_path.setObjectName("input_path")
        self.input_path.setPlaceholderText("Выберите видеофайл...")
        btn_browse_input = QPushButton("Обзор...")
        btn_browse_input.setObjectName("btn_browse_input")
        btn_browse_input.clicked.connect(self.select_input_file)
        source_layout.addWidget(self.input_path)
        source_layout.addWidget(btn_browse_input)

        # Кнопка для выбора нескольких файлов
        btn_browse_multi = QPushButton("Выбрать несколько видео...")
        btn_browse_multi.setObjectName("btn_browse_multi")
        btn_browse_multi.clicked.connect(self.select_input_files)
        source_layout.addWidget(btn_browse_multi)

        # Группа выходного файла
        output_group = QGroupBox("Выходное видео")
        output_group.setObjectName("group_output")
        output_layout = QHBoxLayout(output_group)
        self.output_path = QLineEdit()
        self.output_path.setObjectName("output_path")
        self.output_path.setPlaceholderText("Куда сохранить результат...")
        btn_browse_output = QPushButton("Обзор...")
        btn_browse_output.setObjectName("btn_browse_output")
        btn_browse_output.clicked.connect(self.select_output_file)
        output_layout.addWidget(self.output_path)
        output_layout.addWidget(btn_browse_output)

        # Добавление путей в основной лейаут
        main_layout.addWidget(source_group)
        main_layout.addWidget(output_group)

        # Группа информации о видео
        info_group = QGroupBox("Информация о видео")
        info_group.setObjectName("group_info")
        info_layout = QVBoxLayout(info_group)
        
        # Создаем контейнер для блоков информации
        self.info_container = QWidget()
        self.info_grid = QGridLayout(self.info_container)
        self.info_grid.setSpacing(15)
        self.info_grid.setContentsMargins(10, 10, 10, 10)
        
        # Добавляем контейнер в скроллируемую область
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.info_container)
        
        info_layout.addWidget(scroll_area)
        
        # Правая часть: превью
        preview_group = QGroupBox("Превью")
        preview_group.setObjectName("group_preview")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_label = QLabel("Превью будет здесь...")
        self.preview_label.setObjectName("preview_label")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setFixedSize(300, 180)  # Увеличенный размер превью
        preview_layout.addWidget(self.preview_label)
        
        # Расположение информации и превью
        info_preview_layout = QHBoxLayout()
        info_preview_layout.addWidget(info_group, 60)  # 60% ширины
        info_preview_layout.addWidget(preview_group, 40)  # 40% ширины
        
        main_layout.addLayout(info_preview_layout)

        # Создание вкладок
        self.tabs = QTabWidget()
        self.tabs.setObjectName("main_tabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabBarAutoHide(False)
        main_layout.addWidget(self.tabs)

        # Вкладка видео
        self.setup_video_tab()
        # Вкладка аудио настроек
        self.setup_audio_settings_tab()
        # Вкладка аудио извлечения
        self.setup_audio_extract_tab()
        # Вкладка логов
        self.setup_log_tab()
        # Вкладка настроек
        self.setup_settings_tab()

        # Прогресс пакетного рендеринга
        self.batch_status_label = QLabel("")
        self.batch_status_label.setObjectName("batch_status_label")
        self.batch_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.batch_status_label.setStyleSheet("font-size: 13px; color: #333;")
        self.batch_status_label.setMinimumHeight(22)
        # Добавляем над прогресс-баром
        self.centralWidget().layout().addWidget(self.batch_status_label)
        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("main_progress_bar")
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setMaximumHeight(20)
        self.centralWidget().layout().addWidget(self.progress_bar)

    def setup_video_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # Настройки кодирования
        settings_group = QGroupBox("Настройки кодирования видео")
        grid = QGridLayout(settings_group)
        
        # Разрешение
        grid.addWidget(QLabel("Разрешение:"), 0, 0)
        self.resolution = QComboBox()
        self.resolution.addItems(["Без изменений", "4K (3840x2160)", "1440p (2560x1440)", "1080p (1920x1080)", 
                                 "720p (1280x720)", "480p (854x480)", "360p (640x360)", 
                                 "240p (426x240)", "144p (256x144)", "128p (256x128)"])
        grid.addWidget(self.resolution, 0, 1)
        
        # Кодек
        grid.addWidget(QLabel("Кодек:"), 1, 0)
        self.video_codec = QComboBox()
        self.video_codec.addItems(["Без изменений", "libx264", "libx265", "h264_nvenc", "hevc_nvenc", "vp9", "av1"])
        grid.addWidget(self.video_codec, 1, 1)
        
        # Формат
        grid.addWidget(QLabel("Формат:"), 2, 0)
        self.format = QComboBox()
        self.format.addItems(["mp4", "mkv", "mov", "avi", "flv", "webm"])
        grid.addWidget(self.format, 2, 1)
        
        # Битрейт
        grid.addWidget(QLabel("Битрейт:"), 3, 0)
        self.bitrate = QComboBox()
        self.bitrate.setEditable(True)
        self.bitrate.addItems(["Без изменений", "500k", "1M", "2M", "5M", "10M", "20M"])
        grid.addWidget(self.bitrate, 3, 1)

        # Кнопка рендеринга
        self.btn_render = QPushButton("Начать рендеринг видео")
        self.btn_render.clicked.connect(self.start_video_render)
        self.btn_render.setMinimumHeight(35)

        # Добавление элементов на вкладку
        layout.addWidget(settings_group, 0, 0, 1, 2)
        layout.addWidget(self.btn_render, 1, 0, 1, 2)
        
        self.tabs.addTab(tab, "Видео")

    def setup_audio_settings_tab(self):
        """Вкладка для настроек аудио при конвертации видео"""
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # Настройки аудио
        settings_group = QGroupBox("Настройки аудио для видео")
        grid = QGridLayout(settings_group)
        
        # Аудио кодек
        grid.addWidget(QLabel("Аудио кодек:"), 0, 0)
        self.audio_codec = QComboBox()
        self.audio_codec.addItems(["Без изменений", "aac", "mp3", "flac", "opus", "ac3"])
        grid.addWidget(self.audio_codec, 0, 1)
        
        # Битрейт аудио
        grid.addWidget(QLabel("Битрейт аудио:"), 1, 0)
        self.audio_bitrate = QComboBox()
        self.audio_bitrate.setEditable(True)
        self.audio_bitrate.addItems(["Без изменений", "64k", "128k", "192k", "256k", "320k"])
        grid.addWidget(self.audio_bitrate, 1, 1)
        
        # Каналы
        grid.addWidget(QLabel("Каналы:"), 2, 0)
        self.audio_channels = QComboBox()
        self.audio_channels.addItems(["Без изменений", "1 (моно)", "2 (стерео)", "5.1", "7.1"])
        grid.addWidget(self.audio_channels, 2, 1)
        
        layout.addWidget(settings_group)
        self.tabs.addTab(tab, "Аудио настройки")

    def setup_audio_extract_tab(self):
        """Вкладка для извлечения аудио"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Группа формата аудио
        audio_group = QGroupBox("Настройки извлечения аудио")
        vbox = QVBoxLayout(audio_group)
        
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Формат аудио:"))
        self.audio_format = QComboBox()
        self.audio_format.addItems(["mp3", "aac", "flac", "wav", "ogg", "ac3"])
        hbox.addWidget(self.audio_format)
        hbox.addStretch()
        vbox.addLayout(hbox)
        
        # Кнопка извлечения аудио
        self.btn_extract = QPushButton("Извлечь аудио")
        self.btn_extract.clicked.connect(self.extract_audio)
        self.btn_extract.setMinimumHeight(35)
        vbox.addWidget(self.btn_extract)
        
        layout.addWidget(audio_group)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Аудио извлечение")

    def setup_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        
        layout.addWidget(self.log_text)
        self.tabs.addTab(tab, "Логи выполнения")

    def setup_settings_tab(self):
        """Вкладка для настроек программы"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Группа настроек уведомлений
        notification_group = QGroupBox("Настройки уведомлений")
        form_layout = QFormLayout(notification_group)
        
        self.chk_video_notify = QCheckBox("Показывать уведомления после рендеринга видео")
        self.chk_video_notify.setChecked(self.settings["show_video_notifications"])
        form_layout.addRow(self.chk_video_notify)
        
        self.chk_audio_notify = QCheckBox("Показывать уведомления после извлечения аудио")
        self.chk_audio_notify.setChecked(self.settings["show_audio_notifications"])
        form_layout.addRow(self.chk_audio_notify)
        
        # Кнопка сохранения настроек
        btn_save = QPushButton("Сохранить настройки")
        btn_save.clicked.connect(self.save_settings)
        btn_save.setMinimumHeight(35)
        
        layout.addWidget(notification_group)
        # Группа выбора языка
        language_group = QGroupBox("Язык интерфейса")
        lang_layout = QHBoxLayout(language_group)
        self.locale_combo = QComboBox()
        self.locale_combo.setEditable(False)
        btn_apply_locale = QPushButton("Применить")
        btn_apply_locale.clicked.connect(self.on_apply_locale)
        btn_refresh_locales = QPushButton("Обновить список")
        btn_refresh_locales.clicked.connect(self.load_locales)
        btn_open_locales = QPushButton("Открыть папку локалей")
        btn_open_locales.clicked.connect(self.open_locales_folder)
        lang_layout.addWidget(self.locale_combo)
        lang_layout.addWidget(btn_apply_locale)
        lang_layout.addWidget(btn_refresh_locales)
        lang_layout.addWidget(btn_open_locales)
        layout.addWidget(language_group)
        layout.addWidget(btn_save)
        layout.addStretch(1)
        
        self.tabs.addTab(tab, "Настройки")

    def save_settings(self):
        """Сохраняет настройки программы"""
        self.settings["show_video_notifications"] = self.chk_video_notify.isChecked()
        self.settings["show_audio_notifications"] = self.chk_audio_notify.isChecked()
        QMessageBox.information(self, "Сохранено", "Настройки успешно сохранены!")
        # Сохраняем текущие настройки в config
        try:
            cfg = {}
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
            cfg['show_video_notifications'] = self.chk_video_notify.isChecked()
            cfg['show_audio_notifications'] = self.chk_audio_notify.isChecked()
            # сохраняем также выбранный язык
            if hasattr(self, 'locale_combo') and self.locale_combo.currentData():
                cfg['language'] = self.locale_combo.currentData()
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def load_locales(self):
        """Сканирует папку locales рядом со скриптом и заполняет self.locale_combo."""
        app_dir = APP_DIR
        # При запуске из PyInstaller реальные распакованные ресурсы могут быть в RESOURCE_DIR
        # Читаем локали из RESOURCE_DIR если там есть, иначе из APP_DIR
        locales_dir = os.path.join(RESOURCE_DIR, 'locales') if os.path.exists(os.path.join(RESOURCE_DIR, 'locales')) else os.path.join(app_dir, 'locales')
        # Создадим папку, если её нет
        try:
            os.makedirs(locales_dir, exist_ok=True)
        except Exception:
            pass

        self.locales_map = {}
        self.locale_combo.clear()
        try:
            files = [f for f in os.listdir(locales_dir) if f.lower().endswith('.json')]
            for fname in sorted(files):
                code = os.path.splitext(fname)[0]
                path = os.path.join(locales_dir, fname)
                # Попробуем прочитать поле 'name' внутри JSON чтобы показать удобочитаемое имя
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

    def open_locales_folder(self):
        app_dir = APP_DIR
        locales_dir = os.path.join(app_dir, 'locales')
        try:
            if platform.system() == 'Windows':
                os.startfile(locales_dir)
            elif platform.system() == 'Darwin':
                subprocess.call(('open', locales_dir))
            else:
                subprocess.call(('xdg-open', locales_dir))
        except Exception as e:
            QMessageBox.warning(self, 'Ошибка', f'Не получилось открыть папку локалей: {e}')

    def on_apply_locale(self):
        code = None
        if hasattr(self, 'locale_combo'):
            code = self.locale_combo.currentData()
        if not code:
            QMessageBox.information(self, 'Внимание', 'Сначала выберите язык локали.')
            return
        self.apply_locale(code)
        # Сохраняем выбор в config
        try:
            cfg = {}
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
            cfg['language'] = code
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def apply_locale(self, code):
        """Загружает JSON локали и применяет переводы к ключевым виджетам."""
        path = self.locales_map.get(code) if hasattr(self, 'locales_map') else None
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        self.translations = data
        t = self.translations
        # Универсальный перевод: сначала по objectName, затем по текущему тексту/placeholder
        def _set_text_by_type(w, text):
            try:
                from PyQt6.QtWidgets import QPushButton, QLabel, QGroupBox, QCheckBox, QLineEdit, QComboBox, QTextEdit
                # Пробуем установить текст в зависимости от типа виджета
                if isinstance(w, QPushButton):
                    w.setText(text)
                    return True
                if isinstance(w, QLabel):
                    w.setText(text)
                    return True
                if isinstance(w, QGroupBox):
                    w.setTitle(text)
                    return True
                if isinstance(w, QCheckBox):
                    w.setText(text)
                    return True
                if isinstance(w, QLineEdit):
                    w.setPlaceholderText(text)
                    return True
                if isinstance(w, QComboBox):
                    # Если перевод даёт список элементов для combobox — применим
                    if isinstance(text, (list, tuple)):
                        try:
                            w.clear()
                            w.addItems([str(i) for i in text])
                            return True
                        except Exception:
                            pass
                    else:
                        # Иначе, если есть точное совпадение с одним из элементов — заменим его
                        try:
                            for i in range(w.count()):
                                item = w.itemText(i)
                                if item in t and isinstance(t[item], str):
                                    w.setItemText(i, t[item])
                            return True
                        except Exception:
                            pass
                if isinstance(w, QTextEdit):
                    # Не трогаем содержимое логов
                    return False
            except Exception:
                pass
            return False

        # Window title
        if t.get('window_title'):
            try:
                self.setWindowTitle(t.get('window_title'))
            except Exception:
                pass

        # Сначала обработаем явные ключи, если они заданы (старый стиль JSON)
        explicit_map = {
            'btn_render': getattr(self, 'btn_render', None),
            'btn_extract': getattr(self, 'btn_extract', None),
            'chk_video_notify': getattr(self, 'chk_video_notify', None),
            'chk_audio_notify': getattr(self, 'chk_audio_notify', None)
        }
        for key, widget in explicit_map.items():
            if widget and t.get(key):
                try:
                    _set_text_by_type(widget, t.get(key))
                except Exception:
                    pass

        # Вкладки: поддерживаем и старые ключи и поиск по текущему тексту
        try:
            for idx in range(self.tabs.count()):
                current = self.tabs.tabText(idx)
                # сначала по известным именам
                if idx == 0 and t.get('tab_video'):
                    self.tabs.setTabText(idx, t.get('tab_video'))
                    continue
                if idx == 1 and t.get('tab_audio_settings'):
                    self.tabs.setTabText(idx, t.get('tab_audio_settings'))
                    continue
                if idx == 2 and t.get('tab_audio_extract'):
                    self.tabs.setTabText(idx, t.get('tab_audio_extract'))
                    continue
                if idx == 3 and t.get('tab_logs'):
                    self.tabs.setTabText(idx, t.get('tab_logs'))
                    continue
                if idx == 4 and t.get('tab_settings'):
                    self.tabs.setTabText(idx, t.get('tab_settings'))
                    continue
                # иначе пробуем перевести по текущему тексту
                if current and isinstance(current, str) and current in t and isinstance(t[current], str):
                    self.tabs.setTabText(idx, t[current])
        except Exception:
            pass

        # Проходим по всем виджетам и пробуем перевести
        try:
            for w in self.findChildren(QWidget):
                try:
                    # Пропускаем QTabWidget самих вкладок (уже обработали)
                    if w is self.tabs:
                        continue
                    obj = w.objectName() if hasattr(w, 'objectName') else None
                    applied = False
                    # 1) По objectName
                    if obj:
                        # В JSON может быть как простая строка, так и список для combobox
                        if obj in t:
                            applied = _set_text_by_type(w, t[obj])
                            if applied:
                                continue
                        # Также поддерживаем суффикс ".items" для списков
                        items_key = f"{obj}.items"
                        if items_key in t and isinstance(t[items_key], (list, tuple)) and isinstance(w, QComboBox):
                            try:
                                w.clear()
                                w.addItems([str(i) for i in t[items_key]])
                                continue
                            except Exception:
                                pass

                    # 2) По текущему тексту (для QPushButton, QLabel, QGroupBox, QCheckBox)
                    # Получаем возможные текстовые представления
                    cur_texts = []
                    try:
                        # label-like
                        if hasattr(w, 'text'):
                            cur_texts.append(w.text())
                    except Exception:
                        pass
                    try:
                        if hasattr(w, 'placeholderText'):
                            cur = w.placeholderText()
                            if cur:
                                cur_texts.append(cur)
                    except Exception:
                        pass
                    # Попытка применить перевод по любому найденному текущему тексту
                    for ct in cur_texts:
                        if not ct:
                            continue
                        if ct in t and isinstance(t[ct], (str, list, tuple)):
                            try:
                                if _set_text_by_type(w, t[ct]):
                                    applied = True
                                    break
                            except Exception:
                                pass
                    if applied:
                        continue

                    # 3) Для QComboBox: попытка заменить отдельные элементы по ключам в JSON
                    from PyQt6.QtWidgets import QComboBox
                    if isinstance(w, QComboBox):
                        try:
                            for i in range(w.count()):
                                item = w.itemText(i)
                                if item in t and isinstance(t[item], str):
                                    w.setItemText(i, t[item])
                        except Exception:
                            pass

                except Exception:
                    # Не критично — продолжаем со следующими виджетами
                    continue
        except Exception:
            pass

    def setup_styles(self):
        # Светлая тема с современными тенями
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F0F2F5;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #DCDFE6;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #409EFF;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #66B1FF;
            }
            QPushButton:pressed {
                background-color: #3A8EE6;
            }
            QLineEdit, QComboBox, QTextEdit {
                border: 1px solid #DCDFE6;
                border-radius: 4px;
                padding: 5px;
                font-size: 13px;
            }
            QProgressBar {
                border: 1px solid #DCDFE6;
                border-radius: 4px;
                text-align: center;
                height: 18px;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background-color: #409EFF;
                border-radius: 3px;
            }
            QTabWidget::pane {
                border: 1px solid #DCDFE6;
                border-radius: 6px;
                background: white;
            }
            QTabBar::tab {
                background: #E4E7ED;
                border: 1px solid #DCDFE6;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 6px 12px;
                margin-right: 2px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background: white;
                border-bottom: 2px solid #409EFF;
                font-weight: bold;
            }
            QScrollArea {
                border: none;
            }
        """)
        
        # Добавление теней к группам
        for group in self.findChildren(QGroupBox):
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(8)
            shadow.setXOffset(0)
            shadow.setYOffset(2)
            shadow.setColor(QColor(0, 0, 0, 20))
            group.setGraphicsEffect(shadow)

    def select_input_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "Выберите видеофайл", "", 
            "Видеофайлы (*.mp4 *.mkv *.mov *.avi *.flv)"
        )
        if file:
            self.input_path.setText(file)
            self.input_file = file
            # ОЧИЩАЕМ выходной файл при выборе нового входного
            self.output_path.clear()
            self.output_file = ""
            self.load_video_info(file)
            self.show_video_preview(file)
            self.update_video_settings()
            self.update_audio_settings()

    def select_input_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите видеофайлы", "", 
            "Видеофайлы (*.mp4 *.mkv *.mov *.avi *.flv)"
        )
        if files:
            self.input_files = files
            self.input_file = files[0]
            self.input_path.setText(files[0])
            self.output_path.clear()
            self.output_file = ""
            self.load_video_info(files[0])
            self.show_video_preview(files[0])
            self.update_video_settings()
            self.update_audio_settings()

    def select_output_file(self):
        file, _ = QFileDialog.getSaveFileName(
            self, "Сохранить результат", "", 
            "Видеофайлы (*.mp4 *.mkv *.mov *.avi *.flv)"
        )
        if file:
            self.output_path.setText(file)
            self.output_file = file

    def load_video_info(self, file_path):
        try:
            # Очищаем предыдущую информацию
            for i in reversed(range(self.info_grid.count())): 
                self.info_grid.itemAt(i).widget().setParent(None)
            
            ffprobe_cmd = getattr(self, "ffprobe_path", "ffprobe")
            cmd = [
                ffprobe_cmd, '-v', 'error', '-show_format',
                '-show_streams', '-of', 'json', file_path
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            )
            info = json.loads(result.stdout)
            
            # Сохраняем информацию о видео для последующего использования
            self.video_info = info
            
            # Собираем информацию для отображения
            streams = info.get('streams', [])
            format_info = info.get('format', {})
            
            # Видео потоки
            video_streams = [s for s in streams if s['codec_type'] == 'video']
            # Аудио потоки
            audio_streams = [s for s in streams if s['codec_type'] == 'audio']
            
            # Основные блоки информации
            blocks = []
            
            # Видео поток
            if video_streams:
                video_info = "<b>Видео поток:</b><br>"
                for stream in video_streams:
                    video_info += f"Кодек: {stream.get('codec_name', 'N/A')}<br>"
                    video_info += f"Разрешение: {stream.get('width', 'N/A')}x{stream.get('height', 'N/A')}<br>"
                    
                    # Битрейт
                    bit_rate = stream.get('bit_rate', 0)
                    try:
                        bit_rate = int(bit_rate) / 1000
                        video_info += f"Битрейт: {bit_rate:.0f} kbps<br>"
                    except:
                        video_info += "Битрейт: N/A<br>"
                    
                    # FPS
                    frame_rate = stream.get('avg_frame_rate', '0/0')
                    try:
                        num, den = map(float, frame_rate.split('/'))
                        fps = num / den if den != 0 else 0
                        video_info += f"FPS: {fps:.2f}<br>"
                    except:
                        video_info += "FPS: N/A<br>"
                    
                    # Длительность
                    duration = float(stream.get('duration', 0))
                    video_info += f"Длительность: {duration:.2f} сек<br><br>"
                blocks.append(video_info)
            
            # Аудио потоки
            if audio_streams:
                audio_info = "<b>Аудио поток:</b><br>"
                for i, stream in enumerate(audio_streams):
                    if i > 0:
                        audio_info += "<br>"
                    audio_info += f"Поток #{i+1}:<br>"
                    audio_info += f"Кодек: {stream.get('codec_name', 'N/A')}<br>"
                    audio_info += f"Каналы: {stream.get('channels', 'N/A')}<br>"
                    
                    # Частота дискретизации
                    sample_rate = stream.get('sample_rate', 0)
                    try:
                        sample_rate = int(sample_rate) / 1000
                        audio_info += f"Частота: {sample_rate:.1f} kHz<br>"
                    except:
                        audio_info += "Частота: N/A<br>"
                    
                    # Битрейт
                    audio_bitrate = stream.get('bit_rate', 0)
                    try:
                        audio_bitrate = int(audio_bitrate) / 1000
                        audio_info += f"Битрейт: {audio_bitrate:.0f} kbps<br>"
                    except:
                        audio_info += "Битрейт: N/A<br>"
                blocks.append(audio_info)
            
            # Контейнер
            container_info = "<b>Контейнер:</b><br>"
            container_info += f"Формат: {format_info.get('format_name', 'N/A')}<br>"
            
            # Общая длительность
            total_duration = float(format_info.get('duration', 0))
            container_info += f"Длительность: {total_duration:.2f} сек<br>"
            
            # Размер файла
            file_size = int(format_info.get('size', 0)) / (1024 * 1024)
            container_info += f"Размер: {file_size:.2f} MB"
            blocks.append(container_info)
            
            # Дополнительная информация
            extra_info = ""
            if video_streams:
                extra_info += "<b>Доп. видео информация:</b><br>"
                for stream in video_streams:
                    extra_info += f"Профиль: {stream.get('profile', 'N/A')}<br>"
                    extra_info += f"Уровень: {stream.get('level', 'N/A')}<br>"
                    extra_info += f"Пикс. формат: {stream.get('pix_fmt', 'N/A')}<br><br>"
            
            if audio_streams:
                extra_info += "<b>Доп. аудио информация:</b><br>"
                for stream in audio_streams:
                    extra_info += f"Язык: {stream.get('tags', {}).get('language', 'N/A')}<br>"
                    extra_info += f"Название: {stream.get('tags', {}).get('title', 'N/A')}<br><br>"
            
            if extra_info:
                blocks.append(extra_info)
            
            # Размещаем блоки в сетке (по 3 в ряд)
            row, col = 0, 0
            for block in blocks:
                html_block = f'<div style="word-break:break-all;">{block}</div>'
                label = QLabel(html_block)
                label.setWordWrap(True)
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                label.setStyleSheet("background-color: #F8F9FA; padding: 6px; border-radius: 4px; font-size: 11px;")
                label.setMinimumWidth(180)
                label.setMaximumWidth(220)
                self.info_grid.addWidget(label, row, col)
                
                col += 1
                if col > 2:
                    col = 0
                    row += 1
            
            # Если последний ряд не заполнен, добавляем пустой виджет
            if col > 0 and col <= 2:
                for i in range(col, 3):
                    empty = QWidget()
                    self.info_grid.addWidget(empty, row, i)
            
        except Exception as e:
            error_label = QLabel(f"Ошибка получения информации: {str(e)}")
            error_label.setStyleSheet("color: red;")
            self.info_grid.addWidget(error_label, 0, 0)

    def update_video_settings(self):
        """Обновляет настройки видео на основе информации о загруженном файле"""
        if not self.video_info:
            return
            
        # Определяем текущее разрешение
        for stream in self.video_info.get('streams', []):
            if stream['codec_type'] == 'video':
                width = stream.get('width', '')
                height = stream.get('height', '')
                if width and height:
                    res_str = f"{width}x{height}"
                    # Проверяем, есть ли такое разрешение в списке
                    for i in range(self.resolution.count()):
                        if res_str in self.resolution.itemText(i):
                            self.resolution.setCurrentIndex(i)
                            break
                    else:
                        # Если нет - добавляем
                        self.resolution.addItem(f"{res_str} (исходное)")
                        self.resolution.setCurrentIndex(self.resolution.count() - 1)
                
                # Определяем текущий кодек
                codec = stream.get('codec_name', '')
                if codec:
                    # Проверяем, есть ли такой кодек в списке
                    for i in range(self.video_codec.count()):
                        if codec in self.video_codec.itemText(i).lower():
                            self.video_codec.setCurrentIndex(i)
                            break
                    else:
                        # Если нет - добавляем
                        self.video_codec.addItem(f"{codec} (исходный)")
                        self.video_codec.setCurrentIndex(self.video_codec.count() - 1)
                
                # Определяем текущий битрейт
                bitrate = stream.get('bit_rate', 0)
                try:
                    bitrate = int(bitrate) // 1000  # Переводим в kbps
                    bitrate_str = f"{bitrate}k"
                    # Устанавливаем в комбобокс
                    self.bitrate.setCurrentText(bitrate_str)
                except:
                    pass
                break

    def update_audio_settings(self):
        """Обновляет настройки аудио на основе информации о загруженном файле"""
        if not self.video_info:
            return
            
        audio_streams = [s for s in self.video_info.get('streams', []) if s['codec_type'] == 'audio']
        if not audio_streams:
            return
            
        # Берем первый аудиопоток
        stream = audio_streams[0]
        
        # Определяем текущий кодек
        codec = stream.get('codec_name', '')
        if codec:
            # Проверяем, есть ли такой кодек в списке
            for i in range(self.audio_codec.count()):
                if codec in self.audio_codec.itemText(i).lower():
                    self.audio_codec.setCurrentIndex(i)
                    break
            else:
                # Если нет - добавляем
                self.audio_codec.addItem(f"{codec} (исходный)")
                self.audio_codec.setCurrentIndex(self.audio_codec.count() - 1)
        
        # Определяем текущий битрейт
        bitrate = stream.get('bit_rate', 0)
        try:
            bitrate = int(bitrate) // 1000  # Переводим в kbps
            bitrate_str = f"{bitrate}k"
            # Устанавливаем в комбобокс
            self.audio_bitrate.setCurrentText(bitrate_str)
        except:
            pass
        
        # Определяем количество каналов
        channels = stream.get('channels', 0)
        if channels:
            # Проверяем, есть ли такое количество каналов в списке
            for i in range(self.audio_channels.count()):
                if str(channels) in self.audio_channels.itemText(i):
                    self.audio_channels.setCurrentIndex(i)
                    break
            else:
                # Если нет - добавляем
                self.audio_channels.addItem(f"{channels} каналов (исходное)")
                self.audio_channels.setCurrentIndex(self.audio_channels.count() - 1)

    def show_video_preview(self, file_path):
        try:
            # Создаем временное превью
            preview_path = os.path.join(os.path.dirname(file_path), "preview.jpg")
            ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
            # Проверяем, что ffmpeg доступен либо как абсолютный путь, либо в PATH
            import shutil as _shutil
            if os.path.isabs(ffmpeg_cmd):
                if not os.path.exists(ffmpeg_cmd):
                    raise FileNotFoundError(ffmpeg_cmd)
            else:
                if _shutil.which(ffmpeg_cmd) is None:
                    raise FileNotFoundError(ffmpeg_cmd)
            cmd = [
                ffmpeg_cmd, '-i', file_path, 
                '-ss', '00:00:01', '-vframes', '1',
                '-q:v', '2', preview_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            pixmap = QPixmap(preview_path)
            if not pixmap.isNull():
                # Уменьшаем размер превью
                pixmap = pixmap.scaled(
                    300, 180, 
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.preview_label.setPixmap(pixmap)
            os.remove(preview_path)
            
        except Exception as e:
            self.log_text.append(f"Ошибка создания превью: {str(e)}")
            self.preview_label.setText("Не удалось загрузить превью")

    def check_codec_available(self, ffmpeg_cmd, codec_name):
        """Проверяет, доступен ли указанный кодек в ffmpeg. Если нет — возвращает 'libx264' в качестве безопасного фолбэка."""
        try:
            # Быстрая эвристика: если запрошен nvenc — проверяем наличие nvcuda.dll на Windows
            if 'nvenc' in codec_name.lower() and platform.system() == 'Windows':
                try:
                    # Попытка загрузить драйвер CUDA
                    ctypes.WinDLL('nvcuda.dll')
                except Exception:
                    return 'libx264'

            # Запросим список энкодеров
            proc = subprocess.run([ffmpeg_cmd, '-hide_banner', '-encoders'], capture_output=True, text=True, timeout=5)
            out = proc.stdout + proc.stderr
            # Проверяем, есть ли строка с именем кодека
            # У энкодеров формат: " V..... h264_nvenc"
            if codec_name in out:
                return codec_name
            # Также проверим по короткому имени (например h264 для libx264)
            if codec_name.lower() in out.lower():
                return codec_name
        except Exception:
            pass
        return 'libx264'

    def map_audio_codec(self, ffmpeg_cmd, codec_name):
        """Сопоставляет короткое имя кодека с реальным энкодером ffmpeg и проверяет доступность.
        Возвращает 'copy' для копирования, либо выбранный энкодер, либо разумный фолбэк (например 'aac').
        """
        if not codec_name:
            return 'aac'
        name = str(codec_name).lower()
        # Прямые маркеры
        if name in ('copy', 'исходный', 'original'):
            return 'copy'

        # Базовое сопоставление удобных имён к реальным энкодерам
        mapping = {
            'opus': 'libopus',
            'mp3': 'libmp3lame',
            'aac': 'aac',
            'flac': 'flac',
            'vorbis': 'libvorbis',
            'ac3': 'ac3',
            'wav': 'pcm_s16le',
            'wma': 'wmav2'
        }
        mapped = mapping.get(name, name)

        # Проверим доступность через ffmpeg -encoders
        out = ''
        try:
            proc = subprocess.run([ffmpeg_cmd, '-hide_banner', '-encoders'], capture_output=True, text=True, timeout=5)
            out = (proc.stdout or '') + (proc.stderr or '')
        except Exception:
            out = ''

        # Если энкодер найден в выводе — возвращаем его
        try:
            if mapped in out or mapped.lower() in out.lower():
                return mapped
        except Exception:
            pass

        # Попробуем подобрать разумный фолбэк из часто доступных
        for candidate in ('aac', 'libopus', 'libvorbis', 'libmp3lame'):
            try:
                if candidate in out.lower():
                    return candidate
            except Exception:
                continue

        # Последняя попытка: вернуть mapped как есть
        return mapped

    def start_video_render(self):
        # Если выбрано несколько файлов — пакетная обработка
        files_to_render = getattr(self, "input_files", None)
        if files_to_render and len(files_to_render) > 1:
            self.batch_files = files_to_render
            self.batch_index = 0
            self.batch_total = len(files_to_render)
            self.batch_settings = {
                "res_text": self.resolution.currentText(),
                "video_codec": self.video_codec.currentText(),
                "format": self.format.currentText(),
                "bitrate": self.bitrate.currentText(),
                "audio_codec": self.audio_codec.currentText(),
                "audio_bitrate": self.audio_bitrate.currentText(),
                "audio_channels": self.audio_channels.currentText()
            }
            self.render_next_in_batch()
            return

        files_to_render = self.input_files if self.input_files else [self.input_file]
        if not files_to_render or not all(os.path.exists(f) for f in files_to_render):
            QMessageBox.warning(self, "Ошибка", "Выберите существующие видеофайлы!")
            return

        self.batch_index = 0
        self.batch_total = len(files_to_render)
        self.batch_files = files_to_render
        self.batch_settings = {
            "res_text": self.resolution.currentText(),
            "video_codec": self.video_codec.currentText(),
            "format": self.format.currentText(),
            "bitrate": self.bitrate.currentText(),
            "audio_codec": self.audio_codec.currentText(),
            "audio_bitrate": self.audio_bitrate.currentText(),
            "audio_channels": self.audio_channels.currentText()
        }
        self.render_next_in_batch()

    def render_next_in_batch(self):
        if self.batch_index >= self.batch_total:
            self.batch_status_label.setText("Пакетное перекодирование завершено!")
            self.log_text.append("Пакетное перекодирование завершено!")
            self.progress_bar.setValue(100)
            return

        input_file = self.batch_files[self.batch_index]
        # Показываем статус
        self.batch_status_label.setText(
            f"Видео {self.batch_index+1} из {self.batch_total}: {os.path.basename(input_file)}"
        )
        base, ext = os.path.splitext(input_file)
        i = 1
        while True:
            candidate = f"{base}_{i}{ext}"
            if not os.path.exists(candidate):
                output_file = candidate
                break
            i += 1

        self.output_file = output_file
        self.output_path.setText(output_file)

        # Формируем команду FFmpeg с настройками
        settings = self.batch_settings
        resolutions = {
            "4K": "3840:2160",
            "1440p": "2560:1440",
            "1080p": "1920:1080",
            "720p": "1280:720",
            "480p": "854:480",
            "360p": "640:360",
            "240p": "426:240",
            "144p": "256:144",
            "128p": "256:128"
        }
        ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
        cmd = [ffmpeg_cmd, '-i', input_file]
        # Видео кодек
        if "Без изменений" not in settings["video_codec"] and "исходный" not in settings["video_codec"]:
            selected_codec = settings["video_codec"].split()[0]
            # Проверяем доступность выбранного кодека и при необходимости подменяем
            safe_codec = self.check_codec_available(ffmpeg_cmd, selected_codec)
            if safe_codec != selected_codec:
                self.log_text.append(f"⚠️ Кодек {selected_codec} недоступен на этой системе — используем {safe_codec}.")
            cmd.extend(['-c:v', safe_codec])
        # Разрешение
        res_found = False
        for key in resolutions:
            if key in settings["res_text"]:
                scale = resolutions[key]
                cmd.extend([
                    '-vf',
                    f"scale={scale}:force_original_aspect_ratio=decrease,pad={scale}:(ow-iw)/2:(oh-ih)/2"
                ])
                res_found = True
                break
        if not res_found and 'x' in settings["res_text"]:
            res = settings["res_text"].split()[0]
            cmd.extend([
                '-vf',
                f"scale={res}:force_original_aspect_ratio=decrease,pad={res}:(ow-iw)/2:(oh-ih)/2"
            ])
        # Битрейт видео
        if "Без изменений" not in settings["bitrate"] and "исходный" not in settings["bitrate"]:
            cmd.extend(['-b:v', settings["bitrate"].split()[0]])
        # Аудио кодек
        if "Без изменений" not in settings["audio_codec"] and "исходный" not in settings["audio_codec"]:
            requested_audio = settings["audio_codec"].split()[0]
            safe_audio = self.map_audio_codec(ffmpeg_cmd, requested_audio)
            if safe_audio == 'copy':
                cmd.extend(['-c:a', 'copy'])
            else:
                cmd.extend(['-c:a', safe_audio])
        # Битрейт аудио
        if "Без изменений" not in settings["audio_bitrate"] and "исходный" not in settings["audio_bitrate"]:
            # Сохраним только корректные значения вида '128k'
            ab = settings["audio_bitrate"].split()[0]
            if ab.endswith('k'):
                try:
                    n = int(ab[:-1])
                    if n > 0:
                        cmd.extend(['-b:a', f"{n}k"])
                except Exception:
                    pass
        # Каналы аудио
        if "Без изменений" not in settings["audio_channels"] and "исходное" not in settings["audio_channels"]:
            if "моно" in settings["audio_channels"]:
                cmd.extend(['-ac', '1'])
            elif "стерео" in settings["audio_channels"]:
                cmd.extend(['-ac', '2'])
            elif "5.1" in settings["audio_channels"]:
                cmd.extend(['-ac', '6'])
            elif "7.1" in settings["audio_channels"]:
                cmd.extend(['-ac', '8'])
        # Формат и выходной файл
        cmd.append(output_file)

        self.log_text.clear()
        self.log_text.append(f"Начато перекодирование видео {self.batch_index+1}/{self.batch_total}...")
        self.log_text.append("Команда: " + " ".join(cmd))
        self.progress_bar.setValue(0)

        self.worker = FFmpegWorker(cmd)
        self.worker.progressUpdated.connect(self.update_progress)
        self.worker.outputReceived.connect(self.log_text.append)
        self.worker.finished.connect(self.batch_render_finished)
        self.worker.start()

    def batch_render_finished(self, success):
        if success:
            self.log_text.append(f"Видео {self.batch_index+1} успешно перекодировано!")
        else:
            self.log_text.append(f"Ошибка при перекодировании видео {self.batch_index+1}!")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при обработке видео {self.batch_index+1}")

        self.batch_index += 1
        # Обновляем статус для следующего файла
        if self.batch_index < self.batch_total:
            next_file = self.batch_files[self.batch_index]
            self.batch_status_label.setText(
                f"Видео {self.batch_index+1} из {self.batch_total}: {os.path.basename(next_file)}"
            )
            self.render_next_in_batch()
        else:
            self.batch_status_label.setText("Пакетное перекодирование завершено!")
            # Показываем уведомление только после последнего файла
            if success and self.settings["show_video_notifications"]:
                dialog = NotificationDialog(self.output_file, self)
                dialog.exec()

    def extract_audio(self):
        if not self.input_file:
            QMessageBox.warning(self, "Ошибка", "Выберите видеофайл!")
            return
            
        # Определяем путь для аудио
        base_name = os.path.splitext(self.input_file)[0]
        audio_format = self.audio_format.currentText()
        output_file = f"{base_name}.{audio_format}"
        
        # Команда FFmpeg
        ffmpeg_cmd = getattr(self, "ffmpeg_path", "ffmpeg")
        # Выбираем энкодер для выбранного формата
        selected = audio_format.lower()
        chosen = self.map_audio_codec(ffmpeg_cmd, selected)
        cmd = [ffmpeg_cmd, '-i', self.input_file, '-vn']
        if chosen == 'copy':
            cmd.extend(['-acodec', 'copy'])
        else:
            cmd.extend(['-acodec', chosen])
        cmd.append(output_file)
        
        self.log_text.clear()
        self.log_text.append("Начато извлечение аудио...")
        self.log_text.append("Команда: " + " ".join(cmd))
        self.progress_bar.setValue(0)
        
        # Запуск в отдельном потоке
        self.worker = FFmpegWorker(cmd)
        self.worker.progressUpdated.connect(self.update_progress)
        self.worker.outputReceived.connect(self.log_text.append)
        self.worker.finished.connect(self.audio_extraction_finished)
        self.worker.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def render_finished(self, success):
        if success:
            self.log_text.append("Перекодирование видео успешно завершено!")
            
            # Показываем уведомление, если включено в настройках
            if self.settings["show_video_notifications"]:
                dialog = NotificationDialog(self.output_file, self)
                dialog.exec()
        else:
            self.log_text.append("Ошибка при перекодировании видео!")
            QMessageBox.critical(self, "Ошибка", "Произошла ошибка при обработке видео")

    def audio_extraction_finished(self, success):
        if success:
            self.log_text.append("Аудио успешно извлечено!")
            
            # Определяем путь к аудио файлу
            base_name = os.path.splitext(self.input_file)[0]
            audio_format = self.audio_format.currentText()
            output_file = f"{base_name}.{audio_format}"
            
            # Показываем уведомление, если включено в настройках
            if self.settings["show_audio_notifications"]:
                dialog = NotificationDialog(output_file, self)
                dialog.exec()
        else:
            self.log_text.append("Ошибка при извлечении аудио!")
            QMessageBox.critical(self, "Ошибка", "Произошла ошибка при извлечении аудио")

class FFmpegWorker(QThread):
    progressUpdated = pyqtSignal(int)
    outputReceived = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            # Проверим наличие запускаемого файла/команды заранее, чтобы не получить [Errno 2]
            import shutil as _shutil
            exe = self.command[0] if isinstance(self.command, (list, tuple)) and len(self.command) > 0 else None
            if exe:
                if os.path.isabs(exe) and not os.path.exists(exe):
                    self.outputReceived.emit(f"Ошибка: исполняемый файл не найден: {exe}")
                    self.finished.emit(False)
                    return
                if not os.path.isabs(exe) and _shutil.which(exe) is None:
                    self.outputReceived.emit(f"Ошибка: команда не найдена в PATH: {exe}")
                    self.finished.emit(False)
                    return

            process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            total_duration = None
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                    
                self.outputReceived.emit(line.strip())
                
                # Парсинг прогресса
                if "Duration:" in line:
                    parts = line.split("Duration:")[1].split(",")[0].strip()
                    try:
                        h, m, s = parts.split(":")
                        total_duration = int(h)*3600 + int(m)*60 + float(s)
                    except:
                        pass
                    
                elif "time=" in line:
                    time_str = line.split("time=")[1].split()[0]
                    try:
                        h, m, s = time_str.split(":")
                        current_time = int(h)*3600 + int(m)*60 + float(s)
                        
                        if total_duration and total_duration > 0:
                            progress = int((current_time / total_duration) * 100)
                            self.progressUpdated.emit(min(progress, 100))
                    except:
                        pass

            process.wait()
            self.finished.emit(process.returncode == 0)
            
        except Exception as e:
            self.outputReceived.emit(f"Ошибка: {str(e)}")
            self.finished.emit(False)

# ========== Запуск приложения ==========
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    ffmpeg_path = ""
    ffprobe_path = ""

    # Проверка config.json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("ffmpeg_installed"):
                ffmpeg_path = cfg.get("ffmpeg_path", "")
                ffprobe_path = cfg.get("ffprobe_path", "")
        except:
            pass

    # Если FFmpeg ещё не установлен — установка
    if not ffmpeg_path or not os.path.exists(ffmpeg_path):
        setup_dialog = FFmpegSetupDialog()
        setup_dialog.exec()

        # Повторная загрузка конфигурации
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                ffmpeg_path = cfg.get("ffmpeg_path", "")
                ffprobe_path = cfg.get("ffprobe_path", "")

    # Если всё ок — запуск основного окна
    if ffmpeg_path and os.path.exists(ffmpeg_path):
        window = VideoConverter()
        window.ffmpeg_path = ffmpeg_path
        window.ffprobe_path = ffprobe_path if ffprobe_path else ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe")
        window.show()
        sys.exit(app.exec())
    else:
        QMessageBox.critical(None, "Ошибка", "Не удалось установить FFmpeg.")
        sys.exit(1)