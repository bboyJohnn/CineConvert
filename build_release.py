"""
build_release.py — собирает готовые артефакты CineConvert.

Результат (папка release/):
  1) CineConvert.exe            — лёгкий standalone; FFmpeg докачивается при
                                  первом запуске (нужен интернет один раз).
  2) CineConvert-portable.zip   — exe + встроенный FFmpeg + locales; работает
                                  сразу и офлайн, «из коробки».

Требуется: PyInstaller (pip install pyinstaller). Для портативной сборки —
папка ffmpeg/bin рядом (ffmpeg.exe, ffprobe.exe).

Запуск:  python build_release.py
Каталог вывода можно переопределить переменной окружения CINECONVERT_BUILD.
"""
import os
import sys
import shutil
import subprocess
import zipfile

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("CINECONVERT_BUILD", SRC)
WORK = os.path.join(OUT, "build")
DIST = os.path.join(OUT, "dist")
RELEASE = os.path.join(OUT, "release")
NAME = "CineConvert"
EXE = NAME + (".exe" if sys.platform == "win32" else "")
SEP = ";" if sys.platform == "win32" else ":"


def run_pyinstaller():
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--windowed", "--name", NAME,
           "--add-data", f"{os.path.join(SRC, 'locales')}{SEP}locales",
           "--distpath", DIST, "--workpath", WORK, "--specpath", WORK]
    icon = os.path.join(SRC, "app.ico")
    if os.path.exists(icon):
        cmd += ["--icon", icon, "--add-data", f"{icon}{SEP}."]
    cmd.append(os.path.join(SRC, "CineConvert.py"))
    print(">>> PyInstaller\n    " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def assemble():
    exe_path = os.path.join(DIST, EXE)
    if not os.path.exists(exe_path):
        raise SystemExit("Сборка не удалась: exe не найден: " + exe_path)
    if os.path.exists(RELEASE):
        shutil.rmtree(RELEASE)
    os.makedirs(RELEASE, exist_ok=True)

    # 1) standalone exe
    shutil.copy2(exe_path, os.path.join(RELEASE, EXE))

    # 2) portable folder (exe + ffmpeg + locales)
    port = os.path.join(RELEASE, NAME + "-portable")
    os.makedirs(os.path.join(port, "ffmpeg", "bin"), exist_ok=True)
    shutil.copy2(exe_path, os.path.join(port, EXE))
    shutil.copytree(os.path.join(SRC, "locales"), os.path.join(port, "locales"))
    ff_src = os.path.join(SRC, "ffmpeg", "bin")
    for base in ("ffmpeg", "ffprobe"):
        s = os.path.join(ff_src, base + (".exe" if sys.platform == "win32" else ""))
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(port, "ffmpeg", "bin", os.path.basename(s)))
        else:
            print("!!! Внимание: не найден", s, "— портативная сборка без offline-ffmpeg")

    zip_path = os.path.join(RELEASE, NAME + "-portable.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(port):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, RELEASE))

    print("\n>>> Готово:")
    print("   ", os.path.join(RELEASE, EXE),
          f"({os.path.getsize(exe_path) // (1024*1024)} МБ)")
    print("   ", zip_path,
          f"({os.path.getsize(zip_path) // (1024*1024)} МБ)")


if __name__ == "__main__":
    run_pyinstaller()
    assemble()
