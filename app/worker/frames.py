"""Turn an upload into a small set of still images for the detector."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from app.worker.errors import UnprocessableMedia
from app.worker.metadata import probe_video

FFMPEG_TIMEOUT_SECONDS = 60
JPEG_QUALITY = 95


@dataclass(frozen=True)
class Frame:
    path: Path
    timestamp: float | None


def sample_times(duration: float, count: int) -> list[float]:
    """Spread samples evenly, using the middle of each equal slice of the video."""
    return [round((i + 0.5) * duration / count, 3) for i in range(count)]


def _from_image(source: Path, output_dir: Path) -> list[Frame]:
    target = output_dir / "frame-0.jpg"
    try:
        with Image.open(source) as image:
            ImageOps.exif_transpose(image).convert("RGB").save(
                target, "JPEG", quality=JPEG_QUALITY
            )
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise UnprocessableMedia("This image is damaged or too large to read.") from exc
    return [Frame(target, None)]


def _grab(source: Path, timestamp: float, target: Path) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-nostdin", "-y",
                "-protocol_whitelist", "file",
                "-ss", str(timestamp), "-i", str(source),
                "-frames:v", "1", "-q:v", "2", str(target),
            ],
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.SubprocessError:
        return False
    return target.exists() and target.stat().st_size > 0


def _from_video(source: Path, output_dir: Path, max_frames: int) -> list[Frame]:
    info = probe_video(source)
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        duration = 0.0
    times = sample_times(duration, max_frames) if duration > 0 else [0.0]

    frames = []
    for index, timestamp in enumerate(times):
        target = output_dir / f"frame-{index}.jpg"
        if _grab(source, timestamp, target):
            frames.append(Frame(target, timestamp))
    if not frames:
        raise UnprocessableMedia("No frames could be read from this video.")
    return frames


def extract(source: Path, media_type: str, output_dir: Path, max_frames: int) -> list[Frame]:
    if media_type.startswith("image/"):
        return _from_image(source, output_dir)
    return _from_video(source, output_dir, max_frames)
