"""Settings read from environment variables.

The same code runs on a laptop and on AWS. Only these values change.
"""

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    bucket: str
    table: str
    queue_url: str
    s3_addressing_style: str = "auto"
    max_upload_mb: int = 200
    max_frames: int = 12

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bucket=_required("SCAN_BUCKET"),
            table=_required("SCAN_TABLE"),
            queue_url=_required("SCAN_QUEUE_URL"),
            s3_addressing_style=os.environ.get("S3_ADDRESSING_STYLE", "auto"),
            max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "200")),
            max_frames=int(os.environ.get("MAX_FRAMES", "12")),
        )
