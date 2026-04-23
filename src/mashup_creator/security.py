import hashlib
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

try:
    import ctypes
except Exception:
    ctypes = None

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _read_head(path: Path, size: int = 16) -> bytes:
    with path.open("rb") as f:
        return f.read(size)


def _matches_signature(ext: str, head: bytes) -> bool:
    if ext in {".mp4", ".m4v", ".mov"}:
        return b"ftyp" in head
    if ext == ".avi":
        return head.startswith(b"RIFF") and b"AVI" in head
    if ext == ".mkv":
        return head.startswith(b"\x1A\x45\xDF\xA3")
    if ext == ".webm":
        return head.startswith(b"\x1A\x45\xDF\xA3")
    if ext == ".mp3":
        return head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)
    if ext == ".wav":
        return head.startswith(b"RIFF") and b"WAVE" in head
    if ext == ".flac":
        return head.startswith(b"fLaC")
    if ext == ".ogg":
        return head.startswith(b"OggS")
    if ext == ".aac":
        return head[:2] == b"\xFF\xF1" or head[:2] == b"\xFF\xF9"
    if ext == ".m4a":
        return b"ftyp" in head
    return False


def _is_hidden(path: Path) -> bool:
    name = path.name
    if name.startswith("."):
        return True
    if os.name == "nt" and ctypes is not None:
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1:
                return False
            return bool(attrs & 2)
        except Exception:
            return False
    return False


def _hash_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _mime_ok(path: Path, kind: str) -> bool:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        return False
    if kind == "video":
        return mime.startswith("video/")
    if kind == "audio":
        return mime.startswith("audio/")
    return False


def _duration_ok(path: Path, kind: str, min_duration: Optional[float], max_duration: Optional[float]) -> Tuple[bool, str]:
    if min_duration is None and max_duration is None:
        return True, "OK"
    try:
        if kind == "video":
            from moviepy import VideoFileClip
            clip = VideoFileClip(str(path))
        else:
            from moviepy import AudioFileClip
            clip = AudioFileClip(str(path))
        try:
            dur = clip.duration or 0.0
        finally:
            clip.close()
    except Exception:
        return False, "Could not read media duration."
    if min_duration is not None and dur < min_duration:
        return False, f"Duration {dur:.2f}s is below minimum {min_duration:.2f}s."
    if max_duration is not None and dur > max_duration:
        return False, f"Duration {dur:.2f}s exceeds maximum {max_duration:.2f}s."
    return True, "OK"


def validate_media_file(
    path: Path,
    kind: str,
    max_size_mb: int = 2048,
    base_dir: Optional[Path] = None,
    allow_hashes: Optional[set] = None,
    deny_hashes: Optional[set] = None,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
    block_hidden: bool = True,
) -> Tuple[bool, str]:
    if not path.exists():
        return False, "File does not exist."
    if path.is_dir():
        return False, "Path is a directory."
    if path.is_symlink():
        return False, "Symbolic links are not allowed."
    if block_hidden and _is_hidden(path):
        return False, "Hidden files are not allowed."

    if base_dir is not None:
        try:
            if not path.resolve().is_relative_to(base_dir.resolve()):
                return False, "File is outside the allowed base directory."
        except AttributeError:
            # Python < 3.9 fallback
            if str(path.resolve()).startswith(str(base_dir.resolve())) is False:
                return False, "File is outside the allowed base directory."

    ext = path.suffix.lower()
    if kind == "video" and ext not in VIDEO_EXTS:
        return False, f"Unsupported video format: {ext}"
    if kind == "audio" and ext not in AUDIO_EXTS:
        return False, f"Unsupported audio format: {ext}"

    size = path.stat().st_size
    if size <= 0:
        return False, "File is empty."
    if size > max_size_mb * 1024 * 1024:
        return False, f"File is too large (> {max_size_mb} MB)."

    try:
        head = _read_head(path)
    except OSError:
        return False, "File is not readable."

    if not _matches_signature(ext, head):
        return False, "File signature does not match its extension."

    if not _mime_ok(path, kind):
        return False, "File MIME type does not match its extension."

    if allow_hashes or deny_hashes:
        digest = _hash_sha256(path)
        if deny_hashes and digest in deny_hashes:
            return False, "File hash is blocked."
        if allow_hashes and digest not in allow_hashes:
            return False, "File hash is not in allow list."

    ok, msg = _duration_ok(path, kind, min_duration, max_duration)
    if not ok:
        return False, msg

    return True, "OK"


def validate_and_quarantine(
    path: Path,
    kind: str,
    quarantine_dir: Path,
    **kwargs,
) -> Tuple[bool, str]:
    ok, msg = validate_media_file(path, kind, **kwargs)
    if ok:
        return True, msg
    try:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        dest = quarantine_dir / path.name
        if dest.exists():
            dest = quarantine_dir / f"{path.stem}_blocked{path.suffix}"
        shutil.move(str(path), str(dest))
        return False, f"{msg} (moved to quarantine)"
    except Exception:
        return False, msg
