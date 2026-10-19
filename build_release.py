"""
build_release.py — собирает готовые к запуску сборки CineConvert для текущей ОС.

    python build_release.py

FFmpeg скачивается сам (те же источники, что и у кнопки «Обновить» в программе)
и кладётся внутрь сборки — программа работает сразу и без интернета.

Результат (папка release/):
  Windows  CineConvert-portable.zip            exe + FFmpeg + locales, сразу и офлайн
           CineConvert.exe                     лёгкий exe; FFmpeg докачается при первом запуске
  Linux    CineConvert-linux-<arch>.tar.gz     папка с программой и FFmpeg; запуск ./CineConvert
  macOS    CineConvert-macos-<arch>.dmg        CineConvert.app с FFmpeg внутри

Нужно: Python 3.9+, PyQt6 (или PyQt5), PyInstaller, Pillow (иконка для macOS).
Каталог вывода можно переопределить переменной окружения CINECONVERT_BUILD.
Проверка готовой сборки: python build_release.py --selftest
"""
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("CINECONVERT_BUILD", SRC)
WORK = os.path.join(OUT, "build")
DIST = os.path.join(OUT, "dist")
RELEASE = os.path.join(OUT, "release")
NAME = "CineConvert"
IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
EXE = ".exe" if IS_WIN else ""
SEP = ";" if IS_WIN else ":"
FFMPEG_BIN = os.path.join(SRC, "ffmpeg", "bin")      # кэш скачанного FFmpeg (в .gitignore)


def app_version():
    with open(os.path.join(SRC, "CineConvert.py"), encoding="utf-8") as f:
        m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
    return m.group(1) if m else "0"


def arch_name():
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "x64" if IS_WIN else "x86_64"


def qt_binding():
    """Какой Qt-биндинг попадёт в сборку: PyQt6, если он рабочий (как и в самой программе)."""
    import importlib
    try:
        importlib.import_module("PyQt6.QtWidgets")
        return "PyQt6"
    except ImportError:
        return "PyQt5"


def fetch_ffmpeg():
    """Скачивает ffmpeg и ffprobe для этой ОС в ./ffmpeg/bin (если их там ещё нет)."""
    need = [os.path.join(FFMPEG_BIN, n + EXE) for n in ("ffmpeg", "ffprobe")]
    if all(os.path.isfile(p) for p in need):
        print(">>> FFmpeg уже скачан:", FFMPEG_BIN)
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, SRC)
    import CineConvert as cc            # те же источники и распаковка, что и в программе
    last_err = None
    with tempfile.TemporaryDirectory() as tmp:
        for urls in cc.ffmpeg_sources():
            try:
                archives = []
                for i, url in enumerate(urls):
                    print(">>> FFmpeg:", url)
                    path = os.path.join(tmp, f"part{i}")
                    cc.download_file(url, path)
                    archives.append(path)
                cc.extract_ffmpeg_binaries(archives, FFMPEG_BIN)
                break
            except Exception as e:      # следующий источник
                last_err = e
                print("!!! не получилось:", e)
        else:
            raise SystemExit(f"Не удалось скачать FFmpeg: {last_err}")
    for p in need:
        if not os.path.isfile(p):
            raise SystemExit("В скачанном FFmpeg нет " + os.path.basename(p))
    out = subprocess.run([need[0], "-version"], capture_output=True, text=True).stdout
    print(">>> FFmpeg готов:", (out.splitlines() or ["?"])[0])


def pyinstaller(onefile, extra=()):
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--onefile" if onefile else "--onedir", "--name", NAME,
           "--add-data", f"{os.path.join(SRC, 'locales')}{SEP}locales",
           "--add-data", f"{os.path.join(SRC, 'fonts')}{SEP}fonts",
           "--distpath", DIST, "--workpath", WORK, "--specpath", WORK]
    icon = os.path.join(SRC, "app.ico")
    if os.path.exists(icon):
        cmd += ["--icon", icon, "--add-data", f"{icon}{SEP}."]
    if IS_MAC:
        cmd += ["--osx-bundle-identifier", "io.github.bboyjohnn.cineconvert"]
    cmd += ["--exclude-module", "PyQt5" if qt_binding() == "PyQt6" else "PyQt6"]   # в сборке — одна Qt
    cmd += list(extra)
    cmd.append(os.path.join(SRC, "CineConvert.py"))
    print(">>> PyInstaller\n    " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def copy_extras(folder):
    for name in ("THIRD_PARTY_NOTICES.md", "README.md"):
        p = os.path.join(SRC, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(folder, name))


def fresh_release_dir():
    if os.path.exists(RELEASE):
        shutil.rmtree(RELEASE)
    os.makedirs(RELEASE)


def build_windows():
    pyinstaller(onefile=True)
    exe = os.path.join(DIST, NAME + EXE)
    fresh_release_dir()
    shutil.copy2(exe, os.path.join(RELEASE, NAME + EXE))           # лёгкий exe

    port = os.path.join(DIST, NAME + "-portable")                  # portable: exe + ffmpeg + locales
    if os.path.exists(port):
        shutil.rmtree(port)
    shutil.copytree(FFMPEG_BIN, os.path.join(port, "ffmpeg", "bin"))
    shutil.copy2(exe, os.path.join(port, NAME + EXE))
    shutil.copytree(os.path.join(SRC, "locales"), os.path.join(port, "locales"))
    copy_extras(port)
    zip_path = os.path.join(RELEASE, NAME + "-portable.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(port):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.join(NAME + "-portable", os.path.relpath(full, port)))
    return port


def build_linux():
    pyinstaller(onefile=False)
    app = os.path.join(DIST, NAME)            # папка: CineConvert + _internal
    shutil.copytree(FFMPEG_BIN, os.path.join(app, "ffmpeg", "bin"))
    copy_extras(app)
    fresh_release_dir()
    tar_path = os.path.join(RELEASE, f"{NAME}-linux-{arch_name()}.tar.gz")
    with tarfile.open(tar_path, "w:gz", compresslevel=6) as t:
        t.add(app, arcname=NAME)
    return app


def build_macos():
    binaries = []
    for n in ("ffmpeg", "ffprobe"):
        binaries += ["--add-binary", f"{os.path.join(FFMPEG_BIN, n)}{SEP}ffmpeg/bin"]
    pyinstaller(onefile=False, extra=binaries)
    app = os.path.join(DIST, NAME + ".app")
    plist_path = os.path.join(app, "Contents", "Info.plist")
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)
    plist.update({"CFBundleShortVersionString": app_version(), "CFBundleVersion": app_version(),
                  "CFBundleDisplayName": "Cine Convert", "NSHighResolutionCapable": True,
                  "NSRequiresAquaSystemAppearance": False})
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)
    # после правки Info.plist — заново подписать (ad-hoc): без подписи arm64 не запустится
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app], check=True)
    fresh_release_dir()
    label = "apple-silicon" if arch_name() == "arm64" else "intel"
    dmg = os.path.join(RELEASE, f"{NAME}-macos-{label}.dmg")
    with tempfile.TemporaryDirectory() as stage:
        shutil.copytree(app, os.path.join(stage, NAME + ".app"), symlinks=True)
        os.symlink("/Applications", os.path.join(stage, "Applications"))
        subprocess.run(["hdiutil", "create", "-volname", "Cine Convert", "-srcfolder", stage,
                        "-ov", "-format", "UDZO", dmg], check=True)
    return app


def app_executable(built):
    if IS_MAC:
        return os.path.join(built, "Contents", "MacOS", NAME)
    return os.path.join(built, NAME + EXE)


def selftest(built):
    """Запускает собранную программу в режиме самопроверки (без окна на экране)."""
    report = os.path.join(OUT, "selftest.json")
    if os.path.exists(report):
        os.remove(report)
    env = dict(os.environ, CINECONVERT_SELFTEST=report, QT_QPA_PLATFORM="offscreen")
    exe = app_executable(built)
    print(">>> Самопроверка:", exe)
    rc = subprocess.run([exe], env=env, timeout=300).returncode
    data = json.load(open(report, encoding="utf-8")) if os.path.exists(report) else {}
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if rc != 0 or not data.get("ok"):
        raise SystemExit(f"Самопроверка не прошла (код {rc})")


def main():
    for stream in (sys.stdout, sys.stderr):     # консоль Windows (cp1252) не печатает кириллицу
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    fetch_ffmpeg()
    if IS_WIN:
        built = build_windows()
    elif IS_MAC:
        built = build_macos()
    else:
        built = build_linux()
    if "--selftest" in sys.argv:
        selftest(built)
    print("\n>>> Готово:")
    for f in sorted(os.listdir(RELEASE)):
        print(f"    {f}  ({os.path.getsize(os.path.join(RELEASE, f)) // (1024 * 1024)} МБ)")


if __name__ == "__main__":
    main()
