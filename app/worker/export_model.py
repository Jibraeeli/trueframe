"""Build the detection model file while the worker image is being built.

Downloads pinned weights, verifies their checksum and converts them to ONNX.
PyTorch is only needed for this step, so it stays out of the final image.
The build fails if the converted model does not match the original.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

import numpy as np
import onnxruntime as ort
import timm
import torch
from safetensors.torch import load_file

REPO = "OwensLab/commfor-model-384"
REVISION = "6076002bf0d9dd37537f965ee2f06f826c333b61"
SHA256 = "b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387"
INPUT_SIZE = 384
MAX_DIFFERENCE = 1e-3


def download(destination: Path) -> None:
    url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/model.safetensors"
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != SHA256:
        raise SystemExit(f"Checksum mismatch for {url}")


def main(output: str) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    weights = target.with_suffix(".safetensors")
    download(weights)

    state = {key.removeprefix("vit."): value for key, value in load_file(weights).items()}
    model = timm.create_model("vit_small_patch16_384", pretrained=False, num_classes=1)
    model.load_state_dict(state)
    model.eval()
    weights.unlink()

    example = torch.randn(2, 3, INPUT_SIZE, INPUT_SIZE)
    torch.onnx.export(
        model,
        (example,),
        target,
        input_names=["pixel_values"],
        output_names=["logits"],
        dynamic_axes={"pixel_values": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )

    with torch.no_grad():
        expected = model(example).numpy()
    session = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
    actual = session.run(None, {"pixel_values": example.numpy()})[0]
    if np.abs(expected - actual).max() > MAX_DIFFERENCE:
        raise SystemExit("Converted model does not match the original")
    print(f"Model saved to {target}")


if __name__ == "__main__":
    main(sys.argv[1])
