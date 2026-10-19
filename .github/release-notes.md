```
=== LEVEL 3 ===
```
A new look, a file list with per-file settings, smarter encoding — and builds for **Windows, Linux and macOS** that run out of the box. FFmpeg is already inside: nothing to install.

## ⬇ What to download

| System | File | How to run |
|---|---|---|
| 🪟 **Windows 10/11** | **CineConvert-portable.zip** — recommended | Unzip → run `CineConvert.exe`. Works offline, FFmpeg bundled |
| 🪟 Windows (light) | CineConvert.exe | Run it — downloads FFmpeg by itself on first launch (internet needed once) |
| 🐧 **Linux x86_64** | **CineConvert-linux-x86_64.tar.gz** | Extract → run `CineConvert/CineConvert`. Ubuntu 22.04+, Debian 12+, Fedora 36+ and similar |
| 🍎 **macOS, Apple Silicon (M1–M4)** | **CineConvert-macos-apple-silicon.dmg** | Open → drag *CineConvert* into *Applications* |
| 🍎 macOS, Intel | CineConvert-macos-intel.dmg | Same as above |

### First launch
- **Windows**: SmartScreen may warn about an unknown publisher — click **More info → Run anyway**.
- **macOS**: the app is not notarized by Apple, so the first launch is blocked. Open **System Settings → Privacy & Security** and click **Open Anyway** (or right-click the app → **Open** on older macOS). Alternatively, in Terminal: `xattr -dr com.apple.quarantine /Applications/CineConvert.app`.
- **Linux**: if the file manager does not start it, run `./CineConvert` from a terminal in the extracted folder.

## ✨ POWER-UPS in v3.0
- 🗂 **File list**: every video gets a card with a preview, characteristics and quick format / resolution / codec / bitrate controls for that file only
- 🔬 **Settings window**: all render settings on one page — format, quality and exact CRF/CQ, resolution, codec, bitrate, speed, audio
- 🎛 **Common settings** for every file + **"Set up selected"** for a group; changes show on the cards at once, Cancel undoes them
- 🎧 **Audio extraction per file**: format, bitrate, channels, **audio track**, fragment (start/end), sample rate, loudness normalization (EBU R128), Opus
- 🎚 **Quality presets** modelled on HandBrake (CRF/CQ per encoder): smaller files with no visible loss
- ⚡ **Smart lossless remux**, hardware encoders (NVIDIA / Intel QSV / AMD) tested before use, orientation-aware scaling
- 🎨 New interface: sidebar, Inter font, Lucide icons, live theme in any color, light/dark — the **waves in the header** are still here
- 🌐 7 languages · ⌨ shortcuts · 🔄 1-click FFmpeg update on every system
