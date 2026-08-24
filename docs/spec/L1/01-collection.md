---
id: L1-collection
layer: L1
title: 収集サブシステム
owns:
  - collect.py
  - x_queries.json
  - collection_support/x_raw_archive.py
  - collection_support/x_budget_guard.py
  - collection_support/x_cost_ledger.py
  - collection_support/x_collection_health.py
  - collection_support/x_source_registry.py
  - collection_support/x_author_profile.py
  - collection_support/x_official_source_accounts.py
  - collection_support/voices_s3_artifact.py
  - voices_s3_artifact.py
  - collect_venue_sites.py
  - venue_sites.json
  - build_x_gap_candidates.py
  - discover_x_social_graph.py
  - sync_x_promoted_members.py
  - sync_weekly_costs.py
  - .github/workflows/collect.yml
  - .github/workflows/refresh_official_source_review.yml
  - scan_ward_official_sources.py
  - data/ward_official_source_registry.json
depends_on: []
invariants:
  - INV-COL-001
  - INV-COL-002
  - INV-COL-003
  - INV-COL-004
  - INV-COL-005
  - INV-COL-006
  - INV-COL-007
  - INV-COL-008
  - INV-COL-009
verified_by:
  - tests/test_x_raw_archive.py
  - tests/test_x_collection_health.py
  - tests/test_collect_no_semantic_exclusion.py
  - tests/test_x_search_watermark.py
  - tests/test_x_gap_candidates.py
  - tests/test_collect_event_state_axes_wiring.py
  - tests/test_sync_event_date_predictions_rdb.py
  - tests/test_ward_official_source_registry.py
updated_for: a47769f
---

# 収集サブシステム

> 上位は[全体地図](../README.md)。収集は候補と観測を集める工程であり、採否を決める工程ではない。

## この工程は何のためにあるか

RSS、YouTube、X、公式ソースから、盆踊りに関係しうる情報を失わず集める。外部APIは欠損や失敗が普通に起きるため、失敗を「情報なし」と取り違えず、次の判断工程へ根拠と状態を渡すことが責務である。

## 入力と出力

入力は各サービスの取得結果、既読URL、X設定（`x_queries.json`）、予算状態、検索クエリの読み取り位置（`data/x_query_watermarks.json`）、および会場公式サイトの監視設定（`venue_sites.json`）である。出力は `data/voices.json`、`data/latest.json`、生X投稿のアーカイブ、収集状態・コスト台帳、および候補キューである。

`collect.yml` には、2026-08-16の公開detail修復専用jobも一時的に同居する。通常の収集jobとは排他的で、
mainのOIDC信頼を緩めず、merge済みmainのSHA・S3 checksum・確認文字列を全て照合してからMaster RDBを扱う。
これは収集経路をPR branchから本番へ広げる例外ではない。修復後は証跡を残して専用jobを除去する。

## 不変条件

### INV-COL-001 Xの生投稿は意味判定より先に保存する

- **内容**: 未見のX投稿は `_prepare_new_x_posts()` が `capture_raw_x_posts()` で保存に成功してから後続の仕分けへ渡す。保存失敗時は既読を進めない。
- **なぜ**: 分類ルールは後で直せるが、取りこぼした原文は復元できないから。
- **破れたときの症状**: 判定規則を直しても過去投稿を再評価できず、候補が静かに欠落する。
- **守っているコード**: `collect.py` の `_prepare_new_x_posts()`、`collection_support/x_raw_archive.py`
- **守っているテスト**: `tests/test_x_raw_archive.py::test_archive_failure_propagates_without_seen_advance`

### INV-COL-002 同じURLを1回の収集で重複して取り込まない

- **内容**: `_prepare_new_x_posts()` は既読集合・今回の既読予定集合・今回の準備済みURLを照合して重複を除く。
- **なぜ**: 同じ投稿の重複は候補の件数と重要度を水増しし、後段の人の判断を歪めるから。
- **破れたときの症状**: 同一投稿が複数の候補として並び、レビュー件数とXコストの説明が合わなくなる。
- **守っているコード**: `collect.py` の `_prepare_new_x_posts()`
- **守っているテスト**: `tests/test_collect_duplicate_urls.py::test_prepare_new_x_posts_excludes_duplicate_seen_new_seen_and_empty_urls`

### INV-COL-003 収集不能・受理0件を正常な「投稿なし」として扱わない

- **内容**: `collect_x_voices()` はキー・設定・予算が欠けると理由つきで安全にスキップする。さらに `finalize_health_report()` は、収集が必要なのに無効だった場合と、成功扱いでも受理0件だった場合を `unhealthy` にする。
- **なぜ**: 2026-08-10のtwitterapi.io課金切れでは、HTTP上は成功しても取得が空だった。止めるだけでは障害を「投稿なし」と取り違えるため、空を異常として見える化しなければならない。
- **破れたときの症状**: API費用が予想外に増える、または収集停止・受理0件が正常終了に見えて探索の穴が何日も続く。
- **守っているコード**: `collect.py` の `collect_x_voices()`、`collection_support/x_budget_guard.py`、`collection_support/x_collection_health.py` の `finalize_health_report()`
- **守っているテスト**: `tests/test_x_collection_health.py::test_successful_but_zero_item_run_is_unhealthy`、`tests/test_x_collection_health.py::test_measured_scheduled_outage_is_unhealthy_for_402_and_zero_items`

### INV-COL-004 未完了のホワイトリスト収集では since_time を進めない

- **内容**: `collect_whitelist_voices()` は、全バッチが完了したときだけ次回検索の `since_time` を保存する。402などで一部でも未完了なら従来の時刻を維持する。
- **なぜ**: `since_time` を先に進めると、その時間窓の投稿は次回以降の検索対象から外れ、取りこぼしが恒久化するから。
- **破れたときの症状**: 課金・通信障害の時間帯だけ候補が永久に消え、復旧後も再収集されない。
- **守っているコード**: `collect.py` のホワイトリスト収集と `since_time` 保存経路
- **守っているテスト**: `tests/test_x_collection_health.py::test_whitelist_402_after_partial_success_does_not_advance_since_time`、`tests/test_x_collection_health.py::test_whitelist_advances_since_time_only_after_every_batch_completes`

### INV-COL-005 収集の関門は意味を理由に投稿を捨てない

- **内容**: 取得した投稿を落としてよいのは、意味を読まなくても判定できる条件だけである（既見URL、重複、文脈信号が1つも無い＝`no_context`）。**語彙の一致で「これは盆踊りの話ではない」と決めて捨ててはならない。** `_x_post_value_score` の除外語打ち切り、`_score_voice` の🔴ノイズ、`classify_event_evidence` の除外語減点は、いずれも 2026-08-15 に廃止した。
- **なぜ**: 生投稿7,162件で実測したところ、除外語の関門が落としていた212件のうち**117件（55%）が盆踊りの話**だった。「セトリ」「セットリスト」で曲目そのものを、「ガチャ」で縁日のガチャガチャを、「ポケモン」でポケモン音頭の参加報告を、部分文字列の一致だけで捨てていた。正しく弾けていたのは95件（全体の1.3%）で、うち79件は同一アカウントのお笑いライブ定型告知である。**1.3%の手間のために、盆助が集めている情報の中心（曲目）を捨てる取引は割に合わない。** 「これは盆踊りの話か」は意味の判断なので、LLMが候補として読んでから決める。定型連投のような相手は、同一発信者・同一文型といった意味を見ない条件で落とす。
- **破れたときの症状**: 曲目や参加報告が収集の時点で消え、下流のどこを直しても出てこない。捨てた記録も残らない（raw アーカイブにはあるが、下流には流れない）。
- **守っているコード**: `collect.py` の `_x_post_value_score()` と `_score_voice()`、`collection_support/event_evidence.py` の `classify_event_evidence()`
- **守っているテスト**: `tests/test_collect_no_semantic_exclusion.py::test_real_posts_are_not_dropped_by_the_value_gate`、`tests/test_collect_no_semantic_exclusion.py::test_voice_scoring_never_returns_noise`、`tests/test_collect_no_semantic_exclusion.py::test_the_gate_still_drops_posts_without_any_context`

### INV-COL-006 読み切れなかった検索クエリでは since_time を進めない

- **内容**: `collect_x_voices()` はクエリごとに「ここまで読んだ」時刻を `data/x_query_watermarks.json` へ持ち、次回はその先だけを読む。窓を進めてよいのは、そのクエリを**読み切れたとき**（次ページが無い／空ページに達した／新規0件のページに達した）だけである。ページ上限で切れた場合とHTTP失敗の場合は、従来の時刻を維持する。
- **なぜ**: INV-COL-004 とまったく同じ理由である。読み切れていないのに窓を進めると、その時間帯の投稿は次回以降の検索対象から外れ、取りこぼしが恒久化する。検索は名簿の直読みと違って「誰の投稿か」で後から追いかけ直せないので、一度飛ばした時間帯は二度と拾えない。
- **破れたときの症状**: 費用は下がるのに voices の採用件数が静かに減る。とくに投稿が集中する開催日の夜（ページ上限に当たりやすい時間帯）の声が欠ける。
- **守っているコード**: `collect.py` の `collect_x_voices()`、`_load_query_watermarks()` / `_save_query_watermarks()` / `_query_since_time()` / `_apply_since_time()`
- **守っているテスト**: `tests/test_x_search_watermark.py::XSearchWatermarkTest::test_page_limited_query_does_not_advance_the_watermark`、`tests/test_x_search_watermark.py::XSearchWatermarkTest::test_http_failure_does_not_advance_the_watermark`、`tests/test_x_search_watermark.py::XSearchWatermarkTest::test_other_queries_keep_their_own_position`

### INV-COL-007 収集の読み取り位置と費用台帳は実行のたびにコミットする

- **内容**: 日次の `collect.yml` は `data/x_query_watermarks.json` と `data/x_cost_ledger.json` を毎回コミット対象に含める。
- **なぜ**: どちらもリポジトリのファイルが正本で、Actions のワークスペースは実行ごとに消える。読み取り位置が残らなければ毎回「初回」扱いに戻り、既読分への課金がそのまま復活する。費用台帳が残らなければ、削減の前後を比べる材料そのものが無くなる。
- **破れたときの症状**: 費用削減の変更を入れたのに日次費用が下がらない。費用ログの表を実測で更新できず「見込み」のまま放置される（2026-08-12に台帳を作ったとき、実際に `git add` から漏れていて1件も残っていなかった）。
- **守っているコード**: `.github/workflows/collect.yml` のコミット段
- **守っているテスト**: `tests/test_x_search_watermark.py::XSearchWatermarkPersistenceTest::test_workflow_commits_the_watermark_and_the_cost_ledger`

### INV-COL-008 区名のないX告知も既知会場の構造化住所で23区候補にできる

- **内容**: `build_x_gap_candidates.py` は、投稿本文だけでは東京23区と断定できないとき、任意入力の
  `data/blog_venue_rows.json` にある十分に長い会場名との完全な正規化部分一致を調べる。その行の
  `region_hint` / `address` が23区を示す場合だけ地域根拠として採用する。同じ既知会場・同じ初日の
  非公式投稿は一候補へ束ね、全投稿URLとポスター画像URLを保持する。会場行が無い場合は従来の
  明示地域シグナルへfail closedする。
- **なぜ**: 「京華スクエア（八丁堀3-17-9）」のように、人には中央区と分かる詳細な告知でも、
  本文に「東京都」「中央区」が無いだけで従来のX gapから落ちていた。個別地名を正規表現へ足すと
  同じ欠落を別会場で繰り返すため、すでに住所を持つ構造化会場行を根拠として再利用する。
- **破れたときの症状**: 日時・会場・ポスター・複数投稿が揃った未登録イベントが
  `x_news_digest_for_oto.json` にはあるのに、`x_gap_candidates.json` とReview Inboxへ一度も現れない。
- **守っているコード**: `build_x_gap_candidates.py` の `known_tokyo23_venue_evidence()`、
  `known_venue_event_key()`、`build()`
- **守っているテスト**: `tests/test_x_gap_candidates.py::test_known_tokyo_venue_groups_kyoka_posts_without_a_ward_token`

### INV-COL-009 日次収集は生成日付予測を正本RDBへ同期してから公開射影へ進む

- **内容**: `collect.yml` は取得・監査したMaster RDBに対し、
  `sync_event_date_predictions_rdb.py` のdry-run → execute → 監査を公開射影とcollectorより前に行う。
  生成予測の同期は状態軸feature flagから独立して動き、状態軸と同じDB成果物をCASで1回だけpublishする。
  再取得後は `--check` が変更0でなければ後続へ進まない。
- **なぜ**: YouTube日次と収集日次は別workflowなので、前者がJSONだけを更新した状態は通常に起こる。
  正本RDBを同期しないまま公開射影すると安全ガードがcollectorより先に落ち、RSS・X収集も止まる。
- **破れたときの症状**: `collect.yml` が `event_date_predictions.json` の更新翌日から連続失敗し、
  X収集健全性レポートやイベント状態の証跡も作られない。
- **守っているコード**: `.github/workflows/collect.yml` の
  `Sync date predictions and canonical event-state axes to master RDB` ステップ、
  `sync_event_date_predictions_rdb.py`
- **守っているテスト**: `tests/test_collect_event_state_axes_wiring.py`、
  `tests/test_sync_event_date_predictions_rdb.py::SyncEventDatePredictionsRdbTest::test_sync_closes_public_json_fallback_without_changing_confirmed_date`

## 主要な流れ

1. S3からMaster RDBを取得・監査し、生成済みの日付予測を正本の予測表へ同期する（INV-COL-009）。
2. `collect.py` がRSS・動画・Xを取得し、既読情報と照合する。
3. Xは生投稿をアーカイブしてから、候補・声・収集状態へ分ける。
4. `collect_venue_sites.py` が会場公式サイトを直接見に行き、`venue_sites.json` に登録されたRSS/HTMLから
   お知らせを取る。ニュースメディア経由では拾えない告知がここでしか取れないためで、
   取れたものは `source: "official_venue"` / `confirmed: true` を付けて `latest.json` へ合流する。
   1サイトの失敗が他サイトを止めない作りにしてある。
5. コストと健全性を記録し、候補は判断工程へ渡す。
6. `voices_s3_artifact.py`（中身は `collection_support/voices_s3_artifact.py` を呼ぶだけの互換入口）で、
   声をS3の成果物として受け渡す。日次の各workflowは処理の最初に `fetch --overwrite`、
   最後に `publish` を実行する。リポジトリに巨大なJSONを置かずに、複数のworkflowが同じ声を見るための仕組みである。
7. `refresh_official_source_review.yml` は薄い8区の `data/ward_official_source_registry.json` を週次巡回する。
   `scan_ward_official_sources.py` は既存の `scan_official_sources()` を再利用し、盆踊り文脈を確認できた区公式ページだけを
   `ward_official_source_candidates.json` にする。日付・催事名・会場を見出しで特定できるHTML tableは1行を1候補に分割し、
   日付と盆踊り語を含むHTML listも1項目を1候補にする。構造を特定できないHTML、PDF、JavaScript描画ページは
   従来どおりページ単位候補へfallbackする。これは候補作成までで、canonical eventや公開JSONは変更しない。

### 収集の穴と、読む相手を広げる経路（日次）

集めることと並んで、**集められていないものを見つける**のもこの工程の仕事である。
以下は日次で動いているが、2026-08-14まで仕様のどこにも属していなかった。

- `build_x_gap_candidates.py --limit 30` — 収集済みの投稿の中から、
  **公開データに無いイベントの話をしていそうなもの**を選ぶ。「穴」とはこの取りこぼしのことである。
  30件は日次表示の上限であり、上限超過分を捨てる境界ではない。`collect.yml` は直後に
  [レビュー](03-review.md)側の `x_candidate_backlog.py` を呼び、選択分と `archived_candidates` の双方を
  永続台帳へ合流する。そこから5件だけをReview Inboxの部分コホートにする契約は
  INV-RVW-021 / INV-RVW-022にある。`build_x_gap_candidates.py` またはこのworkflow配線を触るときは、
  収集INVだけでなくその2つも確認する。
- `discover_x_social_graph.py` — いま読んでいるアカウントの周辺から、新しく読むべき相手を探す。
  日次の `collect.yml` ではなく専用の workflow から動く。
- `sync_x_promoted_members.py` — 人が承認した「読む相手に加える」判断を、Xのメンバー台帳へ反映する。
  `review_x_candidate_posts.yml` から、候補の投稿を人が見る補助（`review_x_candidate_posts.py`、[レビュー](03-review.md)の持ち物）と対で動く。

読む相手が偏ると、特定の区だけ情報が薄くなるという形で症状が出る。
これは判定の精度の問題に見えるが、原因は入口の偏りであることが多い。

### 同じ投稿に二度払わないための読み取り位置

X検索は取得件数ぶんだけ課金される（$0.15/1000件）。従来は11本のクエリを毎回1ページ目から読み直し、
既読URLは `data/voices.json` へ保存する段で捨てていた。**捨てていたのは保存であって課金ではない。**
2026-08-11 の実測では、1日1,760件を取得して新規は660件（37.5%）、
残り1,100件は前日までに読んだ投稿の読み直しだった。

そこで `collect_x_voices()` は、クエリごとの `since_time` を `data/x_query_watermarks.json` に持ち、
`盆踊り lang:ja since_time:1786...` の形で「前回読んだ先」だけを取りに行く。
仕組みは名簿の直読み（`data/x_whitelist_state.json`）と同じで、次の2点だけ違う。

- **クエリ単位で持つ。** クエリを1本足したとき、その1本だけが過去にさかのぼって読み始められる。
- **重なりを残す。** `overlap_minutes`（既定60分）ぶん手前から読み直す。窓の境目に来た投稿を落とさないため。

窓を進めてよい条件は INV-COL-006 のとおりで、**読み切れたときだけ**である。
`queryType=Latest` は新しい順に返すので、新規が1件も無いページに達したらそこから先は既読の領域であり、
そのクエリは打ち切ってよい（`stop_after_zero_new_page`）。逆にページ上限に当たって切れた場合は、
まだ読めていない時間帯が残っているので窓は据え置く。**据え置いても費用は増えない**——
ページ上限が費用の天井なので、読む量は変わらず、次に投稿が少ない日が来たときに窓が追いつく。

なお `x_queries.json` の `search_watermark.enabled` を `false` にすると、
設定だけで従来の全件読み直しへ戻せる。取りこぼしが疑われたときの退避路として残してある。

費用の記録は `sync_weekly_costs.py` が担う。`data/x_budget.json` を読んでNotionの費用DBへ週次で書き出すもので、
`weekly_harvest.yml` から動く。X収集は使った分だけ課金される仕組みなので、
**使いすぎだけでなく「払えていない」こともここに現れる**。2026-08-10の課金切れでは、
HTTP上は成功しているのに取得が0件という形で障害が出た（INV-COL-003）。

## 依存と影響

下流の判断とレビューは、収集の重複除去・生原文・失敗理由を前提にする。収集を「候補なし」と誤ると、下流は何も直せない。

## 壊れたときの症状

候補が急減したらAPIキー・予算・収集健全性を、同じ投稿が並ぶなら既読・URL正規化を、再評価できないならアーカイブを確認する。

## 未解決・注意点

外部サービスの応答品質はこの工程だけでは保証できない。取得なしと障害を区別する観測は引き続き強化が必要である。

---

おと（Codex）
