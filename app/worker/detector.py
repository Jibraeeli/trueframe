"""Check 3: run an AI-generated image detector on a picture.

The model outputs one raw number. A sigmoid turns it into a probability that
the image is fake. The image must be prepared exactly as the model's authors
did, because a model only works on inputs that look like its training data.
"""

from pathlib import Path
from typing import Protocol

import numpy as np
import onnxruntime as ort
from PIL import Image

RESIZE_SHORT_SIDE = 440
CROP_SIZE = 384
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
MODEL_NAME = "Community Forensics ViT-S 384"


class Detector(Protocol):
    name: str

    def fake_probability(self, image_path: Path) -> float: ...


def preprocess(image: Image.Image) -> np.ndarray:
    """Resize the short side, cut out the centre, then normalise the colours."""
    rgb = image.convert("RGB")
    scale = RESIZE_SHORT_SIDE / min(rgb.size)
    width, height = round(rgb.width * scale), round(rgb.height * scale)
    resized = rgb.resize((width, height), Image.Resampling.BILINEAR)

    left, top = (width - CROP_SIZE) // 2, (height - CROP_SIZE) // 2
    cropped = resized.crop((left, top, left + CROP_SIZE, top + CROP_SIZE))

    pixels = np.asarray(cropped, dtype=np.float32) / 255.0
    normalised = (pixels - MEAN) / STD
    # The model expects (batch, colour channels, height, width).
    return np.expand_dims(normalised.transpose(2, 0, 1), axis=0).astype(np.float32)


def sigmoid(value: float) -> float:
    return float(1.0 / (1.0 + np.exp(-value)))


class OnnxDetector:
    name = MODEL_NAME

    def __init__(self, model_path: str):
        self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name

    def fake_probability(self, image_path: Path) -> float:
        with Image.open(image_path) as image:
            batch = preprocess(image)
        logit = self._session.run(None, {self._input_name: batch})[0][0][0]
        return sigmoid(float(logit))
