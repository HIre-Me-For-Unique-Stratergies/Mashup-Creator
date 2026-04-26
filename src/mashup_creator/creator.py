import os
import random
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import constants as c
from . import utils


@dataclass
class CreationJob:
    video_paths: List[Path]
    audio_paths: List[Path]
    sfx_paths: List[Path]
    out_file: Path
    render_preset: str
    target_w: int
    target_h: int
    video_bitrate: str
    clip_len: float
    hw_encode: bool
    sfx_volume: float


class Creator:
    def __init__(self, status_cb, progress_cb):
        self.status_cb = status_cb
        self.progress_cb = progress_cb
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancel_event = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._process_lock = threading.Lock()
        self._current_output: Optional[Path] = None

    def pause(self):
        self._pause_event.clear()
        self.status_cb("Paused (will pause before the next render).")

    def resume(self):
        self._pause_event.set()
        self.status_cb("Resumed.")

    def cancel(self):
        self._cancel_event.set()
        self._pause_event.set()
        self._stop_process(force=True)
        self._remove_current_output()
        self.status_cb("Cancelling current render and deleting partial output...")

    def _checkpoint(self):
        while not self._pause_event.is_set():
            if self._cancel_event.is_set():
                raise RuntimeError("Cancelled.")
            time.sleep(0.1)
        if self._cancel_event.is_set():
            raise RuntimeError("Cancelled.")

    def create(self, job: CreationJob) -> None:
        self.progress_cb(0)
        self._current_output = job.out_file
        self.status_cb("Checking FFmpeg...")
        self._checkpoint()

        ffmpeg = utils.ffmpeg_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg was not found. Install FFmpeg or install imageio-ffmpeg.")

        try:
            video_paths = self._validate_video_sources(job.video_paths)
            audio_paths = self._valid_audio_paths(job.audio_paths, "song")
            sfx_paths = self._valid_audio_paths(job.sfx_paths, "SFX")
            audio_path = random.choice(audio_paths)

            self.status_cb("Picking random scenes...")
            segment_lengths = self._segment_lengths(job.clip_len, len(video_paths))
            video_segments = []
            for path, seg_len in zip(video_paths, segment_lengths):
                duration = utils.probe_duration(path)
                if duration is None:
                    raise ValueError(f"Could not read video duration: {path.name}")
                start = utils.random_start(duration, seg_len)
                video_segments.append((path, start, seg_len))
                self.status_cb(f"Scene: {path.name} @ {start:.2f}s for {seg_len:.2f}s")
                self._checkpoint()

            audio_duration = utils.probe_duration(audio_path)
            if audio_duration is None or audio_duration < 1.0:
                raise ValueError(f"Song is too short or invalid: {audio_path.name}")
            audio_start = utils.random_start(audio_duration, job.clip_len)
            self.status_cb(f"Song: {audio_path.name} @ {audio_start:.2f}s")

            sfx_hits = self._pick_sfx_hits(sfx_paths, job.clip_len)
            self.progress_cb(15)
            self._checkpoint()

            self.status_cb("Rendering output with FFmpeg...")
            cmd = self._build_ffmpeg_command(
                ffmpeg=ffmpeg,
                job=job,
                video_segments=video_segments,
                audio_path=audio_path,
                audio_start=audio_start,
                sfx_hits=sfx_hits,
            )
            self._run_ffmpeg(cmd, job.clip_len)

            if self._cancel_event.is_set():
                self._remove_output(job.out_file)
                raise RuntimeError("Cancelled.")

            self.status_cb("Validating output...")
            ok, msg = utils.validate_output(job.out_file, job.clip_len)
            if not ok:
                self._remove_output(job.out_file)
                raise ValueError(msg)

            self.progress_cb(100)
            self.status_cb(f"Done: {job.out_file}")
        finally:
            if self._cancel_event.is_set():
                self._remove_current_output()
            with self._process_lock:
                self._process = None
            self._current_output = None
            for tmp in c.EDIT_BANK_DIR.glob("*"):
                try:
                    if tmp.is_file():
                        tmp.unlink()
                except Exception:
                    pass

    def _validate_video_sources(self, paths: List[Path]) -> List[Path]:
        unique_paths = [p for p in dict.fromkeys(paths) if p.is_file() and p.suffix.lower() in c.VIDEO_EXTS]
        if not unique_paths:
            raise ValueError("No gameplay videos were found in the selected folder.")

        candidates = unique_paths[:]
        random.shuffle(candidates)

        valid_paths = []
        for path in candidates:
            if not utils.is_video_readable(path):
                continue
            duration = utils.probe_duration(path)
            if duration is None:
                continue
            if duration < c.MIN_SOURCE_SECONDS:
                continue
            valid_paths.append(path)
            if len(valid_paths) >= c.MAX_SOURCE_VIDEOS:
                break
        if not valid_paths:
            raise ValueError("The selected folder has no readable videos that are at least 5 seconds long.")
        if len(valid_paths) < c.MAX_SOURCE_VIDEOS:
            raise ValueError(
                f"The selected source set needs at least {c.MAX_SOURCE_VIDEOS} readable videos "
                "so clips are not reused in the same output."
            )
        return valid_paths

    def _valid_audio_paths(self, paths: List[Path], label: str) -> List[Path]:
        valid_paths = [p for p in dict.fromkeys(paths) if p.is_file() and p.suffix.lower() in c.AUDIO_EXTS]
        if not valid_paths:
            raise ValueError(f"No built-in {label} files found.")
        return valid_paths

    def _segment_lengths(self, clip_len: float, count: int) -> List[float]:
        if count <= 0:
            return []
        if count == 1:
            return [clip_len]

        segment_len = clip_len / count
        return [segment_len for _ in range(count)]

    def _pick_sfx_hits(self, sfx_paths: List[Path], clip_len: float):
        hit_count = max(2, int(clip_len * 0.4))
        sfx_bag = sfx_paths[:]
        random.shuffle(sfx_bag)
        hits = []
        for _ in range(hit_count):
            if not sfx_bag:
                sfx_bag = sfx_paths[:]
                random.shuffle(sfx_bag)
            sfx_path = sfx_bag.pop()
            start = random.uniform(0.0, max(0.0, clip_len - 0.25))
            duration = random.uniform(0.25, min(1.4, max(0.25, clip_len - start)))
            hits.append((sfx_path, start, duration))
        return sorted(hits, key=lambda item: item[1])

    def _build_ffmpeg_command(
        self,
        ffmpeg: str,
        job: CreationJob,
        video_segments,
        audio_path: Path,
        audio_start: float,
        sfx_hits,
    ) -> List[str]:
        cmd = [ffmpeg, "-hide_banner", "-v", "error", "-stats_period", "0.5", "-y"]
        for path, start, duration in video_segments:
            cmd.extend(["-ss", f"{start:.3f}", "-t", f"{duration + 0.35:.3f}", "-i", str(path)])

        cmd.extend(["-stream_loop", "-1", "-ss", f"{audio_start:.3f}", "-t", f"{job.clip_len:.3f}", "-i", str(audio_path)])

        for path, _, _ in sfx_hits:
            cmd.extend(["-i", str(path)])

        filter_parts = []
        for idx, (_, _, duration) in enumerate(video_segments):
            filter_parts.append(
                f"[{idx}:v]"
                f"trim=0:{duration:.3f},setpts=PTS-STARTPTS,"
                f"scale={job.target_w}:{job.target_h}:force_original_aspect_ratio=decrease,"
                f"pad={job.target_w}:{job.target_h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1,fps=30,format=yuv420p"
                f"[v{idx}]"
            )

        video_labels = "".join(f"[v{idx}]" for idx in range(len(video_segments)))
        if len(video_segments) == 1:
            filter_parts.append("[v0]null[vcat]")
        else:
            filter_parts.append(f"{video_labels}concat=n={len(video_segments)}:v=1:a=0[vcat]")

        filter_parts.append("[vcat]null[vout]")

        audio_idx = len(video_segments)
        filter_parts.append(
            f"[{audio_idx}:a]atrim=0:{job.clip_len:.3f},asetpts=PTS-STARTPTS,volume=0.82[music]"
        )

        audio_mix_labels = ["[music]"]
        for idx, (_, start, duration) in enumerate(sfx_hits):
            input_idx = len(video_segments) + 1 + idx
            delay_ms = int(start * 1000)
            filter_parts.append(
                f"[{input_idx}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
                f"volume={job.sfx_volume:.3f},adelay={delay_ms}:all=1[sfx{idx}]"
            )
            audio_mix_labels.append(f"[sfx{idx}]")

        filter_parts.append(
            f"{''.join(audio_mix_labels)}"
            f"amix=inputs={len(audio_mix_labels)}:duration=first:dropout_transition=0,"
            f"atrim=0:{job.clip_len:.3f}[aout]"
        )

        codec = "h264_qsv" if job.hw_encode else "libx264"
        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                codec,
            ]
        )
        if codec == "libx264":
            cmd.extend(["-preset", job.render_preset])
        cmd.extend(
            [
                "-b:v",
                job.video_bitrate,
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                str(os.cpu_count() or 4),
                "-progress",
                "pipe:1",
                "-nostats",
                str(job.out_file),
            ]
        )
        return cmd

    def _run_ffmpeg(self, cmd: List[str], clip_len: float) -> None:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
        with self._process_lock:
            self._process = process
        tail = []
        assert process.stdout is not None
        while True:
            line = process.stdout.readline()
            if line:
                text = line.strip()
                if text:
                    tail.append(text)
                    tail = tail[-20:]
                    self._update_render_progress(text, clip_len)

            if self._cancel_event.is_set():
                self._stop_process(force=True)
                self._remove_current_output()
                raise RuntimeError("Cancelled.")

            if line == "" and process.poll() is not None:
                break

        return_code = process.wait()
        if return_code != 0:
            detail = "\n".join(tail[-8:]) or f"ffmpeg exited with code {return_code}."
            raise RuntimeError(detail)

    def _update_render_progress(self, text: str, clip_len: float) -> None:
        if "=" not in text:
            return
        key, value = text.split("=", 1)
        seconds = None
        if key in {"out_time_ms", "out_time_us"}:
            try:
                seconds = int(value) / 1_000_000
            except ValueError:
                return
        elif key == "out_time":
            seconds = self._parse_ffmpeg_time(value)

        if seconds is None or clip_len <= 0:
            return
        pct = 15 + int(min(1.0, max(0.0, seconds / clip_len)) * 83)
        self.progress_cb(min(98, pct))

    def _parse_ffmpeg_time(self, value: str) -> Optional[float]:
        try:
            hours, minutes, seconds = value.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception:
            return None

    def _remove_output(self, path: Path) -> None:
        for _ in range(8):
            if not path.exists():
                return
            try:
                path.unlink()
                return
            except Exception:
                time.sleep(0.15)

    def _remove_current_output(self) -> None:
        if self._current_output is not None:
            self._remove_output(self._current_output)

    def _stop_process(self, force: bool = False) -> None:
        with self._process_lock:
            process = self._process
        if process is None or process.poll() is not None:
            return

        try:
            if os.name == "nt":
                if force:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                else:
                    process.terminate()
            else:
                if force:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
