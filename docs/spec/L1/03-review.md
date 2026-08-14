---
id: L1-review
layer: L1
title: 人のレビュー運用サブシステム
owns:
  - review_inbox.py
  - review_inbox_adapters/**
  - review_console/**
  - review_console_ops/**
  - scripts/promote_change_requests_for_review.py
  - run_review_inbox_rare_signal_scheduled.py
  - run_review_inbox_rare_signal_canary.py
  - run_review_inbox_rare_signal_decision_canary.py
  - run_review_inbox_low_priority_scheduled.py
  - build_rare_signal_backcheck_queue.py
  - search_rare_signal_backcheck_sources.py
  - export_rare_signal_backcheck_reviews.py
  - stage_rare_signal_backcheck_reviews.py
  - build_historical_reference_quality_review.py
  - build_x_review_lanes.py
  - build_x_account_console.py
  - build_x_news_digest_for_oto.py
  - promote_x_news_digest_reviews.py
  - review_x_candidate_posts.py
  - build_event_poster_ocr_queue.py
  - build_retrospective_harvest.py
  - build_weekly_harvest_candidates.py
  - prepare_weekly_harvest_review.py
  - build_official_source_review.py
  - review_inbox_migration_runner.py
depends_on:
  - L1-master
invariants:
  - INV-RVW-001
  - INV-RVW-002
  - INV-RVW-003
  - INV-RVW-004
  - INV-RVW-005
  - INV-RVW-006
  - INV-RVW-007
verified_by:
  - tests/test_review_inbox_decision_writer.py
  - tests/test_promote_change_requests_for_review.py
updated_for: 7ca7a07
---

# 人のレビュー運用サブシステム

> 上位は[全体地図](../README.md)。下流は[マスタ](04-master.md)。

## この工程は何のためにあるか

機械が決められないものを、人が裁定する工程である。
断片から「この投稿はこのイベントの告知だ」「この会場はここだ」と決めきれないものが必ず残るので、
それを受信箱に積み、レビューコンソールで人が判断し、決定をマスタへ渡す。

**盆助全体の律速はここにある。** 集めることでも判断することでもなく、
人が裁定を下す速度が全体の速度を決めている。実際、精度が悪いように見える場面を追いかけると、
判定アルゴリズムではなく**人のレビューが詰まっている**ことのほうが多い。
「精度が悪い」と感じたら、まず止まっている工程を探すのが正しい順序になる。

もうひとつ、この工程には性質上の難しさがある。人の判断は繰り返せない。
同じ画面をもう一度開いて同じ操作をしたときに、決定が二重に適用されたり、
裁定した相手が別のイベントにすり替わっていたりすると、人は自分の判断を信用できなくなる。
だから設計の重心は「詰まらせないこと」と「決定を取り違えないこと」の2つに置かれている。

## 入力と出力

**入力**

| 何を | どこから |
|---|---|
| 各種の要レビュー項目 | `review_inbox_adapters/` 配下の各アダプタ経由（X由来の穴、公式ソース、会場欠落、過去実績、YouTube など） |
| 現在のマスタ状態 | Master RDB の `review_inbox_items` テーブル |

**出力**

| 何を | どこへ |
|---|---|
| 受信箱の投影 | `data/review_inbox.json` |
| 人の決定 | `review_inbox_items` の状態更新 |
| 適用可能な変更リクエスト | 昇格済みの reviewed JSON → [マスタ](04-master.md) |

## 不変条件

### INV-RVW-001 同じ決定を二度書いても、二重に適用されない

- **内容**: 決定の書き込みは1項目につき1つのライフサイクルだけを発行する。
  まったく同じ決定を再送した場合は noop として扱い、何も起きない。
- **なぜ**: 人はブラウザを再読み込みするし、通信は失敗する。
  再試行が二重適用になる設計だと、人が安心して操作できない。
- **破れたときの症状**: 1回の裁定が2件の変更として適用される。件数が合わなくなる。
- **守っているコード**: `review_inbox_adapters/decision_writer.py`
- **守っているテスト**: `tests/test_review_inbox_decision_writer.py::test_decision_write_publishes_one_lifecycle_only_then_exact_retry_is_noop`、
  `tests/test_review_inbox_decision_writer.py::test_existing_decision_requires_exact_lifecycle_for_noop`

### INV-RVW-002 対象の取り違えと競合は、通さずに止める（fail-closed）

- **内容**: 決定を書くとき、対象の同一性が一致しない場合と、
  比較対象の状態が変わっていた場合（CAS衝突）は、書き込まずに失敗させる。
- **なぜ**: 人が見た画面と、実際に書き込まれる対象がズレていると、
  **裁定そのものが別のイベントに適用される**。これはデータが壊れるより悪い。
  人が「自分は正しく判断した」と思っているのに結果が違う、という形で信頼を壊すからだ。
  迷ったら書かない側に倒すのが正しい。
- **破れたときの症状**: レビューした覚えのないイベントの情報が変わっている。
- **守っているコード**: `review_inbox_adapters/decision_writer.py`
- **守っているテスト**: `tests/test_review_inbox_decision_writer.py::test_target_identity_and_cas_conflict_fail_closed`

### INV-RVW-003 決定の書き込みが、勝手にスキーマを移行しない

- **内容**: 決定writerは、受信箱スキーマが古い版だった場合に自動で移行しない。
- **なぜ**: 移行は専用のworkflow（`migrate_review_inbox_v2.yml`）の仕事で、
  日常の書き込み経路が副作用としてスキーマを変えると、いつ変わったのか誰も追えなくなる。
  マスタ側で起きた [INV-MST-005](04-master.md) の事故と同じ構図で、
  「動いているように見えて、別の工程が壊れる」種類の問題につながる。
- **破れたときの症状**: 意図しないタイミングでスキーマが変わり、他の工程が失敗し始める。
- **守っているコード**: `review_inbox_adapters/decision_writer.py`
- **守っているテスト**: `tests/test_review_inbox_decision_writer.py::test_writer_never_migrates_v1_schema`

### INV-RVW-004 実適用に使う reviewed JSON は、人の昇格を経たものだけ

- **内容**: 自動生成された reviewed JSON は機械検査専用で、人レビュー済みとして扱わない。
  実際に適用する JSON は `scripts/promote_change_requests_for_review.py` を人が実行して作り、
  レビュー担当者と経緯を記録する。承認IDが未知のもの、`dry_run_only` が付いていない選択は拒否される。
- **なぜ**: 「レビュー済み」という印は、人が見たことの証明でなければ意味がない。
  機械が付けた印を人の印と同じ扱いにすると、レビュー工程そのものが形骸化する。
- **破れたときの症状**: 誰も見ていない変更が「レビュー済み」としてマスタへ入る。
- **守っているコード**: `scripts/promote_change_requests_for_review.py`
- **守っているテスト**: `tests/test_promote_change_requests_for_review.py::test_refuses_unknown_approved_id`、
  `tests/test_promote_change_requests_for_review.py::test_refuses_selected_request_without_dry_run_only`

### INV-RVW-005 J0-read は正本factを変更しない

- **内容**: event candidate の packet 化と LLM 判断の取り込みは、canonical decision / queue / hold / claim の台帳だけへ記録する。venue、series、occurrence、song とその alias/link 表は変更しない。
- **守っているコード**: `build_judgment_packets.py`、`apply_judgment_results.py`、`judgment_ledger_writer.py`
- **守っているテスト**: `tests/test_judgment_j0_read.py::test_apply_keeps_canonical_facts_and_candidate_status_unchanged`、`tests/test_judgment_j0_read.py::test_structure_does_not_import_canonical_fact_writers`

### INV-RVW-006 LLMの自己申告は判断主体にしない

- **内容**: actor identity・channel・時刻はローカルentrypointが stamp し、result JSON の申告値は採用しない。
- **守っているテスト**: `tests/test_judgment_j0_read.py::test_untrusted_actor_identity_and_timestamp_are_overwritten`

### INV-RVW-007 J0-read はcandidateを消費しない

- **内容**: `review_inbox_items.status` は `candidate` のまま維持する。E0 の改訂・再実行を止めないためである。
- **守っているテスト**: `tests/test_judgment_j0_read.py::test_apply_keeps_canonical_facts_and_candidate_status_unchanged`

## 主要な流れ

1. **各アダプタが受信箱へ積む** — `review_inbox_adapters/` 配下。X由来の穴、公式ソース、
   会場欠落、過去実績、YouTube など、種類ごとに別アダプタになっている。
   **アダプタが守る形と禁止事項は[受信箱アダプタの契約](../L2/review-inbox-adapter.md)にある**
   （`source_adapter.py` と `parity.py` を触るときは、このL1ではなくそちらのINV-ADPを読む。
   ファイルの持ち主はこのL1のままなので、逆引きからは片道にしか繋がらない）。
2. **受信箱を投影する** — `review_inbox.py --out-json data/review_inbox.json --status pending`。
3. **人が裁定する** — `review_console_ops/run_review_console.py` でローカルサーバを立て、
   `review_console/` のUIで判断する。
4. **決定を書く** — `review_inbox_adapters/decision_writer.py`（INV-RVW-001〜003）。
5. **昇格させる** — `scripts/promote_change_requests_for_review.py` を人が実行（INV-RVW-004）。
6. **マスタへ適用** — [L1-master](04-master.md) の dry-run → apply 経路へ。

### J0-read の局所判断経路

E0 が作った `status='candidate'` を `build_judgment_packets.py` が claim 付きpacketへ凍結する。LLM の result は `apply_judgment_results.py` が packet/source hash/allowed action を照合してから正規化し、`judgment_ledger_writer.py` が decision・queue・hold の3台帳へだけ書く。これは正本factへの適用経路ではない。retry候補、actor identity、時刻をLLMに決めさせると再試行や監査が壊れるため、機械計算またはローカルentrypointの値だけを採用する。

### 日次で積んでいるのは、いくつの入口か

1番の「積む」を、日次の `collect.yml` が実際にどう動かしているかを書いておく。
ここが長らく仕様に書かれておらず、**毎日動いているのに触っても逆引きに出てこない状態だった**
（2026-08-14に配分。それまで `collect.yml` が呼ぶ38本のうち23本がどの仕様にも属していなかった）。

積む入口は4つのレーンに分かれていて、それぞれ独立に有効・無効を切り替えられる。
**スクリプト側の既定はどれも off** で、動かすにはリポジトリ変数のガードと確認句の両方が要る
（たとえば `--confirm 'RUN SCHEDULED YOUTUBE AGGREGATE DUAL WRITE'` のような句を workflow が渡す）。
`83bf7d0` 時点で有効なのは稀少シグナル・YouTube集約・低優先の3つで、
`REVIEW_INBOX_YOUTUBE_ACTIVE_DUAL_WRITE_ENABLED` だけ `false` のままである。
既定を off にしてあるのは、新しい積み方を本番へ繋いだ瞬間に全件が静かに流れ込むのを防ぐためで、
**入口の量が人の処理量を超えることがこの工程の最大の失敗だから**である。

| レーン | 積む前に作るもの | 受信箱へ流す実行 |
|---|---|---|
| 稀少シグナル | `build_rare_signal_backcheck_queue.py` → `export_rare_signal_backcheck_reviews.py` → `stage_rare_signal_backcheck_reviews.py` | `run_review_inbox_rare_signal_scheduled.py` |
| YouTube集約 | [YouTube取り込み](09-youtube.md)側で用意 | `run_review_inbox_youtube_scheduled.py`（同じくあちら） |
| 低優先 | `build_missing_venue_review_from_song_associations.py`（会場側）、`build_historical_reference_quality_review.py` | `run_review_inbox_low_priority_scheduled.py` |
| X由来 | `build_x_gap_candidates.py`（収集側）→ `review_inbox_adapters/x_gap_adapter.py` → `build_x_review_lanes.py` | 定期の二重書き込みは持たず、整形したJSONを置くところで止まる |

X由来だけ形が違う。`build_x_review_lanes.py` は穴の候補を**3つの運用レーンへ切り分ける**のが役目で、
1番目のレーンは意図的に厳しくしてある（登録済みの公式ソースだけを通す）。
機械が拾った穴をそのまま人へ渡すと、レビュー待ちが人の処理速度を超えて詰まるためである。

このほかに、日次で回っている周辺の入口が3種類ある。

- **おと向けのニュース要約** — `build_x_news_digest_for_oto.py` が、収集済みの投稿から要約を作る
  （X・Notion・LLMのいずれも呼ばない）。おとが読んで裁定した結果は
  `promote_x_news_digest_reviews.py` が稀少シグナル候補へ昇格させる。
  機械が用意した要約を最終解釈として信用しない、という前提でこの2段になっている。
- **収穫（harvest）** — `build_retrospective_harvest.py` と `build_weekly_harvest_candidates.py --days 3`、
  `prepare_weekly_harvest_review.py` が、用語候補と曲・会場の共起をレビュー用のキューにする。
  名前は「週次」だが**日次で動いている**ので、名前から実行間隔を推測しないこと。
- **掲示物のOCR** — `build_event_poster_ocr_queue.py` が、チラシ・貼り紙の写真が付いた投稿を
  優先度の高いOCRの列にする。曲目表のOCR（`build_song_ocr_queue.py`）は[曲目](08-songs.md)側の別経路である。

`build_x_account_console.py` は積む入口ではなく、**読んでいる相手を人が見られるようにする画面**を作る。
2026-07-26まで「誰を読んでいるのか」を見る手立てが無かったために作られたもので、
`review_x_candidate_posts.py` はその候補アカウントを直近の投稿から人が判断するための補助である。

日次とは別に、**公式ソースURLのレビュー列**を作る `build_official_source_review.py` が
`refresh_official_source_review.yml` から動く。毎年開かれる行事の公式URLが古くなっていないかを人が見るための列で、
公開面で出典を示せるかどうかに直結する（出典を出してよい情報源の線引きは運用側の判断である）。

受信箱のスキーマ移行は `review_inbox_migration_runner.py` が `migrate_review_inbox_v2.yml` から実行する。
**移行の入口をここに1本だけ置いてあるのは、日常の書き込み経路が副作用でスキーマを変えないようにするため**で、
その約束が INV-RVW-003 である。この runner はマスタDBを publish しない作りになっていて、
移行とS3への公開を必ず別の操作に保っている。

## 依存と影響

**上流**: 各収集・判断工程。積まれる項目の質が悪いと、人の時間が浪費される。
受信箱に積む基準が緩すぎると、**詰まりの原因そのものになる**。

**下流**: [マスタ](04-master.md)。ここでの裁定がRDBの確定情報になる。

## 壊れたときの症状

| 症状 | まず見る場所 |
|---|---|
| レビュー待ちが減らない・増え続ける | 積む基準が緩すぎないか。人の処理速度と釣り合っているか |
| 裁定したのに反映されない | 昇格（INV-RVW-004）を実行したか |
| 1回の裁定が2件になっている | INV-RVW-001 |
| 見覚えのないイベントが変わっている | INV-RVW-002 |

## 未解決・注意点

- **受信箱に積む選別基準の作り直しが未着手。** いまは積まれる量が人の処理量を上回りうる。
  律速工程に対して入口を絞らないままなので、根本的にはここが宿題になっている。
- レビューコンソールの「次に何をすべきか」の提示が弱く、優先順位が人の記憶に依存している。
- ~~アダプタが種類ごとに増える構造なので、共通の契約（L2）を切り出したい。~~
  **2026-08-14に[受信箱アダプタの契約](../L2/review-inbox-adapter.md)として切り出した。**
  ただし切り出したのは共通部分（項目の形・禁止事項・突き合わせ）だけで、
  種類ごとの `payload` の中身は各アダプタの実装にしか書かれていない。

---

こと（Claude Code）
