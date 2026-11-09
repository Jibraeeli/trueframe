"""Reading and writing scan records in DynamoDB.

A scan moves through: queued -> processing -> complete (or failed).
The report is stored as JSON text because DynamoDB does not accept Python
floats, and nothing ever needs to query inside a report.
"""

import json
import time
from typing import Any

QUEUED = "queued"
PROCESSING = "processing"
COMPLETE = "complete"
FAILED = "failed"

RETENTION_SECONDS = 24 * 60 * 60


def create(table: Any, scan_id: str, filename: str, media_type: str, s3_key: str) -> None:
    now = int(time.time())
    table.put_item(
        Item={
            "scan_id": scan_id,
            "status": QUEUED,
            "filename": filename[:200],
            "media_type": media_type,
            "s3_key": s3_key,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + RETENTION_SECONDS,
        }
    )


def get(table: Any, scan_id: str) -> dict | None:
    return table.get_item(Key={"scan_id": scan_id}, ConsistentRead=True).get("Item")


def _update(table: Any, scan_id: str, status: str, **fields: Any) -> None:
    fields = {"status": status, "updated_at": int(time.time()), **fields}
    table.update_item(
        Key={"scan_id": scan_id},
        UpdateExpression="SET " + ", ".join(f"#{key} = :{key}" for key in fields),
        ExpressionAttributeNames={f"#{key}": key for key in fields},
        ExpressionAttributeValues={f":{key}": value for key, value in fields.items()},
    )


def mark_processing(table: Any, scan_id: str) -> None:
    _update(table, scan_id, PROCESSING)


def mark_complete(table: Any, scan_id: str, report: dict) -> None:
    _update(table, scan_id, COMPLETE, report=json.dumps(report))


def mark_failed(table: Any, scan_id: str, error: str) -> None:
    _update(table, scan_id, FAILED, error=error)
