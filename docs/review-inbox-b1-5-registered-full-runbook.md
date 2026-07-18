# Review Inbox B1-5 Registered Investigation Full Shadow Runbook

作成日: 2026-07-18 JST

署名: おと（Codex）

ステータス: B1-5a配線コード実装、default off、未実行

## 対象とフェーズ

B1-5は、`registered_event_investigation_queue.json`の全79件を、B1-1の
`RegisteredEventInvestigationAdapter`とB1-2のsource-scoped writerでbulk shadowする。

1. **B1-5a**: full shadow CLI、証跡、FakeStore検証を実装する。本番RDB/S3へ接続・書き込みしない。
2. **B1-5b**: こと独立レビュー合格後にmergeし、直前Rstartを固定して本番bulk shadowを実行する。

B1-3bで投入済みの白金1行は、full snapshotでも同じstable IDを使う。同一内容なら更新せず、
既存`last_seen_at`とdecision lifecycleを保持する。2026-07-18時点では白金1件unchanged、残78件新規を想定する。

## Snapshot契約

`run_review_inbox_registered_full_shadow.py`は次を凍結証跡へ残す。

- `source_id=registered_event_investigation`
- `selection.mode=all`
- 全79 source key（重複なし、白金canary keyを含む）
- input path / SHA-256 / byte数、adapter snapshot path / SHA-256
- time scope別件数、kind別件数

現在の実入力は79件で、future 79、kind内訳はcurrent year confirmation 55、occurrence creation 17、
venue review 7である。件数は本番実行時の凍結入力を正とし、adapterが返す全件をcurrent observationにする。

## 壊さない5点とCLIゲート

ArtifactStore生成前に、`--execute`、exact confirm、4環境変数、cron帯外、64hex Rstart、固定public date、
新規証跡パスをすべて検証する。

```text
REVIEW_INBOX_DUAL_WRITE_MODE=bulk
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true
REVIEW_INBOX_READER_MODE=legacy
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true
```

confirmは`RUN REGISTERED INVESTIGATION FULL SHADOW`と完全一致させる。`--force`は存在しない。

各本番runで次を必須監査とする。

1. SQLite authorizerによりreview inbox以外のdomain tableへ書かない。
2. `public_projection_digest`がRstart、candidate、Rend別fetchで一致する。
3. 新規行はpending、decision系5列はNULL。既存白金lifecycleも変えない。
4. S3 latestを別fetchし、実体SHA-256がRendと一致する。
5. Rstart pre-stateを記録し、CAS expect-rstart、forceなしでrollback可能にする。

いずれかが崩れた場合は次sourceへ進まず、内田さんへ停止報告する。

## 本番実行テンプレート

以下はB1-5aレビュー合格・merge後に限り使う。開始直前statusの実測Rstartを固定し、
JST 17:20以上18:00未満のcron帯を避ける。

```bash
REVIEW_INBOX_DUAL_WRITE_MODE=bulk \
REVIEW_INBOX_CAS_PUBLISH_ENABLED=true \
REVIEW_INBOX_READER_MODE=legacy \
REVIEW_INBOX_LEGACY_WRITER_ENABLED=true \
python3 run_review_inbox_registered_full_shadow.py \
  --execute \
  --confirm 'RUN REGISTERED INVESTIGATION FULL SHADOW' \
  --observation-id '<approved-run-id>' \
  --expect-rstart-checksum '<直前statusのRstart SHA-256>' \
  --public-today '<YYYY-MM-DD>' \
  --snapshot-out '<new-evidence-dir>/registered-full-adapter-snapshot.json' \
  --report-out '<new-evidence-dir>/registered-full-run-report.json'
```

成功後、ことがS3実体、全行lifecycle、白金保持、domain counts、public digestを独立再現する。
合格後だけB1-6へ進む。workflow/cronへの自動配線はこの工程に含めない。
