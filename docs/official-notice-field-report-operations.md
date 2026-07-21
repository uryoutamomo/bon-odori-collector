# Official notice field report operations

内田さんが撮影・受信した町の掲示板・回覧板・公式チラシなどの画像を、Claude
Code（こと）が書き起こし、master RDBへ反映するための運用手順。`data/bon_odori_master.sqlite`
が正本で、S3が真のアーティファクト（`docs/master-rdb-s3-artifact.md`参照）。Notionは
使わない。[[project_bon-odori-firsthand-field-report]]（本人の一次体験を反映する対の機能）
と役割を分ける：こちらは本人の実測ではなく、公式/第三者発信の掲示物という情報源。

1枚の掲示物・チラシから複数の盆踊りイベント情報が得られるのが典型的なケース
（連合町会のチラシ等）。1レポート=1掲示物として、複数イベントをまとめて処理する。

本番apply（`--apply --confirm`）を実行してよいのは、dry-run結果をことがレ
ビューし、内田さんが明示的に承認した後だけ。

## 語彙表（新規追加した種別値）

スキーマ変更は不要（対象列はいずれもフリーテキスト、CHECK制約なし）。

| 列 | 値 | 用途 |
| --- | --- | --- |
| `evidence_items.platform` | `web` | 掲示物・チラシ由来のevidence |
| `evidence_items.evidence_type` | `poster_post` | ポスター/チラシ的な一次資料 |
| `event_occurrences.source_kind` | `official_current_year`（公式）/ `third_party_current_year`（非公式回覧等） | イベント単位で`notice_kind_override`により上書き可 |
| `occurrence_evidence_links.target` | `date_venue_program` | 日付・会場・プログラムの根拠 |
| `occurrence_songs.role` | `setlist` | 告知された予定曲目（内田さんの実測`result`とは区別） |
| `occurrence_songs.evidence_status` | `announced` | 告知・予定（実測`observed`ではない） |

`manual_apply_guards.OFFICIAL_NOTICE_FIELD_REPORT_CONFIRMATION` = `"APPLY OFFICIAL NOTICE FIELD REPORT"`。

## レポートJSONスキーマ

ことが掲示物の内容から `data/official_notice_reports/<report_id>.json` に書き出す。

トップレベル:

- `report_type`: 固定で `"official_notice"`
- `reported_at`: ISO8601
- `source`: `{"report_id": str, "title": str, "account_key": str(発行元), "raw_text": str(全文書き起こし), "url"?: str, "notice_kind"?: str(既定 official_current_year)}`
- `events`: 下記オブジェクトの配列（**非空必須**）
- `skipped_events`: 省略可。`[{"name": str, "reason": str}]`。判定保留・スコープ外の記録用（書き込みはされない）

`events`の各要素、共通フィールド:

- `action`: `"confirm_existing"` | `"register_new"`
- `venue`: 省略可。`{"name": str, "area"?: str, "address"?: str, "access"?: str}`
- `date_start` / `date_end`: 省略可（`confirm_existing`で両方省略すると「detail追記のみ」）
- `detail_addendum`: 省略可。既存detailへ冪等に改行追記（同一文字列があれば追記しない）
- `notice_kind_override`: 省略可。このイベントだけ`source.notice_kind`と異なる種別にしたい場合
- `songs`: 省略可。`[{"title": str, "uncertain"?: bool}]`

`confirm_existing`追加フィールド:

- `occurrence_id`: 省略可。ことが検索で1件に絞れた場合のみ埋める
- `match_hint`: `occurrence_id`が無い場合必須。`{"event_name_hint": str, "venue_name_hint"?: str, "event_year"?: int}`

`register_new`追加フィールド（必須）:

- `event_name_hint`, `event_year`, `date_start`, `venue.name`
- `series_name`: 省略可（省略時は`event_name_hint`を使う）

## Step 0: 最新化

```sh
python3 master_db_s3_artifact.py fetch --overwrite
```

## Step 1: dry-run review

```sh
python3 -m report_apply.apply_official_notice_report --report data/official_notice_reports/<report_id>.json
```

- `data/official_notice_report_apply_report.json` / `.md` を生成する。
- **部分適用方針**: 一部のイベントが曖昧で解決できなくても、確定できたイベントだけ
  適用され`db_committed=True`になる。曖昧なイベントは`issues`に`severity=medium`
  として記録され、書き込まれない（他の確定イベントの適用を妨げない）。真のデータ
  不整合（FK違反等）のみ`severity=high`で全体ロールバックする。
- ことがこのdry-run結果を内田さんに提示し、明示的なGOを待つ。

## Step 2: 本番apply

```sh
python3 -m report_apply.apply_official_notice_report \
  --report data/official_notice_reports/<report_id>.json \
  --apply \
  --confirm 'APPLY OFFICIAL NOTICE FIELD REPORT'
```

- `report_apply/apply_firsthand_field_report.py`と同じ安全機構（preflight→backup→本番トランザ
  クション→post-audit）を通る。

## 一部イベントが曖昧なままだった場合の再実行

同一レポートJSONは冪等。曖昧だったイベントを解決（`occurrence_id`を明示指定する、
`venue.address`を補うなど）してから同じファイルを再度`--apply`すれば、既に適用
済みのイベントはno-op、新たに解決したイベントだけが反映される。

## Step 3: S3へpublish（省略すると翌日の自動収集で上書き消失する）

```sh
REMOTE_CHECKSUM=$(python3 master_db_s3_artifact.py status | sed -n 's/^remote_exists: .* checksum=//p')
python3 master_db_s3_artifact.py publish --expect-remote-checksum "$REMOTE_CHECKSUM"
```

## Step 4: git commit

sqlite本体はcommitしない（`.gitignore`の`data/*.sqlite`対象）。commitするのは:

- `data/official_notice_reports/<report_id>.json`（入力レポート）
- `data/official_notice_report_apply_report.json` / `.md`（applyレポート）
- `data/bon_odori_master_manifest.json`

## 一回限りスクリプトからの移行方針

`legacy/apply/apply_kyobashi5_nouryou_map_2026.py`は、この機能が無かった時期に書いた一回限り
のスクリプト。今後、同様の掲示物・チラシ反映で新規スクリプトは作らず、この
`report_apply/apply_official_notice_report.py`を使う。`legacy/apply/apply_kyobashi5_nouryou_map_2026.py`
自体は過去の実行記録として凍結保持する（削除しない）。

## スコープ外: 盆助サイトへの反映

このツールはmaster RDBへの反映までを担当する。盆助サイト（bonsuke.jp）への
表示反映は別途、内田さんの明示指示があったタイミングでまとめて実施する
（firsthand機能と同じ運用ルール）。
