"""The whole journey: upload, queue, worker, report."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.shared import scans
from app.worker.explainer import TemplateExplainer
from app.worker.main import GENERIC_FAILURE, MAX_ATTEMPTS, Worker
from tests.conftest import FakeDetector


class BrokenDetector(FakeDetector):
    def fake_probability(self, image_path):
        raise RuntimeError("model crashed")


@pytest.fixture
def client(stack):
    with TestClient(app) as test_client:
        yield test_client


def make_worker(stack, detector=None) -> Worker:
    aws, settings = stack
    return Worker(aws, settings, detector or FakeDetector(), TemplateExplainer())


def upload(client, content: bytes, name: str = "photo.jpg"):
    return client.post("/api/scans", files={"file": (name, content, "application/octet-stream")})


def queue_size(stack) -> int:
    aws, settings = stack
    attributes = aws.sqs.get_queue_attributes(
        QueueUrl=settings.queue_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return sum(int(value) for value in attributes.values())


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_web_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "TrueFrame" in response.text


def test_upload_to_report(client, stack, jpeg_bytes):
    created = upload(client, jpeg_bytes)
    assert created.status_code == 202
    scan_id = created.json()["scan_id"]
    assert client.get(f"/api/scans/{scan_id}").json()["status"] == "queued"

    assert make_worker(stack).poll_once(wait_seconds=0) == 1

    scan = client.get(f"/api/scans/{scan_id}").json()
    assert scan["status"] == "complete"
    assert scan["filename"] == "photo.jpg"
    assert scan["report"]["trust_score"] == 10
    assert scan["report"]["verdict"] == "likely_manipulated"
    assert scan["report"]["summary"]
    assert queue_size(stack) == 0

    frame = client.get(f"/api/scans/{scan_id}/frames/0")
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"


def test_video_upload_to_report(client, stack, sample_video):
    created = upload(client, sample_video.read_bytes(), "clip.mp4")
    scan_id = created.json()["scan_id"]
    make_worker(stack, FakeDetector(0.1)).poll_once(wait_seconds=0)

    report = client.get(f"/api/scans/{scan_id}").json()["report"]
    assert report["checks"]["detector"]["frames_analysed"] == 12
    assert report["trust_score"] == 90
    assert report["suspicious_frames"] == []


def test_unsupported_file_is_refused(client):
    response = upload(client, b"MZ this is an executable", "photo.jpg")
    assert response.status_code == 415


def test_oversized_file_is_refused(client, jpeg_bytes):
    response = upload(client, jpeg_bytes + b"\0" * (2 * 1024 * 1024))
    assert response.status_code == 413


def test_invalid_scan_id_is_refused(client):
    assert client.get("/api/scans/not-a-valid-id").status_code == 422


def test_unknown_scan_returns_404(client):
    assert client.get("/api/scans/" + "0" * 32).status_code == 404


def test_damaged_file_fails_with_a_message_and_is_not_retried(client, stack):
    scan_id = upload(client, b"\xff\xd8\xff\xe0 damaged").json()["scan_id"]
    make_worker(stack).poll_once(wait_seconds=0)

    scan = client.get(f"/api/scans/{scan_id}").json()
    assert scan["status"] == "failed"
    assert "damaged" in scan["error"]
    assert queue_size(stack) == 0


def _receive(stack) -> dict:
    aws, settings = stack
    return aws.sqs.receive_message(QueueUrl=settings.queue_url, MaxNumberOfMessages=1)["Messages"][0]


def test_unexpected_error_keeps_the_job_for_retry(client, stack, jpeg_bytes):
    scan_id = upload(client, jpeg_bytes).json()["scan_id"]
    make_worker(stack, BrokenDetector()).poll_once(wait_seconds=0)

    assert client.get(f"/api/scans/{scan_id}").json()["status"] == "processing"
    assert queue_size(stack) == 1


def test_final_attempt_marks_the_scan_failed(client, stack, jpeg_bytes):
    scan_id = upload(client, jpeg_bytes).json()["scan_id"]
    message = _receive(stack)
    message["Attributes"] = {"ApproximateReceiveCount": str(MAX_ATTEMPTS)}

    make_worker(stack, BrokenDetector()).handle(message)

    scan = client.get(f"/api/scans/{scan_id}").json()
    assert (scan["status"], scan["error"]) == ("failed", GENERIC_FAILURE)


def test_duplicate_delivery_does_not_redo_finished_work(client, stack, jpeg_bytes):
    aws, _ = stack
    scan_id = upload(client, jpeg_bytes).json()["scan_id"]
    message = _receive(stack)
    scans.mark_complete(aws.table, scan_id, {"trust_score": 77})

    make_worker(stack, BrokenDetector()).handle(message)

    assert client.get(f"/api/scans/{scan_id}").json()["report"] == {"trust_score": 77}
    assert queue_size(stack) == 0


def test_report_is_valid_json_when_stored(client, stack, jpeg_bytes):
    aws, _ = stack
    scan_id = upload(client, jpeg_bytes).json()["scan_id"]
    make_worker(stack).poll_once(wait_seconds=0)
    assert isinstance(json.loads(scans.get(aws.table, scan_id)["report"]), dict)
