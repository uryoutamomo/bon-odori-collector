# D 状態語彙2軸化 移行計画

作成日: 2026-07-20 JST  
署名: おと（Codex）

## 目的と完了条件

イベントの公開状態を、次の2軸だけを正本として扱う。

- `current_event_state`: `predicted` / `announced` / `confirmed` / `ended` / `cancelled`
- `date_certainty_tier`: `confirmed` / `rule_predicted` / `historical_slide` / `season_hint` / `historical_reference`

`public_category`、`public_status`、`display_tier`、表示ラベルは2軸からの互換投影にする。
`recurrence_score` は状態ではなく根拠強度の派生スコアとして残す。`review_inbox_items.time_scope`
は受信箱の並び順・振り分け専用であり、イベント状態の第3軸にはしない。
`lifecycle_status` に残っている `merged` / `duplicate` / `rejected` /
`superseded_by_curated` / `archived` は公開状態ではなく、行の技術的な処分・除外情報として扱う。
移行後も互換列に残すが、公開状態の判断には使わない。行処分済みの行にも有限な2軸を入れ、
公開投影では従来どおり行処分フィルタを先に適用する。

Dの完了条件は次のすべて。

1. Master RDB の `event_occurrences` に2軸が入り、全行が有限語彙で埋まる。
2. 既存の `date_status` / `lifecycle_status` は公開判断の入力に使わず、移行中の互換列・技術的な行処分情報としてのみ残す。
3. 公開JSONの旧フィールドを2軸から再現できる。
4. サイトが2軸を優先して表示し、旧JSONでも動くフォールバックを保つ。
5. メール配信経路に状態語彙の直接依存がないことをテストまたは棚卸しで確認する。
6. 同一DB・同一基準日で、切替前後のカード分類、日付表示、バッジ、並び順が差分ゼロになる。
7. 本番RDBはbackup、audit、checksum CAS、再fetch検証つきで移行し、日次runでも2軸が欠落・逆行しない。

## 現状（2026-07-20）

- 公開JSON 209件にはすでに `current_event_state` / `date_certainty_tier` がある。
- ただし `apply_public_display_tiers.py` が旧 `public_category` と後処理結果から逆算しており、RDB正本ではない。
- 現行209件の組み合わせは次のとおり。
  - `confirmed / confirmed`: 52件
  - `ended / confirmed`: 21件
  - `predicted / rule_predicted`: 5件
  - `predicted / historical_slide`: 58件
  - `predicted / season_hint`: 38件
  - `unconfirmed / historical_reference`: 32件
  - `unconfirmed / season_hint`: 3件
- `unconfirmed` はDの有限語彙に含めず、今年未発表の継続候補として `predicted` へ正規化する。
- `announced` は「当年の公式・主催情報で開催自体は発表済みだが、日付確定条件を満たさない」場合だけに使う。
- site の `scripts/build_public_snapshot.py` は2軸を許可リストへ含めておらず、`app.js` も旧語彙優先。
- `send_mail.py` / `send_mail.yml` は `pending_mail.json` の本文を送るだけで、イベント状態語彙を参照しない。

## 互換写像

| `current_event_state` | `date_certainty_tier` | 旧 `public_category` | 旧 `display_tier` |
| --- | --- | --- | --- |
| `confirmed` | `confirmed` | `upcoming` | `confirmed` |
| `ended` | `confirmed` | `ended` | `ended` |
| `cancelled` | 任意 | `cancelled` | `cancelled` |
| `predicted` / `announced` | `rule_predicted` | `recurring_last_year` | `rule_predicted` |
| `predicted` / `announced` | `historical_slide` | `recurring_last_year` | `historical_slide` |
| `predicted` / `announced` | `historical_reference` | `recurring_last_year` | `historical_reference` |
| `predicted` / `announced` | `season_hint` | `date_unknown` | `season_hint` |

`confirmed` と `ended` は `date_certainty_tier=confirmed` を必須とする。`predicted` / `announced`
に `date_certainty_tier=confirmed` は許可しない。`cancelled` は中止前の根拠を保持できるようtierを限定しない。

## 実装順

### D1 契約とshadow比較

- `event_state_axes.py` に有限語彙、組み合わせ検証、旧公開フィールドへの写像を集約する。
- 現行投影から2軸を作る `legacy_derived` と、RDBの2軸を読む `canonical` を同一入力で比較する。
- 比較対象は件数、イベントidentity、カード分類、display tier、日付範囲、表示ラベル、並び順。

### D2 RDB migration

- `event_occurrences` に `current_event_state` / `date_certainty_tier` を追加する明示migration runnerを作る。
- 通常のread/exportで暗黙migrationしない。
- 公開対象行は現行の最終投影と `public_event_source_map` の `occurrence_id` でbackfillする。
- 非公開・merge済み行は既存 `date_status` / `lifecycle_status` / `source_kind` から有限写像する。
- `schema_migrations` にDのversionを記録し、不正語彙・不正組み合わせをtriggerとauditで拒否する。
- migration前後でevent/inbox/domain tableの行数、FK、integrity、公開投影を検証する。

### D3 writer更新

- 現役の occurrence writer は2軸を明示更新し、旧 `date_status` / `lifecycle_status` は互換写像で同時生成する。
- 対象は `event_report_helpers.py`、`apply_change_requests.py` 経路、公式待ち昇格、日付fill、
  `apply_predicted_occurrence_source_rechecks.py`、初期RDB builder。
- 詳細・会場・URLだけを変えるwriterは2軸を変更しない。
- 日次同期は基準日で `confirmed -> ended` など必要な遷移だけを算出し、no-op時はpublishしない。

### D4 export/site切替

- `export_public_events.py` はRDBに2軸列があればcanonicalを使い、旧DBだけ `legacy_derived` へfail-safe fallbackする。
- 旧 `public_category` / `display_tier` は2軸から生成してJSON互換を維持する。
- site snapshotへ2軸を通し、`app.js` は2軸優先・旧語彙fallbackにする。
- mail経路は変更せず、状態語彙参照0の契約テストを追加する。

### D5 本番切替と閉鎖

- 本番S3 Master RDBをfetchし、Rstart checksumを固定する。
- 一時コピーでmigration、全件audit、旧新shadow差分ゼロを確認する。
- `event_occurrences` と `schema_migrations` 以外の変更を拒否し、CAS publishする。
- Rendを再fetchしてschema、全行2軸、行数、integrity、公開投影を再検証する。
- 日次workflowはD同期をexportより前に実行し、証跡をartifactとして保存する。
- 最初の実runと次の定時runで差分ゼロ・欠損0を確認後、Dを完了扱いにする。

## 停止条件

- occurrence_idで公開209件を一意にbackfillできない。
- 旧新でカード分類・日付表示・バッジ・並び順に説明不能な差が出る。
- RDBの対象外table、公開データ、site表示、mail本文に意図しない差が出る。
- Rstart checksum不一致、migrationの再実行非冪等、integrity/FK/audit失敗。
