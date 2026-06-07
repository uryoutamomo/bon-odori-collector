import hashlib
import os
import re
from datetime import datetime, timezone


AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
QUEUE_TABLE_NAME = os.environ.get("DYNAMODB_QUEUE_TABLE", "")


def normalize_candidate_key(name, candidate_type="会場"):
    normalized = re.sub(r"\s+", "", (name or "").strip()).casefold()
    if candidate_type != "会場":
        normalized = f"{candidate_type}\0{normalized}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_venue_key(venue):
    """既存DynamoDBレコードと互換性のある会場キーを返す。"""
    return normalize_candidate_key(venue, "会場")


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
        candidate_type = candidate.get("type") or "会場"
        identity = candidate.get("identity") or candidate["venue"]
        item = {
            "venue_key": normalize_candidate_key(
                identity, candidate_type
            ),
            "identity": identity,
            "venue": candidate["venue"],
            "candidate_type": candidate_type,
            "status": candidate.get("status") or "要裏取り",
            "source": candidate.get("source") or "unknown",
            "priority": candidate.get("priority") or "通常",
            "source_url": candidate.get("url") or "",
            "source_text": (candidate.get("text") or "")[:1900],
            "detected_at": detected_at,
            "updated_at": detected_at,
            "notion_synced": False,
        }
        optional_fields = {
            "account": candidate.get("account"),
            "spoken_at": candidate.get("spoken_at"),
            "tweet_id": candidate.get("tweet_id"),
            "patterns": candidate.get("patterns"),
            "score": candidate.get("score"),
            "score_reasons": candidate.get("score_reasons"),
            "time_hints": candidate.get("time_hints"),
            "place_hints": candidate.get("place_hints"),
            "venue_hints": candidate.get("venue_hints"),
            "song_hints": candidate.get("song_hints"),
            "group_hints": candidate.get("group_hints"),
            "year_signals": candidate.get("year_signals"),
            "estimated_event": candidate.get("estimated_event"),
            "estimated_venue": candidate.get("estimated_venue"),
            "related_key": candidate.get("related_key"),
        }
        item.update({
            key: value for key, value in optional_fields.items()
            if value not in (None, "", [])
        })
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

    def is_notion_synced(self, venue, candidate_type="会場"):
        response = self.table.get_item(
            Key={
                "venue_key": normalize_candidate_key(
                    venue, candidate_type
                )
            },
            ProjectionExpression="notion_synced",
            ConsistentRead=True,
        )
        return bool(response.get("Item", {}).get("notion_synced"))

    def mark_notion_synced(self, venue, candidate_type="会場"):
        now = datetime.now(timezone.utc).isoformat()
        self.table.update_item(
            Key={
                "venue_key": normalize_candidate_key(
                    venue, candidate_type
                )
            },
            UpdateExpression=(
                "SET notion_synced = :synced, updated_at = :updated_at"
            ),
            ExpressionAttributeValues={
                ":synced": True,
                ":updated_at": now,
            },
            ConditionExpression="attribute_exists(venue_key)",
        )

    def update_status(self, venue, status, candidate_type="会場"):
        now = datetime.now(timezone.utc).isoformat()
        self.table.update_item(
            Key={
                "venue_key": normalize_candidate_key(
                    venue, candidate_type
                )
            },
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
