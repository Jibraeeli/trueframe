"""The worker: take jobs off the queue and run the analysis.

A message stays hidden on the queue while it is being worked on and is only
deleted after success. If the worker crashes, the message reappears and another
worker retries it. That is why a killed worker never loses a scan.
"""

import json
import logging
import os
import signal
import tempfile
import time
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from app.shared import scans
from app.shared.aws import Aws, connect
from app.shared.config import Settings
from app.worker.detector import Detector, OnnxDetector
from app.worker.errors import UnprocessableMedia
from app.worker.explainer import Explainer, TemplateExplainer
from app.worker.pipeline import analyse
from app.worker.scanner import ClamdScanner, Scanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("trueframe.worker")

# Matches maxReceiveCount on the queue, after which SQS moves the message aside.
MAX_ATTEMPTS = 3
POLL_SECONDS = 20
RETRY_DELAY_SECONDS = 5
GENERIC_FAILURE = "Something went wrong while analysing this file."


class Worker:
    def __init__(
        self,
        aws: Aws,
        settings: Settings,
        detector: Detector,
        explainer: Explainer,
        scanner: Scanner,
    ):
        self.aws = aws
        self.settings = settings
        self.detector = detector
        self.explainer = explainer
        self.scanner = scanner
        self.stopping = False

    def request_stop(self, *_: object) -> None:
        """Finish the current job, then exit. ECS sends this signal when scaling in."""
        self.stopping = True

    def _delete(self, message: dict) -> None:
        self.aws.sqs.delete_message(
            QueueUrl=self.settings.queue_url, ReceiptHandle=message["ReceiptHandle"]
        )

    def _process(self, job: dict) -> None:
        scan_id = job["scan_id"]
        scans.mark_processing(self.aws.table, scan_id)
        with tempfile.TemporaryDirectory(prefix="scan-") as tmp:
            workdir = Path(tmp)
            source = workdir / "source"
            self.aws.s3.download_file(self.settings.bucket, job["s3_key"], str(source))
            self.scanner.check(source)
            analysis = analyse(
                source,
                job["media_type"],
                workdir,
                self.detector,
                self.explainer,
                self.settings.max_frames,
            )
            for index, path in analysis.suspicious_frames.items():
                self.aws.s3.upload_file(
                    str(path),
                    self.settings.bucket,
                    f"frames/{scan_id}/{index}.jpg",
                    ExtraArgs={"ContentType": "image/jpeg"},
                )
        scans.mark_complete(self.aws.table, scan_id, analysis.report)
        log.info("Scan %s complete, trust score %s", scan_id, analysis.report["trust_score"])

    def handle(self, message: dict) -> None:
        attempt = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        scan_id = None
        try:
            job = json.loads(message["Body"])
            scan_id = job["scan_id"]
            scan = scans.get(self.aws.table, scan_id)
            # Queues can deliver a message twice, so finished work is skipped.
            if scan is None or scan["status"] in (scans.COMPLETE, scans.FAILED):
                self._delete(message)
                return
            self._process(job)
        except UnprocessableMedia as exc:
            log.warning("Scan %s rejected: %s", scan_id, exc)
            scans.mark_failed(self.aws.table, scan_id, str(exc))
        except Exception:
            # Leave the message alone. It reappears on the queue for a retry.
            log.exception("Scan %s failed on attempt %s", scan_id, attempt)
            if scan_id and attempt >= MAX_ATTEMPTS:
                scans.mark_failed(self.aws.table, scan_id, GENERIC_FAILURE)
            return
        self._delete(message)

    def poll_once(self, wait_seconds: int = POLL_SECONDS) -> int:
        response = self.aws.sqs.receive_message(
            QueueUrl=self.settings.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=wait_seconds,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        for message in messages:
            self.handle(message)
        return len(messages)

    def run(self) -> None:
        log.info("Worker started, waiting for jobs")
        while not self.stopping:
            try:
                self.poll_once()
            except (BotoCoreError, ClientError):
                log.exception("Could not reach the queue, retrying")
                time.sleep(RETRY_DELAY_SECONDS)
        log.info("Worker stopped cleanly")


def main() -> None:
    settings = Settings.from_env()
    scanner = ClamdScanner()
    scanner.start()
    worker = Worker(
        connect(settings),
        settings,
        OnnxDetector(os.environ["MODEL_PATH"]),
        TemplateExplainer(),
        scanner,
    )
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)
    try:
        worker.run()
    finally:
        scanner.stop()


if __name__ == "__main__":
    main()
