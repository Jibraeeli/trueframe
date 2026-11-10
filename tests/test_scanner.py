"""Runs the real ClamAV daemon against a harmless test file."""

from pathlib import Path

import pytest

from app.worker.errors import UnprocessableMedia
from app.worker.scanner import MALWARE_MESSAGE, ClamdScanner

# EICAR is the industry's standard harmless test file. It is split up so that
# antivirus tools do not flag this source file.
EICAR = (
    r"X5O!P%@AP[4\PZX54(P^)7CC)7}$"
    + r"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$"
    + r"H+H*"
).encode()


@pytest.fixture(scope="module")
def scanner():
    daemon = ClamdScanner()
    daemon.start()
    yield daemon
    daemon.stop()


def test_clean_file_passes(scanner, tmp_path: Path, jpeg_bytes: bytes):
    path = tmp_path / "clean.jpg"
    path.write_bytes(jpeg_bytes)
    scanner.check(path)


def test_malware_is_flagged(scanner, tmp_path: Path):
    path = tmp_path / "upload"
    path.write_bytes(EICAR)
    with pytest.raises(UnprocessableMedia, match=MALWARE_MESSAGE):
        scanner.check(path)
