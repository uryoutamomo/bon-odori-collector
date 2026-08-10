"""Private S3 artifact storage for the all-source voices snapshot.

S3 is authoritative; ``data/voices.json`` is a verified, ignored working copy.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "voices-snapshot/v1"
DEFAULT_PREFIX = "voices"
DEFAULT_VOICES_PATH = Path("data/voices.json")
DEFAULT_PROVENANCE_PATH = Path("data/voices_s3_manifest.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def clean_prefix(value: str | None) -> str:
    return str(value or DEFAULT_PREFIX).strip("/") or DEFAULT_PREFIX


def safe_key_part(value: str | None, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.=-]+", "-", str(value or "").strip())
    return value.strip("-") or fallback


def require_bucket(value: str | None = None) -> str:
    bucket = (value or os.environ.get("VOICES_S3_BUCKET") or "").strip()
    if not bucket:
        raise SystemExit("VOICES_S3_BUCKET is required")
    return bucket


def artifact_keys(prefix: str, snapshot_id: str | None = None) -> dict[str, str]:
    prefix = clean_prefix(prefix)
    keys = {
        "latest_data": f"{prefix}/latest/voices.json.gz",
        "latest_manifest": f"{prefix}/latest/voices.manifest.json",
    }
    if snapshot_id:
        keys.update({
            "snapshot_data": f"{prefix}/snapshots/{snapshot_id}/voices.json.gz",
            "snapshot_manifest": f"{prefix}/snapshots/{snapshot_id}/voices.manifest.json",
        })
    return keys


def s3_client():
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("boto3 is required for voices S3 artifacts") from exc
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION") or None)


def is_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", {}) or {}
    code = (response.get("Error") or {}).get("Code")
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


def get_json(client: Any, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if is_not_found(exc):
            return None
        raise
    return json.loads(response["Body"].read().decode("utf-8"))


def put_object(client: Any, bucket: str, key: str, body: bytes, content_type: str, *, gzip_encoded: bool = False):
    kwargs = {
        "Bucket": bucket, "Key": key, "Body": body, "ContentType": content_type,
        "ServerSideEncryption": "AES256",
    }
    if gzip_encoded:
        kwargs["ContentEncoding"] = "gzip"
    client.put_object(**kwargs)


def atomic_write(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    shutil.move(str(temp_path), path)


def voices_payload(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"voices working copy not found: {path}; run fetch first") from exc
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise SystemExit(f"voices working copy is not a JSON array of objects: {path}")
    return data, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or "(missing)")
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def read_provenance(path: Path = DEFAULT_PROVENANCE_PATH) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(
            f"voices provenance not found: {path}; run voices_s3_artifact.py fetch --overwrite first"
        ) from exc


def require_writable_local_voices(path: str | Path = DEFAULT_VOICES_PATH):
    """Reject canonical writes that did not start from a verified S3 fetch.

    Temporary paths used by unit tests remain ordinary files.
    """
    path = Path(path)
    if path.resolve() != (Path.cwd() / DEFAULT_VOICES_PATH).resolve():
        return
    provenance = read_provenance()
    _, payload = voices_payload(path)
    if provenance.get("content_sha256") != sha256_bytes(payload):
        raise SystemExit("voices working copy differs from fetched artifact; refetch and resolve before writing")


def make_manifest(rows: list[dict[str, Any]], payload: bytes, *, bucket: str, prefix: str,
                  keys: dict[str, str], snapshot_id: str, previous_checksum: str, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "content_sha256": sha256_bytes(payload),
        "item_count": len(rows),
        "source_counts": source_counts(rows),
        "previous_checksum": previous_checksum,
        "snapshot_id": snapshot_id,
        "published_at": now_iso(),
        "run_id": run_id,
        "artifact": {
            "storage": "s3", "bucket": bucket, "prefix": prefix,
            "latest_data_key": keys["latest_data"], "latest_manifest_key": keys["latest_manifest"],
            "snapshot_data_key": keys["snapshot_data"], "snapshot_manifest_key": keys["snapshot_manifest"],
        },
    }


def fetch(args, client: Any | None = None) -> dict[str, Any]:
    bucket = require_bucket(args.bucket)
    prefix = clean_prefix(args.prefix or os.environ.get("VOICES_S3_PREFIX"))
    keys = artifact_keys(prefix)
    client = client or s3_client()
    manifest = get_json(client, bucket, keys["latest_manifest"])
    if not manifest:
        raise SystemExit(f"voices artifact missing: s3://{bucket}/{keys['latest_manifest']}; run seed before enabling")
    expected = manifest.get("content_sha256")
    if not expected:
        raise SystemExit("voices artifact manifest has no content_sha256")
    path = Path(args.voices)
    if path.exists() and not args.overwrite:
        raise SystemExit(f"{path} already exists; use --overwrite")
    response = client.get_object(Bucket=bucket, Key=keys["latest_data"])
    payload = gzip.decompress(response["Body"].read())
    if sha256_bytes(payload) != expected:
        raise SystemExit("voices artifact checksum mismatch")
    rows = json.loads(payload.decode("utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("voices artifact is not a JSON list")
    atomic_write(path, payload)
    provenance = dict(manifest)
    provenance["fetched_at"] = now_iso()
    provenance["local_path"] = str(path)
    atomic_write(Path(args.provenance), (json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    print(f"fetched voices: {len(rows)} items from s3://{bucket}/{keys['latest_data']}")
    return manifest


def publish(args, client: Any | None = None, *, allow_empty_remote: bool = False) -> dict[str, Any]:
    bucket = require_bucket(args.bucket)
    prefix = clean_prefix(args.prefix or os.environ.get("VOICES_S3_PREFIX"))
    client = client or s3_client()
    rows, payload = voices_payload(Path(args.voices))
    provenance_path = Path(args.provenance)
    if provenance_path.exists():
        provenance = read_provenance(provenance_path)
    elif allow_empty_remote:
        provenance = {}
    else:
        provenance = read_provenance(provenance_path)
    if provenance.get("content_sha256") and provenance["content_sha256"] != sha256_bytes(payload):
        # Changes are expected; provenance only proves the starting point. Do not reject them.
        pass
    latest_keys = artifact_keys(prefix)
    remote = get_json(client, bucket, latest_keys["latest_manifest"])
    expected = getattr(args, "expect_remote_checksum", "") or provenance.get("content_sha256") or ""
    remote_checksum = (remote or {}).get("content_sha256") or ""
    if remote and remote_checksum != expected:
        raise SystemExit(f"voices remote checksum changed: expected={expected} actual={remote_checksum}")
    if not remote and not allow_empty_remote:
        raise SystemExit("voices remote artifact is absent; use seed exactly once")
    if remote:
        remote_item_count = remote.get("item_count")
        if not isinstance(remote_item_count, int) or remote_item_count < 0:
            raise SystemExit("voices remote artifact manifest has no valid item_count")
        if len(rows) < remote_item_count and not getattr(args, "allow_item_count_decrease", False):
            raise SystemExit(
                "voices item count would decrease: "
                f"remote={remote_item_count} new={len(rows)}; "
                "rerun with --allow-item-count-decrease only for an intentional deletion"
            )
    snapshot_id = safe_key_part(args.snapshot_id or os.environ.get("GITHUB_RUN_ID") or now_iso(), "manual")
    keys = artifact_keys(prefix, snapshot_id)
    run_id = safe_key_part(os.environ.get("GITHUB_RUN_ID") or "manual", "manual")
    manifest = make_manifest(rows, payload, bucket=bucket, prefix=prefix, keys=keys,
                             snapshot_id=snapshot_id, previous_checksum=remote_checksum, run_id=run_id)
    compressed = gzip.compress(payload, mtime=0)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    put_object(client, bucket, keys["snapshot_data"], compressed, "application/json", gzip_encoded=True)
    put_object(client, bucket, keys["snapshot_manifest"], manifest_bytes, "application/json")
    put_object(client, bucket, keys["latest_data"], compressed, "application/json", gzip_encoded=True)
    put_object(client, bucket, keys["latest_manifest"], manifest_bytes, "application/json")
    atomic_write(Path(args.provenance), (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    print(f"published voices: items={len(rows)} checksum={manifest['content_sha256']} snapshot={snapshot_id}")
    return manifest


def seed(args, client: Any | None = None) -> dict[str, Any]:
    bucket = require_bucket(args.bucket)
    prefix = clean_prefix(args.prefix or os.environ.get("VOICES_S3_PREFIX"))
    client = client or s3_client()
    if get_json(client, bucket, artifact_keys(prefix)["latest_manifest"]):
        raise SystemExit("voices artifact already exists; seed is one-time only")
    rows, _ = voices_payload(Path(args.voices))
    source_checksum = sha256_bytes(Path(args.voices).read_bytes())
    if not args.expect_source_sha256 or args.expect_item_count is None:
        raise SystemExit("seed requires --expect-source-sha256 and --expect-item-count")
    if source_checksum != args.expect_source_sha256:
        raise SystemExit(f"seed source checksum mismatch: expected={args.expect_source_sha256} actual={source_checksum}")
    if len(rows) != args.expect_item_count:
        raise SystemExit(f"seed item count mismatch: expected={args.expect_item_count} actual={len(rows)}")
    # ``seed`` does not accept a remote checksum: it is valid only when no
    # remote manifest exists. ``publish`` still shares its implementation.
    args.expect_remote_checksum = ""
    args.snapshot_id = args.snapshot_id or f"seed-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    return publish(args, client=client, allow_empty_remote=True)


def run(args):
    args.overwrite = True
    args.expect_remote_checksum = ""
    args.snapshot_id = ""
    fetch(args)
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
    publish(args)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    # Keep this attribute present on every subcommand: seed and run also call
    # publish(), and must not depend on a publish-only argparse attribute.
    parser.set_defaults(allow_item_count_decrease=False)
    parser.add_argument("--bucket", default="")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--voices", default=str(DEFAULT_VOICES_PATH))
    parser.add_argument("--provenance", default=str(DEFAULT_PROVENANCE_PATH))
    sub = parser.add_subparsers(dest="command_name", required=True)
    fetch_p = sub.add_parser("fetch")
    fetch_p.add_argument("--overwrite", action="store_true")
    publish_p = sub.add_parser("publish")
    publish_p.add_argument("--expect-remote-checksum", default="")
    publish_p.add_argument("--snapshot-id", default="")
    publish_p.add_argument("--allow-item-count-decrease", action="store_true")
    seed_p = sub.add_parser("seed")
    seed_p.add_argument("--snapshot-id", default="")
    seed_p.add_argument("--expect-source-sha256", required=True)
    seed_p.add_argument("--expect-item-count", type=int, required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--allow-item-count-decrease", action="store_true")
    run_p.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command_name == "fetch":
        fetch(args)
    elif args.command_name == "publish":
        publish(args)
    elif args.command_name == "seed":
        seed(args)
    elif args.command_name == "run":
        if not args.command:
            raise SystemExit("run requires a command after --")
        run(args)
    return 0
