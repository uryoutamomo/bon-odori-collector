# Master RDB S3 Artifact Runbook

`data/bon_odori_master.sqlite` is a local working copy. The authoritative
artifact should live in S3, while Git keeps code, manifests, schemas, audits,
and review reports.

## Configuration

Set these environment variables in local shells or GitHub Actions variables:

- `MASTER_DB_S3_BUCKET`: required bucket name.
- `MASTER_DB_S3_PREFIX`: optional object prefix. Defaults to `master-rdb`.
- `AWS_REGION`: optional AWS region for boto3. GitHub Actions uses
  `ap-northeast-1`.

Expected object layout:

```text
s3://$MASTER_DB_S3_BUCKET/$MASTER_DB_S3_PREFIX/latest/bon_odori_master.sqlite
s3://$MASTER_DB_S3_BUCKET/$MASTER_DB_S3_PREFIX/latest/bon_odori_master_manifest.json
s3://$MASTER_DB_S3_BUCKET/$MASTER_DB_S3_PREFIX/snapshots/<snapshot-id>/bon_odori_master.sqlite
s3://$MASTER_DB_S3_BUCKET/$MASTER_DB_S3_PREFIX/snapshots/<snapshot-id>/bon_odori_master_manifest.json
```

## First Publish

Run this once after the bucket is ready:

```bash
python3 master_db_s3_artifact.py publish --snapshot-id initial-YYYYMMDD --force
```

`--force` is acceptable only for the initial publish or for an explicit recovery
operation. Normal publishes should use optimistic locking.

## Daily Local Workflow

Fetch the latest DB before work:

```bash
python3 master_db_s3_artifact.py fetch --overwrite
```

Run local scripts against `data/bon_odori_master.sqlite` as usual. After a DB
change has passed audit and tests, publish it:

```bash
REMOTE_CHECKSUM=$(python3 master_db_s3_artifact.py status | sed -n 's/^remote_exists: .* checksum=//p')
python3 master_db_s3_artifact.py publish --expect-remote-checksum "$REMOTE_CHECKSUM"
```

Then commit only the manifest, schema, reports, and code changes. Do not commit
`data/bon_odori_master.sqlite`.

## GitHub Actions

The collect workflow fetches the DB only when `MASTER_DB_S3_BUCKET` is set. This
keeps existing workflows safe before the bucket is configured.

If a workflow mutates the master RDB in the future, it must:

1. Fetch the latest artifact at the start.
2. Record the remote checksum.
3. Run the local SQLite mutation.
4. Audit the DB.
5. Publish with `--expect-remote-checksum`.
6. Commit the manifest/report changes only.

## Safety Rules

- SQLite is never opened directly on S3.
- S3 stores snapshots and the latest artifact.
- Local scripts read and write the local file path only.
- The publish command refuses to overwrite an existing latest artifact unless
  `--expect-remote-checksum` matches or `--force` is explicitly passed.
