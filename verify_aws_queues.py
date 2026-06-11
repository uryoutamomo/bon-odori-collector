import os
import sys

import boto3
from botocore.exceptions import ClientError


AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")


def verify_table(client, resource, table_name, key_name):
    if not table_name:
        raise RuntimeError(f"{key_name.upper()} table name is empty")

    description = client.describe_table(TableName=table_name)["Table"]
    status = description.get("TableStatus")
    item_count = description.get("ItemCount")
    print(f"[verify-aws-queue] {table_name}: status={status} item_count={item_count}")
    if status != "ACTIVE":
        raise RuntimeError(f"{table_name} is not ACTIVE: {status}")

    table = resource.Table(table_name)
    key = {key_name: "__codex_verify_nonexistent__"}
    table.get_item(Key=key, ConsistentRead=True)
    print(f"[verify-aws-queue] {table_name}: get_item_ok key={key_name}")

    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET verify_checked_at = :checked_at",
            ExpressionAttributeValues={":checked_at": "nonwriting-permission-check"},
            ConditionExpression=f"attribute_exists({key_name})",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code != "ConditionalCheckFailedException":
            raise
        print(f"[verify-aws-queue] {table_name}: update_item_permission_ok key={key_name}")
    else:
        raise RuntimeError(
            f"{table_name} unexpected verification item exists: {key[key_name]}"
        )


def verify_event_candidate_query(resource, table_name):
    if not table_name:
        return
    table = resource.Table(table_name)
    response = table.query(
        IndexName="status-updated_at-index",
        KeyConditionExpression="#status = :status",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "未確認"},
        Select="COUNT",
    )
    count = int(response.get("Count") or 0)
    print(f"[verify-aws-queue] {table_name}: query_status_unconfirmed_count={count}")
    if count <= 0:
        raise RuntimeError(f"{table_name} has no unconfirmed event candidates")

    sample = table.query(
        IndexName="status-updated_at-index",
        KeyConditionExpression="#status = :status",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "未確認"},
        ProjectionExpression="candidate_key, title, confidence_score, evidence_count, speaker_count",
        Limit=3,
        ScanIndexForward=False,
    )
    for item in sample.get("Items", []):
        print(
            "[verify-aws-queue] event_candidate_sample "
            f"score={item.get('confidence_score')} "
            f"evidence={item.get('evidence_count')} "
            f"speakers={item.get('speaker_count')} "
            f"title={item.get('title')} "
            f"key={item.get('candidate_key')}"
        )


def main():
    client = boto3.client("dynamodb", region_name=AWS_REGION)
    resource = boto3.resource("dynamodb", region_name=AWS_REGION)
    verify_table(
        client,
        resource,
        os.environ.get("DYNAMODB_QUEUE_TABLE", ""),
        "venue_key",
    )
    verify_table(
        client,
        resource,
        os.environ.get("EVENT_CANDIDATE_QUEUE_TABLE", ""),
        "candidate_key",
    )
    verify_event_candidate_query(
        resource,
        os.environ.get("EVENT_CANDIDATE_QUEUE_TABLE", ""),
    )
    print("[verify-aws-queue] ok")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[verify-aws-queue] failed: {exc}", file=sys.stderr)
        raise
