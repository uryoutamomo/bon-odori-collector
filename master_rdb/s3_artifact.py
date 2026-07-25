"""Fetch and publish the master SQLite database as an S3 artifact.

SQLite is still opened as a local file. S3 is the authoritative artifact store:
fetch downloads the latest artifact before work, and publish uploads a verified
snapshot plus the latest copy after work.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from review_inbox import inbox_schema_version

from .master_db import (
    MASTER_DB,
    MASTER_MANIFEST,
    connect_existing,
    file_sha256,
    refresh_manifest_database_state,
    table_counts,
)


DEFAULT_PREFIX = "master-rdb"
DB_NAME = "bon_odori_master.sqlite"
MANIFEST_NAME = "bon_odori_master_manifest.json"
INBOX_SCHEMA_MANIFEST_KEY = "review_inbox_schema_version"


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_prefix(prefix):
    return str(prefix or DEFAULT_PREFIX).strip("/")


def artifact_keys(prefix, snapshot_id=None):
    prefix = clean_prefix(prefix)
    keys = {
        "latest_database_key": f"{prefix}/latest/{DB_NAME}",
        "latest_manifest_key": f"{prefix}/latest/{MANIFEST_NAME}",
    }
    if snapshot_id:
        keys.update(
            {
                "snapshot_database_key": f"{prefix}/snapshots/{snapshot_id}/{DB_NAME}",
                "snapshot_manifest_key": f"{prefix}/snapshots/{snapshot_id}/{MANIFEST_NAME}",
            }
        )
    return keys


def require_bucket(value):
    bucket = value or os.environ.get("MASTER_DB_S3_BUCKET")
    if not bucket:
        raise SystemExit("MASTER_DB_S3_BUCKET is required")
    return bucket


def config_from_env(args):
    bucket = require_bucket(args.bucket)
    prefix = clean_prefix(args.prefix or os.environ.get("MASTER_DB_S3_PREFIX") or DEFAULT_PREFIX)
    return bucket, prefix


def s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise SystemExit("boto3 is required for S3 artifact operations; install requirements.txt") from exc
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION") or None)


def is_not_found_error(exc):
    response = getattr(exc, "response", {}) or {}
    code = response.get("Error", {}).get("Code")
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


def load_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def head_object(client, bucket, key):
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if is_not_found_error(exc):
            return None
        raise


def remote_manifest(client, bucket, key):
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if is_not_found_error(exc):
            return None
        raise
    body = response["Body"].read().decode("utf-8")
    return json.loads(body)


def atomic_replace(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def download_file(client, bucket, key, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(destination))


def upload_file(client, source, bucket, key, content_type):
    client.upload_file(
        str(source),
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def database_summary(db_path):
    with connect_existing(db_path) as conn:
        return table_counts(conn)


def local_inbox_schema_version(db_path):
    """review_inbox_items のスキーマ版を読むだけ。作成も移行も一切しない。

    テーブルが無い場合は監査(master_rdb/audit.py)と同じく 1 を返す。
    v2 前提の dual-write から見れば「使えない」ことに違いはなく、
    退行ガードとしても安全側（新しいリモートを上書きさせない）に倒れる。
    """
    if not Path(db_path).exists():
        return None
    with connect_existing(db_path) as conn:
        return inbox_schema_version(conn, ensure_schema=False)


def enforce_inbox_schema_not_downgraded(local_version, remote, force):
    """スキーマ退行したDBが latest を上書きするのを止める。

    publish の既存ガードは「新しい成果を上書きしない」ためのチェックサム照合
    (CAS)だけで、スキーマの中身を見ていない。そのため 2026-07-24 に v1 系統の
    DB が本番を上書きし、v2 を要求する dual-write が 5 日間毎日失敗した。
    監査では翌日に気づけるようになったので、ここで publish 自体を止める。
    """
    remote_version = (remote or {}).get(INBOX_SCHEMA_MANIFEST_KEY)
    if remote_version is None:
        # このガードより前に publish された manifest にはキーが無い。
        # 比較できないので通すが、黙って通したことは残す。
        # 次の publish 以降は必ずキーが載るので、これは移行期間だけの分岐。
        print(
            f"notice: remote manifest has no {INBOX_SCHEMA_MANIFEST_KEY}; "
            f"skipping downgrade check (local={local_version})"
        )
        return
    if local_version is None or local_version >= remote_version:
        return
    message = (
        "review inbox schema downgrade blocked: "
        f"local={local_version} remote={remote_version}. "
        "Publishing this database would break the scheduled dual-write "
        '("review inbox schema v2 is required"). '
        "Run the migrate-review-inbox-v2 workflow on this database first, "
        "or pass --force if the downgrade is intended."
    )
    if force:
        print(f"warning: {message}")
        return
    raise SystemExit(message)


def manifest_with_artifact(db_path, manifest_path, bucket, prefix, keys, snapshot_id, published_at):
    manifest = refresh_manifest_database_state(db_path, manifest_path, updated_at=published_at)
    # refresh_manifest_database_state 側では書けない。master_db が review_inbox を
    # import すると循環参照になるため、publish 経路のここで載せる。
    manifest[INBOX_SCHEMA_MANIFEST_KEY] = local_inbox_schema_version(db_path)
    manifest["artifact"] = {
        "storage": "s3",
        "bucket": bucket,
        "prefix": prefix,
        "snapshot_id": snapshot_id,
        "latest_database_key": keys["latest_database_key"],
        "latest_manifest_key": keys["latest_manifest_key"],
        "snapshot_database_key": keys["snapshot_database_key"],
        "snapshot_manifest_key": keys["snapshot_manifest_key"],
        "published_at": published_at,
        "local_database_path": str(db_path),
    }
    write_json(manifest_path, manifest)
    return manifest


def verify_checksum(path, expected):
    actual = file_sha256(path)
    if actual != expected:
        raise SystemExit(f"checksum mismatch for {path}: expected={expected} actual={actual}")
    return actual


def fetch(args, client=None):
    bucket, prefix = config_from_env(args)
    keys = artifact_keys(prefix)
    db_path = Path(args.db)
    manifest_path = Path(args.manifest)
    client = client or s3_client()
    manifest = remote_manifest(client, bucket, keys["latest_manifest_key"])
    if not manifest:
        raise SystemExit(f"remote manifest not found: s3://{bucket}/{keys['latest_manifest_key']}")
    if db_path.exists() and not args.overwrite:
        raise SystemExit(f"{db_path} already exists; use --overwrite to replace it")

    expected = manifest.get("database_checksum")
    if not expected:
        raise SystemExit("remote manifest is missing database_checksum")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / DB_NAME
        download_file(client, bucket, keys["latest_database_key"], tmp_db)
        verify_checksum(tmp_db, expected)
        atomic_replace(tmp_db, db_path)

    manifest["artifact_fetch"] = {
        "fetched_at": now_iso(),
        "source": f"s3://{bucket}/{keys['latest_database_key']}",
        "local_database_path": str(db_path),
    }
    write_json(manifest_path, manifest)
    print(f"fetched master db: s3://{bucket}/{keys['latest_database_key']} -> {db_path}")
    return {"database_checksum": expected, "database": str(db_path), "manifest": str(manifest_path)}


def publish(args, client=None):
    bucket, prefix = config_from_env(args)
    db_path = Path(args.db)
    manifest_path = Path(args.manifest)
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")
    client = client or s3_client()
    snapshot_id = args.snapshot_id or now_stamp()
    keys = artifact_keys(prefix, snapshot_id=snapshot_id)

    remote = remote_manifest(client, bucket, keys["latest_manifest_key"])
    if remote:
        enforce_inbox_schema_not_downgraded(
            local_inbox_schema_version(db_path), remote, args.force
        )
    if remote and not args.force:
        remote_checksum = remote.get("database_checksum")
        if not args.expect_remote_checksum:
            raise SystemExit(
                "remote manifest exists; pass --expect-remote-checksum or --force to avoid overwriting newer work"
            )
        if remote_checksum != args.expect_remote_checksum:
            raise SystemExit(
                "remote checksum changed: "
                f"expected={args.expect_remote_checksum} actual={remote_checksum}"
            )

    published_at = now_iso()
    manifest = manifest_with_artifact(db_path, manifest_path, bucket, prefix, keys, snapshot_id, published_at)
    checksum = manifest["database_checksum"]

    upload_file(client, db_path, bucket, keys["snapshot_database_key"], "application/vnd.sqlite3")
    upload_file(client, manifest_path, bucket, keys["snapshot_manifest_key"], "application/json")
    upload_file(client, db_path, bucket, keys["latest_database_key"], "application/vnd.sqlite3")
    upload_file(client, manifest_path, bucket, keys["latest_manifest_key"], "application/json")

    print(f"published master db: checksum={checksum}")
    print(f"snapshot: s3://{bucket}/{keys['snapshot_database_key']}")
    print(f"latest: s3://{bucket}/{keys['latest_database_key']}")
    return {
        "database_checksum": checksum,
        "snapshot_database": f"s3://{bucket}/{keys['snapshot_database_key']}",
        "latest_database": f"s3://{bucket}/{keys['latest_database_key']}",
    }


def status(args, client=None):
    bucket, prefix = config_from_env(args)
    keys = artifact_keys(prefix)
    client = client or s3_client()
    db_path = Path(args.db)
    local_checksum = file_sha256(db_path)
    remote = remote_manifest(client, bucket, keys["latest_manifest_key"])
    remote_checksum = (remote or {}).get("database_checksum", "")
    remote_artifact = (remote or {}).get("artifact") or {}
    remote_published_at = remote_artifact.get("published_at") or ""
    remote_snapshot_id = remote_artifact.get("snapshot_id") or ""
    remote_generated_by = (remote or {}).get("generated_by") or ""
    remote_table_counts = (remote or {}).get("table_counts") or {}
    remote_head = head_object(client, bucket, keys["latest_database_key"])
    local_inbox_version = local_inbox_schema_version(db_path)
    remote_inbox_version = (remote or {}).get(INBOX_SCHEMA_MANIFEST_KEY)
    print(f"local_db: {db_path} checksum={local_checksum or '(missing)'}")
    print(f"remote_db: s3://{bucket}/{keys['latest_database_key']}")
    print(f"remote_exists: {bool(remote_head)} checksum={remote_checksum or '(missing)'}")
    print(f"remote_published_at: {remote_published_at or '(missing)'}")
    print(f"remote_snapshot_id: {remote_snapshot_id or '(missing)'}")
    print(f"remote_generated_by: {remote_generated_by or '(missing)'}")
    print(f"remote_table_counts: {json.dumps(remote_table_counts, sort_keys=True)}")
    print(f"local_review_inbox_schema_version: {local_inbox_version if local_inbox_version is not None else '(missing)'}")
    print(f"remote_review_inbox_schema_version: {remote_inbox_version if remote_inbox_version is not None else '(missing)'}")
    return {
        "local_checksum": local_checksum,
        "remote_checksum": remote_checksum,
        "remote_exists": bool(remote_head),
        "remote_published_at": remote_published_at,
        "remote_snapshot_id": remote_snapshot_id,
        "remote_generated_by": remote_generated_by,
        "remote_table_counts": remote_table_counts,
        "local_review_inbox_schema_version": local_inbox_version,
        "remote_review_inbox_schema_version": remote_inbox_version,
    }


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", default="")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--db", default=str(MASTER_DB))
    parser.add_argument("--manifest", default=str(MASTER_MANIFEST))
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument("--overwrite", action="store_true")

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--snapshot-id", default="")
    publish_parser.add_argument("--expect-remote-checksum", default="")
    publish_parser.add_argument("--force", action="store_true")

    subparsers.add_parser("status")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args)
    elif args.command == "publish":
        publish(args)
    elif args.command == "status":
        status(args)
    else:
        raise SystemExit(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
