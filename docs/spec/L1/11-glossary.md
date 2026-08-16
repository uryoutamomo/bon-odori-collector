---
id: L1-glossary
layer: L1
title: 用語集・別名サブシステム
owns:
  - build_glossary_runtime.py
  - build_event_alias_runtime.py
  - build_glossary_review_ui.py
  - build_glossary_v2_seed_candidates.py
  - export_public_glossary.py
  - run_manual_glossary_review.py
  - run_series_alias_migration.py
  - collection_support/merge_glossary_v2_oto_reports.py
  - scripts/manual/fill_glossary_readings.py
  - docs/local-glossary-manual-operations.md
depends_on:
  - L1-judgment
  - L1-review
  - L1-master
  - L1-publication
invariants:
  - INV-GLS-001
  - INV-GLS-002
  - INV-GLS-003
verified_by:
  - tests/test_glossary.py
  - tests/test_event_alias_runtime.py
  - tests/test_series_alias_migration.py
  - tests/test_local_glossary_manual_policy.py
  - tests/test_x_post_extraction_songs.py
updated_for: 7bcacd0
---

# 用語集・別名サブシステム

> 上位は[全体地図](../README.md)。用語を使った収集判断は[判断・仕分け](02-judgment.md)、人の裁定は[レビュー](03-review.md)、イベント系列と会場の正本は[マスタ](04-master.md)、公開データの出口は[公開](05-publication.md)を読む。
> ここは、言葉の意味とイベント／会場の別名を「実行時に読める辞書」へ展開する範囲である。RDBの系列別名テーブルそのものと移行ロジックはマスタの所有であり、ここは実行入口とruntimeへの受け渡しを持つ。

## この工程は何のためにあるか

盆踊りをめぐる文章には、同じイベントを指す旧称・英語名・略称、会場の別表記、そして「やぐら」「投げ銭」のように意味によって収集時の扱いが変わる語が混ざる。文字列が一致しないだけで別イベントとして扱えば、検索結果、YouTube照合、根拠の結び付きが分断される。反対に、候補語を無審査で有効化すれば、ノイズや誤った地理的手掛かりを日次収集へ混ぜてしまう。

このサブシステムは二種類の辞書を分けて扱う。用語集v2は Notion のレビュー済み語から、除外語・参加報告語・曲候補・型付きエンティティ別名を作る。イベント／会場別名は Master RDB の `event_series_aliases` と `venue_aliases` から、YouTubeなど照合経路専用のruntime JSONへ作る。どちらも正本を各runtime JSONに移すのではなく、**日次処理がDBやNotionを直接読まなくても動けるようにする投影**である。

2026-08-14時点で `collect.yml` が毎日実行しmainへコミットするのは `build_glossary_runtime.py` と `build_event_alias_runtime.py` の2本である。名前の近いレビューUI、候補シード、公開exportが残っていても、同じ日次経路だと推測してはいけない。呼び出し元を検索して状態を分ける。

## 入力と出力

| 区分 | 正本・入力 | 出力 | 実行状態 |
|---|---|---|---|
| X界隈語観測 | E0X回答の `glossary` と投稿本文 | `data/x_glossary_observations.json` | `apply_x_extraction_results.py` 実行時に生成。用語集v2・Notion・runtimeへ未接続 |
| 用語runtime | Notion の用語集v2 DB。状態・確度・自動適用可・役割を読む | `data/glossary_runtime.json` | `collect.yml` が日次実行・mainへcommit |
| 別名runtime | Master RDB の `event_series_aliases` / `venue_aliases` と既存runtime | `data/event_alias_runtime.json` | `collect.yml` が日次実行・mainへcommit |
| 用語候補シード | `voices.json`、公開イベント、旧会場JSON | `data/glossary_v2_seed_candidates.json` | 呼び出し元なし。休眠候補 |
| 用語レビューUI | おとの用語レビュー報告を統合した行と決定JSON | `data/glossary_v2_oto123_review_ui.html` | 手動。workflow呼び出しなし |
| ローカルfallback | 日次と同種の収穫候補 | review JSON / HTML と実行report | 明示 `--manual` 必須の手動fallback |
| 公開用用語集 | Notion用語集v2、補足JSON、曲マスタ | site側の `glossary_public.json` | workflow呼び出しなし。手動export |

`glossary_runtime.json` の正本はNotion用語集v2 DBである。`build_glossary_runtime.py` は `collect.load_glossary_v2()` を呼び、Notion token とDB IDが無いと空の辞書を出す。日次workflowでは token を渡して生成し、生成物をmainへcommitする。`collect.py` のX設定読込はこのファイルの除外語・参加報告語・型付き別名を上乗せして使う。

`event_alias_runtime.json` の正本はMaster RDBである。`build_event_alias_runtime.py` は系列別名をcanonical event名ごとに、会場別名をcanonical venue名ごとにまとめる。RDBが無い環境では既存のcommit済みruntimeをそのまま残し、RDBに別名表が無い／表はあるが空の場合も、既存の非空sectionを保持する。日次の照合器が突然すべての別名を失わないための後退防止である。

この二つのruntimeは似ていても、更新に失敗したときの振る舞いが異なる。別名runtimeはRDB欠落・空表を既存データで明示的に保護する一方、用語runtimeはNotionから読めないと空の辞書を返すため、日次artifactの件数を見る必要がある。両者を同じ「辞書だから安全」と扱うと、後者の空出力を見逃す。語の別名は投稿の分類・曲候補・表示上の解釈に使い、イベント／会場別名はcanonicalな系列または物理会場を決める照合の手掛かりにするため、型を失った一般aliasを地理的根拠へ流用しない。

## 不変条件

### INV-GLS-001 未レビュー・低確度・手動専用の用語を日次runtimeへ入れない

- **内容**: `collect.load_glossary_v2()` は、状態が有効、自動適用可がtrue、かつ自動適用を許す確度の行だけを `glossary_runtime.json` の辞書へ入れる。候補状態または手動待ちの行は除く。イベント／会場別名は型付き `entity_aliases` として、一般のalias_mapと区別して出す。
- **なぜ**: 候補語は人が調べるために残すもので、日次の判定規則ではない。未確認の会場・イベント別名を地理的根拠として扱えば、無関係の開催回へ結び付く。除外語・参加報告語の誤登録も、Xのノイズ判定と一次レポ判定を反転させる。
- **破れたときの症状**: レビューしていない略称がイベント候補として扱われる／本来の参加報告がノイズになる、または無関係な投稿が一次レポになる。
- **守っているコード**: `collect.py` の `load_glossary_v2()` と `_apply_glossary_runtime_to_x_config()`、`build_glossary_runtime.py`。
- **守っているテスト**: `tests/test_glossary.py::GlossaryV2RuntimeTest::test_loads_only_active_auto_apply_v2_rows`、`tests/test_glossary.py::GlossaryV2RuntimeTest::test_x_config_merges_runtime_terms_without_duplicates`。

### INV-GLS-002 RDBの別名表が空・欠落しても、既存runtimeを空で上書きしない

- **内容**: `build_event_alias_runtime.py` は、RDBが欠落した場合は出力を書かない。RDBが移行前で別名表が無い、または移行直後で表が空のときは、既存runtimeの非空 `event_aliases` / `venue_aliases` sectionを保持する。明示 `--allow-empty` のときだけ空sectionを書ける。
- **なぜ**: 日次照合はMaster RDBを直接開かず、commit済みruntimeを読む。移行の途中で空の投影をcommitすると、英語名・旧称・会場別表記を含む照合が一斉に失われる。workflowは成功するため、件数低下だけが静かに現れる。
- **破れたときの症状**: YouTubeのタイトル／概要欄に既知の別名があるのにイベント・会場を解決できない／別名を含む候補が急減する。
- **守っているコード**: `build_event_alias_runtime.py` の `build_runtime()` と `main()`、`youtube_backfill/event_aliases.py` のruntime読込。
- **守っているテスト**: `tests/test_event_alias_runtime.py::EventAliasRuntimeBuilderTest::test_missing_alias_table_keeps_the_previous_section`、`tests/test_event_alias_runtime.py::EventAliasRuntimeBuilderTest::test_empty_alias_table_keeps_the_previous_section`、`tests/test_event_alias_runtime.py::EventAliasRuntimeBuilderTest::test_main_keeps_the_existing_file_when_the_rdb_is_absent`。

### INV-GLS-003 系列別名テーブルの移行はdry-run既定で、実行には確認句を要する

- **内容**: `run_series_alias_migration.py` は既定で一時コピーしたDBを検査するdry-runである。実DBを変更する `--execute` には正確な確認句が必要で、実行後はintegrity checkとforeign key検査を報告する。
- **なぜ**: 系列別名は日次runtimeの正本である。移行入口が通常実行で表を作ると、調査・レビューのつもりの操作がMaster RDBのスキーマを変える。未検証の移行後RDBを日次が読むと、INV-GLS-002の保護があっても原因調査が難しくなる。
- **破れたときの症状**: 手元で確認しただけのつもりでRDBに別名表が作られる／移行後にforeign key不整合を含むDBが残る。
- **守っているコード**: `run_series_alias_migration.py` の `run()`、`event_model/series_alias_migration.py` の移行本体。
- **守っているテスト**: `tests/test_series_alias_migration.py::SeriesAliasMigrationRunnerTest::test_dry_run_leaves_the_database_untouched`、`tests/test_series_alias_migration.py::SeriesAliasMigrationRunnerTest::test_execute_requires_the_confirm_phrase`、`tests/test_series_alias_migration.py::SeriesAliasMigrationRunnerTest::test_execute_creates_the_table`。

`event_model/series_alias_migration.py` はL1-masterが所有する。このL1は実行入口を持つだけで、移行本体のschema契約やマスタ所有を重複定義しない。`apply_curated_youtube_aliases.py` と `youtube_backfill/event_aliases.py` もL1-youtubeの所有であり、runtimeの利用先として参照するがここでは所有しない。

## 主要な流れ

### 0. X投稿から界隈語観測を貯める（新設・未接続）

E0X回答の `glossary` にある文字列を `apply_x_extraction_results.py` が投稿本文へ照合し、原表記のまま `data/x_glossary_observations.json` へ集約する。語ごとに全件の `source_tweet_ids` と最大5件の例を持ち、`count` はtweet IDの件数から導出する。同じ回答を再取り込みしても増えない。

この台帳は「投稿本文で見た語」の観測であり、Notion用語集v2の候補・有効状態や `glossary_runtime.json` ではない。自動適用可否を決めず、Notionへ書かず、日次収集の判断規則も変えない。本文照合・冪等性・異常要素の隔離は [判断・仕分けのINV-XPE-010〜013](02-judgment.md)、回答形式は [E0X-S設計](../../x-post-extraction-songs-v1.md) を参照する。

### 1. 用語集v2から日次runtimeを作る（稼働中）

`collect.yml` はMaster RDB取得・監査の後に `build_glossary_runtime.py` を実行する。スクリプトはNotion用語集v2をページングで読み、状態、確度、自動適用可の3条件を通る語だけを出力する。語の種別と役割により、`exclude_keywords`、`experience_keywords`、`song_terms`、`role_terms`、`alias_map`、`entity_aliases` に分ける。

日次収集の `collect._load_x_config()` は `glossary_runtime.json` を読んで、Xクエリ設定の除外語と参加報告語を重複なく追加する。型付きentity aliasは一般語として文字列置換せず、後段の地理・イベント解決に渡す。用語runtimeが無い、または壊れて読めない場合は、X設定をそのまま返すfail-safeである。

この生成物は `collect.yml` のcommit段で `git add data/glossary_runtime.json` される。Notionの正本を毎回外部へ問い合わせずに、後続のリポジトリ内処理が同じ語彙を使えるようになる。ただし空の用語runtimeが出た場合の保持保護は、別名runtimeほど実装で確認できていない。Notion認証やDB設定の異常は日次artifactの内容も確認する。

### 2. Master RDBから別名runtimeを作る（稼働中）

同じ日次workflowは `build_event_alias_runtime.py` を実行する。`event_series_aliases` と `venue_aliases` をそれぞれcanonical名ごとの配列へ投影し、`event_alias_runtime.json` をatomic replaceで書く。canonical表記自身もaliasとして残す。照合器は「既知名のどれかが本文にあるか」を調べるため、これを消すと従来できた一致まで失うからである。

RDB artifactが無ければスクリプトは成功扱いで既存JSONを残す。表の欠落または空についても、既存の非空sectionをcarry overし、report用の `carried_over_sections` に理由を残す（INV-GLS-002）。このとき出力された助言は、空なら curated YouTube aliasesの適用、表そのものが無ければ系列別名移行の実行入口を示す。

日次commit段は `event_alias_runtime.json` もstageする。これにより、RDBを持たない照合経路でも最後に安全に生成できた別名を読み続けられる。

RDBの表が空だった理由は同じではない。`event_series_aliases` が無いなら古いRDBに系列別名移行をまだ適用していない状態であり、表が存在して空なら移行直後でseedが未投入の可能性がある。原因によって次に確認すべき作業が違うため、runtime builderは理由を区別して残し、使うべき手動入口も表示する。

### 3. 別名を照合に使う（稼働中の利用先）

`youtube_backfill/event_aliases.py` はcommit済みの `event_alias_runtime.json` を読み、canonical event名またはvenue名とYouTubeのタイトル・概要欄を比較する。別名が本文に見つかれば、その表記を返して後続のイベント名・会場名解決を助ける。runtimeファイルが無い／JSONが壊れている場合は別名なしへ劣化するため、処理は落ちないが照合率は下がる。

YouTube側のRDBへの別名投入 `apply_curated_youtube_aliases.py` は、L1-youtubeのレビュー済みデータを正本へ入れる入口である。ここで別名を増やしただけでは照合器が即座に変わるわけではない。次の日次でruntimeが再生成・commitされるか、明示的にruntime生成を行って初めて利用側へ届く。

### 4. 人のレビューと手動fallback（手動）

`run_manual_glossary_review.py` は日次収集が使えないときのローカルfallbackである。`--manual` が無いと生成前に失敗し、LaunchAgentテンプレートも Disabled=true・scheduleなしである。生成するのはreview候補とHTMLであって、レビュー済み決定のapplyではない。レビューの時期は人が選ぶ（[ローカル運用書](../../local-glossary-manual-operations.md)）。

`collection_support/merge_glossary_v2_oto_reports.py` はおとの複数の用語レビュー報告を統合し、`build_glossary_review_ui.py` はその行からローカルのチェックリストHTMLを作る。この二本は互いのimport関係以外にworkflow／Python呼び出しが見つからない**手動レビュー経路**である。`build_glossary_v2_seed_candidates.py` はvoicesから初期候補を作るが、呼び出し元が見つからない**休眠候補**である。

`scripts/manual/fill_glossary_readings.py` はNotion用語集v2の読みを補う手動ツールで、`--apply` を付けたときだけNotionへ書く。workflow・Python呼び出しは見つからない。読みの補完は用語runtimeの検索・表示には役立つが、日次の自動適用を意味しない。

手動fallbackは日次の失敗を隠すための常設代替ではない。ローカルで作ったreview artifactはGitHub Actionsが見ない未レビュー差分になり得るため、運用書は日次が使えず、内田さんが即時のreview UIを必要としたときだけ使うよう定めている。`run_series_alias_migration.py` もworkflowから呼ばれない手動入口であり、通常はdry-run、実DBへ表を作る操作は確認句を伴う。日次runtimeの欠落を見つけても移行を自動実行して埋めないのは、原因の確認より先にマスタのschemaを変えないためである。

### 5. 公開用の用語集は自動経路に未接続である

`export_public_glossary.py` はNotion用語集v2から公開可能な項目だけを作り、補足JSONと曲マスタの項目をマージしてsite側の `glossary_public.json` へ書く。生の根拠や運用レビュー注記は公開形へ出さない設計である。

ただし2026-08-14の検索では、このexportを呼ぶworkflow・Pythonスクリプトは見つからなかった。`docs/build-export-report-operations.md` は安全なpublic exportに分類するが、**現在の定期実行・公開反映に接続されている証拠ではない**。exporterが存在することだけで、用語集が公開面へ届いていると断定してはいけない。実行されればsiteリポジトリへのJSON書き出しまで進むが、サイト同期・deployは公開サブシステムの別工程である。

## 依存と影響

**上流**

- [判断・仕分け](02-judgment.md) — 収集文から生じる候補、X判定規則、イベント・会場解決の入力を持つ。
- [レビュー](03-review.md) — 用語の候補を有効化する人の裁定を持つ。候補を自動適用へ変える前にレビュー境界を越える必要がある。
- [マスタ](04-master.md) — `event_series_aliases` と `venue_aliases` の正本、系列別名移行、RDB artifactの可用性を持つ。

**下流**

- X収集 — 除外語と参加報告語がノイズ／一次レポの仕分けに効く。誤った用語が入ると候補量と質の両方が変わる。
- YouTube取り込み — `event_alias_runtime.json` がタイトル・概要欄の別表記を同じイベント／会場へ寄せる手掛かりになる。具体的な利用コードはL1-youtubeを読む。
- [公開](05-publication.md) — 公開用用語集exportとサイトへの同期は公開側の責務である。現在は定期実行への接続を確認できていない。

別名の正本を直すときは、RDBへの書き込み、runtimeへの投影、利用側の照合という三段を分けて確認する。RDBだけ直してもruntimeが古ければ照合に効かず、runtimeだけ手で直しても次の日次で正本から戻る。

用語集の変更も、Notionの行、日次runtime、収集時の判定という三段を通り、候補を有効化する決定は最初の段で行う。runtime JSONを直接編集して緊急回避してもNotionの正本を直さなければ次の生成で消え、逆にNotionだけ直しても日次生成前のcommit済みruntimeを読む利用側にはすぐ届かない。この時間差を知らずに調査すると、正本を直したのに効かない、または一時修正が戻ったように見える。

## 壊れたときの症状

| 見えている症状 | まず疑うところ |
|---|---|
| 未レビューの略称がイベント・会場の根拠として使われる | INV-GLS-001。Notion行の状態・確度・自動適用可の絞り込み |
| X投稿のノイズ／一次レポ判定が急に変わる | `glossary_runtime.json` の除外語・参加報告語とX設定へのマージ |
| 英語名・旧称を含むYouTube動画が既知イベントへ結び付かない | INV-GLS-002。RDB alias表、carry over、runtimeファイルの鮮度 |
| 日次は成功したのに別名照合件数が急減する | 空のalias sectionをcommitしていないか、`carried_over_sections` の理由 |
| 別名をRDBへ追加したのに翌日まで照合に出ない | runtime再生成・commitがまだ行われていない |
| ローカル実行でレビュー用の未確認差分が増えた | `run_manual_glossary_review.py` を `--manual` で意図して実行したか |
| 公開用の用語集が更新されない | `export_public_glossary.py` は現在workflowから呼ばれていない。export・site同期の接続を個別に確認 |

## 未解決・注意点

- **X界隈語観測は用語集v2へ未接続である。** 観測回数が多くても候補採用や自動適用を意味しない。第2段で候補化、レビュー、Notion正本への反映を別々に設計する必要がある。
- **用語runtimeの空出力防止は別名runtimeほど確認できていない。** Notion token／DB IDが無いと `load_glossary_v2()` は空辞書を返す。日次が空artifactをcommitしてよいかの明示的保護は、別途検討が必要である。
- **公開用用語集の自動接続は未確認ではなく、現状のworkflow／Python検索では未接続である。** 手動exportがsiteへ書くことと、本番サイトに反映されることは別である。
- **候補シードとレビューUIは日次ではない。** `build_glossary_v2_seed_candidates.py`、`merge_glossary_v2_oto_reports.py`、`build_glossary_review_ui.py` を日次へ足すには、候補の正本、レビュー境界、artifactのcommit方針を決める必要がある。
- **系列別名移行はL1-masterとの境界にまたがる。** `run_series_alias_migration.py` はここが所有するが、`event_model/series_alias_migration.py` のschema変更や本番適用の判断はマスタ側を優先する。
- **YouTubeのcurated alias applyはここで所有しない。** L1-youtubeが `apply_curated_youtube_aliases.py` と `youtube_backfill/event_aliases.py` を持つ。runtimeの利用先としてこの本文から参照するだけである。
- **公開用exportのテストは限定的である。** `tests/test_export_public_glossary.py` は曲項目の説明・読みのマージを検査するが、Notionからsiteまでの実行経路を守るテストではないため、本L1のINVには引用していない。
- **手動レビューUIの正本は固定されていない。** おとのレビュー報告を統合して作る経路は残るが、日次候補とどちらを優先して裁定するかは運用上の判断である。候補を自動有効化する経路にはしてはいけない。
- **別名runtimeのcarry overは可用性を優先する。** RDBが空の場合に古いaliasを残すため、正本を意図して削除したい場合は `--allow-empty` を含む明示操作と、利用側への影響確認が必要になる。

この仕様の中心にあるのは、日次に動く二つのruntime builderだけである。周辺のexport・候補生成・レビューUIは同じ用語を扱うので一体に見えるが、稼働状態はばらばらで、同じ経路だと思って触ると実際には動いていないものを直すことになる。だから新しい処理を足すときは、まずどちらの正本（Notionの用語集v2か、Master RDBの別名表か）を読むのかを決める。そのうえで、候補を作る段・人が裁定する段・正本へ書く段・runtimeへ投影する段のどこを担当するのかを書く。この区別が無いまま足した処理は、レビュー境界をまたいで未確認の語を日次へ流し込むため、仕様を変える前にはruntimeを読む利用側も検索し、その結果をこのL1へ反映する。
