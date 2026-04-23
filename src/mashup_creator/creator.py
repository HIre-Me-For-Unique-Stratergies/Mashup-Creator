import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips
from moviepy.video.fx.FadeIn import FadeIn
from moviepy.video.fx.FadeOut import FadeOut
from moviepy.video.fx.Loop import Loop
from moviepy.audio.fx.AudioLoop import AudioLoop
from moviepy.audio.fx.AudioNormalize import AudioNormalize
from moviepy.audio.fx.MultiplyVolume import MultiplyVolume

from . import constants as c
from . import utils


@dataclass
class CreationJob:
    video_paths: List[Path]
    audio_path: Path
    sfx_paths: List[Path]
    out_file: Path
    equal_lengths: bool
    render_preset: str
    target_w: int
    target_h: int
    video_bitrate: str
    order_mode: str
    max_videos: int
    min_seg: float
    sfx_volume: float
    duck_volume: float
    clip_len: float
    hw_encode: bool
    epic_mode: bool


class Creator:
    def __init__(self, status_cb, progress_cb):
        self.status_cb = status_cb
        self.progress_cb = progress_cb
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancel_event = threading.Event()

    def pause(self):
        self._pause_event.clear()
        self.status_cb("Paused (will pause between steps).")

    def resume(self):
        self._pause_event.set()
        self.status_cb("Resumed.")

    def cancel(self):
        self._cancel_event.set()
        self._pause_event.set()
        self.status_cb("Cancel requested (will stop as soon as possible).")

    def _checkpoint(self):
        while not self._pause_event.is_set():
            if self._cancel_event.is_set():
                raise RuntimeError("Cancelled.")
            time.sleep(0.1)
        if self._cancel_event.is_set():
            raise RuntimeError("Cancelled.")

    def create(self, job: CreationJob) -> None:
        self.progress_cb(0)
        self.status_cb("Loading media...")
        self._checkpoint()

        clip_len = job.clip_len
        fade_dur = 0.5
        target_w = job.target_w
        target_h = job.target_h
        video_bitrate = job.video_bitrate
        min_seg = max(0.5, job.min_seg)
        max_videos = max(1, job.max_videos)
        order_mode = job.order_mode
        sfx_volume = max(0.5, job.sfx_volume)
        duck_volume = min(1.0, max(0.2, job.duck_volume))
        codec = "h264_qsv" if job.hw_encode else "libx264"

        segments = []
        video_clips = []
        sfx_sources = []
        stitched_v = None
        epic_v = None
        final_v = None
        a = None
        final = None

        try:
            video_paths = list(job.video_paths)
            if not video_paths:
                raise ValueError("No video files selected.")

            if order_mode == "random":
                random.shuffle(video_paths)

            if len(video_paths) > max_videos:
                self.status_cb(f"Using first {max_videos} video(s) based on settings.")
                video_paths = video_paths[:max_videos]

            if len(video_paths) * min_seg > clip_len:
                max_count = max(1, int(clip_len // min_seg))
                self.status_cb(f"Too many videos selected; using first {max_count}.")
                video_paths = video_paths[:max_count]

            self.status_cb(f"Loading {len(video_paths)} video source(s)...")
            self._checkpoint()

            valid_paths = [p for p in video_paths if utils.is_video_readable(p)]
            for p in video_paths:
                if p not in valid_paths:
                    self.status_cb(f"Skipped unreadable video: {p.name}")
            if not valid_paths:
                raise ValueError("No usable videos found.")

            if job.equal_lengths:
                seg_len = clip_len / len(valid_paths)
                seg_lengths = [seg_len] * len(valid_paths)
            else:
                weights = [random.random() for _ in valid_paths]
                total = sum(weights) or 1.0
                seg_lengths = [max(min_seg, clip_len * w / total) for w in weights]
                total = sum(seg_lengths)
                seg_lengths = [d * (clip_len / total) for d in seg_lengths]
                seg_lengths[-1] = clip_len - sum(seg_lengths[:-1])

            for path, seg_len in zip(valid_paths, seg_lengths):
                v = VideoFileClip(str(path))
                video_clips.append(v)
                if v.duration < 1.0:
                    raise ValueError(f"Video is too short or invalid: {path.name}")
                start_v = utils.random_start(v.duration, seg_len)
                self.status_cb(f"Selected video segment start: {path.name} @ {start_v:.2f}s")
                self._checkpoint()
                seg = v.subclipped(start_v, min(start_v + seg_len, v.duration)).without_audio()
                if seg.duration < seg_len:
                    seg = seg.with_effects([Loop(duration=seg_len)])
                else:
                    seg = seg.subclipped(0, seg_len)
                segments.append(seg)

            stitched_v = concatenate_videoclips(segments, method="compose")
            stitched_v = utils.fit_to_vertical(stitched_v, target_w=target_w, target_h=target_h)

            if job.epic_mode:
                epic_v = utils.add_epic_motion(stitched_v, target_w=target_w, target_h=target_h)
            else:
                epic_v = stitched_v

            final_v = epic_v.with_effects([FadeIn(fade_dur), FadeOut(fade_dur)])
            self.progress_cb(25)
            self._checkpoint()

            self.status_cb("Selecting random audio segment...")
            a = AudioFileClip(str(job.audio_path))
            if a.duration < 1.0:
                raise ValueError("Audio is too short or invalid.")
            start_a = utils.random_start(a.duration, clip_len)
            self.status_cb(f"Selected audio segment start: {start_a:.2f}s")
            self._checkpoint()

            base_a = a.subclipped(start_a, min(start_a + clip_len, a.duration))
            if base_a.duration < clip_len:
                base_a = base_a.with_effects([AudioLoop(duration=clip_len)])
            else:
                base_a = base_a.subclipped(0, clip_len)
            base_a = base_a.with_effects([AudioNormalize()])

            self.progress_cb(45)
            self._checkpoint()

            self.status_cb("Adding random SFX hits...")
            sfx_paths = [
                p for p in dict.fromkeys(job.sfx_paths)
                if p.is_file() and p.suffix.lower() in c.AUDIO_EXTS
            ]
            if not sfx_paths:
                raise ValueError("No SFX files found in the library.")

            hit_count = 10 if clip_len >= 1.0 else 1
            hit_times = sorted(random.uniform(0.0, max(0.0, clip_len - 0.2)) for _ in range(hit_count))
            sfx_hits = []
            duck_effects = []
            for t0 in hit_times:
                max_len = min(2.0, clip_len - t0)
                if max_len <= 0.05:
                    continue
                sfx_path = random.choice(sfx_paths)
                sfx = AudioFileClip(str(sfx_path))
                sfx_sources.append(sfx)
                sfx_clip = sfx.subclipped(0, min(sfx.duration, max_len)).with_start(t0)
                sfx_hits.append(sfx_clip.with_effects([MultiplyVolume(sfx_volume)]))
                duck_effects.append(MultiplyVolume(duck_volume, start_time=t0, end_time=t0 + max_len))

            if duck_effects:
                base_a = base_a.with_effects(duck_effects)
            mixed_audio = CompositeAudioClip([base_a] + sfx_hits).with_duration(clip_len)

            self.progress_cb(65)
            self._checkpoint()

            self.status_cb("Rendering output (this is the longest step)...")
            self.progress_cb(75)

            final = final_v.with_audio(mixed_audio).with_duration(clip_len)

            final.write_videofile(
                str(job.out_file),
                codec=codec,
                audio_codec="aac",
                audio_bitrate="192k",
                bitrate=video_bitrate,
                fps=30,
                threads=os.cpu_count() or 4,
                preset=job.render_preset,
                temp_audiofile_path=str(c.EDIT_BANK_DIR),
                ffmpeg_params=["-movflags", "faststart"],
                pixel_format="yuv420p",
                logger=None,
            )

            if self._cancel_event.is_set():
                if job.out_file.exists():
                    try:
                        job.out_file.unlink()
                    except Exception:
                        pass
                raise RuntimeError("Cancelled.")

            self.status_cb("Validating output...")
            ok, msg = utils.validate_output(job.out_file, clip_len)
            if not ok:
                if job.out_file.exists():
                    try:
                        job.out_file.unlink()
                    except Exception:
                        pass
                raise ValueError(msg)

            self.progress_cb(100)
            self.status_cb(f"Done: {job.out_file}")
        finally:
            try:
                if final is not None:
                    final.close()
                if final_v is not None:
                    final_v.close()
                if epic_v is not None and epic_v is not stitched_v:
                    epic_v.close()
                if stitched_v is not None:
                    stitched_v.close()
                for seg in segments:
                    seg.close()
                for v in video_clips:
                    v.close()
                for sfx in sfx_sources:
                    sfx.close()
                if a is not None:
                    a.close()
                if self._cancel_event.is_set() and job.out_file.exists():
                    try:
                        job.out_file.unlink()
                    except Exception:
                        pass
                for tmp in c.EDIT_BANK_DIR.glob("*"):
                    try:
                        if tmp.is_file():
                            tmp.unlink()
                    except Exception:
                        pass
            except Exception:
                pass
