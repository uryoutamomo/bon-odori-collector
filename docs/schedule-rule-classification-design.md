# 開催パターン分類・日程予測 詳細設計

更新: 2026-06-20
署名: おと（Codex）

> 2026-06-23 update: 日程ルールの正規反映先はMaster RDBを優先する。
> Notion反映の記述は、旧設計または明示的な手動レビュー用途として扱う。

## 目的

YouTube、公式アーカイブ、X、ブログなどから集めた過去年実績を使い、イベント系列ごとに「曜日で決まるのか」「月日で決まるのか」を機械的に分けられるようにする。

この分類は、2026年の開催日を確定するためではなく、次の用途に使う。

- 公式情報を探す優先日・優先期間を決める。
- 今年未確認イベントに「過去実績にもとづく目安日」を出す。
- 2027年以降の冬ロールオーバーで翌年候補を作る。
- 曲目・雰囲気・規模感と同じく、イベント系列の継続的なプロフィールとして保持する。

短期的な位置づけ:

- これは「今夏の掲載数を大きく増やす施策」ではなく、来年以降に向けた系列ごとの開催パターン資産を蓄積する施策。
- 直近で効くのは、2年以上の観測が同一ルールで揃う系列に限る。
- 今年の公開増を期待値にせず、まずは十数件規模から分類品質を確認する。
- 観測が3年、4年と積み上がるほど効くため、日次フローでは「新規掲載数」より「判定可能系列数」「信頼度が上がった系列数」を見る。

## 前提

- イベントDBの1行は「年ごとの開催回」を表す。
- 日程ルールは年次開催回ではなく、イベント系列に近い情報として扱う。
- 過去年実績は今年の開催確定には使わない。
- 今年の確定日は、公式HP、自治体/主催発表、信頼できる今年X投稿などで確認できた場合だけ昇格する。
- 2020年、2021年は欠測または例外年になりやすいため、標準の5年判定からは原則として除外する。

## 収集範囲

当面は、2026年6月下旬と7月開催候補を中心に、過去5年分相当を集める。

優先年:

1. 2025年
2. 2024年
3. 2023年
4. 2022年
5. 2019年

補助年:

- 2026年: 今年の確定・実測として別扱い。
- 2020年、2021年: 開催中止・縮小・オンラインなどの例外確認に使うが、通常ルール推定の支持年には入れない。

優先月:

- 最優先: 6月下旬、7月
- 次点: 8月上旬
- 後続: 8月中旬以降、9月以降

## データモデル

### event_occurrence_observations

既存の `data/event_occurrence_observations.json` を、過去年開催回の観測テーブルとして使う。

必須に寄せるフィールド:

```json
{
  "observation_id": "string",
  "series_key": "string",
  "event_name": "丸の内de盆踊り",
  "venue": "行幸通り",
  "area": "千代田区",
  "year": 2025,
  "date_start": "2025-07-25",
  "date_end": "2025-07-25",
  "weekday_start": "金",
  "weekday_end": "金",
  "source_type": "youtube_backfill_observed",
  "source_kind": "youtube",
  "source_video_count": 3,
  "source_urls": [],
  "confidence": "high",
  "date_precision": "exact",
  "date_evidence_type": "observed_actual",
  "review_status": "accepted"
}
```

追加したい意味:

- `source_kind`: `youtube` / `official_archive` / `x` / `blog` / `manual`。
- `date_precision`: `exact` / `range` / `month_only` / `unknown`。
- `date_evidence_type`: `observed_actual` / `announcement` / `poster_image` / `title_inferred` / `published_date_inferred`。
- `review_status`: `accepted` / `review` / `rejected`。

X由来では投稿日と開催日がズレやすいため、本文や画像から開催日が読めないものは `date_precision=unknown` とし、日程ルール推定には使わない。

### series_key の品質

開催パターン分類は、日付推定より前に系列名寄せの品質に強く依存する。

同じイベントが別 `series_key` に割れると、2年一致・3年一致が成立せず、分類効果はゼロになる。
逆に別イベントが同じ `series_key` に混ざると、曜日固定・固定日判定が誤る。

実装前に確認すること:

- `observations` と `series` の辞書構造が `series_key` 基準で一貫している。
- 代表名、会場名、別名、年号つき表記を正規化してから `series_key` を作る。
- `event_schedule_rules.md` には `series_key`、正規名、会場、根拠年を出し、名寄せ違和感をレビューできるようにする。
- `venue_ambiguous`、`series_split_suspected`、`series_merge_suspected` を警告として出す。

### event_series_schedule_rules

新しい中間成果物として、系列ごとの開催パターン分類を作る。

出力先候補:

- `data/event_schedule_rules.json`
- `data/event_schedule_rules.md`

構造:

```json
{
  "series_key": "abc123",
  "event_name": "丸の内de盆踊り",
  "venue": "行幸通り",
  "target_year": 2026,
  "rule": {
    "rule_type": "weekday_last",
    "primary_axis": "weekday",
    "confidence": "medium",
    "score": 0.74,
    "basis": "7月の最終金曜",
    "evidence_years": [2024, 2025],
    "evidence_count": 2,
    "coverage_years": [2024, 2025],
    "missing_years": [2023, 2022, 2019],
    "exception_years": [],
    "date_rule": null,
    "weekday_rule": {
      "month": 7,
      "weekday": 4,
      "weekday_label": "金",
      "nth": null,
      "is_last": true
    },
    "near_rule": null,
    "duration_days": 1,
    "predicted_date_start": "2026-07-31",
    "predicted_date_end": "2026-07-31",
    "warnings": []
  },
  "candidate_rules": [],
  "observations": []
}
```

## 分類体系

`rule_type` は既存の `build_event_date_predictions.py` と互換にする。

| rule_type | primary_axis | 意味 | 例 |
| --- | --- | --- | --- |
| `fixed_date` | `date` | 毎年同じ月日で開始 | 毎年6/13 |
| `fixed_date_range` | `date` | 毎年同じ月日範囲 | 毎年8/1〜8/2 |
| `weekday_last` | `weekday` | 月の最終X曜 | 7月最終金曜 |
| `weekday_nth` | `weekday` | 月の第N X曜 | 8月第3土曜 |
| `weekday_near_day` | `weekday_near_date` | 特定日前後の同じ曜日 | 7/16前後の土曜 |
| `weekend_near_day` | `weekend_near_date` | 特定日前後の週末 | 8/9前後の週末 |
| `date_near` | `near_date` | 月日近辺だが曜日規則が弱い | 7/26前後 |
| `seasonal_hint` | `seasonal` | 月・旬だけ | 7月下旬 |
| `unknown` | `unknown` | 判定不可 | なし |

公開やNotion上で内田さん向けに見せる場合は、以下の日本語ラベルにする。

| primary_axis | 表示ラベル |
| --- | --- |
| `date` | 同一日タイプ |
| `weekday` | 同一曜日タイプ |
| `weekday_near_date` | 曜日優先・日付近傍タイプ |
| `weekend_near_date` | 週末寄せタイプ |
| `near_date` | 日付近傍タイプ |
| `seasonal` | 時期目安タイプ |
| `unknown` | 不明 |

## ルール判定の特徴量

各観測日から以下を計算する。

```json
{
  "year": 2025,
  "month": 7,
  "day": 25,
  "weekday": 4,
  "weekday_label": "金",
  "nth_weekday": 4,
  "is_last_weekday": true,
  "is_weekendish": true,
  "duration_days": 1,
  "day_of_year": 206
}
```

`is_weekendish` は木・金・土・日を広めに含める。盆踊りは金土、土日、土月祝のような開催が多いため、土日だけに狭めすぎない。

## スコアリング

### 候補ルール生成

系列ごとに、以下の候補を作る。

1. `fixed_date`: 同じ `month/day` が2年以上一致。
2. `fixed_date_range`: 同じ開始月日・終了月日が2年以上一致。
3. `weekday_last`: 同じ月の最終同一曜日が2年以上一致。
4. `weekday_nth`: 同じ月の第N同一曜日が2年以上一致。
5. `weekday_near_day`: 同じ月・同じ曜日で、日付差が7日以内。
6. `weekend_near_day`: 同じ月で、週末寄せかつ日付差が7日以内。
7. `date_near`: 同じ月で、日付差が7日以内。
8. `seasonal_hint`: 月または旬だけ分かる。

`seasonal_hint` は、既存の `public_json_postprocessors/apply_public_season_hints.py` と役割が重複しやすい。
最初の実装では `event_schedule_rules` 側は `seasonal_hint` を正規ルールとして生成しない。
月・旬だけの公開ヒントは、既存どおり `public_json_postprocessors/apply_public_season_hints.py` を正本とする。

`event_schedule_rules` 側が扱うのは、原則として日付または曜日を含む観測がある系列だけにする。
どうしても統合する場合は、後続フェーズで `public_json_postprocessors/apply_public_season_hints.py` の責務を `event_schedule_rules` に移す。

### 基本スコア

| 条件 | 目安スコア |
| --- | --- |
| 4年以上一致 | 0.90 |
| 3年以上一致 | 0.82〜0.88 |
| 2年一致 | 0.70〜0.78 |
| 3年以上で近傍一致 | 0.64〜0.78 |
| 2年で近傍一致 | 0.55〜0.68 |
| 1年のみ | 0.30〜0.45 |

### 補正

加点:

- 公式アーカイブまたは主催告知で日付確認: `+0.04`
- タイトル・説明・チラシ画像で開催日が明示: `+0.03`
- 複数動画・複数チャンネルで同日確認: `+0.02`
- 「毎年」「恒例」「第N回」など継続性語あり: `+0.02`

減点:

- 投稿日からの推定だけ: `-0.15`
- イベント名または会場が曖昧: `-0.10`
- 年ズレ疑い: `-0.10`
- 同じ系列で別ルール候補が同点に近い: `-0.05`
- 開催期間の一部日だけ観測: `-0.05`

## 信頼度

| confidence | 条件 |
| --- | --- |
| `high` | 3年以上の実績が同じルールで一致、または2年以上一致かつ公式に「毎年X」と明記 |
| `medium` | 2年実績が同じルールで一致 |
| `low` | 1年のみ、または近傍一致だが別ルール候補と競合 |
| `manual_verified` | 人間レビューで系列ルールとして固定 |

既存の `build_event_date_predictions.py` では、スコアから機械的に `high` / `medium` / `low` を返している。
新設する `event_schedule_rules` では、年数ベースの定義を正本にする。

実装時の扱い:

- `rule_confidence`: 上記の年数・根拠種別ベースの分類。
- `score`: ソートや競合解決に使う連続値。
- `legacy_prediction_confidence`: 既存 `build_event_date_predictions.py` 互換が必要な場合だけ残す。

`confidence` の意味が年数ベースとスコア閾値ベースでズレないよう、公開JSONへ出す場合は `rule_confidence` を使う。

欠測年は原則として減点しない。例えば2025年・2024年だけ取れていて2023年が未取得でも、2年一致なら `medium` にする。

一方で、2025年と2024年が明確に別ルールの場合は、`unknown` または `date_near` に落とす。

## 競合解決

候補ルールが複数ある場合は、スコア優先で選ぶ。ただし同点に近い場合は以下の順で優先する。

1. `fixed_date_range`
2. `fixed_date`
3. `weekday_last`
4. `weekday_nth`
5. `weekday_near_day`
6. `weekend_near_day`
7. `date_near`
8. `seasonal_hint`

理由:

- 固定日は公式・町会運用で明記されやすく、曜日スライドより強い。
- 「最終金曜」「第3土曜」は翌年予測に使いやすい。
- 近傍系は便利だが、確定日と誤認されやすいので少し弱く扱う。

ただし、固定日と曜日固定の競合は、単純な優先順位だけで決めない。
盆踊りでは「町会・商店街は週末寄せ」「神社祭礼・送り盆は固定日寄せ」になりやすい。

固定日を優先する条件:

- 公式・主催・自治体などに「毎年X月Y日」「例年X月Y日」と明記されている。
- 3年以上で同じ月日または同じ月日範囲が一致する。
- 固定日カラムまたは `fixed_date_rule` が人間レビュー済み。

曜日固定を優先する条件:

- 固定日候補が2年だけの偶然一致で、同時に `weekday_last` / `weekday_nth` が成立する。
- 町会・商店街・駅前イベントなど、週末開催に寄りやすい系列である。
- 3年以上で同一曜日ルールが一致する。

競合時は、`candidate_rules` に両方を残し、選ばなかった候補もレビューMDに出す。
実装では `tie_break_reason` を出す。

## 出力と既存コードの接続

### 既存のまま使うもの

- `build_event_date_predictions.py`
  - 現在の `rule_type` 推定と予測日生成を活かす。
- `public_json_postprocessors/apply_public_date_predictions.py`
  - 確定日があるイベントには予測を付けない挙動を維持する。
- `public_json_postprocessors/apply_public_historical_references.py`
  - 過去実績カードへの目安日付付与を維持する。

### 追加するもの

1. `youtube_backfill/build_event_schedule_rules.py`
   - `event_occurrence_observations.json` から系列ルールを生成する。
   - `event_date_predictions.json` より上位の「分類結果」を出す。
2. `data/event_schedule_rules.json`
   - 系列ルールの正規中間成果物。
3. `data/event_schedule_rules.md`
   - 人間レビュー用サマリ。
4. `sync_schedule_rules_to_notion.py`
   - レビュー済みの高信頼ルールだけ Notion の開催パターン系プロパティへ反映する。

### Notion反映先

既存プロパティを優先して使う。

- `開催パターン種別`
  - `固定日`
  - `曜日固定`
  - `週末寄せ`
  - `日付近傍`
  - `時期目安`
  - `不明`
- `開催パターン詳細`
  - `[schedule_rule] 7月最終金曜。根拠: 2024, 2025 YouTube実績。confidence=medium`

固定日については既存の固定日カラムも使う。

- `固定日開始月`
- `固定日開始日`
- `固定日終了月`
- `固定日終了日`
- `固定日根拠URL`

曜日固定用の新規プロパティを増やす場合の候補:

- `曜日ルール月`
- `曜日ルール種別`: `第N曜日` / `最終曜日` / `日付近傍曜日`
- `曜日ルール第N`
- `曜日ルール曜日`
- `曜日ルール基準日`
- `開催パターン信頼度`
- `開催パターン根拠年`

ただし、最初はプロパティを増やさず、JSON/MDと `開催パターン詳細` で運用する。

## 6月下旬・7月向け運用

### 対象抽出

対象は以下のどちらかに該当するイベント系列。

- 公開JSONの `months` に `6` または `7` がある。
- `historical_reference` または `date_prediction` の日付が6月下旬から7月に入る。

6月は下旬だけを優先する。

- 6/20以降
- 6月中旬以前は、今年すでに終了している可能性が高いため後回し

### 収集優先順位

1. 2025年・2024年が両方欠けている7月主要イベント。
2. 2025年だけあるイベントの2024年。
3. 2024年だけあるイベントの2025年。
4. 2年揃ったが競合しているイベントの2023年。
5. `medium` から `high` に上げたい重要イベントの2023年・2022年・2019年。

YouTube APIが使えない日は、以下だけ進める。

- 既存候補のレビュー。
- 公式アーカイブ検索用クエリの作成。
- Xやブログの候補URL整理。
- `event_schedule_rules.md` の人間レビュー。

## 毎日のフローへの組み込み

既存の日次処理 `run_daily_youtube_backfill.py` には、すでに以下が入っている。

1. YouTube過去年候補を少量取得する。
2. `youtube_backfill/build_event_occurrence_backfill_plan.py` で開催回観測候補を作る。
3. `youtube_backfill/apply_event_occurrence_backfill_plan.py` でレビュー済み観測を `event_occurrence_observations.json` へ反映する。
4. `build_event_date_predictions.py --target-year 2026` で日付予測を作る。
5. `public_json_postprocessors/apply_public_date_predictions.py` で公開JSONへ予測を付ける。
6. `public_json_postprocessors/apply_public_historical_references.py`、`public_json_postprocessors/apply_public_season_hints.py`、`export_public_events.py` で公開成果物を再生成する。

今回の開催パターン分類は、この4番の前に入れる。

追加後の日次フロー:

```text
YouTube/公式/X/ブログ候補
  -> event_occurrence_backfill_plan
  -> event_occurrence_observations
  -> event_schedule_rules
  -> event_date_predictions
  -> public events
  -> month backfill queue
```

具体的には `run_daily_youtube_backfill.py` の `regenerate_outputs()` を次の順序にする。

```text
python3 -m youtube_backfill.build_event_occurrence_backfill_plan
python3 build_low_confidence_backfill_review.py
python3 -m youtube_backfill.apply_event_occurrence_backfill_plan
python3 -m youtube_backfill.build_event_schedule_rules --target-year 2026
python3 build_event_date_predictions.py --target-year 2026
python3 -m public_json_postprocessors.apply_public_date_predictions
python3 -m public_json_postprocessors.apply_public_historical_references
python3 -m public_json_postprocessors.apply_public_season_hints
python3 build_song_occurrences.py
python3 export_public_events.py
python3 -m public_json_postprocessors.apply_public_date_predictions
python3 -m public_json_postprocessors.apply_public_historical_references
python3 -m public_json_postprocessors.apply_public_season_hints
python3 -m youtube_backfill.build_month_youtube_backfill_queue --month N
```

ただし、毎日フル再生成を重くしすぎない。

実装時は2モードに分ける。

- `daily-light`: API取得、観測反映、`event_schedule_rules`、`event_date_predictions`、月別キュー更新、日次レポートまで。
- `daily-full`: `daily-light` に加えて `export_public_events.py` と apply系3本を再実行し、公開JSONまで更新。

APIが429の日やレビューだけの日は `daily-light` を基本にする。
公開JSONに影響する変更を出す日は `daily-full` にする。

日次コミット対象にも以下を追加する。

- `data/event_schedule_rules.json`
- `data/event_schedule_rules.md`

### APIが叩けた日の動き

- 新しいYouTube候補を取得する。
- strong/review候補から開催回観測を増やす。
- 増えた観測年で `event_schedule_rules` を再計算する。
- `medium` 以上の系列は予測日生成へ流す。
- 6月下旬・7月の次回探索キューを更新する。

### APIが429などで叩けない日の動き

APIが止まっても、分類フローは止めない。

- 既存候補とレビュー済み判断だけで `event_occurrence_observations` を更新する。
- `event_schedule_rules` を再生成する。
- `event_schedule_rules.md` で競合・低信頼・不足年を確認する。
- 公式アーカイブ、X、ブログの手動探索対象を `month_N_youtube_backfill_queue` または別レビューMDへ積む。

この日の成果は「新規API取得」ではなく、既存証拠の整理、分類、次回探索優先度の改善とする。

### 日次レポートに出す指標

`youtube_daily_backfill_report.md` には、開催パターン分類の指標も追加する。

- `schedule_rule_count`
- `schedule_rule_confidence_counts`
- `schedule_rule_axis_counts`
- `new_medium_or_high_rules`
- `conflicting_rule_count`
- `june_late_july_target_count`
- `series_key_warning_count`

これにより、日々の収集が「動画候補が増えたか」だけでなく、「同一日/同一曜日の判定が何件増えたか」で見えるようになる。

## X・ブログ・公式アーカイブの扱い

X:

- チラシ画像や本文に日付がある場合だけ、日程ルール推定に使う。
- 「今日」「昨日」「行ってきた」だけの場合は、開催確認には使っても日付ルールには使わない。
- 投稿日を開催日として使う場合は `date_evidence_type=published_date_inferred` として減点する。

ブログ:

- タイトルまたは本文に日付があれば使う。
- 旅行記・参加記は投稿日と開催日がズレることがあるため、本文中の日付を優先する。

公式アーカイブ:

- 最も強い過去年実績。
- 「令和7年」「2025年」など年が明示され、開催日が読めるものは `confidence=high` にしやすい。

## レビューキュー

`event_schedule_rules.md` には以下の列を出す。

| confidence | axis | rule | predicted | event | venue | evidence_years | observations | warnings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

警告例:

- `conflicting_rules`: 固定日と曜日固定が競合。
- `single_day_from_multi_day_event`: 複数日開催の一部だけ観測。
- `date_from_publish_time`: 投稿日からの推定。
- `venue_ambiguous`: 会場一致が弱い。
- `series_split_suspected`: 同じ系列らしい観測が別キーに割れている。
- `series_merge_suspected`: 別系列らしい観測が同じキーに混ざっている。
- `year_mismatch`: 動画タイトル年と対象年がズレる。
- `missing_recent_year`: 2025年実績がなく2024年以前だけ。

## 実装順序

1. `series_key` 品質チェックを先に入れ、名寄せ警告を `event_schedule_rules.md` に出せるようにする。
2. 既存 `build_event_date_predictions.py` の候補生成を `youtube_backfill/build_event_schedule_rules.py` 側へ共通化する。
3. 固定日と曜日固定のタイブレーク方針を実装する。
4. `data/event_schedule_rules.json/md` を生成する。
5. `build_event_date_predictions.py` は `event_schedule_rules.json` を読んで予測日に変換する形へ寄せる。
6. 6月下旬・7月対象だけでdry-runする。
7. `medium` 以上のルールをレビューし、問題なければ公開JSONへ `schedule_rule` として添付する。
8. 高信頼・固定日だけ Notion へ反映する。
9. 2027年以降の冬ロールオーバーで、翌年候補生成に使う。

## 完了条件

最初の実用版では、以下を満たせばよい。

- 6月下旬・7月の対象について、2年以上観測がある系列を一覧化できる。
- `同一日タイプ` と `同一曜日タイプ` を明示的に分けられる。
- `weekday_near_day` と `weekend_near_day` を、固定ルールより弱い近傍タイプとして扱える。
- 予測日は公開上「予測」「目安」「公式未確認」として扱われる。
- 今年の確定日があるイベントには予測日を上書きしない。
- 人間レビュー用MDで、根拠年・観測日・警告が見える。
