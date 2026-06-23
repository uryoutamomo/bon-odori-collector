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

After local AWS credentials are configured, the setup script performs the full
bootstrap sequence:

1. Deploy or update the CloudFormation stack.
2. Run the one-time bootstrap workflow.
3. Set the GitHub Actions variables after the artifact publish succeeds.

```bash
scripts/setup_master_rdb_s3.sh
```

To override the bucket name or prefix:

```bash
MASTER_DB_S3_BUCKET=<unique-bucket-name> \
MASTER_DB_S3_PREFIX=master-rdb \
scripts/setup_master_rdb_s3.sh
```

For manual setup, deploy or update the stack before enabling the collect
workflow variable:

```bash
aws cloudformation deploy \
  --stack-name bon-odori-dynamodb \
  --template-file infra/dynamodb-queue.yml \
  --capabilities CAPABILITY_NAMED_IAM
```

If the default bucket name is unavailable, pass a globally unique name:

```bash
aws cloudformation deploy \
  --stack-name bon-odori-dynamodb \
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

## Production Verification

As of 2026-06-23, the S3 artifact path is enabled for GitHub Actions:

- `MASTER_DB_S3_BUCKET=bon-odori-master-rdb-169805602203`
- `MASTER_DB_S3_PREFIX=master-rdb`
- latest checksum:
  `1519a9e05011b692136fae6440a1efd9b5812535b5e9ecb09d1a0aa3358a5583`

Verified runs:

- `bootstrap-master-rdb-s3` run `28002138921`: initial publish succeeded.
- `verify-master-rdb-s3` run `28004172057`: fetch, checksum, audit, and
  untracked DB guard succeeded.
- `verify-aws-queue` run `28004500579`: queue access and table counts
  succeeded.
- `bon-odori-collect` run `28004533368`: production collect fetched
  `s3://bon-odori-master-rdb-169805602203/master-rdb/latest/bon_odori_master.sqlite`,
  completed in 10m10s, passed pre/post duplicate audits, ran
  `guard_git_large_files.py`, and committed only JSON data updates.

## Safety Rules

- SQLite is never opened directly on S3.
- S3 stores snapshots and the latest artifact.
- Local scripts read and write the local file path only.
- The publish command refuses to overwrite an existing latest artifact unless
  `--expect-remote-checksum` matches or `--force` is explicitly passed.
