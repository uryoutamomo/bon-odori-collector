# Review Inbox B1-3 Canary Runbook

作成日: 2026-07-18 JST

署名: おと（Codex）

ステータス: B1-3a配線コード実装、default off、未実行

## フェーズ分離

B1-3は次の二段階に分ける。

1. **B1-3a**: production ArtifactStore、公開projection digest、白金canary CLIを実装・テストする。本番RDB/S3へ接続・書き込みしない。
2. **B1-3b**: B1-3aのことレビュー・merge後、内田さんの別最終GOを得て、白金1件を初めて正本へ書きCAS publishする。

この文書を含むB1-3a PRではB1-3bを実行しない。workflow/cronへの自動配線も行わない。

## Production配線

`review_inbox_production_wiring.py` は次を提供する。

- `MasterDbS3ArtifactStore`: `master_db_s3_artifact.py` の`status` / `fetch` / `publish`をB1-2の`ArtifactStore` Protocolへ適合する。
- publishは`force=False`固定で、空でない`expected_remote_checksum`を必須にする。publish後はstatusを再取得し、返却checksumと照合する。
- `public_projection_digest`: `export_public_events.py` と共通の純粋projection関数を使い、`events_public.json`と同じ`ensure_ascii=False, indent=2`の内容bytesをSHA-256化する。ファイルは書かない。
- 公開投影には明示した`public_today`と、runnerが検査中の一時DBを使う。review inboxだけの変更ではdigestが変わらない。

## CLI安全ゲート

`run_review_inbox_shirokane_canary.py` は、次の条件をすべて満たす前にArtifactStoreを生成しない。

1. `--execute`
2. `--confirm 'RUN SHIROKANE CANARY DUAL WRITE'` 完全一致
3. 次の4環境変数が省略されず明示されている
4. JST 17:20以上18:00未満のcron帯ではない
5. `observation-id`、ことが提示した`expect-rstart-checksum`、固定`public-today`が有効
6. input、snapshot、reportのパスが別で、既存証跡を上書きしない
7. adapter snapshotが白金source key 1件だけを選択する

```text
REVIEW_INBOX_DUAL_WRITE_MODE=canary
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true
REVIEW_INBOX_READER_MODE=legacy
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true
```

環境変数未設定時はB1-2どおりdual-write off / CAS offである。reader切替、legacy writer停止、bulkは
このCLIから実行できない。`--force`も存在しない。

## B1-3b実行テンプレート（最終GO後だけ）

以下はB1-3a PRでは実行しない。merge後にことが提示するR1固定・証跡ディレクトリ・実行時刻を確認し、
内田さんのB1-3b最終GOを得てから使う。

```bash
REVIEW_INBOX_DUAL_WRITE_MODE=canary \
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true \
REVIEW_INBOX_READER_MODE=legacy \
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true \
python3 run_review_inbox_shirokane_canary.py \
  --execute \
  --confirm 'RUN SHIROKANE CANARY DUAL WRITE' \
  --observation-id '<workflow-or-approved-run-id>' \
  --expect-rstart-checksum '<ことが直前確認したR1 SHA-256>' \
  --public-today '<YYYY-MM-DD>' \
  --snapshot-out '<new-evidence-dir>/shirokane-adapter-snapshot.json' \
  --report-out '<new-evidence-dir>/shirokane-run-report.json'
```

bucket/prefixは既存`MASTER_DB_S3_BUCKET` / `MASTER_DB_S3_PREFIX`を使うか、承認済み値を引数で渡す。
Macからの実行可否・AWS認証経路はB1-3b段取り時に改めて確認する。

## B1-3b停止条件と完了証跡

既存B1-2 runnerの停止条件をそのまま使う。

- Rstartとfetch checksum不一致
- schema v2でない、integrity/FK異常、inbox以外へのwrite
- parity missing/extra/mismatch、coverage unmapped、lifecycle変化
- public projection digestまたはdomain table countsの変化
- publish直前CAS conflict
- Rend status、別fetch checksum/audit/public digest不一致

成功時は、R1/R2、snapshot ID、adapter input/snapshot SHA、白金stable ID、parity、監査、別fetchを
reportへ残す。ことがS3 latest実体と白金1行、decision自動昇格0、domain counts/public不変を独立検証する。
