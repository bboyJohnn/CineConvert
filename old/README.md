# CineConvert (Alfa) - Professional Video Converter

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)
![FFmpeg](https://img.shields.io/badge/Powered-FFmpeg-orange)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-yellow)

A modern, user-friendly video conversion application with powerful batch processing capabilities. Built with Python and PyQt6, CineConvert makes video processing accessible to everyone.

## ✨ Features

### 🎥 Video Conversion
- **Multiple Formats**: Convert between MP4, MKV, MOV, AVI, FLV, WebM
- **Quality Control**: Adjust resolution (4K to 144p), bitrate, and codec settings
- **Codec Support**: H.264, H.265, VP9, AV1, and hardware-accelerated options
- **Smart Scaling**: Maintain aspect ratio with intelligent padding

### 🔊 Audio Processing
- **Audio Extraction**: Extract audio to MP3, AAC, FLAC, WAV, OGG, AC3
- **Audio Conversion**: Convert audio streams with customizable bitrate and channels
- **Multi-track Support**: Handle multiple audio streams in single video

### ⚡ Performance & Usability
- **Batch Processing**: Convert multiple files simultaneously
- **Real-time Progress**: Monitor conversion with detailed progress bars
- **Auto FFmpeg Setup**: Automatic download and configuration of FFmpeg
- **Media Information**: Detailed video/audio stream analysis
- **Video Previews**: Generate thumbnails for quick preview

### 🌍 Internationalization
- **Multi-language UI**: Support for English, Russian, and easily extensible
- **Locale System**: JSON-based translation files for easy customization
- **Portable Design**: Single executable with embedded resources

## 🚀 Quick Start

### Download
1. Go to [Releases page](https://github.com/bboyJohnn/CineConvert/releases/download/video-converter/CineConvert.0.04alf.exe)
2. Download the latest `CineConvert.exe`
3. Run the executable - no installation required!

### System Requirements
- **Windows 10/11** (64-bit)
- 4GB RAM minimum, 8GB recommended
- 500MB free disk space
- Internet connection for first-time FFmpeg setup

### First Run
1. Launch `CineConvert.exe`
2. Application will automatically download FFmpeg (one-time setup)
3. Start converting videos immediately!

## 🖥️ Interface Overview

The application features a tab-based interface:

- **Video Tab**: Main video conversion settings
- **Audio Settings**: Audio stream configuration
- **Audio Extraction**: Extract audio from videos
- **Logs**: Real-time conversion progress
- **Settings**: Preferences and language selection

## 📋 How to Use

### Basic Video Conversion
1. Click **"Browse"** to select input video file
2. Choose output destination
3. Adjust video settings (resolution, codec, bitrate)
4. Click **"Start Video Render"**
5. Monitor progress in real-time

### Batch Processing
1. Click **"Select Multiple Videos"**
2. Choose multiple files for conversion
3. Configure output settings once
4. All files process automatically with progress tracking

### Audio Extraction
1. Load a video file
2. Switch to **"Audio Extraction"** tab
3. Choose output format (MP3, AAC, FLAC, etc.)
4. Click **"Extract Audio"**

## 🎯 Supported Formats

| Category | Formats |
|----------|---------|
| **Video Input** | MP4, MKV, MOV, AVI, FLV, WebM |
| **Video Output** | MP4, MKV, MOV, AVI, FLV, WebM |
| **Audio Output** | MP3, AAC, FLAC, WAV, OGG, AC3 |
| **Video Codecs** | H.264, H.265, VP9, AV1, NVIDIA NVENC |
| **Audio Codecs** | AAC, MP3, FLAC, Opus, AC3 |

