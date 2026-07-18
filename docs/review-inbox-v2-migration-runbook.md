# Review Inbox v2 Migration Runbook

作成日: 2026-07-17 JST
署名: おと（Codex）

このrunbookは `review_inbox_items` のproduction schemaをv1からv2へ移す手順である。
runnerはローカルSQLiteだけを変更し、S3 publish・公開JSON生成・サイトdeployは行わない。

## 実行時間

正本applyからS3 publishまでのPhase 2は、日次cronの発火帯である
**17:20〜18:00 JSTを避ける**。開始後にcron帯へ入りそうな場合は作業を開始しない。

## Phase 1: dry-run

まずS3 statusからremote checksum `R0`を記録する。`fetch --overwrite` の前に、現在のlocal DBが
`R0`と一致することをrunnerで確認する。不一致は未publish変更または競合の可能性があるため、
上書きせず停止する。

```bash
python3 master_db_s3_artifact.py status
python3 review_inbox_migration_runner.py guard-fetch \
  --expect-remote-checksum R0
python3 master_db_s3_artifact.py fetch --overwrite
python3 review_inbox_migration_runner.py dry-run \
  --expect-local-checksum R0
```

JSON/Markdown report、dry-run DB、public exportの同一入力日でのbefore/after比較をことがレビューする。
`schema_migrations` は `review_inbox_v2` の1行だけ増える。その他のtable counts、既存inbox行、
status分布、payloadと時刻は不変でなければならない。v1からの移行時にdecision系を自動設定しない。

## Phase 2: apply（内田さんの別途GO後のみ）

Phase 1の証跡承認後、内田さんからproduction applyの明示GOを得る。実行直前にstatusを取り直し、
remoteが `R0` から変わっていたらPhase 1からやり直す。

```bash
python3 review_inbox_migration_runner.py apply \
  --expect-local-checksum R0 \
  --confirm 'APPLY REVIEW INBOX V2'
python3 master_db_s3_artifact.py status
python3 master_db_s3_artifact.py publish \
  --expect-remote-checksum R0
python3 master_db_s3_artifact.py status
```

runnerはapply前にtimestamp付きbackupを作り、`BEGIN IMMEDIATE`内でmigrationと監査を行う。
監査失敗時はtransactionをrollbackし、S3へpublishしない。publish直前にもremoteが`R0`のままかを
確認する。publish後は新checksum `R1` のlatestを別ディレクトリへfetchし、integrity、foreign key、
schema、counts、backfill、public export不変を再確認する。B1 dual-writeは別PR・別GOまで無効のままとする。

## Rollback

- publish前: transaction rollbackまたはrunnerのlocal backupを復元する。S3 latestは不変。
- publish後: `--force`は禁止。remoteが`R1`であることを確認し、検証済みbackupを
  `--expect-remote-checksum R1`で新しいrollback snapshotとしてpublishする。
- remoteが`R1`以外なら、他作業を上書きせず停止する。

rollback後も別fetchでchecksum、integrity、foreign key、table countsを再確認する。
