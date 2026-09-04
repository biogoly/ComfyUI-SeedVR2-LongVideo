import os
import math
import shutil
import subprocess
from pathlib import Path

import torch
import folder_paths

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpg", ".mpeg"}


def _input_videos():
    root = Path(folder_paths.get_input_directory())
    items = []
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                try:
                    items.append(p.relative_to(root).as_posix())
                except ValueError:
                    items.append(str(p))
    return sorted(items)


def _resolve_input_video(video):
    p = Path(video)
    if not p.is_absolute():
        p = Path(folder_paths.get_input_directory()) / p
    return p.resolve()


def _probe_video(path):
    # OpenCV is already a VideoHelperSuite dependency and reports the same nominal
    # CFR-style FPS that VHS normally uses when force_rate=0.
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frames = int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        cap.release()
        if not math.isfinite(fps) or fps <= 0:
            raise RuntimeError("Video FPS could not be determined")
        duration = frames / fps if frames > 0 else 0.0
        return fps, frames, duration
    except Exception as cv_err:
        # Fallback to ffprobe if OpenCV is unavailable/broken.
        ffprobe = shutil.which("ffprobe")
        if ffprobe is None:
            raise RuntimeError(f"Video probe failed via OpenCV ({cv_err}) and ffprobe is unavailable")
        cmd = [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate,nb_frames,duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)
        ]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip().splitlines()
        if len(out) < 3:
            raise RuntimeError(f"ffprobe returned incomplete metadata for {path}")
        rate = out[0].strip()
        if "/" in rate:
            a, b = rate.split("/", 1)
            fps = float(a) / float(b)
        else:
            fps = float(rate)
        frames = int(out[1]) if out[1].strip().isdigit() else 0
        duration = float(out[2]) if out[2].strip() not in ("N/A", "") else (frames / fps if frames else 0.0)
        if frames <= 0 and duration > 0:
            frames = int(round(duration * fps))
        return fps, frames, duration


def _batch_requeue_index(meta_batch, prompt):
    """Read VHS's requeue counter from the BatchManager prompt node when possible."""
    if prompt is None or meta_batch is None:
        return 0
    uid = getattr(meta_batch, "unique_id", None)
    if uid is None:
        return 0
    for key in (uid, str(uid)):
        try:
            return int(prompt[key]["inputs"].get("requeue", 0))
        except Exception:
            pass
    return 0


class SeedVR2LongVideoInput:
    """Select a Comfy input video and derive the nearest 4n+1 VHS MetaBatch size from seconds."""

    @classmethod
    def INPUT_TYPES(cls):
        videos = _input_videos()
        if not videos:
            videos = [""]
        return {
            "required": {
                "video": (videos,),
                "chunk_seconds": ("FLOAT", {"default": 2.0, "min": 0.20, "max": 60.0, "step": 0.05}),
                "overlap_frames": ("INT", {"default": 8, "min": 0, "max": 128, "step": 4}),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "INT", "FLOAT", "INT", "INT")
    RETURN_NAMES = ("source_path", "fps", "source_frames", "duration", "frames_per_batch", "overlap_frames")
    FUNCTION = "probe"
    CATEGORY = "SeedVR2/Long Video"

    def probe(self, video, chunk_seconds, overlap_frames):
        path = _resolve_input_video(video)
        if not path.exists():
            raise FileNotFoundError(f"Input video not found: {path}")
        fps, total_frames, duration = _probe_video(path)

        # Choose the nearest SeedVR2-friendly 4n+1 frame count to the requested duration.
        # This keeps chunk_seconds intuitive while preserving SeedVR2's temporal shape.
        target = max(5.0, fps * float(chunk_seconds))
        n = max(1, int(math.floor(((target - 1.0) / 4.0) + 0.5)))
        frames_per_batch = 4 * n + 1

        # Outer overlap must be a multiple of four so prepending it keeps 4n+1 valid.
        overlap_frames = max(0, (int(overlap_frames) // 4) * 4)
        # Prevent pathological overlap; normally 8 with 49-61 frame chunks is ideal.
        max_overlap = max(0, ((frames_per_batch // 2) // 4) * 4)
        overlap_frames = min(overlap_frames, max_overlap)

        print(
            f"[SeedVR2 Long Video] {path.name}: {fps:.6g} fps, {total_frames} frames, "
            f"{duration:.3f}s | MetaBatch={frames_per_batch} new frames, overlap={overlap_frames}"
        )
        return (str(path), fps, total_frames, duration, frames_per_batch, overlap_frames)

    @classmethod
    def IS_CHANGED(cls, video, chunk_seconds, overlap_frames):
        try:
            p = _resolve_input_video(video)
            s = p.stat()
            return f"{p}:{s.st_mtime_ns}:{s.st_size}:{chunk_seconds}:{overlap_frames}"
        except Exception:
            return float("nan")


class SeedVR2BatchOverlapIn:
    """
    Prepend source frames deferred from the previous MetaBatch, then pad only the
    final partial model window to the next 4n+1 count. State lives on the VHS
    BatchManager object and is reset on a fresh (requeue=0) run.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "meta_batch": ("VHS_BatchManager",),
                "overlap_frames": ("INT", {"default": 8, "min": 0, "max": 128, "step": 4}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("images_with_context", "valid_frame_count")
    FUNCTION = "apply"
    CATEGORY = "SeedVR2/Long Video"

    def apply(self, images, meta_batch, overlap_frames, unique_id=None, prompt=None):
        k = max(0, int(overlap_frames))
        requeue = _batch_requeue_index(meta_batch, prompt)

        if not hasattr(meta_batch, "_seedvr2_lv_state"):
            meta_batch._seedvr2_lv_state = {}
        state = meta_batch._seedvr2_lv_state
        key = str(unique_id)

        # Fresh manual queue or a restarted/aborted run: never reuse stale carry frames.
        if requeue == 0:
            state.pop(key, None)

        carry = state.get(key)
        current = images
        if carry is not None and k > 0:
            carry = carry.to(device=current.device, dtype=current.dtype)
            combined = torch.cat((carry, current), dim=0)
        else:
            combined = current

        valid_count = int(combined.shape[0])
        if valid_count <= 0:
            raise RuntimeError("SeedVR2 overlap node received an empty image batch")

        # Store only unpadded current source frames for the next pass.
        if k > 0:
            take = min(k, int(current.shape[0]))
            state[key] = current[-take:].detach().cpu().clone()
        else:
            state[key] = None

        # SeedVR2's temporal VAE is happiest with 4n+1 pixel frames. Regular batches
        # already satisfy this (and +8 overlap preserves it); pad only irregular tails.
        pad = (1 - valid_count) % 4
        if pad:
            tail = combined[-1:].expand(pad, *combined.shape[1:])
            combined = torch.cat((combined, tail), dim=0)

        # No future invocation needs the carry after the loader has hit EOF.
        if getattr(meta_batch, "has_closed_inputs", False):
            state[key] = None

        return (combined, valid_count)


class SeedVR2BatchOverlapOut:
    """
    For non-final batches, withhold the last K processed frames. They are regenerated
    on the next pass after the matching source frames are prepended, so the version
    written to disk has temporal context from the following batch. On the final pass,
    emit everything real and remove any internal 4n+1 padding.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "valid_frame_count": ("INT", {"default": 1, "min": 1, "max": 1_000_000}),
                "meta_batch": ("VHS_BatchManager",),
                "overlap_frames": ("INT", {"default": 8, "min": 0, "max": 128, "step": 4}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("frames_to_write",)
    FUNCTION = "apply"
    CATEGORY = "SeedVR2/Long Video"

    def apply(self, images, valid_frame_count, meta_batch, overlap_frames):
        valid_count = min(int(valid_frame_count), int(images.shape[0]))
        real = images[:valid_count]
        k = max(0, int(overlap_frames))
        final = bool(getattr(meta_batch, "has_closed_inputs", False))

        if final or k == 0:
            return (real,)

        if real.shape[0] <= k:
            # Should not occur with the Input node's overlap clamp, but never emit zero frames.
            return (real[:1],)
        return (real[:-k],)


class SeedVR2RemuxOriginalAudio:
    """Mux the untouched source audio streams onto VHS's completed video without re-encoding video."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "processed_video": ("VHS_FILENAMES",),
                "source_video": ("STRING", {"default": ""}),
                "filename_prefix": ("STRING", {"default": "video/Upscaled_seedVR2_final"}),
                "container": (["mkv", "mp4", "same"], {"default": "mkv"}),
                "audio_mode": (["copy", "aac_320k"], {"default": "copy"}),
                "delete_intermediate": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("final_video",)
    FUNCTION = "remux"
    OUTPUT_NODE = True
    CATEGORY = "SeedVR2/Long Video"

    @staticmethod
    def _ffmpeg():
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
        raise RuntimeError("ffmpeg was not found. Install ffmpeg or imageio-ffmpeg.")

    @staticmethod
    def _next_output(prefix, ext):
        output_root = Path(folder_paths.get_output_directory())
        rel = Path(prefix)
        folder = output_root / rel.parent
        folder.mkdir(parents=True, exist_ok=True)
        stem = rel.name or "Upscaled_seedVR2_final"
        candidate = folder / f"{stem}.{ext}"
        if not candidate.exists():
            return candidate
        i = 1
        while True:
            candidate = folder / f"{stem}_{i:05d}.{ext}"
            if not candidate.exists():
                return candidate
            i += 1

    def remux(self, processed_video, source_video, filename_prefix, container, audio_mode, delete_intermediate):
        # During MetaBatch's unfinished requeues VHS intentionally returns an empty file list.
        try:
            _, files = processed_video
        except Exception:
            files = []
        files = list(files or [])
        if not files:
            return ("",)

        candidates = [Path(f) for f in files if Path(f).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}]
        if not candidates:
            return ("",)
        video_in = candidates[-1]
        source = Path(source_video)
        if not source.exists():
            raise FileNotFoundError(f"Original source video not found for audio remux: {source}")

        ext = video_in.suffix.lstrip(".").lower() if container == "same" else container
        if ext == "mov" and container == "same":
            ext = "mov"
        out = self._next_output(filename_prefix, ext)
        ffmpeg = self._ffmpeg()

        def build(audio_copy=True):
            cmd = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video_in), "-i", str(source),
                "-map", "0:v:0", "-map", "1:a?",
                "-c:v", "copy",
            ]
            if audio_copy:
                cmd += ["-c:a", "copy"]
            else:
                cmd += ["-c:a", "aac", "-b:a", "320k"]
            cmd += ["-map_metadata", "0", "-map_chapters", "1", str(out)]
            return cmd

        want_copy = audio_mode == "copy"
        try:
            subprocess.run(build(want_copy), check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            # MP4 in particular may reject Opus/PCM/etc. Preserve video bit-for-bit and
            # only fall back to high-bitrate AAC when stream-copy is container-incompatible.
            if want_copy and ext == "mp4":
                subprocess.run(build(False), check=True, capture_output=True)
            else:
                err = e.stderr.decode(errors="replace") if e.stderr else str(e)
                raise RuntimeError(f"Audio remux failed: {err}")

        if delete_intermediate:
            for f in files:
                p = Path(f)
                try:
                    # VHS output is intentionally temp in the supplied workflow.
                    if p.exists() and p.resolve() != out.resolve():
                        p.unlink()
                except Exception:
                    pass

        print(f"[SeedVR2 Long Video] Final muxed video: {out}")
        return (str(out),)


NODE_CLASS_MAPPINGS = {
    "SeedVR2LongVideoInput": SeedVR2LongVideoInput,
    "SeedVR2BatchOverlapIn": SeedVR2BatchOverlapIn,
    "SeedVR2BatchOverlapOut": SeedVR2BatchOverlapOut,
    "SeedVR2RemuxOriginalAudio": SeedVR2RemuxOriginalAudio,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SeedVR2LongVideoInput": "SeedVR2 Long Video Input / Chunk Control",
    "SeedVR2BatchOverlapIn": "SeedVR2 MetaBatch Context Overlap (In)",
    "SeedVR2BatchOverlapOut": "SeedVR2 MetaBatch Context Overlap (Out)",
    "SeedVR2RemuxOriginalAudio": "SeedVR2 Restore Original Audio (Stream Copy)",
}
