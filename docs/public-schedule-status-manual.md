# 公開日程ステータス運用マニュアル

更新: 2026-07-20
署名: おと（Codex）

## 目的

公開サイトで、今年の開催確定情報と、過去年の実績にもとづく参考情報を混同しない。
2025年だけでなく、2024年・2023年などのYouTube/公式アーカイブ/X実績が追加されても破綻しない分類で運用する。

## 基本原則

- 「今年の開催日が確定しているか」と「未確認情報の根拠が何か」を分ける。
- 過去年の開催実績は、今年の開催確定にはしない。
- 過去年のYouTubeは、過去実績・曲目・雰囲気・開催時期の推定材料として使う。
- 今年の公式HP、自治体/主催発表、信頼できる今年X投稿は、今年の開催日・開催確定の直接証拠にできる。
- `last_year` や `recurring_last_year` を新しい正規概念にしない。過去年実績は `historical_reference` として扱う。

## 正本となる2軸

現在の正規入力は `current_event_state × date_certainty_tier` の2軸である。

| 軸 | 有限値 | 意味 |
| --- | --- | --- |
| `current_event_state` | `predicted` / `announced` / `confirmed` / `ended` / `cancelled` | 今年の開催状態 |
| `date_certainty_tier` | `confirmed` / `rule_predicted` / `historical_slide` / `season_hint` / `historical_reference` | 日付・時期情報の確度と根拠 |

`confirmed` と `ended` は `date_certainty_tier=confirmed` を必須とする。
`predicted` / `announced` に `confirmed` tierは使わない。過去実績があっても、今年の直接証拠がなければ
`confirmed` に昇格させない。

`public_category`、`display_tier`、画面上のラベルは、この2軸から生成する互換・表示フィールドである。
新しいwriterや判断ロジックで、これら旧フィールドを独立更新してはならない。

## 互換公開カテゴリ

以下は2軸から機械生成する旧JSONとの対応であり、正本ではない。

| `current_event_state` | `date_certainty_tier` | `public_category` | `display_tier` |
| --- | --- | --- | --- |
| `confirmed` | `confirmed` | `upcoming` | `confirmed` |
| `ended` | `confirmed` | `ended` | `ended` |
| `cancelled` | 任意 | `cancelled` | `cancelled` |
| `predicted` / `announced` | `rule_predicted` | `recurring_last_year` | `rule_predicted` |
| `predicted` / `announced` | `historical_slide` | `recurring_last_year` | `historical_slide` |
| `predicted` / `announced` | `historical_reference` | `recurring_last_year` | `historical_reference` |
| `predicted` / `announced` | `season_hint` | `date_unknown` | `season_hint` |

## 推奨データ構造

公開JSONは2軸を必須とし、表示互換のため旧フィールドも派生出力する。

```json
{
  "current_event_state": "predicted",
  "date_certainty_tier": "historical_reference",
  "public_category": "recurring_last_year",
  "display_tier": "historical_reference",
  "current_year": 2026,
  "current_date_status": "unconfirmed",
  "historical_occurrences": [
    {
      "year": 2025,
      "date": "2025-07-26",
      "date_end": "2025-07-27",
      "source_kind": "youtube",
      "source_count": 2
    },
    {
      "year": 2024,
      "date": "2024-07-27",
      "source_kind": "official_archive",
      "source_count": 1
    }
  ],
  "latest_seen_year": 2025,
  "evidence_years": [2025, 2024],
  "continuity_score": 0.78
}
```

運用上の意味:

- `current_event_state` と `date_certainty_tier` が判断の正本。
- `public_category` は公開表示互換の派生値。
- `current_date_status` は今年情報の確定状態。`confirmed` / `candidate` / `unconfirmed` / `ended` を使う。
- `historical_occurrences` は過去年の実績証拠。2025年だけに固定しない。
- `latest_seen_year` は表示文言に使う直近の根拠年。
- `evidence_years` は複数年実績の説明に使う。
- `continuity_score` は継続しそうかの補助指標で、開催確定とは別。

## 証拠の役割

| 証拠 | 今年の開催確定に使えるか | 主な用途 |
| --- | --- | --- |
| 今年の公式HP | 使える | 開催日・会場・主催・曲目の確定 |
| 今年の自治体/主催発表 | 使える | 開催日・会場・開催確定 |
| 今年の信頼済みX告知 | 条件付きで使える | 開催日候補または確定 |
| 今年の非公式HP/X | 原則は候補 | 今年情報の手がかり、要レビュー |
| 今年の事後YouTube/X | 事後実績として使える | 終了済み実績、曲目、雰囲気 |
| 過去年の公式アーカイブ | 今年確定には使わない | 過去実績、開催時期、系列確認 |
| 過去年のYouTube | 今年確定には使わない | 過去実績、曲目、雰囲気、継続性 |

## 昇格ルール

### `confirmed × confirmed` へ昇格できる条件

- 今年の開催年が明示されている。
- イベント名または会場が対象イベントと対応している。
- 開催日が確認できる。
- 根拠が公式HP、自治体/主催発表、信頼済みXなど、今年の直接証拠である。

### `predicted × historical_reference` に留める条件

- 2025年、2024年、2023年などの具体的な開催日がある。
- ただし今年の開催日は未確認。
- YouTube、過去公式アーカイブ、過去X、過去ブログなどが根拠。
- 複数年の証拠があっても、今年の直接証拠がなければ開催確定にはしない。

### `predicted × season_hint` に留める条件

- 「例年7月」「8月中旬」「町会夏祭り」などの時期ヒントがある。
- 具体的な過去年開催日までは確認できていない。
- 会場メモや公開紹介文から月だけ分かる。

### 日程情報がほぼない場合

- 開催日、開催月、過去実績、時期ヒントがほぼない。
- 会場やイベント名だけの未整備情報。

## 公開表示ルール

| 状態 | カード表示 | セクション |
| --- | --- | --- |
| 今年の開催確定 | `7/26 開催確定` | 日付順 |
| 今年の開催終了 | `今年は終了` | 「過去の開催を含む」で表示 |
| 過去実績あり・今年未確認 | `過去実績` / `2025年実績` / `7月下旬ごろ` | 過去実績あり・今年未確認 |
| 時期ヒントのみ | `7月予定` / `8月中旬予定` | 日程目安 |
| 日程情報なし | `日程未定` | 日程未定 |

表示文言の原則:

- 「昨年実績」は、根拠年が本当に前年だけの場合の補助表現に留める。
- 汎用表示は「過去実績あり・今年未確認」を使う。
- 根拠年が分かる場合は `2025年実績あり・今年未確認` のように年を出す。
- 複数年なら `2023-2025年実績あり・今年未確認` または `過去3年実績あり・今年未確認` とする。
- 予測日を出す場合は、必ず `予測`、`目安`、`公式未確認` のいずれかを添える。

## フィルタ・地図の運用

通常表示:

- `current_event_state` が `predicted` / `announced` / `confirmed` のもの。
- `date_certainty_tier` に応じて、確定・予測・過去実績・時期ヒントの表示を分ける。

通常表示から除外:

- `current_event_state=ended`（「過去の開催を含む」で表示可能）。
- `current_event_state=cancelled`（中止表示の明示的な導線だけで扱う）。

「開催確定情報のみ」:

- `confirmed × confirmed`。
- 「過去の開催を含む」がオンなら `ended × confirmed` も含む。
- `predicted` / `announced` は含めない。

地図表示:

- `current_confirmed_upcoming` は表示する。
- `historical_reference` は `continuity_score` が中以上のものだけ、未確認マーカーとして表示してよい。
- `schedule_hint_only` と `date_unknown` は原則として地図に出さず、一覧側で見せる。

## 日々の作業手順

1. 今年の公式/主催/自治体情報を優先して確認する。
2. 今年の直接証拠があれば、開催日・会場・根拠URLを入れて `confirmed × confirmed` に昇格する。
3. 今年の直接証拠がなければ、過去年YouTube/公式アーカイブ/Xを `historical_occurrences` に積む。
4. 過去年実績があるものは `predicted × historical_reference` とし、`continuity_score` と `evidence_years` を更新する。
5. 月や旬しか分からないものは `predicted × season_hint` に置く。
6. ヒントも薄いものも有限語彙外へ逃がさず、根拠を要レビューとして受信箱へ戻す。
7. Web公開前に、カテゴリ別件数と「開催確定情報のみ」の件数を確認する。

## 禁止事項

- 過去年の開催日を今年の開催日にコピーしない。
- 過去年YouTubeを今年の開催確定根拠にしない。
- `last_year` を新規の正規カテゴリ名にしない。
- `continuity_score` が高いだけで `current_confirmed_upcoming` にしない。
- 予測日を確定日のように表示しない。
