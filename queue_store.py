import hashlib
import os
import re
from datetime import datetime, timezone


AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
QUEUE_TABLE_NAME = os.environ.get("DYNAMODB_QUEUE_TABLE", "")
EVENT_CANDIDATE_QUEUE_TABLE_NAME = os.environ.get("EVENT_CANDIDATE_QUEUE_TABLE", "")


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


class EventCandidateQueueStore:
    def __init__(self, table_name=None, region_name=None, table=None):
        self.table_name = table_name or EVENT_CANDIDATE_QUEUE_TABLE_NAME
        self.region_name = region_name or AWS_REGION
        if table is not None:
            self.table = table
            return
        if not self.table_name:
            raise ValueError("EVENT_CANDIDATE_QUEUE_TABLE is required")
        import boto3

        self.table = boto3.resource(
            "dynamodb", region_name=self.region_name
        ).Table(self.table_name)

    def put_candidate(self, candidate, detected_at=None):
        now = datetime.now(timezone.utc).isoformat()
        detected_at = detected_at or now
        existing = self.table.get_item(
            Key={"candidate_key": candidate["candidate_key"]},
            ConsistentRead=True,
        ).get("Item", {})
        evidence = _merge_evidence(
            existing.get("evidence") or [],
            candidate.get("evidence") or [],
        )
        first_seen = existing.get("first_seen_at") or detected_at
        item = {
            "candidate_key": candidate["candidate_key"],
            "match_key": candidate.get("match_key") or "",
            "match_key_parts": candidate.get("match_key_parts") or [],
            "candidate_type": "event",
            "title": candidate.get("title") or candidate.get("venue") or "",
            "estimated_event": candidate.get("estimated_event") or "",
            "estimated_venue": candidate.get("estimated_venue") or "",
            "estimated_month": candidate.get("estimated_month") or "",
            "estimated_date": candidate.get("estimated_date") or "",
            "hashtags": candidate.get("hashtags") or [],
            "status": existing.get("status") or candidate.get("status") or "未確認",
            "priority": candidate.get("priority") or "通常",
            "confidence_score": candidate.get("confidence_score", 0),
            "score_breakdown": candidate.get("score_breakdown") or [],
            "evidence_count": len(evidence),
            "speaker_count": candidate.get("speaker_count", 0),
            "speakers": candidate.get("speakers") or [],
            "evidence": evidence[:50],
            "notion_synced": bool(existing.get("notion_synced", False)),
            "notion_page_id": existing.get("notion_page_id", ""),
            "promoted_event_page_id": existing.get("promoted_event_page_id", ""),
            "source": candidate.get("source") or "x_event_evidence",
            "first_seen_at": first_seen,
            "last_seen_at": detected_at,
            "updated_at": now,
        }
        item = {
            key: value for key, value in item.items()
            if value not in (None, "")
        }
        self.table.put_item(Item=item)
        return not bool(existing)

    def is_notion_synced(self, candidate_key):
        response = self.table.get_item(
            Key={"candidate_key": candidate_key},
            ProjectionExpression="notion_synced",
            ConsistentRead=True,
        )
        return bool(response.get("Item", {}).get("notion_synced"))

    def mark_notion_synced(self, candidate_key, notion_page_id=None):
        now = datetime.now(timezone.utc).isoformat()
        update = "SET notion_synced = :synced, updated_at = :updated_at"
        values = {
            ":synced": True,
            ":updated_at": now,
        }
        if notion_page_id:
            update += ", notion_page_id = :notion_page_id"
            values[":notion_page_id"] = notion_page_id
        self.table.update_item(
            Key={"candidate_key": candidate_key},
            UpdateExpression=update,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(candidate_key)",
        )

    def update_status(self, candidate_key, status, promoted_event_page_id=None):
        now = datetime.now(timezone.utc).isoformat()
        update = "SET #status = :status, updated_at = :updated_at"
        values = {
            ":status": status,
            ":updated_at": now,
        }
        if promoted_event_page_id:
            update += ", promoted_event_page_id = :promoted_event_page_id"
            values[":promoted_event_page_id"] = promoted_event_page_id
        self.table.update_item(
            Key={"candidate_key": candidate_key},
            UpdateExpression=update,
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(candidate_key)",
        )


def _merge_evidence(existing, incoming):
    by_id = {}
    for item in list(existing or []) + list(incoming or []):
        identity = item.get("identity") or item.get("tweet_id") or item.get("url")
        if identity:
            by_id.setdefault(identity, item)
    return list(by_id.values())


def _is_conditional_check_failure(exc):
    response = getattr(exc, "response", {})
    code = response.get("Error", {}).get("Code")
    return code == "ConditionalCheckFailedException"
