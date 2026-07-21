# Firsthand field report operations

内田さん本人が実際に盆踊りイベントへ参加し、現地で聞いた曲目や、master RDB
にまだ無い新規イベントの存在を、Claude Code（こと）との会話から master RDB
へ反映するための運用手順。`data/bon_odori_master.sqlite` が正本で、S3 が
真のアーティファクト（`docs/master-rdb-s3-artifact.md` 参照）。Notion は
使わない。

本番apply（`--apply --confirm`）を実行してよいのは、dry-run結果をことがレ
ビューし、内田さんが明示的に承認した後だけ。

## 語彙表（新規追加した種別値）

スキーマ変更は不要（対象列はいずれもフリーテキスト、CHECK制約なし）。

| 列 | 値 | 用途 |
| --- | --- | --- |
| `evidence_items.platform` | `personal_firsthand` | 内田さん一次体験由来のevidence |
| `evidence_items.evidence_type` | `firsthand_attendance` | 現地参加による直接観測 |
| `evidence_items.source_key` | `uchida_firsthand` | 発信者の識別 |
| `event_occurrences.source_kind` | `personal_firsthand_current_year` | 新規イベント登録時のみ設定（既存イベントの曲追加では既存値を上書きしない） |
| `occurrence_evidence_links.target` | `firsthand_report` | 日付・会場・曲目をまとめて一次証拠として紐付ける対象 |
| `occurrence_songs.evidence_status` | `observed`（既存値を流用） | 実測（`export_public_events.py`で「実測」表示に変換される既存ロジックをそのまま使う） |
| `occurrence_songs.role` | `result`（既存値を流用） | 開催済みイベントの実測結果 |

`manual_apply_guards.FIRSTHAND_FIELD_REPORT_CONFIRMATION` = `"APPLY FIRSTHAND FIELD REPORT"`。

## レポートJSONスキーマ

ことが会話内容から `data/firsthand_reports/<slug>.json` に書き出す。

共通フィールド:

- `report_type`: `"existing_event_songs"` | `"new_event"`
- `reported_at`: ISO8601
- `raw_note`: ことが要約した内田さんの発言（evidence_items.text_excerptにそのまま入る証跡）
- `event_name_hint`: イベント名（正式名でなくてよい、あいまい検索の手がかり）
- `event_year`: int
- `event_date`: `YYYY-MM-DD`
- `event_date_end`: 省略可
- `source_url`: 省略可
- `uncertain`: bool 省略可（全体の確度を下げる。個別曲の`uncertain`が優先）
- `songs`: `[{"title": str, "uncertain"?: bool}]`（省略可、曲情報が無ければ空配列）

`existing_event_songs` 追加フィールド:

- `occurrence_id`: 省略可。ことが検索で1件に絞れた場合のみ埋める
- `venue_name_hint`: 省略可。あいまい検索の絞り込みに使う

`new_event` 追加フィールド:

- `venue`: `{"name": str, "address"?: str, "area"?: str, "access"?: str}`（`name`必須）
- `series_name`: 省略可（省略時は`event_name_hint`を使う）

## Step 0: 最新化

```sh
python3 master_db_s3_artifact.py fetch --overwrite
```

S3が正本なので、作業前に必ずローカルDBを最新化する。

## Step 1: dry-run review

```sh
python3 -m report_apply.apply_firsthand_field_report --report data/firsthand_reports/<slug>.json
```

- `data/firsthand_field_report_apply_report.json` / `.md` を生成する。
- 対象イベント/会場が1件に絞れない場合は **何も書き込まず** 、候補一覧を
  `issues` に返す。ことは候補を内田さんに提示し、`occurrence_id` を確定させ
  るか `venue.address` 等を補ってレポートJSONを修正し、再度dry-runする。
- ことがこのdry-run結果を内田さんに提示し、明示的なGOを待つ。

## Step 2: 本番apply

```sh
python3 -m report_apply.apply_firsthand_field_report \
  --report data/firsthand_reports/<slug>.json \
  --apply \
  --confirm 'APPLY FIRSTHAND FIELD REPORT'
```

- preflight（コピーDBに適用し監査でhigh issueが無いことを確認）→
  `data/backups/` へバックアップ→本番トランザクション適用→post-audit、
  という既存の安全機構（`apply_ph2_ebara_fifth_rdb.py`と同じ骨格）を通る。
- high issueが出た場合は自動的にロールバックされ、コミットされない。

## Step 3: S3へpublish（省略すると翌日の自動収集で上書き消失する）

`.github/workflows/collect.yml` は毎日15:13 JSTにS3から
`master_db_s3_artifact.py fetch --overwrite` でDBを取得し直す。ローカルで
`--apply`しただけでpublishを飛ばすと、その変更は翌日の自動サイクルで
消えてしまう。**apply成功後は必ず実行する**。

```sh
REMOTE_CHECKSUM=$(python3 master_db_s3_artifact.py status | sed -n 's/^remote_exists: .* checksum=//p')
python3 master_db_s3_artifact.py publish --expect-remote-checksum "$REMOTE_CHECKSUM"
```

## Step 4: git commit

sqlite本体（`data/bon_odori_master.sqlite`）はcommitしない
（`.gitignore`の`data/*.sqlite`対象）。commitするのは:

- `data/firsthand_reports/<slug>.json`（入力レポート）
- `data/firsthand_field_report_apply_report.json` / `.md`（applyレポート）
- `data/bon_odori_master_manifest.json`（`refresh_manifest_database_state`が更新）
- `data/bon_odori_master.schema.sql`（スキーマ変更があれば）

## スコープ外: 盆助サイトへの反映

このツールはmaster RDBへの反映までを担当する。盆助サイト
（bonsuke.jp）に実際に表示するには、別途 `export_public_events.py` の
実行とサイトデプロイ（既存の手動 `workflow_dispatch`）が必要。これは
内田さんの明示指示があったタイミングで、まとめて実施する
（「細かい修正は都度デプロイせず1日1回まとめor明示時」という既存運用
ルールに従う）。
