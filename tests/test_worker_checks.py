"""Tests that run the real tools: Pillow, ffmpeg, C2PA and the actual model."""

import os
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.worker import frames, metadata, provenance
from app.worker.detector import OnnxDetector, preprocess
from app.worker.errors import UnprocessableMedia


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("Software: Stable Diffusion 3", "Stable Diffusion"),
        ("made with DALL-E 3", "DALL-E"),
        ("Midjourney v6", "Midjourney"),
        ("x:DigitalSourceType trainedAlgorithmicMedia", "IPTC AI label"),
    ],
)
def test_ai_tools_are_recognised(text, tool):
    assert tool in metadata.find_signatures(text)[0]


@pytest.mark.parametrize("text", ["Canon EOS R5", "Sorawit's camera", "Vero Beach", "kindling"])
def test_ordinary_text_is_not_flagged(text):
    assert metadata.find_signatures(text)[0] == []


def test_stable_diffusion_settings_in_png_are_flagged(tmp_path: Path):
    info = PngInfo()
    info.add_text("parameters", "a cat\nSteps: 20, Sampler: Euler a, CFG scale: 7")
    path = tmp_path / "image"
    Image.new("RGB", (16, 16)).save(path, "PNG", pnginfo=info)
    assert metadata.inspect(path, "image/png").ai_tools == ["Stable Diffusion"]


def test_damaged_image_is_rejected_with_a_clear_error(tmp_path: Path):
    path = tmp_path / "image"
    path.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    with pytest.raises(UnprocessableMedia):
        metadata.inspect(path, "image/jpeg")


def test_video_metadata_is_read(sample_video: Path):
    result = metadata.inspect(sample_video, "video/mp4")
    assert result.fields["dimensions"] == "160x120"
    assert result.fields["duration_seconds"] == "4.0"


def test_sample_times_are_spread_through_the_video():
    assert frames.sample_times(12.0, 3) == [2.0, 6.0, 10.0]


def test_frames_are_extracted_from_video(sample_video: Path, tmp_path: Path):
    output = tmp_path / "out"
    output.mkdir()
    result = frames.extract(sample_video, "video/mp4", output, max_frames=4)
    assert len(result) == 4
    assert [f.timestamp for f in result] == [0.5, 1.5, 2.5, 3.5]
    assert all(f.path.stat().st_size > 0 for f in result)


def test_unsigned_file_has_no_credentials(tmp_path: Path):
    path = tmp_path / "image"
    Image.new("RGB", (32, 32)).save(path, "JPEG")
    assert provenance.check(path, "image/jpeg").status == provenance.NONE


def _manifest(source_type: str) -> dict:
    action = {"action": "c2pa.created", "digitalSourceType": source_type}
    return {
        "active_manifest": "m",
        "manifests": {
            "m": {
                "signature_info": {"issuer": "Example"},
                "assertions": [{"label": "c2pa.actions.v2", "data": {"actions": [action]}}],
            }
        },
    }


AI_SOURCE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
CAMERA_SOURCE = "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture"


def test_credentials_declaring_ai_are_detected():
    assert provenance.summarise("Valid", _manifest(AI_SOURCE)).ai_generated is True


def test_camera_credentials_are_not_flagged():
    assert provenance.summarise("Valid", _manifest(CAMERA_SOURCE)).ai_generated is False


def test_valid_signature_without_trust_list_is_only_untrusted():
    assert provenance.summarise("Valid", _manifest(CAMERA_SOURCE)).status == provenance.SIGNED_UNTRUSTED


def test_ai_claim_in_tampered_credentials_is_ignored():
    result = provenance.summarise("Invalid", _manifest(AI_SOURCE))
    assert (result.status, result.ai_generated) == (provenance.INVALID, False)


def test_preprocess_matches_what_the_model_expects():
    batch = preprocess(Image.new("RGB", (500, 300), (255, 0, 127)))
    assert batch.shape == (1, 3, 384, 384)
    assert batch[0, 0, 0, 0] == pytest.approx((1.0 - 0.485) / 0.229, abs=1e-4)
    assert batch[0, 1, 0, 0] == pytest.approx((0.0 - 0.456) / 0.224, abs=1e-4)


def test_real_model_returns_a_probability(tmp_path: Path):
    path = tmp_path / "noise.jpg"
    Image.effect_noise((256, 256), 60).convert("RGB").save(path)
    probability = OnnxDetector(os.environ["MODEL_PATH"]).fake_probability(path)
    assert 0.0 <= probability <= 1.0
