---
id: L1-venues
layer: L1
title: 会場サブシステム
owns:
  - venues/__init__.py
  - venues/extract_venues.py
  - sync_venue_master.py
  - extract_venues_blog.py
  - extract_blog_venue_rows.py
  - triage_blog_venue_candidates.py
  - build_missing_venue_review_from_song_associations.py
  - apply_reviewed_missing_occurrence_venues.py
  - apply_reviewed_venue_field_fixes.py
  - apply_retrospective_ready_venue_events.py
  - apply_ph2_shinagawa_second_venue_review.py
  - scripts/manual/review_venue_batch.py
  - scripts/manual/geocode_venues.py
depends_on:
  - L1-collection
  - L1-review
  - L1-master
  - L1-publication
invariants:
  - INV-VEN-001
  - INV-VEN-002
verified_by:
  - tests/test_apply_reviewed_missing_occurrence_venues.py
  - tests/test_apply_ph2_shinagawa_second_venue_review.py
updated_for: 83bf7d0
---

# 会場サブシステム

> 上位は[全体地図](../README.md)。収集の入口は[収集](01-collection.md)、人の決定は[レビュー](03-review.md)、正本RDBは[マスタ](04-master.md)、公開形は[公開](05-publication.md)を読む。
> ここは「会場を見つけ、候補として整え、レビュー済みのものを開催回へ結ぶ」範囲である。会場の同一性そのものは[マスタの INV-MST-007](04-master.md#inv-mst-007-会場は正規化名と住所の完全一致でのみ再利用する)が持つため、ここで再定義しない。

## この工程は何のためにあるか

盆踊りの「どこで開かれるか」は、日付や名前と同じく公開に必要な事実である。しかし入力文には「公園」「境内」「駅前」のような断片、旧称、住所だけの表記が混ざる。同じような名称を安易に同一視すれば別の会場を結び、逆に候補を捨てれば開催回が場所なしのまま残る。

このサブシステムは、会場らしい文字列と住所を候補として取り出し、人が確認できる形にする。そして、レビュー済みの候補だけを Master RDB の `venues`、`venue_aliases`、`event_occurrences.venue_id`、必要時の `event_series.usual_venue_id` へ結ぶ。候補抽出は証明ではない。確定させるのはレビューとマスタ側の同一性判定である。

ここには二つの時代のコードが残る。現在の正本はRDBだが、Notionを会場マスタの正本としていた時代の exporter と apply が残っている。ファイルが存在しテストが通ることを「日次で動いている」と読んではならない。以下では、2026-08-14 に workflow と Python の参照を検索して確認した呼び出し元を明記する。

## 入力と出力

| 区分 | 入力 | 出力 | 状態 |
|---|---|---|---|
| Blogspot 抽出 | 東京盆踊りマップの Atom feed | `data/venues_seed_blog.json` | `refresh_official_source_review.yml` から実行 |
| Blogspot 行抽出 | 同 feed のHTML表 | `data/blog_venue_rows.json` | 同 workflow から実行 |
| Blogspot 仕分け | `venues_seed_blog.json`、旧 `data/venue_master.json`、任意の `blog_source_urls.json` | `data/venue_candidate_triage.json` | 同 workflow から実行 |
| 曲の会場欠落 | 採用済み会場×曲の apply 結果と根拠 | `accepted_venue_song_missing_venue_review.{json,md}` | `collect.yml` の低優先レーンから実行 |
| RDB適用 | 人レビュー済み会場候補、Master RDB | venue / alias / occurrence の更新、dry-run/report | 手動の one-off apply |
| 手動レビュー | ローカル review console の pending venue items | decision API への決定 | 手動 |

`sync_venue_master.py` は Notion の「🏮 会場マスタ」を正本として `data/venue_master.json` を作る。2026-08-14 の検索ではworkflowからの呼び出しもPython importも見つからなかった。RDB移行後の現設計と食い違う**休眠経路**として扱う（休眠理由はRDB移行と読めるが、廃止の正式決定は未確認）。

`venues/extract_venues.py` も `latest.json` / `voices.json` から `venues_seed.json` を作る「方向案B Step0」であり、workflow・Python importとも見つからない**休眠経路**である。`venues/__init__.py` は空のパッケージ印で、実行入口ではない。

候補出力に `needs_review=True` が付いていても、RDBの `review_status` とは別の段階の印である。
前者は抽出器が付ける「原文からの推定」、後者はマスタへ入った会場行の状態である。
この二つを混ぜると、候補JSONを読んだだけで公開可能だと誤解する。

会場名、住所、アクセス、根拠URLは同じ強さではない。
会場名だけの候補は探索の入口になり、住所と根拠URLはレビューの材料になる。
どちらも無い別名を、類似文字列だけで既存会場へ寄せることはしない。

## 不変条件

### INV-VEN-001 レビュー済みの新規会場は開催回と系列へ一貫して結ぶ

- **内容**: `apply_reviewed_missing_occurrence_venues.py` が `ready_new_venue_candidate` を適用するとき、会場行を作成または既存の正確な会場を再利用し、canonical 名を alias にも登録する。対象開催回の `venue_id` を埋め、系列の `usual_venue_id` が空なら同じ ID を入れる。既に `venue_id` がある開催回は上書きしない。
- **なぜ**: 会場だけを作って開催回へ結ばなければ公開に場所が出ず、開催回と系列で別 ID を持てば「いつもの会場」の意味が割れる。既存の開催回を無条件で上書きすれば、人が確認した結び付けを壊す。
- **破れたときの症状**: 会場マスタには名前があるのにイベントの場所が空のままになる／同じ系列の会場表示が開催回ごとに食い違う／既存の場所が意図せず変わる。
- **守っているコード**: `apply_reviewed_missing_occurrence_venues.py` の `ensure_new_venue()`、`build_plan()`、`apply_plan()`。
- **守っているテスト**: `tests/test_apply_reviewed_missing_occurrence_venues.py::ApplyReviewedMissingOccurrenceVenuesTest::test_creates_reviewed_new_venue_and_fills_occurrence`。

### INV-VEN-002 品川第二地区の会場修正はRDBだけを変え、Notion同期を起こさない

- **内容**: `apply_ph2_shinagawa_second_venue_review.py --apply` は天妙国寺の住所・根拠URL・別名を Master RDB に反映するが、Notion API を呼ばず、`notion_sync_jobs` も作らず、公開JSONも書かない。
- **なぜ**: この one-off 修正を旧Notion経路へ漏らすと、RDBを正本とする現在の設計に逆向きの書き込みが生じる。公開投影まで同時に変えると、修正対象と公開差分を分けて検証できない。
- **破れたときの症状**: 会場の局所修正後に、意図しないNotion同期ジョブや公開データの差分が発生する。
- **守っているコード**: `apply_ph2_shinagawa_second_venue_review.py` の `apply_review()` と `run()`。
- **守っているテスト**: `tests/test_apply_ph2_shinagawa_second_venue_review.py::ApplyPh2ShinagawaSecondVenueReviewTest::test_apply_is_rdb_only_and_does_not_queue_notion_sync_job`。

会場の「同じものを再利用してよい条件」はこの仕様のINVではない。`report_apply/event_report_helpers.py` の `ensure_venue()` を変える場合は、必ず[INV-MST-007](04-master.md#inv-mst-007-会場は正規化名と住所の完全一致でのみ再利用する)を先に読む。似た名称の部分一致へ広げることは禁じられている。

## 主要な流れ

### 1. Blogspot から候補と構造化行を取る（稼働中）

`refresh_official_source_review.yml` は次の順で毎回実行する。

1. `extract_venues_blog.py` は feed 本文から会場接尾辞を持つ文字列を拾い、区の推定付き `venues_seed_blog.json` を作る。`needs_review=True` は「候補であって事実ではない」という印である。
2. `extract_blog_venue_rows.py` は同じHTMLの表を読み、会場、住所、日付文、詳細URLを残した `blog_venue_rows.json` を作る。本文の単語抽出より、住所と根拠を持てる入口である。
3. `triage_blog_venue_candidates.py` は旧 `venue_master.json` に対し完全名、手書き別名、正規化名を使って `registered` / `registered_alias` / `research` / `noise` に仕分ける。これは候補キューの優先付けであり、現RDBの会場同一性判定ではない。

feed取得に失敗した `extract_venues_blog.py` は「スキップ」と出して終了する。
そのためworkflow自体が緑でも候補が更新されない可能性がある。
候補数の急減を見たときは、workflow成功だけでなく出力件数を見る。

HTML表の構造が残っていれば `extract_blog_venue_rows.py` は `cLoc`、`cDsc`、`cAdr` の列から会場・説明・住所を取る。
表として取れない場合はテキスト行へフォールバックする。
このフォールバックは原文の形式変更に耐えるためのものだが、列の意味まで保証するものではない。

この三本は workflow から呼ばれる**生きている経路**である。ただし `triage_blog_venue_candidates.py` が参照する `venue_master.json` の生成元 `sync_venue_master.py` は休眠なので、入力ファイルの鮮度は別途確認が必要である。

### 2. 曲の根拠から会場欠落をレビューへ出す（稼働中）

`collect.yml` は `build_missing_venue_review_from_song_associations.py` を呼ぶ。これは採用済みの「会場×曲」根拠の apply 結果で、登録済み会場が見つからなかった行を集め、根拠URL・元の会場文字列・曲名を含むレビュー表へする。ここでも会場を自動作成しない。候補を人が追える形に落とすだけである。

`scripts/manual/review_venue_batch.py` は review console の pending venue item を読み、既知の旧決定を参照して `accept` / `reject` / `hold` / `needs_research` を decision API へ送る手動補助である。`missing_occurrence_venue` は同一性未確定なら直接 `venue_id` を入れず、追加調査へ回す。

この補助は「旧決定に合わせた一括入力」であって、根拠の再調査を省略する承認ではない。
未知の `source_id` は `hold` に倒れる。
レビューコンソールの対象IDと、候補JSONの表示名を取り違えないことが必要である。

レビューを通った入力だけが apply の候補になる。
`ready_existing_venue_candidate` には既存の `candidate_venue_id` が必要である。
`ready_new_venue_candidate` には少なくとも `candidate_venue_data.canonical_name` が必要である。
それ以外のreview actionは、計画に入れず次回の判断材料として残る。

### 3. レビュー済み候補をRDBへ適用する（手動）

`apply_reviewed_missing_occurrence_venues.py` は dry-run を既定とする。review JSON の `ready_existing_venue_candidate` または `ready_new_venue_candidate` だけを計画に入れ、コピーした SQLite か、明示確認つきの Master RDB に適用する。適用後は foreign key と、開催回へ期待した `venue_id` が入ったことを検査する（INV-VEN-001）。Notionと公開JSONは書かない。

計画作成時に対象開催回が無い、既存会場候補が無い、候補に canonical 名が無い、または開催回に既に `venue_id` がある場合は skip する。
skip は安全な停止であって、空欄を推測で補う指示ではない。
apply report の `planned` / `skipped` / `consistency_issues` を見ずに、終了コードだけで反映済みと判断しない。

新規候補に同名・同住所の会場があれば、その行を再利用し、アクセス・根拠URL・review statusを更新する。
ただしこのスクリプトの検索条件も正規化名と住所の完全一致である。
名前だけが似ている場合に再利用されないことは、マスタ側の INV-MST-007 と同じ安全側の意味を持つ。

`apply_reviewed_venue_field_fixes.py` も同じく、明示リストにあるRDB会場フィールドの修正を dry-run / apply する one-off 経路である。`apply_ph2_shinagawa_second_venue_review.py` は品川第二地区の天妙国寺の住所と別名に限定したRDB-only修正である（INV-VEN-002）。この二本はworkflowとPython importが見つからない**手動 one-off 経路**である。

one-off apply は通常の収集・レビュー・公開を置き換えない。
個別スクリプトが残している backup、確認句、manifest更新の有無を、対象ごとに読んでから使う。
別の会場修正へ同じスクリプトを流用してはいけない。

### 4. 旧Notion適用は隔離された休眠経路として扱う

`apply_retrospective_ready_venue_events.py` は Notion API を直接呼び、会場とイベントを作成・更新する。workflow・Python importは見つからず、RDB移行後の正本と逆向きなので**休眠**である。手動実行できる形で残っていることは、現行経路であることを意味しない。

`sync_venue_master.py`、`venues/extract_venues.py`、`apply_retrospective_ready_venue_events.py` を再稼働させるには、RDBとの責務、レビュー境界、公開への反映先を先に決める必要がある。単にworkflowへ足してはいけない。

### 5. 公開用の地理データは別経路である

`scripts/manual/geocode_venues.py` は `data/public/venues_public.json` を国土地理院住所検索へ送り `venues_geo.json` を作る手動ツールである。2026-08-14 の検索ではworkflow・Python importが見つからない。入力パスは `scripts/manual/data/...` を組み立てる実装なので、現状どおりではリポジトリ直下の `data/public/...` を読まない可能性がある。**休眠または要修正の可能性（未確認）**として、公開経路に含めない。

会場公開の `venues/export_public_venues.py` と、公開JSONの欠落会場後処理 `public_json_postprocessors/review_missing_occurrence_venues.py` は、この仕様の所有物ではない。前者は[公開](05-publication.md)、後者も公開側の責務である。公式サイトを直接監視する `collect_venue_sites.py` は[収集](01-collection.md)、レビュー受信箱アダプタ `review_inbox_adapters/missing_venue_adapter.py` は[レビュー](03-review.md)を読む。

## 依存と影響

**上流**

- [収集](01-collection.md) — Blogspot feed、公式サイト、Xなどの原文が薄ければ、会場候補にも根拠にもならない。
- [レビュー](03-review.md) — 候補を `ready_*` へ上げる人の判断が無ければ、RDB適用は進まない。自動生成reviewed JSONを人レビュー済みとして扱わない約束は INV-RVW-004 にある。
- [マスタ](04-master.md) — RDBの表構造、backup、manifest、会場同一性はマスタの責務である。特に INV-MST-007 が会場の誤吸収を止める。

**下流**

- [公開](05-publication.md) — RDBの開催回と会場の正しい結び付きが、公開イベント・会場表示の入力になる。ただし `venues/export_public_venues.py` を含む投影と公開判断は公開側が持つ。
- 曲目サブシステム — 会場×曲の根拠が未登録会場を示すと、ここでレビュー行を作る。曲から会場を確定してはいけない。

会場修正で `report_apply/event_report_helpers.py` を触る場合、逆引きはL1-masterへしか出ない。これは意図された排他所有である。この仕様から INV-MST-007 へのリンクを残すことで、片道の逆引きを補う。

会場を追加しても、公開面でただちに表示が変わるとは限らない。
RDBから公開JSONへの投影、公開側の欠落会場レビュー、サイトへの同期は別の工程である。
会場の事実がRDBにあることと、公開投影がその行を採用することを分けて確認する。

## 壊れたときの症状

| 見えている症状 | まず疑うところ |
|---|---|
| 開催情報に会場名・住所が出ない | review候補が `ready_*` まで昇格しているか、INV-VEN-001 の apply 計画が skip していないか |
| 同じ会場のはずなのに系列の会場表示がばらつく | occurrence と `usual_venue_id` の結び付き、別名、INV-VEN-001 |
| 別の物理会場が一つにまとまった | INV-MST-007。類似名を自動同一視していないか |
| Blogspot候補が急に空、または少ない | `refresh_official_source_review.yml` のfeed取得、HTML形式変更、接尾辞抽出 |
| Blogspot候補の既登録判定が古い | `venue_master.json` は休眠 `sync_venue_master.py` 由来で、鮮度を保証できない |
| 局所会場修正の後にNotion同期や公開差分が出た | INV-VEN-002。RDB-only one-off の経路から漏れていないか |
| geocode結果が作られない／入力が読めない | `scripts/manual/geocode_venues.py` の相対パス構築。現行経路として扱わない |

## 未解決・注意点

- **Notion旧マスタの正式な廃止状態は未確認**である。`sync_venue_master.py` と `apply_retrospective_ready_venue_events.py` は現行RDB設計と矛盾するが、削除や再接続はこの仕様追加の範囲外。
- **Blogspot仕分けは旧JSONを見ている。** 現RDBへ移行した会場同一性と同じ判定ではない。`registered_alias` はRDBにそのまま適用してよい印ではない。
- **Blogspotの抽出と構造化行の二経路は統合されていない。** 前者は候補名中心、後者は住所・日付文を含む。どちらをレビュー入力の正本にするかは未確認である。
- **`venues/extract_venues.py` は2026-05-31のStep0のまま休眠している。** テストや抽出規則を整えても、workflowへ繋がるまで公開件数は増えない。
- **RDB適用スクリプトは one-off である。** `apply_reviewed_missing_occurrence_venues.py`、`apply_reviewed_venue_field_fixes.py`、`apply_ph2_shinagawa_second_venue_review.py` を日次へ足すには、レビュー済み入力の由来、dry-run、backup、再検証を含む設計が必要である。
- **地理座標の生成は未接続の可能性がある。** `geocode_venues.py` の入力相対パスと実際の公開会場データの位置を、再稼働前に検証する。
- **会場の同一性をこの仕様に複製しない。** 変更時は必ず INV-MST-007 を確認し、正規化名と住所の完全一致以外での自動再利用を追加しない。

レビュー対象が多いときも、会場名だけで一括acceptしない。
住所、根拠URL、開催回との対応を確認できない候補は `needs_research` または `hold` に留める。
候補の件数を減らすことは、このサブシステムの成功条件ではない。

最後に、休眠コードを削除する作業と、この仕様で休眠と明記する作業は別である。
削除・再稼働・workflow接続は、呼び出し元とRDBの責務を確認する別変更として扱う。
