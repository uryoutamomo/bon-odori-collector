---
id: L2-public-json
layer: L2
title: 公開JSONのフィールド契約
owns:
  - data/public/events_public.json
  - data/public/event_songs_public.json
  - data/public/events_public.js
depends_on:
  - L1-publication
invariants:
  - INV-PJS-001
  - INV-PJS-002
  - INV-PJS-003
verified_by:
  - tests/test_export_public_events.py
  - tests/test_classify_public_events_diff.py
updated_for: 6537e7f
---

# 公開JSONのフィールド契約

> 上位は[公開サブシステム](../L1/05-publication.md)。書き方の決まりは [SPEC-GUIDE](../SPEC-GUIDE.md)。

## なぜこの文書が要るか

`data/public/events_public.json` は、collector と公開サイト `bon-odori-site` をつなぐ**唯一の受け渡し口**である。
にもかかわらず、どのフィールドが何を意味し、どれを消すと表示が壊れるかは、これまでどこにも書かれていなかった。

両側は別リポジトリなので、collector 側でフィールドを消しても、サイト側のコードは何も言わずに `undefined` を掴む。
テストも通る。気づくのは公開面が壊れたあとになる。**これは事実上の外部APIでありながら、契約が暗黙のままだった。**

この文書は、`6537e7f` 時点の実データ（379件）と `bon-odori-site` の `app.js` / `updates.js` を
突き合わせて確かめた結果である。推測ではなく、実際に数えた。

## 全体像

| | |
|---|---|
| イベント件数 | 379件 |
| フィールド総数 | 59種類（イベントごとに欠けるものがある） |
| サイトが識別子として参照 | 43種類 |
| サイトに参照が見当たらない | 16種類 |

**フィールドはイベントごとに揃っていない。** 59種類は全イベントの和集合であって、
どのイベントも59個持っているわけではない。読む側は常に欠損を前提にする必要がある。

## サイトが参照しているフィールド（43種類）

消すと公開サイトの表示が壊れる。変更する場合は `bon-odori-site` 側も同時に直す必要がある。

**同一性と基本情報**
`name`, `display_name`, `venue`, `address`, `access`, `area`, `lat`, `lng`, `description`, `detail`, `scale`, `edition_number`, `name_confirmed`

**日程**
`date`, `date_end`, `date_candidates`, `date_certainty_tier`, `months`, `jun`, `hints`

**状態と表示制御**
`status`, `current_event_state`, `public_status`, `public_category`, `display_tier`

**過去実績（去年こうだった、を見せる）**
`historical_reference`, `historical_reference_label`, `last_seen_dates`, `last_seen_year`,
`historical_slide`, `historical_slide_basis`, `historical_slide_date`, `historical_slide_date_end`, `historical_slide_method`

**予測（たぶん今年はこうだろう、を見せる）**
`date_prediction`, `predicted_date`, `predicted_date_end`, `prediction_basis`, `recurrence_score`, `recurrence_label`, `season_hint`

**その他**
`songs`, `source_urls`

## サイトが参照していないフィールド（16種類）

`app.js` と `updates.js` に、識別子としての参照が1つも見つからなかったものである。
部分一致ではなく、前後が識別子文字でない完全一致で数えた。

| フィールド | 値がある件数 | 性質 |
|---|---|---|
| `public_note` | 379/379 | 判断の補足 |
| `public_status_label` | 379/379 | 状態の日本語表示 |
| `recurrence_reasons` | 379/379 | **なぜ今年も開かれると考えたかの理由** |
| `date_confidence` | 379/379 | 日付の確からしさ |
| `recurrence_cautions` | 80/379 | 開催可能性についての注意 |
| `historical_reference_confidence` | 75/379 | 過去実績の確からしさ |
| `historical_reference_score` | 75/379 | 同スコア |
| `historical_display_tier` | 75/379 | 過去実績の表示段 |
| `historical_last_seen_dates` | 75/379 | 過去に見た日付 |
| `historical_last_seen_year` | 75/379 | 過去に見た年 |
| `season_hint_label` | 35/379 | 季節ヒントの表示名 |
| `season_confidence` | 35/379 | 季節ヒントの確からしさ |
| `season_months` | 35/379 | 同・月 |
| `season_jun` | 35/379 | 同・旬 |
| `prediction_confidence` | 24/379 | 予測の確からしさ |
| `prediction_evidence_years` | 3/379 | 予測の根拠年 |

### この一覧が示していること

並べてみると、**参照されていない16種類のうち11種類が「確からしさ」と「そう判断した理由」である。**
`recurrence_reasons`（なぜ今年も開かれると考えたか）と `public_note`（判断の補足）は
**全379件に値が入っているのに、公開サイトはこれを一度も表示していない。**

盆助の方針は「AIが何を集め、どう判断したかを見せること」に強みを置くというものだった。
その判断理由は、RDBから公開JSONまでちゃんと運ばれている。**運ばれた先で使われていないだけである。**

つまりこれは「不要なフィールドが残っている」のではなく、**作ったのに見せていない**状態と読むのが正しい。
消す方向ではなく、サイト側で活かす方向の宿題として扱いたい。
（判断していないので、ここでは事実の記録に留める。方針は内田さんの判断領域。）

`fixed_date_rule` は差分分類器が監視対象に含めているが、`6537e7f` 時点の実データでは
保持しているイベントが0件だった。将来使う想定の枠と思われる。

## 不変条件

### INV-PJS-001 同一性は `name` と `venue` の組で決まり、それ以外にIDは無い

- **内容**: 公開JSONにはイベントの安定IDが無い。差分の突き合わせは `f"{name}||{venue}"` で行う。
  したがって `name` か `venue` を変えると、機械には別イベントに見える。
- **なぜ**: 公開JSONはRDBの主キーを外へ出していない。外向けの識別子を持たない設計のまま運用が進んだため、
  表示名がそのまま同一性を担っている。
- **破れたときの症状**: 表記ゆれを直しただけで、同期ガードが「既存イベントの削除と新規追加」として止まる。
  止まらず通れば、公開面で同じ盆踊りが2件に増えるか1件消える。
- **守っているコード**: `public_json_postprocessors/classify_public_events_diff.py` の `event_key()`
- **守っているテスト**: `tests/test_guard_public_events_sync.py::test_exact_key_replacement_preserves_event_count_and_resolves_keys`
- **関連**: [INV-PUB-001](../L1/05-publication.md)

### INV-PJS-002 高リスクフィールドの変化は、無検査で公開へ流さない

- **内容**: 差分分類器は全59フィールドではなく、次の7群だけを「高リスク」として監視する。
  過去実績群、過去実績スライド群、季節群、日付予測群、日程（`date` / `date_end`）、詳細（`detail`）、出典（`source_urls`）、
  そして後処理ルール（`fixed_date_rule`）。これらに差が出た場合は分類され、危険なものはガードが `block` する。
- **なぜ**: 全フィールドを等しく監視すると、表示上どうでもいい揺れでも止まってしまい、
  ガードが「いつも赤いもの」になって読まれなくなる。**止めるべきものだけを止めるために、監視対象を絞っている。**
- **破れたときの症状**: 監視対象から外したフィールドが静かに壊れる。逆に広げすぎるとガードが常時 block になり形骸化する。
- **守っているコード**: `public_json_postprocessors/classify_public_events_diff.py` の `HIGH_RISK_FIELDS`
- **守っているテスト**: `tests/test_classify_public_events_diff.py::test_source_url_removal_is_high_risk_individual_review`、
  `tests/test_classify_public_events_diff.py::test_source_url_metadata_difference_with_same_urls_is_not_high_risk`

> **注意**: 高リスク群には、サイトが表示していないフィールドも含まれている
> （`historical_reference_confidence`、`season_confidence`、`recurrence_reasons` など）。
> つまり**画面に出ないフィールドの差分でも同期は止まる。** これは無駄ではなく、
> それらが表示されていないのは現時点の実装の都合であって、値としては意味を持つため。

### INV-PJS-003 読む側は、フィールドが欠けている前提で書く

- **内容**: 59フィールドは全イベントの和集合であり、個々のイベントには欠けるものがある。
  たとえば季節ヒント群は35件、予測の根拠年は3件にしか存在しない。
- **なぜ**: 情報の確からしさに応じて、付く情報と付かない情報が変わるため。
  「確定した日付が無いイベント」には予測が付き、「予測もできないイベント」には季節ヒントだけが付く、という具合に、
  **欠けていること自体が情報になっている。**
- **破れたときの症状**: サイト側が欠損を想定していないと `undefined` を表示するか、描画が落ちる。
  collector 側が「必ず埋める」ようにすると、今度は推測値で穴埋めすることになり、確定と推測の区別が失われる。
- **守っているコード**: `export_public_events.py` の各フィールド付与処理
- **守っているテスト**: **なし（要追加）** — 「欠損が正常である」ことを明示的に検査するテストは見当たらなかった。

## 気づいた食い違い（`6537e7f` 時点）

collector 側の `data/public/events_public.json` は379件、
`bon-odori-site` 側の `data/events_public.json` は370件で、**9件の差がある。**

同期ガードは件数不一致を `event_count_mismatch` として `block` するので（[INV-PUB-003](../L1/05-publication.md)）、
この状態で一括同期をかけると止まる。サイト側が未同期なだけと思われるが、**確認していない。**
放置すると差が広がるので、公開反映の前に確かめる必要がある。

## 未解決・注意点

- **判断理由を公開面で使っていない**（上述）。作ったものが届いていない状態。
- **安定IDが無い**（INV-PJS-001）。名前を直すだけで別イベント扱いになる構造は、根本的には設計の宿題。
- **欠損が正常であることを検査するテストが無い**（INV-PJS-003）。
- `events_public.js` は JSON と同内容のJS版だが、両者がずれないことを保証する仕組みを確認していない。
- 曲目の `data/public/event_songs_public.json` は本文書で扱えていない。別途必要。

---

こと（Claude Code）
