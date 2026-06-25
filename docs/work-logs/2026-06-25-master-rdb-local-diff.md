# Master RDB local diff hold note 2026-06-25

- generated_by: おと（Codex）
- status: published to S3 artifact
- local_db: `data/bon_odori_master.sqlite`
- local_checksum: `b9bda2eab36c24c739e285400deef3b1a95f630da7293c148671e1e905240807`
- previous_s3_bootstrap_checksum: `1519a9e05011b692136fae6440a1efd9b5812535b5e9ecb09d1a0aa3358a5583`

## Summary

The local master RDB differs from the last tracked pre-S3 database by one
`event_series` row only. It is not a bulk rebuild and does not add or delete
event rows.

On 2026-06-25, after AWS CLI login was restored, this local DB was published to
the Master RDB S3 artifact with optimistic locking.

Changed series:

- `SHIBUYA MIYASHITA PARK BON DANCE`

Changed fields:

- `public_intro`: filled from the reviewed Notion snapshot drift decision.
- `source_url`: replaced the 2025 archive URL with the 2026 PR TIMES/MANTAN
  evidence URL.
- `updated_at`: moved to `2026-06-23T10:10:37+00:00`.

## Evidence

Apply reports:

- `data/notion_drift_public_intro_apply_report.json`
- `data/notion_drift_public_intro_apply_report.md`
- `data/notion_drift_source_url_resolutions_apply_report.json`
- `data/notion_drift_source_url_resolutions_apply_report.md`

The reports state that the writes touched the Master RDB only and did not write
Notion or public JSON.

Audit:

- `python3 audit_master_rdb.py --out-json /tmp/bon_master_rdb_audit_current.json --out-md /tmp/bon_master_rdb_audit_current.md`
- result: `issue_count=1`
- severity: `medium`
- remaining issue: known `source_snapshot_drift`

Published artifact:

- snapshot_id: `shibuya-miyashita-public-intro-source-20260623`
- latest checksum: `b9bda2eab36c24c739e285400deef3b1a95f630da7293c148671e1e905240807`
- snapshot DB: `s3://bon-odori-master-rdb-169805602203/master-rdb/snapshots/shibuya-miyashita-public-intro-source-20260623/bon_odori_master.sqlite`
- latest DB: `s3://bon-odori-master-rdb-169805602203/master-rdb/latest/bon_odori_master.sqlite`

## Why not commit generated public JSON yet

The dirty public and YouTube JSON files are generated outputs. They currently
mix at least these sources:

- the one-row local Master RDB update above,
- YouTube daily backfill output from 2026-06-24,
- regenerated song/public prediction snapshots.

Do not commit them as a normal data snapshot until the Master RDB artifact is
published or the generated outputs are intentionally regenerated from the
current remote artifact.

## Publish steps used

1. Confirmed remote and local checksums:

```sh
/tmp/bon-odori-venv/bin/python master_db_s3_artifact.py \
  --bucket bon-odori-master-rdb-169805602203 \
  --prefix master-rdb \
  status
```

2. Remote checksum was still
   `1519a9e05011b692136fae6440a1efd9b5812535b5e9ecb09d1a0aa3358a5583`.
   Published the reviewed local DB with optimistic locking:

```sh
/tmp/bon-odori-venv/bin/python master_db_s3_artifact.py \
  --bucket bon-odori-master-rdb-169805602203 \
  --prefix master-rdb \
  publish \
  --snapshot-id shibuya-miyashita-public-intro-source-20260623 \
  --expect-remote-checksum 1519a9e05011b692136fae6440a1efd9b5812535b5e9ecb09d1a0aa3358a5583
```

3. Confirmed remote latest checksum now matches local checksum:
   `b9bda2eab36c24c739e285400deef3b1a95f630da7293c148671e1e905240807`.

4. Commit only the manifest and the two apply report pairs after publish.

5. Regenerate public exports from the published DB before deciding whether to
   commit public JSON or site-sync data.

## AWS login blocker

Earlier on 2026-06-25, `aws login` opened the AWS sign-in page, but both the
active session path and the new-session path ended in AWS `400 Bad Request`.
`aws sts get-caller-identity` reported:

```text
Your session has expired. Please reauthenticate using 'aws login'.
```

Uchida-san later completed CLI login manually. `aws sts get-caller-identity`
then returned account `169805602203`, allowing the publish to proceed.
