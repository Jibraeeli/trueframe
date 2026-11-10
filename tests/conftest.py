"""Shared test setup. moto imitates AWS inside the test process."""

import io
import subprocess
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from app.shared.aws import connect
from app.shared.config import Settings

BUCKET = "test-uploads"
TABLE = "test-scans"


class FakeDetector:
    name = "fake"

    def __init__(self, probability: float = 0.9):
        self.probability = probability

    def fake_probability(self, image_path: Path) -> float:
        return self.probability


class FakeScanner:
    """Passes every file unless told to raise an error instead."""

    def __init__(self, error: Exception | None = None):
        self.error = error

    def check(self, path: Path) -> None:
        if self.error:
            raise self.error


@pytest.fixture
def jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.effect_noise((64, 64), 40).convert("RGB").save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "testsrc=duration=4:size=160x120:rate=10",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def stack(monkeypatch):
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    with mock_aws():
        boto3.client("s3").create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-2"}
        )
        queue_url = boto3.client("sqs").create_queue(QueueName="test-scans")["QueueUrl"]
        boto3.client("dynamodb").create_table(
            TableName=TABLE,
            AttributeDefinitions=[{"AttributeName": "scan_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "scan_id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("SCAN_BUCKET", BUCKET)
        monkeypatch.setenv("SCAN_TABLE", TABLE)
        monkeypatch.setenv("SCAN_QUEUE_URL", queue_url)
        monkeypatch.setenv("MAX_UPLOAD_MB", "1")
        settings = Settings.from_env()
        yield connect(settings), settings
