# Master RDB Ph1 freeze release proposal

- generated_at: 2026-06-21T02:50:00+09:00
- status: proposal_only
- scope: Ph1 occurrence_songs public export release

## 判定

freeze は削除しない。

Ph1 で本番反映済みの公開曲目 export だけを通常運用へ戻し、旧 `song_occurrences.json`
生成経路は凍結を維持する。

## 解除候補

- `data/public/event_song_occurrences_public.json`
- `data/public/event_songs_public.json`

## 凍結維持

- `data/song_occurrences.json`
- `data/song_prediction_snapshots.json`
- `data/song_prediction_calibration.json`

## 必要な workflow 変更案

### 共通方針

freeze 判定を「ファイルの有無」だけで扱うのは Ph1 後には粗すぎる。
ただし、いきなり freeze ファイルを削除すると旧 `build_song_occurrences.py` 経路が再開するため危険。

実変更時は、`data/master_rdb_migration_freeze.json` に group を追加し、workflow は group 単位で判定する。

推奨する記録形式:

```json
{
  "active": true,
  "freeze_groups": {
    "legacy_song_occurrence_generation": {
      "active": true,
      "files": [
        "data/song_occurrences.json",
        "data/song_prediction_snapshots.json",
        "data/song_prediction_calibration.json"
      ],
      "actions": [
        "build_song_occurrences.py",
        "calibrate_song_predictions.py",
        "run_daily_youtube_backfill.py --commit/--push"
      ]
    },
    "ph1_public_song_export_files": {
      "active": false,
      "released_at": "2026-06-21",
      "released_by": "おと（Codex）",
      "files": [
        "data/public/event_song_occurrences_public.json",
        "data/public/event_songs_public.json"
      ],
      "source_of_truth": "data/bon_odori_master.sqlite"
    }
  },
  "default_policy": {
    "unknown_group": "frozen",
    "malformed_freeze_file": "frozen"
  }
}
```

`released_files` より `freeze_groups` / `ph1_public_song_export_files` を推奨する。
理由は、解除済みファイルだけでなく「何をまだ止めているか」「どの action を止めるか」を同じ構造で表せるため。

### `.github/workflows/collect.yml`

- `data/master_rdb_migration_freeze.json` がある間は、引き続き `build_song_occurrences.py` と
  `calibrate_song_predictions.py` を実行しない。
- commit step では、freeze 中でも以下2ファイルだけ stage 可能にする。
  - `data/public/event_songs_public.json`
  - `data/public/event_song_occurrences_public.json`
- `data/song_occurrences.json` / `data/song_prediction_snapshots.json` /
  `data/song_prediction_calibration.json` は stage しない。

### `.github/workflows/weekly_harvest.yml`

- `collect.yml` と同じ。
- 週次レビューキューや公開イベントは従来どおり進める。
- 旧曲実績ソース生成は止め続ける。

## レビュー観点への回答

### (a) 通常運用へ戻すステップ / 凍結維持するステップ

戻す:

- `export_public_events.py` による `data/public/event_songs_public.json` 更新。
- `data/public/event_song_occurrences_public.json` の stage。
  - 現状の Actions ではこのファイルを生成する step はないため、通常は変化しない。
  - 将来 SQLite 由来 export step を Actions に入れる場合の受け皿として stage 可能にする。

凍結維持:

- `build_song_occurrences.py`
- `calibrate_song_predictions.py`
- `data/song_occurrences.json`
- `data/song_prediction_snapshots.json`
- `data/song_prediction_calibration.json`
- `run_daily_youtube_backfill.py --commit/--push`

### (b) 公開 export 経路が SQLite 由来で固定されること

Ph1 後の前提:

- `data/public/event_song_occurrences_public.json` は SQLite 由来生成物。
- `export_public_events.py` はこのファイルを読み、`events_public.json` と `event_songs_public.json` に曲目ヒントを反映する。
- Actions では旧 `build_song_occurrences.py` を再実行しないため、公開 export の曲 occurrence 入力は SQLite 由来のまま維持される。

将来の実変更では、commit step のログに以下を出す。

```sh
echo "[master-rdb] Ph1 public song export released; legacy song occurrence source remains frozen"
```

### (c) freeze 判定粒度と安全側の既定値

判定粒度:

- group: `legacy_song_occurrence_generation`
- group: `ph1_public_song_export_files`

安全側の既定値:

- freeze JSON が存在し、group が不明なら frozen 扱い。
- freeze JSON が壊れて読めない場合も frozen 扱い。
- `active=false` が明示されている group だけ解除扱い。
- `data/master_rdb_migration_freeze.json` 自体がない場合は、現行どおり通常運用。ただし移行期間中は削除しない。

実装案:

- 小さな helper script を追加する。
  - 例: `master_rdb_freeze_policy.py is-frozen legacy_song_occurrence_generation`
  - 例: `master_rdb_freeze_policy.py is-released ph1_public_song_export_files`
- workflow に JSON parsing を直書きしない。
- helper が異常終了した場合は workflow 側で frozen とみなす。

### (d) concurrency group

現状の `bon-odori-master-rdb` を維持する。

- `collect.yml`
- `weekly_harvest.yml`
- `send_mail.yml`
- `review_x_candidate_posts.yml`
- `discover_x_social_graph.yml`

段階解除は concurrency を緩めるものではない。
writer の直列化は継続する。

### (e) ロールバック手順

問題が出た場合:

1. `data/master_rdb_migration_freeze.json` の `ph1_public_song_export_files.active` を `true` に戻す。
2. `collect.yml` / `weekly_harvest.yml` の stage 対象から公開曲目2ファイルを外す、または helper 判定で stage しない状態に戻す。
3. 必要なら `data/public/event_song_occurrences_public.json` / `data/public/event_songs_public.json` を直前コミットへ revert。
4. site 側は `bon-odori-site` のデプロイコミット `a573473` を revert し、`Deploy static site` を再実行。
5. こと再検証後、内田さんへロールバック完了を報告。

この rollback は `song_occurrences.json` 系を再開しない。
再開が必要な場合は Ph2/Ph3 の別判断にする。

## collector↔site `events_public.json` 乖離概要

2026-06-21 時点のローカル作業ツリー比較:

- event key 件数: collector 182 / site 182。
- collector にだけあるイベント: 0。
- site にだけあるイベント: 0。
- 共通イベントの内容差分: 181。

主要カテゴリ:

- site 側にだけ historical/season 表示補助フィールドが残っている。
  - `historical_reference`: 94イベント。
  - `historical_slide`: 76イベント。
  - `season_hint`: 59イベント。
- collector 側にだけ `date_prediction` があるイベントが2件ある。
  - `歌舞伎町BON ODORI`
  - `赤坂浄土寺盆踊り大会`
- collector 側には `fixed_date_rule` key が広く出ている。
  - 多くは `null`。
  - site 側にはこの key がない。
- detail 差分は2件。
  - 山王音頭と民踊大会
  - 花園神社 盆踊り

解釈:

- Ph1デプロイで site 側へ collector の `events_public.json` を丸ごとコピーしなかった判断は正しい。
- 乖離の中心は曲 occurrence ではなく、historical/season/date prediction の公開後段処理と固定日ルール表示の扱い。
- Ph2やマスタ正本切替前に、collector 側の公開export後段と site 側の正データをどちらへ寄せるか棚卸しが必要。
- この乖離は Ph1 freeze 解除のブロッカーではないが、`events_public.json` 全体の自動デプロイ再開前には解消または明示承認が必要。

### `run_daily_youtube_backfill.py`

- `--commit` / `--push` ガードは維持する。
- 現状の `regenerate_outputs()` は `build_song_occurrences.py` を呼ぶため、
  Ph2前に commit/push を戻すと SQLite 正本と旧JSON経路が乖離し得る。

### `data/master_rdb_migration_freeze.json`

- ファイル自体は残す。
- `active=true` は維持する。
- `released_files` または `public_export_release` を追加して、
  Ph1範囲だけ解除済みであることを明示する。

## 理由

- Ph1 の本番公開JSONはデプロイ済みで、こと再検証・本番検証とも合格。
- ただし `build_song_occurrences.py` を戻すと、旧経路で `data/song_occurrences.json` が再生成され、
  SQLite由来の公開曲実績とズレる可能性がある。
- 通常の公開イベント export は、Notion 側のイベント変更に追随する必要がある。
  そのため `event_songs_public.json` の stage は戻したい。
- 現行 workflow は freeze ファイルの存在だけで旧生成を止めているため、
  freeze ファイル削除ではなく段階解除が必要。

## レビュー依頼

ことレビュー後、内田さんGOがあれば workflow と freeze JSON をこの方針で更新する。
