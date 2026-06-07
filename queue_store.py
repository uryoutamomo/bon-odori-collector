import hashlib
import os
import re
from datetime import datetime, timezone


AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
QUEUE_TABLE_NAME = os.environ.get("DYNAMODB_QUEUE_TABLE", "")


def normalize_venue_key(venue):
    normalized = re.sub(r"\s+", "", (venue or "").strip()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class DynamoQueueStore:
    def __init__(self, table_name=None, region_name=None, table=None):
        self.table_name = table_name or QUEUE_TABLE_NAME
        self.region_name = region_name or AWS_REGION
        if table is not None:
            self.table = table
            return
        if not self.table_name:
            raise ValueError("DYNAMODB_QUEUE_TABLE is required")
        import boto3

        self.table = boto3.resource(
            "dynamodb", region_name=self.region_name
        ).Table(self.table_name)

    def add_candidate(self, candidate, detected_at=None):
        detected_at = detected_at or datetime.now(timezone.utc).isoformat()
        item = {
            "venue_key": normalize_venue_key(candidate["venue"]),
            "venue": candidate["venue"],
            "status": "要裏取り",
            "source": candidate.get("source") or "unknown",
            "priority": candidate.get("priority") or "通常",
            "source_url": candidate.get("url") or "",
            "source_text": (candidate.get("text") or "")[:1900],
            "detected_at": detected_at,
            "updated_at": detected_at,
            "notion_synced": False,
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(venue_key)",
            )
            return True
        except Exception as exc:
            if _is_conditional_check_failure(exc):
                return False
            raise

    def is_notion_synced(self, venue):
        response = self.table.get_item(
            Key={"venue_key": normalize_venue_key(venue)},
            ProjectionExpression="notion_synced",
            ConsistentRead=True,
        )
        return bool(response.get("Item", {}).get("notion_synced"))

    def mark_notion_synced(self, venue):
        now = datetime.now(timezone.utc).isoformat()
        self.table.update_item(
            Key={"venue_key": normalize_venue_key(venue)},
            UpdateExpression=(
                "SET notion_synced = :synced, updated_at = :updated_at"
            ),
            ExpressionAttributeValues={
                ":synced": True,
                ":updated_at": now,
            },
            ConditionExpression="attribute_exists(venue_key)",
        )

    def update_status(self, venue, status):
        now = datetime.now(timezone.utc).isoformat()
        self.table.update_item(
            Key={"venue_key": normalize_venue_key(venue)},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":updated_at": now,
            },
            ConditionExpression="attribute_exists(venue_key)",
        )


def _is_conditional_check_failure(exc):
    response = getattr(exc, "response", {})
    code = response.get("Error", {}).get("Code")
    return code == "ConditionalCheckFailedException"
