import sys
from pathlib import Path

APP_NAME = "Mashup Creator"


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        cwd = Path.cwd().resolve()
        if (cwd / "library").exists():
            return cwd
        return exe_dir
    return Path(__file__).resolve().parents[2]


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets"
    return _base_dir() / "assets"


BASE_DIR = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
THUMB_DIR = CONFIG_DIR / "thumbnails"
ASSETS_DIR = _assets_dir()
ICON_ICO_PATH = ASSETS_DIR / "icon.ico"
ICON_PATH = ASSETS_DIR / "icon.png"
TITLE_IMAGE_PATH = ASSETS_DIR / "title.png"
LIB_DIR = BASE_DIR / "library"
VIDEO_DIR = LIB_DIR / "video"
AUDIO_DIR = LIB_DIR / "audio"
SFX_DIR = LIB_DIR / "sfx"
OUTPUTS_DIR = BASE_DIR / "creations"
EDIT_BANK_DIR = BASE_DIR / "edit_bank"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

MAX_SOURCE_VIDEOS = 5
MIN_SOURCE_SECONDS = 5

DIRS = [CONFIG_DIR, THUMB_DIR, VIDEO_DIR, AUDIO_DIR, SFX_DIR, OUTPUTS_DIR, EDIT_BANK_DIR]
