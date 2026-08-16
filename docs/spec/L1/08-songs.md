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
verified_by:
  - tests/test_bon_odori_songs.py
  - tests/test_song_catalog.py
  - tests/test_weekly_song_triage.py
  - tests/test_export_public_events.py
  - tests/test_x_post_extraction_songs.py
updated_for: 7bcacd0
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
  抽出側でも公開直前のマージでも落とす。判定は**完全一致のみ**で、このリストからパターンを推測してはいけない。
- **なぜ**: 抽出器はもともと「機械が粗く拾い、人が正式名へ書き直す」前提で作られている。
  その書き直しの工程（週次収穫レビュー）が2026-06-25以降動いていないため、粗いままの候補が公開面へ届く状態になった。
  実際に「大井町駅前中央通り周辺で開かれる街なかの踊り」のような文章がbonsuke.jpに曲名として並んだ。
  2026-08-04に正規表現を絞る案を試したが、**どの絞り方でも佐竹音頭・濱町音頭・舟渡ひろがり音頭といった
  実在のご当地曲が道連れになった**ので、パターンでの一般化を諦めて既知の文字列だけを名指しで消す方式に決めた。
  だからこのリストは「悪い例の集合」であって「悪いパターンの例示」ではない。
- **破れたときの症状**: 公開サイトの曲目欄に、曲名でない説明文（「路上で行われる踊り」「大人の部」など）が並ぶ。
- **守っているコード**: `song_processing/bon_odori_songs.py` の `is_suppressed_song()`、
  `export_public_events.py` の `merge_song_occurrence_hints()`
- **守っているテスト**: `tests/test_export_public_events.py::ExportPublicEventsTest::test_suppressed_prose_never_reaches_public_songs`

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

## 主要な流れ

最初に、なぜこれだけドメインで切ってあるかを書いておく。曲目は収集から公開までの全工程を縦に貫いており、
どの工程のL1へ入れても話が半分になる。抽出だけを判断L1へ置けば「なぜ抑制リストが完全一致なのか」が説明できず、
公開の並べ方だけを公開L1へ置けば「その根拠ラベルはどこで決まったのか」が消える。
**曲目は工程ではなく一本のパイプラインとして読まないと理解できない**ので、縦で切ってある。
同じ理由で、`export_public_events.py` そのものは公開L1が `owns` したままにしてある（1ファイルを2つの仕様が持てないため）。

### 1a. LLMが本文を読んで観測台帳へ記録する（手動・新経路）

E0X回答を `apply_x_extraction_results.py` で取り込むと、5点イベントの `events[].songs` と、点数に関係なく返せる `observations[].songs` の両方を `data/x_song_observations.json` へ記録する。両方に同じ曲があれば `events` を先に扱い、安定IDで重複を止め、`origin` に `events` または `observations` を残す。URLが無い投稿でも観測は残せるが、投稿ID、原文、投稿日時、アカウント、公式性、原文上の行事名を来歴として保持する。

この段階で確認するのは「曲名文字列が投稿本文にある」ことだけである。曲マスタとの同一性判断も、`occurrence_songs` / `event_occurrences` への接続も行わず、行事名が取れなければ `event_name: null` のまま残す。実装の安全境界は [判断・仕分けのINV-XPE-010〜013](02-judgment.md) が持ち、回答形式と受け入れ条件は [E0X-S設計](../../x-post-extraction-songs-v1.md) に置く。

これは既存の正規表現抽出を置き換える経路ではない。まず観測台帳へ並走させ、再現率と誤検知を測ってから、曲マスタ照合・レビュー・開催回接続を第2段として設計する。

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

`occurrence_songs` に曲を積み、確率を計算するのが `calibrate_song_probabilities_rdb.py`（今年の直接証拠）と
`inherit_song_probabilities_rdb.py`（前年からの継承）である。
**この2本はどのworkflowからも呼ばれていない。** 内田さんかAIが必要なときに手で回す。
つまり公開されている曲の確率は、最後に誰かがこれを実行した時点のもので、毎日は更新されない。

### 5. 公開へ渡す（毎日）

`export_public_events.py` が開催回ごとに `occurrence_songs` を読み、本文からの抽出結果とマージして公開形にする。
**RDBに1行でも曲があれば、RDB側が正**として扱う。凍結された旧JSON（`data/song_occurrences.json`）は
RDBに曲が無い開催回のときだけ使う。順序が逆だと、凍結されて古いままの確率がRDBの計算結果を毎日上書きしてしまう。

`f517fa8` 時点の実データでは、公開379件のうち曲目が付いているのは55件、曲の延べ数は642件（異なり375曲）である。
根拠の内訳は実測346・今年告知9・今年ヒント73・過去実績191、そして本文抽出だけで根拠ラベルの無いものが23件ある。

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
- **確率の計算（`calibrate_song_probabilities_rdb.py` / `inherit_song_probabilities_rdb.py`）は
  どのworkflowにも入っていない。** 自動化するかどうかは決まっていない。
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
