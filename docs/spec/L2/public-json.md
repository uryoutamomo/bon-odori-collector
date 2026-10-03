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
  - INV-PJS-004
  - INV-PJS-005
verified_by:
  - tests/test_export_public_events.py
  - tests/test_classify_public_events_diff.py
  - tests/test_public_json_field_sparsity.py
  - tests/test_apply_public_date_predictions.py
updated_for: 3be992d7
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

2026-09-09のR2公開投影では387件。年越し修正により13過去カード155曲の確率・根拠表示を
更新し、曲名・曲数・他イベント項目・内部source mapは維持した。曲目の意味は
[曲目L1のINV-SNG-002/007/008](../L1/08-songs.md)を参照する。
最新の正本取得run `34340430748` によるR2前後の9ケース・4出力はbyte一致した。
以下の379件・参照field数は `6537e7f` 当時の分析値で、最新件数の意味ではない。

2026-09-09の公式情報更新候補は394件（新規7件、既存更新4件、削除0件）。
`data/change_requests/official_refresh_20260909_reviewed.json` の当年根拠から生成し、
過去開催回はRDBへ保持する。フィールド契約は変えず、催し全体の時間と盆踊りの時間は
公開detailで区別する。適用と公開の証跡は `docs/official-data-refresh-20260909.md` を参照。

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
`occurrence_id`, `event_year`, `name`, `display_name`, `venue`, `address`, `access`, `area`, `lat`, `lng`, `description`, `detail`, `scale`, `edition_number`, `name_confirmed`

2026-10-03のID移行では全RDB公開行に`occurrence_id`と`event_year`を追加する。IDはASCII英数字/underscore/hyphen 1〜128文字で一意、年は1〜9999の非bool int。年は実開催回を表し、`--target-year`とは一致しない過去実績カードもある。内部`_series_id`/`_venue_id`や非公開根拠は公開しない。

**日程**
`date`, `date_end`, `date_candidates`, `date_certainty_tier`, `months`, `jun`, `hints`

**状態と表示制御**
`status`, `current_event_state`, `public_status`, `public_category`, `display_tier`

**過去実績（去年こうだった、を見せる）**
`historical_reference`, `historical_reference_label`, `last_seen_dates`, `last_seen_year`,
`historical_slide`, `historical_slide_basis`, `historical_slide_date`, `historical_slide_date_end`, `historical_slide_method`

**予測（たぶん今年はこうだろう、を見せる）**
`date_prediction`, `predicted_date`, `predicted_date_end`, `prediction_basis`, `prediction_probability`,
`prediction_probability_percent`, `prediction_certainty_label`, `prediction_certainty_meaning`,
`recurrence_score`, `recurrence_label`, `season_hint`

**その他**
`songs`, `source_urls`

## 時刻の表示根拠（2026-10-03）

`date` が今年でも、`detail` には過去開催回の時刻が残り得る。旧 `time_text` や
出典リストの存在だけでは、当年の時刻を公式確認済みとして表示できない。

siteの正式契約は [イベント時刻の根拠](https://github.com/uryoutamomo/bon-odori-site/blob/main/docs/spec/L2/event-time-evidence.md)。
任意の `time_evidence` は `text`、`event_date`、`event_date_end`、`source_url`、
`source_kind: official`、`scope: event|bon_odori` を持ち、イベント本体の開催日・終了日と
同じイベントのofficial URLへ完全一致しなければ表示根拠にならない。現行RDB/exporterは
この構造化根拠を生成していないため、欠損を推測で埋めない。

siteが当年日付と結び付く詳細文から導出する `time_reference` は、常に参考・未確認とする。
イベント全体の時間と盆踊りだけの時間、最終日などの例外を混同しない。
過去年・別開催回の時刻は詳細の履歴として保持するが、当年の時間欄には使わない。
実装はsiteの `scripts/build_public_snapshot.py::sanitize_event`、`app.js::timeEvidence` と
静的イベントページ。回帰検査はsiteの `tests/test_event_time_evidence.py`。

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

`prediction_probability` は開催可能性と日付一致をまとめた統合確度で、`prediction_certainty_label` は
その日本語表示である。`date_prediction` の同名フィールドが正規のまとまりで、トップレベルは既存サイト向けの互換投影とする。

## 不変条件

### INV-PJS-001 同一性は `name` と `venue` の組で決まり、それ以外にIDは無い

**新しい同一性の判定としては廃止（2026-10-03）。** 以下は旧契約。現在はINV-PJS-005を使い、旧aliasは一意なv1承認の互換にのみ使う。

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
- **守っているテスト**: `tests/test_public_json_field_sparsity.py::BareOccurrenceKeepsFieldsAbsentTest::test_bare_occurrence_omits_every_optional_field`、
  `tests/test_public_json_field_sparsity.py::PublishedPublicJsonIsSparseTest::test_no_single_event_carries_every_field`、
  `tests/test_public_json_field_sparsity.py::PublishedPublicJsonIsSparseTest::test_each_optional_family_is_absent_from_some_event`。
  2方向から見ている。生成の入口では、根拠の無い開催回に任意フィールドが**付かない**こと
  （`None` や空文字で埋めるのも「埋めた」に入れて弾く）。公開されている実物では、
  いまも疎であること。**全イベントが同じキー集合を持つようになったら、それは入口が壊れた結果**なので、
  「1件が全フィールドを持つことは無い」「任意フィールドは必ずどこかで欠けている」を検査する。

### INV-PJS-004 予測確度は「開催され、かつその日である」1つの意味で渡す

- **内容**: `date_prediction.joint_probability` とトップレベルの `prediction_probability` は、
  対象イベントが対象年に開催され、かつ `date_prediction.date..date_end` と一致する統合確度である。
  `probability_percent`、`certainty_label`、`certainty_meaning` も同じ判断から派生させる。
  開催有無と日付一致の別スコアを公開JSONへ出さない。
- **なぜ**: 利用者が知りたいのは「その日に行けば開催されているか」であり、2つの確率を自分で解釈させるべきではない。
  また単なる規則一致スコアを確率として表示すると、開催中止の可能性が数値から抜け落ちる。
- **破れたときの症状**: 同じカードに開催確率と日付確率が並び、どちらを信じるか分からない。
  または `95%` が規則の一致率なのか、実際にその日に開催される確度なのか分からない。
- **守っているコード**: `event_model/event_date_prediction_judgment.py`、
  `public_export_support/date_predictions.py`
- **守っているテスト**: `tests/test_event_date_prediction_judgment.py`、
  `tests/test_apply_public_date_predictions.py`

### INV-PJS-005 開催回IDと実開催回年は全RDB公開行で必須

- **内容**: `occurrence_id`は全公開行を一意に識別し、`event_year`は表示日や予測対象年ではなくその開催回のRDB年を表す。同名・同会場の別IDを上書きせず、移行時に追加する公開項目はこの2つだけとする。siteはmetadataが1件でも存在すれば全行の型・ID重複を検査し、metadataを公開JSONまで保持する。
- **なぜ**: IDを内部source mapにだけ残すと、collector/site差分と静的ページで別開催回を識別できない。
- **破れたときの症状**: 年を跨いで行が消える、日付予測や曲リンクが別開催回へ付く。
- **守っているコード**: `export_public_events.py::strip_public_internal_event_fields`、`public_export_support/occurrence_identity.py`、siteのsnapshotとdeploy guard。
- **守っているテスト**: `tests/test_public_projection_purity.py`、`tests/test_occurrence_identity.py`、`tests/test_verify_occurrence_identity_migration.py`。site側はtest_public_occurrence_identity.pyを参照する。
- **関連**: INV-PUB-013/014。旧承認の互換と現行394件のURL維持はcollector/siteの移行検査で確認する。

## 気づいた食い違い（`6537e7f` 時点）

collector 側の `data/public/events_public.json` は379件、
`bon-odori-site` 側の `data/events_public.json` は370件で、**9件の差がある。**

同期ガードは件数不一致を `event_count_mismatch` として `block` するので（[INV-PUB-003](../L1/05-publication.md)）、
この状態で一括同期をかけると止まる。サイト側が未同期なだけと思われるが、**確認していない。**
放置すると差が広がるので、公開反映の前に確かめる必要がある。

上記は当時の未同期記録。2026-09-09の本番反映前検査ではcollector・siteとも387件で
件数・キーの差分は0。R2の公開候補も同じ387件で、生JSONの同期ガードと公開ガードを通過した。

## 未解決・注意点

- **この仕様が公開JSONそのものを `owns` しているのは意図的である。** 生成物なので一見すると
  [SPEC-GUIDE](../SPEC-GUIDE.md) の「純粋な生成物は owns しない」に反して見えるが、
  公開JSONは**人も直接手を入れるファイル**で（直近8コミットのうち人が4件）、
  手で触るときにこそ INV-PJS-001 を届けたい。鮮度指標は自動コミットを数えないので汚れない。
  外さないこと。
- **判断理由を公開面で使っていない**（上述）。作ったものが届いていない状態。
- **安定IDが無い**（INV-PJS-001）。名前を直すだけで別イベント扱いになる構造は、根本的には設計の宿題。
- 欠損が正常であることはINV-PJS-003に記載した生成入口・公開実物の両テストで検査している。
- `events_public.js` はJSONと同内容を同じ計算結果から出力し、R2比較器がevents JSON/JS・曲目JSON・
  内部source mapの全4出力を比較する。`tests/test_public_projection_purity.py` と
  `tests/test_compare_public_projection_revisions.py` がこの経路を検査する。
- 曲目の `data/public/event_songs_public.json` は本文書で扱えていない。別途必要。

---

こと（Claude Code）

## 公式リンクの分類（2026-10-03）

`source_urls` はpublicな公式Webボタンとリンクを公開しない出典件数を区別する。RDB `source_kind=official_current_year` かつ `data/public_official_source_links.json` のレビュー済み開催回・年・日付・URLが完全一致する公開可能な非notice Web URLなら `{label: 公式告知あり, url: 当年primaryURL, kind: official}` を先頭に一つ保持する。同URLの旧web項目と単独匿名web count1は重複させない。複数匿名の出典件数を推測減算しない。レビュー済みなら詳細に古いofficial URLがあっても当年primaryを優先し、後段sanitizeで逆転させない。未レビューのtyped分類だけで新公式リンクを作らない。登録は実ページとの照合後に行い、期限や別開催回への横流用をしない。

Notion由来・一般Web・X・YouTube・除外URLはホスト名だけでofficialへ昇格しない。公開導線はofficialのみをクリック可能とする既存site方針を守る。この分類は日程出典の分類であり、時刻の構造化根拠を生成せず公式確認時間の要件を置き換えない。INV-PUB-015と [改善記録6](../../system-improvements-20261003.md#6-当年の公式リンク) を参照。

registryの`reviews`は今回確認済み12組。`legacy_preserved`は改善前に公開済みだった52組を同じRDB source URL・ID・年・日付内だけで保持する互換入口で、新規確認済みとは数えない。旧detail内の公式根拠は元の出典分類を維持する。Xの旧official3組と既存post8組はクリックURLを匿名化し、出典件数を残す。notice hostは完全一致/サブドメイン境界で判定し、`blogspot.com`や`shimokitazawa-east.com`を`t.co`へ誤分類しない。この分類訂正2組も含め、13組の旧/new source payloadは有限manifestで固定して検証する。

review入力はbuild_public_events_from_masterのI/O境界で一度読み、純粋なproject_public_eventsへI/Oを持ち込まない。registryの開催日終了が未設定なら空文字で表し、RDB/publicのNULLと同じ欠損として照合する。schema破損・型不正・重複・review/legacy overlapは拒否する。新URLや別年・別日へ旧保持権限を横流用しない。
