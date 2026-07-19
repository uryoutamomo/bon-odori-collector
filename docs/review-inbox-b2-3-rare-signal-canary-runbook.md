# Review Inbox B2-3 Rare Signal Canary Runbook

作成日: 2026-07-19 JST

署名: おと（Codex）

ステータス: B2-3a配線コード実装、default off、未実行

## フェーズ分離

1. **B2-3a**: rare signal stable keyを厳密に1件だけ選ぶadapter mode、監査付きcanary CLI、
   lifecycle保持テストを実装する。本番RDB/S3へ接続・書き込みしない。
2. **B2-3b**: B2-3aのことレビュー・merge後、対象候補、Rstart、時刻、終了点を固定し、
   内田さんの別GOで初回shadow upsertを実行する。
3. **B2-3c**: 正本decision CAS writerの実装・レビュー後に別GOを得て、有限decision保存と
   同一候補の再観測によるlifecycle保持を実証する。

B2-3aのテストは、既存decisionがあるDBを同一snapshotで再観測してもdecision、reviewer、routeが
pendingへ戻らず、CAS publishも増えないことを固定する。ただし正本decision CAS writerはまだ存在しないため、
B2-3cを手作業SQLで代用しない。

## Canary CLI

`run_review_inbox_rare_signal_canary.py` は次をすべて満たす前にArtifactStoreを生成しない。

1. `--execute`
2. `--confirm 'RUN RARE SIGNAL CANARY SHADOW'` 完全一致
3. 4環境変数の明示
4. JST 17:20以上18:00未満のcron帯外
5. ことレビュー済みの `canary-source-key` が入力内で厳密に1件
6. 固定Rstart SHA-256、observation ID、public today
7. input、snapshot、reportのpath分離と既存証跡の上書き拒否

```text
REVIEW_INBOX_DUAL_WRITE_MODE=canary
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true
REVIEW_INBOX_READER_MODE=legacy
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true
```

runnerは既存の `run_source_shadow` を再利用し、schema v2、SQLite integrity/FK、source parity、
unmapped 0、inbox外table count不変、public projection不変、publish直前CAS、Rend別fetchを検査する。
reader切替、legacy writer停止、workflow接続、DynamoDB変更、domain/public applyは行わない。

## B2-3b実行テンプレート

以下はB2-3aでは実行しない。現在のproduction入力にreview済みrare signal候補が無い場合も実行しない。

```bash
REVIEW_INBOX_DUAL_WRITE_MODE=canary \
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true \
REVIEW_INBOX_READER_MODE=legacy \
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true \
python3 run_review_inbox_rare_signal_canary.py \
  --execute \
  --confirm 'RUN RARE SIGNAL CANARY SHADOW' \
  --input '<frozen-rare-signal-backcheck-queue.json>' \
  --canary-source-key '<reviewed-stable-source-key>' \
  --observation-id '<approved-run-id>' \
  --expect-rstart-checksum '<ことが直前確認したRstart SHA-256>' \
  --public-today '<YYYY-MM-DD>' \
  --snapshot-out '<new-evidence-dir>/rare-signal-canary-snapshot.json' \
  --report-out '<new-evidence-dir>/rare-signal-canary-report.json'
```

## 停止条件と証跡

- 対象stable keyが0件または複数件
- Rstart固定値とremote/fetch checksum不一致
- parity、unmapped、lifecycle、integrity、FK、domain/public不変のいずれか不合格
- publish直前CAS conflict、Rend status/別fetch不一致

成功時はinput/snapshot SHA、stable ID、Rstart/Rend、parity、監査、別fetchを保存する。
初回upsert後もdecisionは自動設定せずpending 1件であることを、ことが独立検証する。
