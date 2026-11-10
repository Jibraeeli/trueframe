"""Malware check: runs before any parser touches an upload.

ClamAV keeps its signature database in memory, so it runs as a small daemon
beside the worker. Loading the database for every file would add many seconds
to each scan. If the daemon cannot give an answer, the scan fails and is
retried, because an unchecked file must never reach ffmpeg or the model.

Containers have no internet route, so signatures cannot update while running.
They are built into the image and are as fresh as the last deployment.
"""

import logging
import subprocess
from pathlib import Path
from typing import Protocol

from app.worker.errors import UnprocessableMedia

log = logging.getLogger("trueframe.scanner")

CONFIG = Path(__file__).with_name("clamd.conf")
SCAN_TIMEOUT_SECONDS = 180
PING_ATTEMPTS = 60
PING_INTERVAL_SECONDS = 2

# Exit codes documented by clamdscan.
CLEAN = 0
INFECTED = 1

MALWARE_MESSAGE = "This file was flagged as malware, so it was not analysed."


class ScannerUnavailable(RuntimeError):
    """The scan gave no answer, which is different from a clean result."""


class Scanner(Protocol):
    def check(self, path: Path) -> None: ...


class ClamdScanner:
    def __init__(self) -> None:
        self._daemon: subprocess.Popen | None = None

    def start(self) -> None:
        """Start the daemon and wait until its database has loaded."""
        self._daemon = subprocess.Popen(["clamd", "--config-file", str(CONFIG)])
        result = subprocess.run(
            [
                "clamdscan",
                "--config-file",
                str(CONFIG),
                f"--ping={PING_ATTEMPTS}:{PING_INTERVAL_SECONDS}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != CLEAN:
            raise ScannerUnavailable(f"clamd did not start: {result.stderr.strip()}")
        log.info("Malware scanner ready")

    def stop(self) -> None:
        if self._daemon is not None:
            self._daemon.terminate()

    def check(self, path: Path) -> None:
        """Raise UnprocessableMedia if the file is flagged."""
        try:
            result = subprocess.run(
                [
                    "clamdscan",
                    "--config-file",
                    str(CONFIG),
                    "--fdpass",
                    "--no-summary",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=SCAN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScannerUnavailable("The malware scan timed out.") from exc

        if result.returncode == INFECTED:
            log.warning("Malware found: %s", result.stdout.strip())
            raise UnprocessableMedia(MALWARE_MESSAGE)
        if result.returncode != CLEAN:
            raise ScannerUnavailable(f"The malware scan failed: {result.stderr.strip()}")
