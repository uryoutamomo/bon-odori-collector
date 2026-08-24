---
id: L1-youtube
layer: L1
title: YouTube取り込みサブシステム
owns:
  - youtube_backfill/**
  - youtube_channels/**
  - run_daily_youtube_backfill.py
  - run_review_inbox_youtube_scheduled.py
  - run_review_inbox_youtube_active_scheduled.py
  - build_youtube_active_video_review.py
  - build_youtube_year_backfill_queue.py
  - build_youtube_year_backfill_review_queue.py
  - build_youtube_channels.py
  - build_youtube_channel_review.py
  - build_youtube_song_master.py
  - build_youtube_event_song_candidates.py
  - build_youtube_nationwide_hold.py
  - apply_youtube_setlist_occurrences_rdb.py
  - apply_curated_youtube_aliases.py
  - apply_youtube_year_backfill_review_decisions.py
  - apply_youtube_2025_koto_decisions.py
  - dry_run_youtube_existing_event_updates.py
  - dry_run_youtube_active_existing_event_updates.py
  - export_youtube_2025_date_backfill_plan.py
  - export_youtube_2025_official_candidate_validation.py
  - export_youtube_2025_second_pass_event_groups.py
  - fetch_youtube_2025_backfill.py
  - promote_youtube_channel_registry.py
  - refresh_youtube_voices.py
  - update_youtube_notion_progress.py
  - update_youtube_followup_progress.py
  - close_youtube_notion_task_checkboxes.py
  - scripts/manual/audit_youtube_song_clip_fragments.py
  - scripts/manual/render_youtube_candidate_report.py
  - .github/workflows/youtube_daily_backfill.yml
  - .github/workflows/rdb-youtube-setlist-pipeline.yml
  - ops/com.ryotauchida.bon-odori.youtube-daily.plist
  - docs/youtube-daily-operations.md
depends_on:
  - L1-collection
  - L1-review
  - L1-master
  - L1-publication
  - L1-songs
invariants:
  - INV-YTB-001
  - INV-YTB-002
  - INV-YTB-003
  - INV-YTB-004
  - INV-YTB-005
  - INV-YTB-006
verified_by:
  - tests/test_run_daily_youtube_backfill.py
  - tests/test_youtube_daily_operations_policy.py
  - tests/test_apply_youtube_setlist_occurrences_rdb.py
  - tests/test_extract_youtube_setlists.py
  - tests/test_rdb_youtube_setlist_pipeline_workflow.py
  - tests/test_sync_event_date_predictions_rdb.py
updated_for: a47769f
---

# YouTube取り込みサブシステム

> 上位は[全体地図](../README.md)。書き方の決まりは [SPEC-GUIDE](../SPEC-GUIDE.md)。
> [曲目](08-songs.md)と同じく、これも**工程ではなくドメイン**で切ってある。理由は「主要な流れ」の冒頭に書いた。

## この工程は何のためにあるか

盆踊りの開催情報がどこにもまとまっていないことは[全体地図](../README.md)に書いたとおりだが、
**過去に開かれたかどうか**はもっと分からない。町会は告知を出しても記録は残さないので、
「この盆踊りは去年もあったのか」「例年いつ頃なのか」を知る手立てが、公式の情報源にはほとんど無い。

ところが踊りに来た人は動画を上げる。そして盆踊りの動画は、他のイベント動画と違って**概要欄に曲順が書かれることがある**。
「1. 東京音頭 2. 炭坑節 …」と時刻リンク付きで並ぶあの形式である。
つまりYouTubeは、盆助にとって次の3つを同時に持っている珍しい入力になっている。

1. **過去にその盆踊りが開かれた証拠**（何年の何月何日に、どこで）
2. **その回で実際に踊られた曲**（[曲目サブシステム](08-songs.md)の主要な入力のひとつ）
3. **会場と日付のヒント**（タイトルや概要欄に書かれた地名・日付）

ただし、**YouTubeは公式の告知ではない**。動画があることは「去年開かれた」証拠にはなるが、
「今年も開かれる」証拠にはならない。ここを混ぜると、中止になった盆踊りへ人を歩かせることになる。
だからこの工程の設計は、集めることそのものより**「集めた証拠をどこで止めるか」**に重心がある。
不変条件の多くが「公開へ流さない」「確定にしない」という形をしているのはそのためである。

## 入力と出力

**入力**

- `data/voices.json` のYouTube由来の投稿 — `83bf7d0` 時点で4,650本。[収集サブシステム](01-collection.md)の出力
- **YouTube Data API v3**（`search` と `videos`）— APIキーは `YOUTUBE_DATA_API_KEY`。1日のクォータが実質の律速
- `data/youtube_year_backfill_queue.json` — 掘り起こしの対象行（362行、2026-06-19生成）
- `data/public/events_public.json` — 動画をどの公開イベントに結びつけるかの照合先
- `data/curated_youtube_aliases.json` 相当の別名定義 — `youtube_backfill/event_aliases.py` が使う

**出力**

- `data/youtube_year_backfill_candidates.json` — 掘り起こしの候補（582件。強一致183・要レビュー48・弱351）
- `data/youtube_backfill_retry_state.json` — 行ごとの最終検索日、次回検索可能日、直近の成果件数を持つ再試行台帳
- `data/event_occurrence_observations.json` — 「この系列はこの年に開かれた」という観測（30系列・53観測）
- `data/event_schedule_rules.json` / `data/event_date_predictions.json` — 観測から導いた開催規則と日付予測（2026-08-18時点で予測17件）
- `data/youtube_setlist_occurrences.json` — 概要欄から取り出したセットリスト（307開催回・延べ2,745曲。うち公開イベントに結びついたもの23件）
- `data/youtube_active_video_review.json` — レビュー対象の動画一覧（4,618本）
- `data/youtube_daily_backfill_report.json` / `.md` — 日次の実行記録。GitHubのジョブ要約にも出る
- `data/pending_mail.json` への催促文（`--mail-reminder`）— [配信サブシステム](06-delivery.md)が拾う

週次の `rdb-youtube-setlist-pipeline.yml` は、セットリスト抽出からRDBへの開催回・曲根拠追加、
直接確率の校正、過去年実績の継承までを必ずdry-runしてから正本へ適用し、auditとCAS付きS3 publishを行う。
手動実行は既定でdry-runだけ、定時実行だけがapplyする。公開JSONは監査用の一時ディレクトリにだけ生成し、commitしない。
生成した日付予測は、後続の収集日次が
`predicted_occurrence_dates` へ同期するが、開催回の確定日にはしない（[INV-MST-013](04-master.md)）。
公開JSONを作るのは[公開サブシステム](05-publication.md)の `export_public_events.py` であり、
この工程からは呼ばない（INV-YTB-001・INV-YTB-002）。

## 不変条件

### INV-YTB-001 日次バックフィルの出力を、公開JSONとして main へ載せない

- **内容**: `.github/workflows/youtube_daily_backfill.yml` の結果コミットで、
  `data/public/events_public.json` と `data/public/events_public.js` を `git add` してはいけない。
  日次のレポート・候補・観測・予測は載せてよいが、公開JSONだけは対象外である。
- **なぜ**: この工程が呼ぶ公開exportには、**まだどのイベントにも結びついていない観測層の行**が混ざる。
  動画タイトルの引用部分をまるごと1曲名として取り込んだような行がその例である。
  これを main へ入れると、公開データを同期する定時実行がそのまま本番サイトへ出してしまう。
  公開JSONの正本は、日次収集がRDBの確定層から作るものひとつだけにしてある。
- **破れたときの症状**: bonsuke.jp に、動画タイトルの断片が曲名として並ぶ。
  誰も裁定していないイベントが公開に現れる。
- **守っているコード**: `.github/workflows/youtube_daily_backfill.yml` の `Commit results to main` ステップ
- **守っているテスト**: `tests/test_youtube_daily_operations_policy.py::YouTubeDailyOperationsPolicyTest::test_workflow_does_not_stage_public_event_json`

### INV-YTB-002 日次の再生成は公開exportへ接続しない

- **内容**: `run_daily_youtube_backfill.py` の `regenerate_outputs()` は、観測・開催規則・日付予測までを再生成するが、
  `export_public_events.py`、`apply_public_date_predictions.py`、`apply_public_season_hints.py`、
  `apply_public_historical_references.py` を呼ばない。workflowのcommit対象にも公開日付の適用結果を含めない。
- **なぜ**: YouTubeから導いた予測は推測であって確定ではない。2026-08-17・18は
  このworkflowがJSON予測を増やした後、別workflowの `collect.yml` がRDBにない予測を検出し、
  INV-PUB-006のガードで2日連続停止した。ガードを緩めたり、この工程から公開物を作ったりせず、
  後続の日次が予測表だけを同期するのが境界として正しい（INV-MST-013）。
- **破れたときの症状**: YouTube日次は候補・予測・再試行台帳を正常にcommitしたのに、
  次の収集日次が公開exportのガードでcollector実行前に停止する。
- **守っているコード**: `run_daily_youtube_backfill.py` の `regenerate_outputs()` と
  `.github/workflows/youtube_daily_backfill.yml` のcommit対象
- **守っているテスト**: `tests/test_run_daily_youtube_backfill.py::RunDailyYoutubeBackfillTest::test_regenerate_outputs_does_not_call_public_export`、
  `tests/test_youtube_daily_operations_policy.py::YouTubeDailyOperationsPolicyTest::test_workflow_does_not_stage_public_event_json`

### INV-YTB-003 クォータ上限に当たったら、失敗させずにその時点で止める

- **内容**: YouTube APIが `quotaExceeded` などの理由で 403 を返したら、
  `run_harvest_batches()` は例外を投げずに `status="quota_limited"` を返し、
  そこまでに取れた候補と、次に再開する位置を記録して終わる。
- **なぜ**: **クォータ切れは異常ではなく、この工程の通常の終わり方である。**
  実際に直近14日すべての実行が `quota_limited` で終わっている。
  例外で落とすとworkflowが赤くなり、日次が壊れているのか単に上限に当たっただけなのか区別できなくなる。
  赤が常態化すると、本物の異常が埋もれる。逆に、途中まで取れた候補を捨ててしまうと、
  クォータを使った分の成果が毎日消える。
- **破れたときの症状**: YouTube日次が毎日失敗として通知される。
  あるいは失敗した日の候補が丸ごと失われ、翌日も同じ行を引き直す。
- **守っているコード**: `run_daily_youtube_backfill.py` の `is_quota_limited_http_error()` と `run_harvest_batches()`
- **守っているテスト**: `tests/test_run_daily_youtube_backfill.py::RunDailyYoutubeBackfillTest::test_run_harvest_batches_stops_cleanly_on_quota_limit`、
  `tests/test_run_daily_youtube_backfill.py::RunDailyYoutubeBackfillTest::test_quota_limited_error_detects_youtube_403_reason`

### INV-YTB-004 セットリスト由来の曲名は、曲マスタの検査を通ったものだけを開催回の曲にする

- **内容**: `apply_youtube_setlist_occurrences_rdb.py` は、セットリストの各行を `resolve_song()` に通してから
  `occurrence_songs` へ書く。曲マスタに完全一致すれば採用、見たことのない文字列でも曲名の形をしていれば
  `status='候補'` として登録、形の検査に落ちれば**書かない**。
  とくに、人が「これは曲名ではない」と判定して `無効` にした行に当たった場合は、形の検査より台帳の判定を優先して落とす。
  採用しなかった文字列は `observed_occurrence_songs.raw_song_title` に原文のまま残す。
- **なぜ**: 概要欄の解析は、イベント名・協賛表記・「第70回」のような断片を曲名として吐くことがある。
  会場名がその会場の全曲に混ざり込む不具合も実際に起きた（2026-07-24の花園神社・下町盆踊りフェスの例）。
  無効化した行を拾わない扱いにしているのは、再取り込みのたびに人が消した曲名が戻ってくる経路が実際にあったからである
  （2026-07-26、DJの進行見出しを無効化した際に発見）。
  捨てずに `raw_song_title` へ残すのは、あとから抽出を直したときに何を落としたか追えるようにするためである。
- **破れたときの症状**: 公開の曲目欄に、曲名でない文字列（イベント名・会場名・「第70回」など）が並ぶ。
  一度人が消した曲名が、日を置いて復活する。
- **守っているコード**: `apply_youtube_setlist_occurrences_rdb.py` の `resolve_song()`、
  `song_title_passes_shape_check()`、`clean_song_candidate_title()`
- **守っているテスト**: `tests/test_apply_youtube_setlist_occurrences_rdb.py::ResolveSongTest::test_rejects_a_title_whose_master_row_was_deactivated`、
  `tests/test_apply_youtube_setlist_occurrences_rdb.py::ResolveSongTest::test_rejects_an_unseen_title_that_is_not_a_song_name`、
  `tests/test_apply_youtube_setlist_occurrences_rdb.py::ResolveSongTest::test_registers_an_unseen_plausible_title_as_a_candidate`、
  `tests/test_apply_youtube_setlist_occurrences_rdb.py::NonSongShapeCheckTest::test_rejects_titles_that_are_not_song_names`

  > 最後のひとつは**形の検査そのもの**を直接呼んで確かめており、`resolve_song()` がその検査を通していることまでは見ていない。
  > この仕様書を書くための変異確認でそれが判明したので、呼び出しを外したら落ちるテスト（2番目）を同じPRで足した。

### INV-YTB-005 日次バックフィルの自動実行元は、GitHub Actions ひとつだけである

- **内容**: 定期実行するのは `.github/workflows/youtube_daily_backfill.yml`（毎日05:00 JST）だけとする。
  ローカルの LaunchAgent 定義 `ops/com.ryotauchida.bon-odori.youtube-daily.plist` は手動フォールバック専用で、
  `StartCalendarInterval` を持たず、`RunAtLoad` も立てず、`--commit` や `--push` を渡さない。
- **なぜ**: この工程はクォータという有限の資源を毎日使い切る。二重に走ると、
  片方が空振りするだけでなく**互いの成果を上書きし合う**。実際どちらもmainへコミットする作りなので、
  競合はデータの喪失になる。実行元をひとつに固定しておくのが、いちばん確実な防ぎ方である。
- **破れたときの症状**: 同じ日に日次コミットが2回入る。
  クォータを使い切っているのに候補が増えない（片方の成果がもう片方に上書きされている）。
- **守っているコード**: `ops/com.ryotauchida.bon-odori.youtube-daily.plist`、`docs/youtube-daily-operations.md`
- **守っているテスト**: `tests/test_youtube_daily_operations_policy.py::YouTubeDailyOperationsPolicyTest::test_local_launchagent_template_is_manual_only`、
  `tests/test_youtube_daily_operations_policy.py::YouTubeDailyOperationsPolicyTest::test_runbook_names_github_actions_as_automatic_owner`

### INV-YTB-006 検索済みの薄い行を毎日引き直さない

- **内容**: 日次検索は、8月・7月の未検索行を、検索済み行の再試行より先に選ぶ。
  検索済み行は `data/youtube_backfill_retry_state.json` の `next_retry_on` を過ぎるまで再検索せず、
  成果ゼロが10バッチ続いた場合は、quota上限まで走らず `harvested_no_yield_limit` で終了する。
- **なぜ**: 2026-07-30〜08-16は毎日およそ100検索を使ったのに、候補は14日で6件しか増えず、
  2026-08-17分は推定108検索・53完了バッチで新規候補ゼロだった。検索済みの薄い6月・7月行を
  `--retry-selected` で毎日引き直していたためである。再試行期限をプロセス外へ保存しなければ、
  翌日のジョブは前日の空振りを知らず、同じ費用を繰り返す。
- **破れたときの症状**: 候補数が増えないまま毎日quota上限へ達する。旬の8月行が未検索のまま残る。
- **守っているコード**: `run_daily_youtube_backfill.py` の `bootstrap_retry_state()`、
  `next_rows_for_args()`、`run_harvest_batches()` と `.github/workflows/youtube_daily_backfill.yml` の対象月・上限引数
- **守っているテスト**: `tests/test_run_daily_youtube_backfill.py::RunDailyYoutubeBackfillTest::test_bootstrap_puts_existing_searches_on_cooldown`、
  `test_retry_cooldown_suppresses_row_until_due_date`、`test_unseen_rows_across_focus_months_precede_retries`、
  `test_run_harvest_batches_stops_after_consecutive_no_yield`、
  `tests/test_youtube_daily_operations_policy.py::YouTubeDailyOperationsPolicyTest::test_workflow_prioritizes_current_month_and_bounds_empty_retries`

## 主要な流れ

先に、なぜこれもドメインで切ってあるかを書いておく。YouTubeは収集・判断・レビュー・マスタ・公開のすべてに顔を出すが、
**そのどこにも収まらない**。収集L1へ入れれば「動画から曲をどう取り出すか」が説明できず、
曲目L1へ入れれば「過去開催の掘り起こし」が行き場を失う。実際 [08-songs](08-songs.md) は
YouTube由来の曲スクリプトを自分では持たず、この仕様が書かれるまで未記述領域として残していた。
一本のパイプラインとして読まないと理解できないので、縦で切ってある。

### 1. 毎朝5時の掘り起こし（稼働中）

`youtube_daily_backfill.yml` が毎日05:00 JSTに走る。直近5回はすべて成功していて、所要は1分11秒〜1分26秒である。
まず[基盤](07-platform.md)の作法どおり声とマスタRDBの成果物をS3から取り、監査してから `run_daily_youtube_backfill.py` を起動する。
渡している引数がこの工程の性格をよく表している。

```
--month 8 --auto-next-month --focus-month 8 --focus-month 7
--limit 1 --max-results 5 --retry-selected --retry-cooldown-days 30
--max-consecutive-no-yield 10 --until-quota-limited --mail-reminder
```

1回に1行だけ、検索結果は5件までとし、8月の未検索行、7月の未検索行、期限を迎えた再試行行の順に繰り返す。
**1回の量を極端に小さくして、回数で稼ぐ形になっている。** APIの1リクエストが重いためで、
`estimated_search_calls` は1行あたり最大2回と数えている。

クォータに当たった時点で `status="quota_limited"` として静かに終わる（INV-YTB-003）。
`--max-batches` は手動実行時の安全弁で、定時実行では0（上限なし）である。
ただし成果ゼロが10バッチ続けば `harvested_no_yield_limit` で先に止まり、残りのquotaを温存する。
既存169行は再試行台帳の導入日に一度だけ初期登録し、直後に同じ検索を繰り返さない。

### 2. 掘り起こした候補を、観測 → 規則 → 予測へ変える（稼働中）

harvest が終わると `regenerate_outputs()` が後段をまとめて回す。ここが「動画から例年の姿を導く」本体である。

1. `youtube_backfill.build_event_occurrence_backfill_plan` — 候補から、どの系列のどの年を埋められるかの計画を作る
2. `youtube_backfill.build_low_confidence_backfill_review` — 確信の薄いものを人のレビューへ回す
3. `youtube_backfill.apply_event_occurrence_backfill_plan` — 計画を観測（`event_occurrence_observations.json`）へ反映する
4. `youtube_backfill.build_event_schedule_rules` — 年ごとの観測から「毎年第1土曜」のような開催規則を分類する
5. `youtube_backfill.build_event_date_predictions` — 規則から今年の日付を予測する
6. `build_song_occurrences.py`（凍結中のため実質は空振り）
7. `youtube_backfill.build_month_youtube_backfill_queue` — 翌回に備えて月別のキューを作り直す

ここでは公開exportを呼ばない。観測と予測は判断材料として保存し、次の収集日次が予測だけを
Master RDBへ同期してから公開射影する。`event_occurrences` の確定日は更新しない（INV-YTB-002・INV-MST-013）。

4・5番のPythonスコアは、日付配列から候補規則を機械的に出す**候補生成**であり、公開用の最終確度ではない。
主催者の明示規則、当年の地域情報、例外・競合を読む最終判断は
[LLM開催日予測・統合確度ポリシー](../../llm-event-date-certainty-policy.md)に従ってLLMが行い、
マスタ側のvalidatorがID・日付計算・確率上限を検査する。

3番の観測ビルダーは docstring で自分の立場をはっきり書いている。
「これは将来の event_series / event_occurrences モデルのための**仮置きデータ**であり、
Notionへは書かず、未来の日付を確定として扱わない」。
[マスタ](04-master.md)の [INV-MST-002](04-master.md)（今年の確定には今年のソースが要る）と対になる制約で、
YouTubeが導いた予測はここで止まり、確定へは上がらない。

### 3. 日次収集の中にあるレビュー入口（稼働中・条件つき）

掘り起こしとは別に、日次収集 `collect.yml` の中にもYouTubeの工程がある。

```
build_youtube_active_video_review.py --max-per-channel 10000
build_youtube_year_backfill_review_queue.py
   ↓
run_review_inbox_youtube_scheduled.py --execute --confirm 'RUN SCHEDULED YOUTUBE AGGREGATE DUAL WRITE'
```

これは動画由来の要レビュー項目を[レビュー受信箱](03-review.md)へ流し込む経路で、
リポジトリ変数 `REVIEW_INBOX_YOUTUBE_AGGREGATE_DUAL_WRITE_ENABLED` が `true`、
かつマスタRDBのS3バケットが設定されているときだけ動く。`83bf7d0` 時点ではどちらも満たしている。
一方 `REVIEW_INBOX_YOUTUBE_ACTIVE_DUAL_WRITE_ENABLED` は `false` で、
`run_review_inbox_youtube_active_scheduled.py` はどのworkflowからも呼ばれていない。

**ここで作られる入力JSON（`youtube_active_video_review.json` など）はコミットされない。**
毎日作り直されるが、mainへ入るのは受信箱の投影 `data/review_inbox.json` だけである。
リポジトリの `youtube_active_video_review.json` が2026-07-20で止まって見えるのはそのためで、
壊れているわけではない。ここを取り違えると「YouTubeのレビュー入口が1か月止まっている」と誤診する。

### 4. 概要欄からセットリストを取り出す（**手動。2026-07-25で止まっている**）

`youtube_channels/extract_youtube_setlists.py` が `voices.json` のYouTube投稿を読み、
番号付きの曲目リスト、タイトル中の引用符つき曲名、章立て（チャプター）などから曲を取り出して
`data/youtube_setlist_occurrences.json` を作る。同じイベントの複数動画を、会場・日付・投稿者でまとめる処理も入っている。

**このスクリプトはどのworkflowからも呼ばれていない。** 出力の生成時刻は2026-07-25で止まっており、
つまり**曲目サブシステムの主要な入力のひとつが、3週間更新されていない**。
テストは24件あって手厚いが、テストが通ることと動いていることは別である。

取り出したセットリストをRDBへ入れるのが `apply_youtube_setlist_occurrences_rdb.py` で、
これも手動である（呼び出し元は `calibrate_song_probabilities_rdb.py` のみ。それ自体も手動実行）。
既定ではコピーDBにしか書かず、本番RDBへ入れるには `--apply` と確認句が要る（[INV-MST-003](04-master.md)と同じ作法）。
曲名の検査は INV-YTB-004 に書いた。**確率の計算はこのスクリプトの仕事ではない**点も重要で、
観測された事実だけをRDBへ上げ、確率は別パスの `calibrate_song_probabilities_rdb.py` が計算する。
ここで確率を作ってしまうと、根拠の無い数字が観測に見えてしまうためである。

### 5. チャンネル台帳（**手動。2026-06-29で止まっている**）

`youtube_channels/discover_youtube_channels.py` が投稿からチャンネルを見つけ、
`build_youtube_channels.py` がセットリストを出す度合いで採点し、
`promote_youtube_channel_registry.py` がレビュー済みのチャンネルを収集対象の台帳へ昇格させる。
`data/youtube_channels.json` は7チャンネル（優先5）で、2026-06-29 生成のまま更新されていない。
この3本もworkflowからは呼ばれていない。

### 6. 一回きりの掘り起こしと、Notion時代の残骸（休眠）

`fetch_youtube_2025_backfill.py`、`export_youtube_2025_*.py`、`apply_youtube_2025_koto_decisions.py` は
2025年分をまとめて掘り起こしたときの一回きりのスクリプトである。再実行は想定されていない。

`update_youtube_notion_progress.py`、`update_youtube_followup_progress.py`、
`close_youtube_notion_task_checkboxes.py` は、Notionが正本だった時代に進捗を書き戻していたもので、
いまはどこからも呼ばれていない**休眠**である。

なお `legacy/notion_writes/` にあるYouTubeのNotion直書き `apply_*` 群は、
うっかり自動化されないように**共有の確認句を要求する**作りが守られている
（[INV-PLT-001](07-platform.md)と同じ考え方で、`tests/test_legacy_youtube_notion_apply_policy.py` が検査している）。
このファイル群は `legacy/` にあるため仕様の網羅対象からは外れているが、
`apply_retrospective_ready_venue_events.py` だけは現役の場所に残っていて、同じ確認句を使う。
このファイル自体は会場サブシステムの持ち物なので、触るときは逆引きをそちらで引く。

## 依存と影響

**上流**

- [収集](01-collection.md) — `voices.json` のYouTube投稿がこの工程の素材である。
  `refresh_youtube_voices.py` と `youtube_channels/backfill_youtube_descriptions.py` は、
  概要欄が欠けている投稿をAPIで埋め直す。概要欄が無ければセットリストは取れない。
- [基盤](07-platform.md) — S3からの声・マスタRDBの受け渡し、APIキーの供給、workflowの実行。
- **YouTube Data API のクォータ** — 事実上の律速。増やすには課金の判断が要る。

**下流**

- [曲目](08-songs.md) — セットリストが主要な入力のひとつ。ただし上に書いたとおり、いまその経路は止まっている。
- [レビュー](03-review.md) — 動画由来の要レビュー項目。アダプタ（`review_inbox_adapters/youtube_*.py`）は
  レビュー側の所有物なので、そちらを読む。
- [マスタ](04-master.md) — 観測と曲の書き込み先。生成予測は日次の狭い同期口から予測表へ入り、
  確定へ上げる判断はマスタ側の不変条件が守る（INV-MST-002・013）。
- [公開](05-publication.md) — この工程から公開exportは呼ばず、RDBへ同期済みの予測と確定層を読む
  日次収集へ任せる（INV-YTB-001・002）。
- [配信](06-delivery.md) — `--mail-reminder` が `pending_mail.json` へ催促を書く。

**この工程は公開JSONを直接変更しないが、生成予測とRDBの同期契約は次の収集日次に影響する。**
解決不能な予測が出た場合は、誤った系列へ自動で結ぶよりINV-PUB-006で次の日次を止める。
一方、YouTube取り込み自体が止まっても既存公開はすぐには変わらないため、気づきにくい弱点は残る。
実際にセットリスト経路は3週間止まっていて、気づいたのは仕様書を書くために呼び出し元を検索したときだった。

## 壊れたときの症状

| 見えている症状 | 疑うところ |
|---|---|
| YouTube日次が毎日失敗として通知される | INV-YTB-003。クォータ切れを例外で落としていないか |
| 同じ日に日次コミットが2回入る | INV-YTB-005。ローカルLaunchAgentが有効になっていないか |
| 公開サイトに動画タイトルの断片が曲名として出る | INV-YTB-004、または[INV-SNG-001](08-songs.md) |
| 一度消した曲名が復活する | INV-YTB-004。無効化した行を再取り込みで拾っている |
| 予測でしかない日付が確定日として公開される | INV-YTB-002、および[INV-MST-002](04-master.md) |
| YouTube日次は成功したのに次の収集日次がJSONフォールバックで止まる | [INV-MST-013](04-master.md)。予測の系列・会場が一意に解決できるか |
| クォータは使い切っているのに候補が増えない | 下の「未解決」の1番目。同じ行を毎日引き直している |
| セットリストの曲が何週間も増えない | 正常。抽出は手動で、いま止まっている（流れの4） |
| `youtube_active_video_review.json` が古いまま | 正常。日次で作り直すがコミットしない（流れの3） |

## 未解決・注意点

- **セットリスト抽出が2026-07-25から止まっている。** 曲目の主要な入力なのに、
  `extract_youtube_setlists.py` はどのworkflowにも入っていない。
  自動化すべきかどうかは未決。手厚いテスト（24件）があるので、繋ぐこと自体は難しくない。
- **チャンネル台帳も2026-06-29から止まっている。** 読む相手が7チャンネルのままなので、
  掘り起こしの入力そのものが増えない。[X盆踊ラーの再評価](../../x-bonodorer-reevaluation-20260811.md)と
  同じ「誰を読むか」の問題だが、YouTube側は手つかずである。
- **`run_post_batch_maintenance.py` はこの仕様の持ち物ではない。** 呼んでいるのはこの工程のworkflowだけだが、
  中身はマスタRDB全体の点検レポートでYouTube固有ではないため、[マスタ](04-master.md)へ寄せた。
  ここが `owns` すると、触った人に「YouTubeの話だ」と誤った案内をしてしまうからである。
- **`data/youtube_user_confirmation_queue.json` は2026-06-16におとが手で書いた4件のままである。**
  掲載基準の判断を内田さんに仰ぐための待ち行列だが、その後は更新されていない。
- **APIキーが無いときの挙動は未確認。** workflowは `--dry-run` でない限りキーの存在を検査して落とすが、
  ローカル実行時に `.env` から読めなかった場合の経路までは追っていない。

---

おと（Codex）
