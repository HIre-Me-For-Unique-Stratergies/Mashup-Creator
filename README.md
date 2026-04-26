# Mashup Creator

Mashup Creator is a Windows desktop app that builds punchy 25-second YouTube Shorts
from a selected folder of gameplay videos. It randomly picks five 5-second clips
from five different source videos, picks a built-in song, and places random built-in
SFX hits across the timeline. Output is vertical (720x1280 by default for faster rendering).

## Features
- Folder-based gameplay video source selection
- Fast FFmpeg-based video rendering
- Random built-in song selection
- Random SFX hits per 25-second output
- Auto-create loop (continuous generation)
- Progress/status reporting in-app
- Readable media validation before rendering

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
- FFmpeg from `imageio-ffmpeg` or a system FFmpeg install on PATH

### Optional: Install FFmpeg (Windows)
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
1) Choose a folder that contains at least five gameplay videos. Each source must be at least 5 seconds long.
2) Choose whether to use only that folder or include videos in subfolders.
3) Each output randomly uses five 5-second clips from five different videos in the selected source set.
4) Press Preview 5s for a short smoke test, or Start for a 25s short.
5) Disable Auto create to render only the configured batch count.
6) Enable Auto create to keep rendering until paused or cancelled.
7) Output files appear in `creations/`.

Songs and SFX are treated as built-in app assets. Put them in `library/audio/` and
`library/sfx/` before distributing or running the app; the UI does not let the user
upload or change those components.

## Settings
Advanced Settings include:
- Render preset (Very fast / Ultra fast)
- Output resolution (720x1280 by default, or 1080x1920)
- SFX volume
- Batch size and auto-create behavior
- Gameplay video source folder and subfolder scan mode

Settings are saved in `config/settings.json`.

## Troubleshooting
- App freezes when rendering:
  - This is normal during heavy encoding. Try smaller resolution or fewer videos.
- Output has no audio:
  - Check your audio file formats are supported and not corrupted.
- FFmpeg errors:
  - Run `pip install -r requirements.txt`, or confirm `ffmpeg -version` works in a terminal.

## Build an Executable (Windows)
Install build tools:
```powershell
pip install -r requirements-dev.txt
```

Build:
```powershell
pyinstaller --noconfirm --clean "Mashup Creator.spec"
```

The executable will be at `dist/Mashup Creator.exe`.

## Notes
- If you bundle FFmpeg, ensure your license obligations are met.
- For best speed, keep 720x1280 and Ultra fast enabled.
