# Review Inbox B1-2 Source-scoped Writer

作成日: 2026-07-18 JST

署名: おと（Codex）

ステータス: 実装済み、default off、production配線なし

## 境界

`review_inbox_source_writer.py` は、凍結済みadapter snapshotを一時Master RDBへ適用し、
source単位のparity・stale・lifecycle・DB・公開不変を監査してから、注入されたartifact storeへ
CAS publishするライブラリである。

B1-2には次を含めない。

- production S3用artifact storeの生成・認証・接続
- workflow、cron、legacy builder、legacy writerへの配線
- reader切替、legacy writer停止、domain apply、公開deploy
- 実Master RDBまたは実S3への書き込み

実行口となるCLIも置かない。B1-3以降で配線する場合も、別GOとレビューを必要とする。

## Default offと分離flag

環境変数を指定しない `SourceWriterFlags` は次の状態であり、artifact status取得前に停止する。

| flag | default | B1-2で許す値 |
|---|---|---|
| `REVIEW_INBOX_DUAL_WRITE_MODE` | `off` | testで明示した`canary` / `bulk` |
| `REVIEW_INBOX_CAS_PUBLISH_ENABLED` | `false` | testのFakeStoreでのみ`true` |
| `REVIEW_INBOX_READER_MODE` | `legacy` | `legacy`のみ |
| `REVIEW_INBOX_LEGACY_WRITER_ENABLED` | `true` | `true`のみ |

canary snapshotは`dual_write_mode=canary`、full snapshotの`selection.mode=all`は
`dual_write_mode=bulk`にだけ対応する。一つのflagでcanary、bulk、reader、writer停止をまとめて越えない。

## Current observationとno-op

1 runのadapter stable ID集合を`seen_ids`とし、`observation_id`をrun IDとしてreportへ固定する。
current parityは、同じ`source_id`の全行ではなく、今回の`seen_ids`に一致するRDB行だけを
source-scoped projectionとして比較する。

内容が追加・変更された行は`last_seen_at=observation_id`としてupsertする。内容が同一の行は
DBを更新せず、run側の`observation_id + seen_ids`でcurrentであることを表す。これにより同一入力の
再runはsemantic no-opとなり、新checksum・新snapshotを作らない。`last_seen_at`更新だけのsnapshotも
作らない。

content比較にはparity項目に加え、writerが管理するtitle、domain、priority、source key等を含める。
status、decision、reviewer、decision routeはsource contentに含めず、upsert前後で別監査する。

## Staleとcoverage

同sourceのRDB行は全件を次のどれかへ分類する。

| 分類 | 条件 | 操作 |
|---|---|---|
| current | `inbox_id in seen_ids` | current parityへ含める |
| stale candidate | unseenかつ`status=pending` | 理由`not_seen_in_observation`でreportする |
| lifecycle retained | unseenかつ判断済み | 理由付きでreportし、判断履歴を保持する |

stale候補を削除・status変更しない。判断済み行も物理削除しない。3分類に入らないsource行があれば
`unmapped_count > 0`としてpublish前に失敗させるため、parityのextraを黙って無視しない。

## Runner順序

1. flagとadapter selectionの組を検証する。
2. artifact statusから`Rstart checksum / snapshot_id`を記録する。
3. clean temporary directoryへfetchし、local SHA-256とRstartを照合する。
4. public projection digestとDB auditを記録する。
5. `BEGIN IMMEDIATE`の1 transactionでchanged itemだけをupsertする。
6. SQLite authorizerでinbox以外の書き込みを拒否し、current projection parity、stale/lifecycle coverage、decision保持、integrity、FK、非inbox table countsを監査する。
7. semantic no-opならrollbackし、status再確認・publish・snapshot作成を行わない。
8. changed runはtransaction commit後もpublic digestが同一であることを確認する。
9. remote statusを再取得し、checksumがRstartと異なればCAS conflictとしてpublishしない。
10. `expected_remote_checksum=Rstart`でpublishする。
11. Rendのchecksum/statusを照合し、別fetchでchecksum、integrity、FK、counts、public digestを再監査する。

parity、DB audit、public digest、CASのいずれかが失敗すればfail closedとする。force publishや
domain table更新、公開反映へfallbackしない。

## B1-2 test範囲

`tests/test_review_inbox_source_writer.py` はtemp SQLiteとFakeArtifactStoreだけを使い、次を固定する。

- default offではartifact storeへ一度も触れない
- canary source-scoped write、0差分parity、CAS expectation、別fetch audit
- schema ensureの暗黙commitを避け、全reconciliationがcallerの1 transaction内に残る
- 同一入力の2回目がno-opとなりsnapshotを作らない
- unseen pendingをstale候補、unseen decidedをlifecycle保持へ分類し、削除しない
- publish直前のCAS conflictでpublish 0回
- public projection差分でpublish 0回
- canary / bulk selectionとflagの不一致を拒否
