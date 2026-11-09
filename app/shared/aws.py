"""Connections to S3, SQS and DynamoDB.

boto3 reads AWS_ENDPOINT_URL by itself. Locally that points at LocalStack.
On real AWS the variable is simply not set, so this file does not change.
"""

from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config

from app.shared.config import Settings


@dataclass(frozen=True)
class Aws:
    s3: Any
    sqs: Any
    table: Any


def connect(settings: Settings) -> Aws:
    session = boto3.session.Session()
    return Aws(
        s3=session.client(
            "s3", config=Config(s3={"addressing_style": settings.s3_addressing_style})
        ),
        sqs=session.client("sqs"),
        table=session.resource("dynamodb").Table(settings.table),
    )
