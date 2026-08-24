---
id: L1-songs
layer: L1
title: 曲目サブシステム
owns:
  - song_processing/**
  - build_event_song_candidates.py
  - build_song_occurrences.py
  - build_song_ocr_queue.py
  - build_song_catalog_shadow_report.py
  - build_song_content_research_queue.py
  - build_song_evidence_adapter_shadow.py
  - build_song_occurrence_matching_candidates.py
  - build_song_publication_review.py
  - calibrate_song_predictions.py
  - calibrate_song_probabilities_rdb.py
  - inherit_song_probabilities_rdb.py
  - .github/workflows/recalculate-song-probabilities.yml
  - export_master_rdb_song_occurrences.py
  - triage_weekly_song_candidates.py
  - register_song_master_initial.py
  - song_candidate_finite_actions.py
  - apply_song_candidate_finite_actions.py
  - apply_song_content_research_batch.py
  - apply_song_ocr_review.py
  - apply_song_official_sources_batch.py
  - apply_song_publication_review_decisions.py
  - apply_weekly_song_final_corrections.py
  - apply_weekly_song_review_decisions.py
  - build_x_song_resolution_packets.py
  - apply_x_song_resolution_results.py
  - build_x_occurrence_resolution_packets.py
  - apply_x_occurrence_resolution_results.py
  - scripts/build_song_candidate_finite_payload.py
  - scripts/run_song_candidate_decision_write.py
  - scripts/manual/render_song_calibration_report.py
depends_on:
  - L1-judgment
  - L1-review
  - L1-master
  - L2-master-schema
invariants:
  - INV-SNG-001
  - INV-SNG-002
  - INV-SNG-003
  - INV-SNG-004
  - INV-SNG-005
  - INV-SNG-006
  - INV-SNG-007
  - INV-SNG-008
verified_by:
  - tests/test_bon_odori_songs.py
  - tests/test_song_catalog.py
  - tests/test_weekly_song_triage.py
  - tests/test_export_public_events.py
  - tests/test_calibrate_song_probabilities_rdb.py
  - tests/test_inherit_song_probabilities_x_safety.py
  - tests/test_recalculate_song_probabilities_workflow.py
  - tests/test_rdb_youtube_setlist_pipeline_workflow.py
  - tests/test_x_post_extraction_songs.py
  - tests/test_x_song_resolution_contract.py
  - tests/test_x_occurrence_resolution_contract.py
  - tests/test_x_song_materialization_lifecycle.py
updated_for: a47769f
---

# 曲目サブシステム

> 上位は[全体地図](../README.md)。書き方の決まりは [SPEC-GUIDE](../SPEC-GUIDE.md)。
> 他のL1が**工程**（収集・判断・レビュー…）で切ってあるのに対し、これだけは**ドメイン**で切ってある。
> 理由は「主要な流れ」の冒頭に書いた。

## この工程は何のためにあるか

盆助が公開しているのは開催日時と場所だけではない。**その盆踊りで何が踊られるか**、つまり曲目も出している。
これは盆踊りを探す人にとって、日付と同じくらい行くかどうかを左右する情報である。
炭坑節と東京音頭だけの会と、地元の音頭が10曲並ぶ会は、まったく別の体験だからだ。

ところが曲目は、開催情報以上に**どこにも書かれていない**。区の広報にもチラシにも曲名までは載らないことが多く、
実際に踊った人のX投稿、YouTubeの概要欄に貼られたセットリスト、会場に張り出された曲目表の写真といった、
断片的で形式のばらばらな痕跡からしか復元できない。しかも同じ曲が「東京音頭」「大東京音頭」「東京五輪音頭」のように
似た名前で並ぶので、取り違えると別の曲を踊ることになってしまう。

そこでこの工程は、次の3つを引き受けている。

1. ばらばらの文章・動画・写真から、**曲名らしき文字列**を取り出す。
2. その文字列が**本当に曲名か**、**どの曲か**を、蓄積した曲マスタに照らして決める。決めきれないものは人へ回す。
3. どの開催回で踊られる（踊られた）かを結びつけ、**確からしさの出どころを添えたまま**公開する。

3番目が肝心である。曲目には「今年の告知に載っていた」「実際に踊られたのを見た」「去年踊っていたから今年もたぶん踊る」の
3種類がどうしても混ざる。これを区別せずに並べると、去年の話を今年の予定として読ませることになる。
盆助全体の設計思想である「確定と推測を混ぜない」が、曲目でも同じ形で効いている。

## 入力と出力

**入力**

- `data/voices.json` — X投稿。収集サブシステムの出力（曲名を含む文章と、曲目表の画像URL）
- E0X回答の `events[].songs` / `observations[].songs` — LLMが投稿本文から書き写した曲名候補
- `data/public/events_public.json` — 公開済みイベントの本文。曲候補を探す対象文章になる
- `data/weekly_harvest_candidates.json` — 週次収穫で拾った用語候補（`category` が `曲候補` の行だけ使う）
- `data/youtube_song_candidates_review.json`、`data/youtube_setlist_occurrences.json` — YouTube概要欄由来のセットリスト
- `data/bon_odori_master.sqlite` の `songs` / `song_aliases` — 蓄積した曲マスタ。曲名の同一性判断の正本
- `data/song_evidence_manual.json` — 人が直接書いた曲の根拠

**出力**

- `data/x_song_observations.json` — X投稿本文に曲名文字列があったという観測。曲マスタ・開催回へは未接続
- `data/bon_odori_master.sqlite` の `occurrence_songs`（＋ `occurrence_song_evidence_links`）— 開催回ごとの曲。**公開の直接の元**
- `data/event_song_candidates.json` — レビュー用の曲候補キュー（`f517fa8` 時点で1,527件、うち要レビュー885件）
- `data/weekly_song_candidates_review.json` — 仕分けで決めきれなかった曲候補。レビュー受信箱へ渡る
- `data/song_ocr_queue.json` — 曲目表の画像がありそうな投稿の一覧（`f517fa8` 時点で68件）
- `data/song_occurrences.json`、`data/song_prediction_snapshots.json`、`data/song_prediction_calibration.json` — **凍結中**（後述）

公開JSONへの書き出しそのものは、この工程ではなく[公開サブシステム](05-publication.md)の
`export_public_events.py` が行う。ただし曲の並べ方・抑制・根拠ラベルの意味づけはこの工程の責任なので、
不変条件はここに置いてある。

## 不変条件

### INV-SNG-001 曲名でないと確認された文字列は公開曲目に出さない

- **内容**: `song_processing/bon_odori_songs.py` の `SUPPRESSED_SONG_NAMES` に載った文字列は、
  抽出側でも公開直前のマージでも落とす。通常の抑制は**完全一致のみ**で、このリストからパターンを推測してはいけない。
  公開境界では、実データで構造が確定した進行記号 `終 ` を曲名から外し、
  `周辺で開かれる街なかの踊り` で終わる文章断片だけを追加で落とす。曲名らしい語を一般化した正規表現は使わない。
- **なぜ**: 抽出器はもともと「機械が粗く拾い、人が正式名へ書き直す」前提で作られている。
  その書き直しの工程（週次収穫レビュー）が2026-06-25以降動いていないため、粗いままの候補が公開面へ届く状態になった。
  実際に「大井町駅前中央通り周辺で開かれる街なかの踊り」のような文章がbonsuke.jpに曲名として並んだ。
  2026-08-04に正規表現を絞る案を試したが、**どの絞り方でも佐竹音頭・濱町音頭・舟渡ひろがり音頭といった
  実在のご当地曲が道連れになった**ので、パターンでの一般化を諦めて既知の文字列だけを名指しで消す方式に決めた。
  だからこのリストは「悪い例の集合」であって「悪いパターンの例示」ではない。
- **破れたときの症状**: 公開サイトの曲目欄に、曲名でない説明文（「路上で行われる踊り」「大人の部」など）が並ぶ。
- **守っているコード**: `song_processing/bon_odori_songs.py` の `is_suppressed_song()`、
  `export_public_events.py` の `canonical_public_song_name()` / `_is_public_non_song_name()` / `merge_song_occurrence_hints()`
- **守っているテスト**: `tests/test_export_public_events.py::ExportPublicEventsTest::test_suppressed_prose_never_reaches_public_songs`、
  `tests/test_export_public_events.py::ExportPublicEventsTest::test_public_song_cleanup_removes_chapter_markers_and_prose`

### INV-SNG-002 公開する曲には、その確からしさの出どころを必ず添える

- **内容**: `occurrence_songs` の行を公開形へ変換するとき、`evidence_status` と `inherited_from_year` から
  `basis` / `basis_label` を決める。今年告知は「今年告知」、実測は「実測」、今年のヒントだけなら「今年ヒント」、
  過去年からの継承なら継承元の年と種別（「2025年実測」など）を出す。
- **なぜ**: 曲目には確定・告知・推測が必ず混ざる。ラベルが無ければ、去年踊っていただけの曲が今年の予定に見える。
  実際にRDB移行のとき、今年のヒントしか無い行が「過去実績」と表示される取り違えが起きた。
  逆に継承元の種別を落とすと、前年に実測された曲まで「ヒント」扱いになり、正しい情報の信頼度を不当に下げてしまう。
- **破れたときの症状**: 公開ページの曲目に付く根拠ラベルが実態とずれる。
  去年の曲が今年の告知として読まれる、または実測済みの曲が推測に見える。
- **守っているコード**: `export_public_events.py` の `_song_from_rdb()`
- **守っているテスト**: `tests/test_export_public_events.py::ExportPublicEventsTest::test_song_from_rdb_labels_basis_by_evidence_status`

### INV-SNG-003 レビュー未了・無効・状態不明の曲を「確認済み」として扱わない

- **内容**: `SongCatalog.resolve()` は、曲マスタの `status` が `active` / `有効` の行だけを検証済みとして返す。
  `候補`（未レビュー）、`無効`、および知らない状態文字列は検証済みにしない。
  複数の曲が同じ別名を持つ場合も、どちらかへ黙って寄せずに曖昧として返す。
  仕分け側（`classify_candidate()`）はこれを受けて、検証済みでないものを `review` か `reject` へ落とす。
- **なぜ**: 曲名らしい**形**をしていることと、曲として**認められている**ことは別である。
  「大人の部」は曲名の形をしているが曲ではない。形の判定で昇格を許すと、未レビューの行が
  レビューを通ったかのように扱われ、公開まで一気に抜けてしまう。だから形より台帳の状態を優先し、
  分からないものは閉じる側（レビュー行き）へ倒す。
- **破れたときの症状**: 誰も確認していない曲名が確定曲として公開される。
  別名が衝突している曲が、無関係の曲名へ勝手に統合される。
- **守っているコード**: `song_processing/song_catalog.py` の `SongCatalog.resolve()` と `_review_state_for_status()`、
  `song_processing/weekly_song_triage.py` の `classify_candidate()`
- **守っているテスト**: `tests/test_song_catalog.py::TestSongCatalog::test_candidate_is_not_verified`、
  `tests/test_song_catalog.py::TestSongCatalog::test_unrecognized_status_is_unknown_not_verified`、
  `tests/test_song_catalog.py::TestSongCatalog::test_ambiguous_alias_is_not_silently_resolved`

### INV-SNG-004 検索missだけでは新曲を作らない

- **内容**: X曲claimのretrieval判定は `match_song` / `candidate_missing` / `unresolved` だけを許す。
  `candidate_missing` がactive台帳へ入った観測だけが、全曲catalogを凍結したnovelty判定へ進み、そこで初めて
  `new_song` を選べる。曲と開催回の判定は別packet・別台帳にする。
- **なぜ**: top 20検索は候補生成器であり、曲が存在しないことの証明ではない。検索漏れを新曲扱いすると、
  alias違いの同じ曲がactiveで重複し、開催回曲目も分裂する。
- **破れたときの症状**: マスタに既にある曲が別song IDで増え、同じ曲が公開欄へ複数表示される。
- **守っているコード**: `review_inbox_adapters/x_song_resolution_contract.py`
- **守っているテスト**: `tests/test_x_song_resolution_contract.py::test_retrieval_packet_freezes_full_candidate_rows_and_forbids_new_song`、
  `tests/test_x_song_resolution_contract.py::test_candidate_missing_must_be_recorded_before_novelty_packet`、
  `tests/test_x_song_resolution_contract.py::test_current_snapshot_decision_is_not_packetized_again`

### INV-SNG-005 X曲factは二つの同定と有効な根拠が揃ったときだけ作る

- **内容**: 行事名が本文と一致する `announced` / `observed` のcurrent observation SHAと、曲・開催回のactive decision、
  選択した曲・開催回の凍結行が現在値と一致したときだけmaterializeする。無関係な別entity追加では再判断しない。対応は
  `announced → setlist/announced`、`observed → result/observed` に固定する。retractはappend-onlyで、
  最後のX根拠が消えた曲のcreate/promotionを撤回順に依存せずCAS cleanupする。
- **なぜ**: 回答経路やイベント名だけから意味を推測すると、願望曲・別年度開催・訂正済み投稿が公開factになる。
- **破れたときの症状**: 「踊ってほしい」が曲目になる、去年の曲が今年へ付く、全根拠撤回後も曲が公開に残る。
- **守っているコード**: `report_apply/materialize_x_song_resolutions.py`、
  `report_apply/retract_x_song_materializations.py`
- **守っているテスト**: `tests/test_x_song_materialization_lifecycle.py`、
  `tests/test_x_occurrence_resolution_contract.py`

### INV-SNG-006 未解決を時刻だけで繰り返さない

- **内容**: 同じpacket IDにdecisionがあれば再提示しない。未解決は曲・開催回・観測・E0 revision/evidenceの
  いずれかが変わり、新しいpacket IDになった場合だけ再eligibleにする。解決済みidentityは選択行が変わらない限り
  無関係なentity追加で開き直さない。30日後など固定時刻で同じ入力を再試行しない。
- **なぜ**: 多くの未解決は処理が遅いのではなく、開催回やaliasがまだ存在しない依存待ちである。
  同じ候補を定期的に読ませても判断負荷だけが増える。
- **破れたときの症状**: `unresolved` / `dependency_pending` が毎日同じ内容で再登場し、保留キューが永久に回り続ける。
- **守っているコード**: `review_inbox_adapters/x_song_resolution_contract.py`、
  `review_inbox_adapters/x_occurrence_resolution_contract.py`
- **守っているテスト**: `tests/test_x_song_resolution_contract.py::test_current_snapshot_decision_is_not_packetized_again`、
  `tests/test_x_occurrence_resolution_contract.py::test_unresolved_occurrence_waits_for_snapshot_change`、
  `tests/test_x_occurrence_resolution_contract.py::test_event_dependency_is_mechanical_and_pending_until_event_decision`

### INV-SNG-007 過去年の曲実績は年ごとに減衰させ、複数年ぶんを合算する

- **内容**: 対象年より前の曲根拠は、まず同じ開催年の複数ソースを noisy-or でまとめ、話者数の係数を掛ける。
  その年の寄与へ `0.75 ** (対象年 - 根拠年)` を掛け、異なる開催年の寄与をもう一度 noisy-or で合算する。
  したがって2023年・2024年の両方に同じ曲があれば2024年だけより高くなり、根拠表示も
  「2023・2024年実測」のように全採用年を残す。当年の直接根拠がある行は過去年継承より優先する。
  過去の移行行にaccepted根拠リンクが無い場合は、その開催年ですでにレビュー済みの確率を年寄与の代替値として使い、
  同じ話者係数・減衰・年どうしの合算を行う。前年カードを公開カードへ補完する最終フォールバックも、
  生の80%/95%をコピーせず、同じ75%減衰を掛ける。
- **なぜ**: 最新の過去年だけを見ると、毎年続いている曲と1回だけ出た曲が同じ確率になる。
  逆に根拠の本数を年を無視して足すと、同一年の転載や複数動画を連年実績のように数えてしまう。
  現在の75%は実測で確定した係数ではなく暫定の初期値であり、将来の較正とは分けて扱う。
- **破れたときの症状**: 2年以上連続して踊られた曲の確率が前年だけの曲と同じになる、または
  同じ年の動画が増えただけで連年実績より高くなる。公開根拠ラベルから古い採用年が消える。
- **守っているコード**: `calibrate_song_probabilities_rdb.py` の `compute_historical_probability()`、
  `inherit_song_probabilities_rdb.py` の過去年継承、`song_processing/song_occurrences.py` の凍結旧経路
- **守っているテスト**: `tests/test_calibrate_song_probabilities_rdb.py::CalibrateHistoricalSongProbabilityTest::test_two_consecutive_years_score_higher_than_latest_year_alone`、
  `tests/test_calibrate_song_probabilities_rdb.py::CalibrateHistoricalSongProbabilityTest::test_legacy_annual_probabilities_also_accumulate_across_years`、
  `tests/test_inherit_song_probabilities_x_safety.py::test_inheritance_combines_direct_evidence_from_multiple_years`、
  `tests/test_inherit_song_probabilities_x_safety.py::test_inheritance_combines_legacy_probabilities_when_links_are_missing`、
  `tests/test_export_public_events.py::ExportPublicEventsTest::test_previous_year_direct_result_is_decayed_and_keeps_result_label`

### INV-SNG-008 「確実」相当は当年の直接根拠だけに限定する

- **内容**: 公開JSONで `basis` が `past_evidence` / `current_hint` / 未設定の曲は、90%を超えてはならない。
  `export_public_events.py` はこの状態を公開前監査で拒否する。サイトの「確実」は90%以上という数値だけでは決めず、
  `current_announced` または `current_observed` の当年開催回に限る。過去実績・看板曲prior・過去年カードは
  数値が90%以上でも「かなり有力」までとする。
- **なぜ**: 前年のYouTube実測95%が減衰なしで今年へコピーされ、「2025年ヒント」なのに「確実」と表示された。
  数値だけを見る表示では、推測と直接確認の違いを利用者が判別できない。
- **破れたときの症状**: 去年しか踊られていない曲や会場の看板曲が「確実」になり、今年の公式曲目より上に並ぶ。
- **守っているコード**: `export_public_events.py` の `audit_public_song_projection()`、
  `bon-odori-site/app.js` の `songCertaintyLabel()`
- **守っているテスト**: `tests/test_export_public_events.py::ExportPublicEventsTest::test_public_song_audit_rejects_indirect_exact_scores`

## 主要な流れ

最初に、なぜこれだけドメインで切ってあるかを書いておく。曲目は収集から公開までの全工程を縦に貫いており、
どの工程のL1へ入れても話が半分になる。抽出だけを判断L1へ置けば「なぜ抑制リストが完全一致なのか」が説明できず、
公開の並べ方だけを公開L1へ置けば「その根拠ラベルはどこで決まったのか」が消える。
**曲目は工程ではなく一本のパイプラインとして読まないと理解できない**ので、縦で切ってある。
同じ理由で、`export_public_events.py` そのものは公開L1が `owns` したままにしてある（1ファイルを2つの仕様が持てないため）。

### 1a. LLMが本文を読んで観測台帳へ記録する（手動・新経路）

E0X回答を `apply_x_extraction_results.py` で取り込むと、`events[].song_claims` と
`observations[].song_claims` の両方を、点数に関係なく `data/x_song_observations.json` へ記録する。
各曲は `announced` / `observed` / `mentioned` / `unknown` のclaim typeと、曲名を含む本文引用を持つ。
`origin` は `events` / `observations` という回答経路だけを表し、告知・実績の意味には使わない。
5点イベントが本文照合を通って実際にE0レポートになった場合だけ、report IDに加えてレポート内event entry IDと
E0 family keyを残す。URLが無い投稿や過去日のclaimも観測としては残すが、存在しないE0系譜を付けない。
旧 `songs: ["..."]` と既存観測はIDを変えず `unknown` として扱う。

この段階で確認するのは「曲名と根拠引用が投稿本文にあり、引用にも曲名がある」ことまでである。
曲マスタとの同一性判断も、`occurrence_songs` / `event_occurrences` への接続も行わず、行事名が取れなければ
`event_name: null` のまま残す。実装の安全境界は [判断・仕分けのINV-XPE-010〜016](02-judgment.md) が持ち、
回答形式と受け入れ条件は [E0X-S v2.0](../../x-post-extraction-songs-v1.md) に置く。

これは既存の正規表現抽出を置き換える経路ではない。まず観測台帳へ並走させ、再現率と誤検知を測ってから、
曲マスタ照合・レビュー・開催回接続を第2段として設計する。claim typeだけが食い違う再回答は同じfamilyの競合として
保持し、下流の自動公開へ流さない。

### 1. 候補を拾う（毎日）

日次の `collect.yml`（毎日 約15:13 JST）で動くのは次の3つである。

- `build_event_song_candidates.py` — 公開済みイベントの本文へ `extract_song_candidates()` をかけ、
  レビュー用の曲候補キューを作り直す。抽出は**わざと甘く**してある。落としたものは復元できないが、
  余計に拾ったものは人が捨てられるからである。
- `build_song_ocr_queue.py` — `data/voices.json` から、曲目表の写真が付いていそうな投稿を選ぶ。
  画像の中の曲目は文章からは取れないので、OCRへ回す入口をここで作る。
- `triage_weekly_song_candidates.py --dry-run` — 週次収穫が拾った用語候補のうち `曲候補` の行を仕分ける。

抽出そのものは `song_processing/bon_odori_songs.py` にある。同じモジュールに2つの入口があり、性格が違う。
`extract_song_hints()` は公開本文から**そのまま出してよい程度**に絞った抽出で、
`extract_song_candidates()` は**レビュー前提でもっと広く拾う**抽出である。混ぜて使ってはいけない。

### 2. どの曲かを決める（毎日）

E0X-S v2由来の新経路は、通常の週次候補とは別に
[E2-S v2契約](../../local-judgment-e2s-song-identity-v2.md)を使う。曲retrieval、全catalogでのnovelty、
開催回同定を別sceneにし、判断writerは同定台帳まで、正本writerはmaterializer一箇所に分ける。

`classify_candidate()` が、候補の文字列を4つの行き先へ振り分ける。
先に手書きの対応表（`CANONICAL_MAP` / `NOISE_EXACT` / `AMBIGUOUS_TERMS`）を見て、
それで決まらなければ `SongCatalog`（RDBの `songs` / `song_aliases`）へ問い合わせる。

台帳が形の判定より優先される。`ふるさと音頭` のように「と」が入っていて形の判定では文章に見える曲でも、
台帳に検証済みで載っていれば正規曲名へ解決する。逆に形が完璧でも台帳が `候補` のままならレビューへ回す（INV-SNG-003）。

`f517fa8` 時点で日次に記録されている仕分け結果は、曲候補207件・直接採用134件・ノイズ68件・要レビュー5件である。

### 3. 人が裁定する

決めきれなかったものは `data/weekly_song_candidates_review.json` に出て、
日次の低優先レーンから[レビュー受信箱](03-review.md)へ入る（`--source daily_song_candidate=...`）。
裁定の結果は `song_candidate_finite_actions.py` が定める**有限の行動**
（`register_song` / `add_song_alias` / `reject_song` / `hold`）に変換され、
`apply_song_candidate_finite_actions.py` がマスタへ書く。
レビューされていないものが暗黙に採用されることはなく、決まっていなければ `hold` になる。

### 4. 開催回へ結びつけ、確からしさを計算する（手動）

`occurrence_songs` に曲を積み、確率を計算するのが `calibrate_song_probabilities_rdb.py`（直接証拠の較正）と
`inherit_song_probabilities_rdb.py`（複数の過去年からの継承）である。過去年は開催年ごとにまとめてから
1年ごとに75%を残し、年どうしを合算する（INV-SNG-007）。
直接根拠の型は `evidence_type` に加えてレビュー済みの `evidence_status` を保守的な補助に使い、
公式曲目画像の `poster_post` は告知として扱う。通常はNULL行だけを埋めるが、既存値を直すときは
`--recalculate-existing` と `--target-year`（または `--occurrence-id`）を同時指定し、acceptedリンクがある行だけを再計算する。
この2本は日次workflowでは呼ばれないが、レビュー済み変更要求の `add_song_evidence` 適用時には
`apply-reviewed-change-requests.yml` が対象開催回を較正する。全件を直すときは手動の
`recalculate-song-probabilities.yml` が、同じ対象年について「直接証拠の再較正→複数年継承→公開前監査」を
dry-runで通し、apply時だけ明示確認・CAS付きでS3正本へ反映する。公開投影もdry-run・適用後・再取得後の3段階で監査し、
対象年の曲行がdry-runと本番、更新前後で一致しなければ停止する。したがって通常の公開曲確率は毎日は更新されず、
レビュー反映時またはこの手動workflowを実行した時点の値である。

### 5. 公開へ渡す（毎日）

`export_public_events.py` が開催回ごとに `occurrence_songs` を読み、本文からの抽出結果とマージして公開形にする。
**RDBに1行でも曲があれば、RDB側が正**として扱う。凍結された旧JSON（`data/song_occurrences.json`）は
RDBに曲が無い開催回のときだけ使う。順序が逆だと、凍結されて古いままの確率がRDBの計算結果を毎日上書きしてしまう。
公開直前には、同一曲の既知表記ゆれを束ね、文章・演目名を落とし、間接根拠が90%を超えていないかを監査する。

2026-08-18の全件再計算dry-runでは、公開379件のうち曲目が付いているのは56件、曲の延べ数は637件である。
前年根拠なのに90%を超える行は30件から0件になり、今年の公式ポスター4曲は未計算から95%へ較正された。

## 依存と影響

**上流**

- [収集](01-collection.md) — `voices.json` が薄い日は曲の入力そのものが無い。
- [判断](02-judgment.md) — E0X回答から曲名の観測台帳を作る。イベントと開催回が特定できていないと、曲を結びつける先が無い。
- [レビュー](03-review.md) — 曲の同一性はここでしか確定しない。**この工程の実質的な律速**。
- [マスタ](04-master.md) / [マスタRDBスキーマ契約](../L2/master-schema.md) — `songs`・`song_aliases`・`occurrence_songs` の形。

**下流**

- [公開](05-publication.md) — `events_public.json` の `songs` 配列と `event_songs_public.json`。
  フィールドの意味は[公開JSONのフィールド契約](../L2/public-json.md)にある。
- [配信](06-delivery.md) — 金曜週報が曲目の話題を含む。

**特に効く前提がひとつある。** 曲マスタ（`songs` テーブル）を直しても、公開されている曲目は変わらない。
公開は `occurrence_songs`（開催回ごとの行）から作られるので、マスタ側の canonical を直しても
既に積まれた開催回の行はそのままである。「曲名を直したのにサイトが変わらない」の原因はたいていこれで、
直す先は開催回の行のほうになる。

## 壊れたときの症状

| 見えている症状 | 疑うところ |
|---|---|
| 曲名でない文章が曲目に並んでいる | INV-SNG-001。抑制リストに無い新種の文章断片が抜けた |
| 曲の根拠ラベルが実態とずれる（去年の曲が今年の告知に見える） | INV-SNG-002。`evidence_status` と `inherited_from_year` の解釈 |
| 誰も確認していない曲名が確定曲として出る | INV-SNG-003。台帳の状態より形の判定が勝った |
| 前年実績や看板曲が「確実」と表示される | INV-SNG-008。数値だけで確実判定していないか |
| 曲名を直したのにサイトの表示が変わらない | `songs` を直して `occurrence_songs` を直していない |
| 曲の確率が何日も同じ | 正常。確率計算は手動実行で、日次では動かない |
| 曲目が付くイベントが増えない | 候補キューは溜まっているがレビューが進んでいない |

## 未解決・注意点

- **E0X-Sは第1段の観測だけで、曲マスタ・レビュー・開催回へ未接続である。** `data/x_song_observations.json` をどの照合器へ渡し、同名曲や表記揺れをどう裁定するかは第2段で決める。観測が増えても公開曲目はまだ増えない。
- **既存の正規表現経路は稼働したままである。** E0X-Sの品質を実測する前に置き換えない。二つの経路の件数差を「重複」だけと決めつけず、本文照合・再現率・誤検知を比較する。
- **週次収穫レビューが2026-06-25から動いていない。** `weekly_harvest.yml` は
  `manual-harvest-fallback` という手動起動のworkflowになっており、定期実行されていない。
  INV-SNG-001の抑制リストは、この停止の応急処置として存在している。レビューが戻れば
  抑制リストは役目を終えるが、**戻すまでリストは伸び続ける**。
- **日次の仕分けは `--dry-run` で動いている。** 「直接採用」と判定された134件も、
  実際には曲マスタへ書かれていない（結果JSONに「作るとしたらこうなる」と記録されるだけ）。
  日次で実際に前へ進むのは要レビュー行の書き出しだけである。
- **確率の全件再計算（`calibrate_song_probabilities_rdb.py` / `inherit_song_probabilities_rdb.py`）は
  日次workflowに入っていない。** レビュー済みの `add_song_evidence` は適用workflowが対象開催回を再計算し、
  全件の補正は `recalculate-song-probabilities.yml` を手動実行する。75%の年次残存率は暫定値で、
  十分な年次実績が蓄積した後に再較正する。
- **旧JSON経路は凍結中。** `build_song_occurrences.py` と `calibrate_song_predictions.py` は
  `master_rdb_freeze_policy.py` の `legacy_song_occurrence_generation` が active なので日次では飛ばされる。
  凍結の判断は2026-06-20のRDB移行時のもので、解除条件は `data/master_rdb_migration_freeze.json` にある。
  **凍結されたコードにもテストが付いたまま残っているので、テストが通ることは「動いている」ことを意味しない。**
- **`song_processing/song_evidence_adapters.py` は影実験のまま。** X・YouTube・OCR・人の報告の4入口へ
  同じ Candidate/Evidence の契約を与える設計だが、呼んでいるのは `build_song_evidence_adapter_shadow.py` だけで、
  そのスクリプトはどのworkflowからも実行されていない。よく書けた層だが**まだ本番の経路ではない**ので、
  ここの約束を不変条件にはしていない。本番へ繋いだ時点でINVを起こす。
- **YouTube由来の曲スクリプトはこの仕様が持っていない。** `build_youtube_song_master.py` や
  `build_youtube_event_song_candidates.py` などは [YouTube取り込み](09-youtube.md) の持ち物である
  （2026-08-14に執筆。それまでは未記述領域だった）。曲名の品質ゲートの約束は
  [INV-YTB-004](09-youtube.md) にあるので、セットリスト由来の曲を触るときはそちらも読む。
  なお**そのセットリスト抽出は2026-07-25から止まっている**。曲目の主要な入力のひとつが
  更新されていないということなので、曲が増えない原因を探すときはここも見る。
- **`sync_public_event_songs_to_site.py` もこの仕様が持っていない。** `sync_public_event_*_to_site.py` は
  4本セットで公開サブシステム側の話なので、まとめてそちらへ寄せるほうがよい。現状は未記述のまま。
- **曲マスタがNotionとRDBの二重になっている可能性がある。** `weekly_song_triage.py` は
  Notionの曲マスタDBへ書く作りのままだが、日次は dry-run なので実際には書かれていない。
  一方で同一性判断はRDBの `songs` を見ている。どちらを正本と決めたかは**未確認**で、
  実装からは読み取れなかった。決めた経緯を知っている人が書き足すのが正しい。

---

こと（Claude Code）
