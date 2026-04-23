# Mashup Creator

Mashup Creator is a Windows desktop app that builds punchy 25-second YouTube Shorts
from exactly five gameplay source videos. It randomly cuts one short scene from each
source, picks a built-in song, and places random built-in SFX hits across the
timeline. Output is vertical (1080x1920 by default).

## Features
- Five-slot gameplay source manager with add, replace, and remove controls
- Fast FFmpeg-based video rendering
- Random built-in song selection
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
1) Add exactly five gameplay videos. Each source must be 5 minutes to 1 hour long.
2) Use Replace Selected or Remove Selected to manage the five video slots.
3) Press Preview 5s for a short smoke test, or Start for a 25s short.
4) Disable Auto create to render only the configured batch count.
5) Enable Auto create to keep rendering until paused or cancelled.
6) Output files appear in `creations/`.

Songs and SFX are treated as built-in app assets. Put them in `library/audio/` and
`library/sfx/` before distributing or running the app; the UI does not let the user
upload or change those components.

## Settings
Advanced Settings include:
- Render preset (Very fast / Ultra fast)
- Output resolution (1080x1920 or 720x1280)
- SFX volume
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
