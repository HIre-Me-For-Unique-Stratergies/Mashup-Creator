import json
import os
import random
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def list_files(folder: Path, exts: set) -> List[Path]:
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts])


def safe_copy_into_library(src: Path, dest_folder: Path) -> Path:
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest = dest_folder / src.name
    if dest.exists():
        stem = src.stem
        ext = src.suffix
        dest = dest_folder / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
    shutil.copy2(src, dest)
    return dest


def open_in_file_explorer(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f"open {str(path)!r}")
        else:
            os.system(f"xdg-open {str(path)!r}")
    except Exception:
        pass


def random_start(duration: float, clip_len: float) -> float:
    if duration <= clip_len:
        return 0.0
    return random.uniform(0.0, duration - clip_len)


def fit_to_vertical(clip, target_w: int = 1080, target_h: int = 1920):
    from moviepy.video.fx.Resize import Resize
    from moviepy.video.fx.Crop import Crop

    scale = max(target_w / clip.w, target_h / clip.h)
    resized = clip.with_effects([Resize(scale)])
    return resized.with_effects(
        [Crop(x_center=resized.w / 2, y_center=resized.h / 2, width=target_w, height=target_h)]
    )


def add_epic_motion(clip, target_w: int, target_h: int, segment_len: float = 5.0, max_zoom: float = 0.08):
    from moviepy import concatenate_videoclips
    from moviepy.video.fx.Resize import Resize
    from moviepy.video.fx.Crop import Crop

    if clip.duration is None or clip.duration <= 0:
        return clip
    segments = []
    t = 0.0
    while t < clip.duration - 0.01:
        end = min(t + segment_len, clip.duration)
        seg = clip.subclipped(t, end)
        scale = 1.02 + random.random() * max_zoom
        zoomed = seg.with_effects([Resize(scale)])
        max_dx = max(0.0, (zoomed.w - target_w) / 2)
        max_dy = max(0.0, (zoomed.h - target_h) / 2)
        dx = random.uniform(-max_dx, max_dx) if max_dx > 1 else 0.0
        dy = random.uniform(-max_dy, max_dy) if max_dy > 1 else 0.0
        zoomed = zoomed.with_effects(
            [Crop(x_center=zoomed.w / 2 + dx, y_center=zoomed.h / 2 + dy, width=target_w, height=target_h)]
        )
        segments.append(zoomed)
        t = end
    return concatenate_videoclips(segments, method="compose")


def ffmpeg_tool(name: str) -> Optional[str]:
    return shutil.which(name)


def probe_media(path: Path) -> Dict:
    ffprobe = ffmpeg_tool("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe was not found on PATH.")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration:stream=codec_type",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "Could not read media metadata.").strip()
        raise RuntimeError(msg)
    return json.loads(result.stdout or "{}")


def probe_duration(path: Path) -> Optional[float]:
    data = probe_media(path)
    duration = data.get("format", {}).get("duration")
    if duration is None:
        return None
    try:
        return float(duration)
    except (TypeError, ValueError):
        return None


def probe_has_stream(path: Path, codec_type: str) -> bool:
    data = probe_media(path)
    return any(stream.get("codec_type") == codec_type for stream in data.get("streams", []))


def is_video_readable(path: Path) -> bool:
    try:
        duration = probe_duration(path)
        return duration is not None and duration > 0 and probe_has_stream(path, "video")
    except Exception:
        return False


def validate_output(path: Path, expected_len: float) -> Tuple[bool, str]:
    if not path.exists():
        return False, "Output file was not created."
    if path.stat().st_size < 1024 * 50:
        return False, "Output file is too small."
    try:
        duration = probe_duration(path)
        if duration is None:
            return False, "Output duration is unknown."
        if abs(duration - expected_len) > 0.35:
            return False, f"Output duration {duration:.2f}s is not close to {expected_len:.2f}s."
        if not probe_has_stream(path, "audio"):
            return False, "Output has no audio track."
    except Exception as e:
        return False, f"Output validation failed: {e}"
    return True, "OK"
