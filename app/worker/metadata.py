"""Check 2: what does the file say about how it was made?

Metadata is easy to strip or fake. Finding an AI tool's name is strong
evidence, but finding nothing proves nothing, so a clean result never raises
the score. Editing software is reported but not penalised, because ordinary
photos and videos get edited and re-encoded all the time.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.worker.errors import UnprocessableMedia

Image.MAX_IMAGE_PIXELS = 50_000_000

FFPROBE_TIMEOUT_SECONDS = 30
MAX_VALUE_LENGTH = 200

_AI_TOOLS = {
    "Stable Diffusion": r"stable[\s_-]?diffusion|automatic1111|sdxl",
    "Midjourney": r"midjourney",
    "DALL-E": r"dall[\s·.-]?e",
    "ComfyUI": r"comfyui",
    "InvokeAI": r"invokeai",
    "NovelAI": r"novelai",
    "Adobe Firefly": r"firefly",
    "Leonardo AI": r"leonardo\.ai",
    "FLUX": r"flux\.?1",
    "Sora": r"\bsora\b",
    "Runway": r"runwayml|runway gen",
    "Pika": r"pika labs",
    "Kling": r"\bkling\b",
    "Google Veo": r"\bveo\s?[23]?\b",
    "Synthesia": r"synthesia",
    "HeyGen": r"heygen",
    "DeepFaceLab": r"deepfacelab",
    "FaceSwap": r"face[\s_-]?swap",
    "IPTC AI label": r"trainedalgorithmicmedia",
}

_EDITORS = {
    "Adobe Photoshop": r"photoshop",
    "Adobe Lightroom": r"lightroom",
    "Adobe Premiere": r"premiere",
    "GIMP": r"\bgimp\b",
    "Canva": r"\bcanva\b",
    "CapCut": r"capcut",
    "DaVinci Resolve": r"davinci",
    "Final Cut": r"final cut",
    "HandBrake": r"handbrake",
    "FFmpeg": r"\blavf|\blavc|ffmpeg",
}

_AI_PATTERNS = {name: re.compile(p, re.IGNORECASE) for name, p in _AI_TOOLS.items()}
_EDITOR_PATTERNS = {name: re.compile(p, re.IGNORECASE) for name, p in _EDITORS.items()}

_EXIF_TAGS = {
    0x010E: "description",
    0x010F: "camera_make",
    0x0110: "camera_model",
    0x0131: "software",
    0x0132: "modified",
    0x013B: "artist",
}
_EXIF_IFD_POINTER = 0x8769
_EXIF_DATE_ORIGINAL = 0x9003


@dataclass
class MetadataResult:
    fields: dict[str, str] = field(default_factory=dict)
    ai_tools: list[str] = field(default_factory=list)
    editors: list[str] = field(default_factory=list)


def find_signatures(text: str) -> tuple[list[str], list[str]]:
    """Return the AI tools and editors named anywhere in the text."""
    ai_tools = [name for name, pattern in _AI_PATTERNS.items() if pattern.search(text)]
    editors = [name for name, pattern in _EDITOR_PATTERNS.items() if pattern.search(text)]
    return ai_tools, editors


def _read_image(path: Path) -> tuple[dict[str, str], str]:
    fields: dict[str, str] = {}
    raw: list[str] = []
    try:
        with Image.open(path) as image:
            fields["dimensions"] = f"{image.width}x{image.height}"
            exif = image.getexif()
            for tag, name in _EXIF_TAGS.items():
                if tag in exif:
                    fields[name] = str(exif[tag]).strip()
            original = exif.get_ifd(_EXIF_IFD_POINTER).get(_EXIF_DATE_ORIGINAL)
            if original:
                fields["captured"] = str(original).strip()

            for key, value in image.info.items():
                if isinstance(value, bytes) and key == "xmp":
                    raw.append(value.decode("utf-8", errors="ignore"))
                elif isinstance(value, str):
                    raw.append(f"{key}: {value}")
                    # Stable Diffusion tools save their settings in this field.
                    if key == "parameters" and "Steps:" in value and "Sampler:" in value:
                        raw.append("stable diffusion")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise UnprocessableMedia("This image is damaged or too large to read.") from exc
    return fields, "\n".join(raw)


def probe_video(path: Path) -> dict:
    """Ask ffprobe to describe a video. Only local files may be opened."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-protocol_whitelist", "file",
                "-print_format", "json", "-show_format", "-show_streams", str(path),
            ],
            capture_output=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=True,
        )
        info = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise UnprocessableMedia("This video is damaged or could not be read.") from exc
    if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
        raise UnprocessableMedia("This file does not contain a video track.")
    return info


def _read_video(path: Path) -> tuple[dict[str, str], str]:
    info = probe_video(path)
    video = next(s for s in info["streams"] if s.get("codec_type") == "video")
    fields = {
        "dimensions": f"{video.get('width')}x{video.get('height')}",
        "codec": str(video.get("codec_name")),
    }
    duration = info.get("format", {}).get("duration")
    if duration:
        fields["duration_seconds"] = f"{float(duration):.1f}"

    tags = dict(info.get("format", {}).get("tags", {}))
    tags.update({f"video_{k}": v for k, v in video.get("tags", {}).items()})
    for key, name in (
        ("encoder", "encoder"),
        ("creation_time", "captured"),
        ("com.apple.quicktime.make", "camera_make"),
        ("com.apple.quicktime.model", "camera_model"),
        ("com.apple.quicktime.software", "software"),
    ):
        if key in tags:
            fields[name] = str(tags[key]).strip()
    return fields, "\n".join(f"{k}: {v}" for k, v in tags.items())


def inspect(path: Path, media_type: str) -> MetadataResult:
    fields, raw = _read_image(path) if media_type.startswith("image/") else _read_video(path)
    searchable = "\n".join([*fields.values(), raw])
    ai_tools, editors = find_signatures(searchable)
    trimmed = {key: value[:MAX_VALUE_LENGTH] for key, value in fields.items() if value}
    return MetadataResult(fields=trimmed, ai_tools=ai_tools, editors=editors)
