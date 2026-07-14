<div align="center">

![CINECONVERT](docs/banner.gif)

# 🎮 CINECONVERT

**Portable FFmpeg-powered video converter for Windows**

*Insert cartridge • Press START • Convert*

![Windows](https://img.shields.io/badge/PLAYER%201-Windows%2010%2F11-3CBCFC?style=flat-square)
![Python](https://img.shields.io/badge/ENGINE-Python%20%2B%20PyQt5-F8B800?style=flat-square)
![FFmpeg](https://img.shields.io/badge/POWER--UP-FFmpeg-F83800?style=flat-square)
![Portable](https://img.shields.io/badge/SAVE-Portable%2C%20no%20install-58D854?style=flat-square)

</div>

---

```
════════════════════════════ STORY ════════════════════════════
```

**CineConvert** is a video converter that works **out of the box**: download it, run it, convert. No installer, no registry, no "please download this other thing first". All settings live in `config.json` right next to the program — carry it on a USB stick.

**FFmpeg** under the hood, a clean interface on top — with a live theme: pick any color with the rainbow slider and the whole app repaints instantly. Light and dark modes included.

<div align="center">

![Main screen](docs/screen-main.png)

</div>

```
═══════════════════════════ POWER-UPS ═══════════════════════════
```

| | Feature | Description |
|---|---|---|
| 🎬 | **Video conversion** | Resolution (4K→144p), codec (x264, x265, NVENC, VP9, AV1), bitrate, container (mp4, mkv, mov, avi, flv, webm) |
| ⚡ | **Smart lossless mode** | If you change nothing, streams are **copied 1:1** with no re-encoding: mp4→mkv in a second with zero quality loss |
| 🎧 | **Audio while converting** | Codec (aac, mp3, flac, opus, ac3), bitrate, channels (mono/stereo/5.1/7.1) or "copy as is" |
| 🎵 | **Audio extraction** | Rip the audio track to mp3, aac, flac, wav, ogg, ac3 |
| 📦 | **Batch processing** | Pick several files (or drag & drop) — they convert one by one |
| 🔍 | **Video info** | Preview frame + 12 key facts at a glance; a "Details" button opens the full breakdown of every stream; with multiple files, page through them with ‹ › |
| 🖥 | **Live theme** | Any color (OKLCH slider + color picker), saturation, light/dark/system, animated waves in the header |
| 🌐 | **7 languages** | en, ru, de, es, fr, zh, ar — translations are plain JSON, easy to add your own |
| 🔄 | **1-click FFmpeg update** | Settings → FFmpeg: checks your version against the latest gyan.dev build and updates atomically (rolls back on failure) |
| 💾 | **Everything auto-saves** | There is no "Save" button — every setting applies and persists instantly, including window size |

```
═══════════════════════════ CONTROLS ═══════════════════════════
```

1. **📂 Pick a video** — the "Browse…" button (multiple files allowed) or drag & drop into the window
2. **⚙ Tune it** — "Video" tab: resolution / codec / bitrate / format + audio options below. Leave everything on "No changes" for an instant lossless remux
3. **▶ Hit "Render"** — the app asks where to save (default folder is configurable), then shows progress, speed and ETA
4. **🏁 Done** — a notification with sound, plus "Open file" / "Open folder" buttons

Audio ripping lives on the **"Audio"** tab: pick a format → "Extract audio".

```
══════════════════════════ SELECT LEVEL ══════════════════════════
                     (which file to download)
```

Grab one of the two builds from [**Releases**](https://github.com/bboyJohnn/CineConvert/releases):

| File | Size | Who it's for |
|---|---|---|
| 🕹 **CineConvert-portable.zip** | ~110 MB | **Recommended.** Unzip → run `CineConvert.exe` → it just works, fully offline. FFmpeg is bundled |
| 🪶 **CineConvert.exe** | ~37 MB | Lightweight. Downloads FFmpeg (~80 MB) by itself on first launch (internet needed once) |

> Nothing to install: no Python, no libraries, no separate FFmpeg. Windows SmartScreen may warn about an unknown publisher — click "More info" → "Run anyway".

```
═══════════════════════════ SCREENSHOTS ═══════════════════════════
```

<div align="center">

| Dark theme | Settings |
|---|---|
| ![Dark theme](docs/screen-dark.png) | ![Settings](docs/screen-settings.png) |

</div>

```
═══════════════════ CARTRIDGE SPECS ═══════════════════
```

- **Single source file** — the whole UI and logic in `CineConvert.py` (~2700 lines, PyQt5/PyQt6-compatible)
- **Theme engine** — colors are computed in OKLCH (like modern CSS) and compiled into Qt stylesheets on the fly
- **Workers** — FFmpeg runs in background threads, the UI never freezes, conversion is cancellable
- **Reliable FFmpeg updates** — download via `.part` with integrity check, the new binary is test-run before an atomic folder swap with backup and rollback
- **Config** — `config.json` next to the exe: theme, language, output folder, last encoding settings, window size
- **Locales** — `locales/*.json`: key = widget objectName or item text; any file with a `"name"` field shows up in the language list automatically

```
════════════════════════ BUILD FROM SOURCE ════════════════════════
                    ↑ ↑ ↓ ↓ ← → ← → B A START
```

```bash
# Player 1 has joined
git clone https://github.com/bboyJohnn/CineConvert.git
cd CineConvert
pip install PyQt5 pyinstaller pillow

# Run from source (FFmpeg auto-downloads on first launch)
python CineConvert.py

# Build the exe + portable zip (output goes to release/)
python build_release.py
```

```
═══════════════════════════ CONTINUE? ═══════════════════════════
```

- 📁 **`old/`** — the previous version of the app (single screen, old design). Kept for history
- 🐛 **Found a bug?** — open an [Issue](https://github.com/bboyJohnn/CineConvert/issues) with the log from the "Logs" tab
- 🧡 Built on [FFmpeg](https://ffmpeg.org/) ([gyan.dev](https://www.gyan.dev/ffmpeg/builds/) builds) and [PyQt5](https://pypi.org/project/PyQt5/)

<div align="center">

```
  GAME OVER? NO — JUST PRESS "RENDER" AGAIN
  © bboyJohnn • CONTINUE ▶
```

</div>
