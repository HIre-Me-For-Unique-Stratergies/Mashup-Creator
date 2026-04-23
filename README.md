# Mashup Creator

Mashup Creator is a Windows desktop app that builds punchy 25-second YouTube Shorts
by randomly cutting multiple source videos, adding a music segment, and placing 10
random SFX hits across the timeline. Output is vertical (1080x1920 by default).

## Features
- Random video mashups with epic motion and start/end fades
- Random audio selection and automatic ducking under SFX
- 10 random SFX hits per 25-second output
- Auto-create loop (continuous generation)
- Progress/status reporting in-app
- Safe file validation before copying into the library

## Folder Structure
```
assets/         App icons and title image
config/         Runtime settings (created/updated by the app)
creations/      Runtime output videos
edit_bank/      Runtime temporary edit files (auto-cleaned)
library/        Runtime media library
  audio/        Music tracks
  sfx/          Sound effects
  video/        Source videos
src/
  mashup_creator/
                Application package
main.py         Launcher
```

## Requirements
- Windows 10/11
- Python 3.10+ (tested with 3.13)
- FFmpeg installed and available on PATH

### Install FFmpeg (Windows)
1) Download from https://ffmpeg.org/download.html
2) Extract and add the `bin` folder to PATH
3) Verify:
```powershell
ffmpeg -version
```

## Install
```powershell
pip install -r requirements.txt
```

## Run
```powershell
python main.py
```

## How to Use
1) Click Upload Video(s), Upload Audio(s), and Upload SFX.
2) Press Preview 5s for a short smoke test, or Start for a 25s short.
3) Disable Auto create to render only the configured batch count.
4) Enable Auto create to keep rendering until paused or cancelled.
5) Output files appear in `creations/`.

## Settings
Advanced Settings include:
- Render preset (Very fast / Ultra fast)
- Output resolution (1080x1920 or 720x1280)
- Max videos per mashup and minimum segment length
- SFX volume and ducking level
- Batch size and auto-create behavior

Settings are saved in `config/settings.json`.

## Troubleshooting
- App freezes when rendering:
  - This is normal during heavy encoding. Try smaller resolution or fewer videos.
- Output has no audio:
  - Check your audio file formats are supported and not corrupted.
- FFmpeg errors:
  - Confirm `ffmpeg -version` works in a terminal.

## Build an Executable (Windows)
Install build tools:
```powershell
pip install -r requirements-dev.txt
```

Build:
```powershell
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name "Mashup Creator" ^
  --paths "src" ^
  --icon "assets/icon.ico" ^
  --add-data "assets;assets" ^
  main.py
```

The executable will be at `dist/Mashup Creator.exe`.

## Notes
- If you bundle FFmpeg, ensure your license obligations are met.
- For best quality, keep 1080x1920 enabled.
