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

## Infrastructure

The shared AWS stack defines the private artifact bucket and grants the
GitHub Actions OIDC role read/write access to only the configured prefix.

Default values:

- bucket: `bon-odori-master-rdb-169805602203`
- prefix: `master-rdb`

Deploy or update the stack before enabling the collect workflow variable:

```bash
aws cloudformation deploy \
  --stack-name bon-odori-collector-queue \
  --template-file infra/dynamodb-queue.yml \
  --capabilities CAPABILITY_NAMED_IAM
```

If the default bucket name is unavailable, pass a globally unique name:

```bash
aws cloudformation deploy \
  --stack-name bon-odori-collector-queue \
  --template-file infra/dynamodb-queue.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides MasterRdbBucketName=<unique-bucket-name>
```

## First Publish

Run this once after the bucket is ready. The manual workflow restores the last
tracked `data/bon_odori_master.sqlite` from Git history and publishes it to S3:

```bash
gh workflow run bootstrap_master_rdb_s3.yml \
  -f bucket=bon-odori-master-rdb-169805602203 \
  -f prefix=master-rdb
```

After the workflow succeeds, enable the collect workflow fetch step:

```bash
gh variable set MASTER_DB_S3_BUCKET --body bon-odori-master-rdb-169805602203
gh variable set MASTER_DB_S3_PREFIX --body master-rdb
```

For local initial publish, use this only after configuring AWS credentials:

```bash
python3 master_db_s3_artifact.py publish --snapshot-id initial-YYYYMMDD
```

`--force` is acceptable only for an explicit recovery operation. Normal
publishes should use optimistic locking.

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

The collect workflow fetches the DB only when `MASTER_DB_S3_BUCKET` is set. Set
that variable only after the S3 bucket exists and the first artifact publish has
succeeded. This keeps scheduled runs safe during setup.

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
