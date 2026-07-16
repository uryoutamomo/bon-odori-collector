# one-off apply classification for E archive pass

作成日: 2026-07-16 JST
署名: おと（Codex）
ステータス: A設計固定後の分類リスト。移動は未実施。

## 目的

E「名残の撤去」では、済んだ one-off apply を `legacy/` へ移動してルート直下の視認性を戻す。ただし削除はしない。
このリストは、A `apply_change_requests.py` の設計固定後に、何を移動候補にし、何を現役として残すかを分けるためのもの。

## 移動ルール

- すでに実行済みのイベント個別 apply は `legacy/apply/` へ移動候補にする。
- 汎用入口、現地/掲示物レポート入口、レビューコンソール入口は残す。
- 公開JSON後付けパッチ系はCが終わるまで残す。
- 受信箱・レビュー判断系はBが終わるまで残す。
- Notion残置・曲/用語系は別移行の影響があるため、E第1段では移動しない。
- 移動前に `rg` で workflow / docs / tests / import 参照を確認し、参照が残るものは「保留」にする。

## 残す: 現役入口

| file | 理由 |
|---|---|
| `apply_change_requests.py` | Aの新しい汎用RDB反映口 |
| `apply_firsthand_field_report.py` | 現地レポート用の専用入口。Aとは入力の性質が違う |
| `apply_official_notice_report.py` | 掲示物・チラシの複数イベント報告入口。Aとは入力の性質が違う |
| `apply_review_console_decisions.py` | B完了までレビューコンソール判断のステージング入口 |

## 移動候補: 実行済みイベント個別 one-off

次はAの4種で今後は置き換える対象。移動時は `legacy/apply/` 配下へ置く想定。

2026-07-16 のmain実移動では、mainに実在していた4本だけを移動した。下表のうち `main未収録` のものは、当時のローカル作業ツリーには未追跡で存在していたが、mainには載っていなかったため移動対象外。

| file | 主な種別 | 備考 | 2026-07-16 main実移動 |
|---|---|---|---|
| `apply_gujo_series_merge.py` | series merge | v2以降の変更種別候補。済みone-offとして移動候補 | `legacy/apply/`へ移動 |
| `apply_irifune_third_historical_reference.py` | historical reference | A `add_historical_reference` 置換対象 | main未収録 |
| `apply_july19_2026_public_events.py` | current-year confirmation / public event add | A `confirm_current_year_date` + venue系で置換対象 | main未収録 |
| `apply_kameari_yuroad_historical_reference.py` | historical reference / songs | A `add_historical_reference` + `add_song_evidence` 置換対象 | main未収録 |
| `apply_kyobashi5_nouryou_map_2026.py` | official notice one-off | 今後は `apply_official_notice_report.py` またはA | `legacy/apply/`へ移動 |
| `apply_marunouchi_2026_official_confirmation.py` | current-year confirmation | A `confirm_current_year_date` 置換対象 | main未収録 |
| `apply_ph2_ebara_fifth_rdb.py` | old RDB phase apply | 済みone-offとして移動候補 | `legacy/apply/`へ移動 |
| `apply_ph2_shinagawa_second_venue_review.py` | venue update | 専用テストがあるため第1段では保留 | 保留 |
| `apply_satake_geba_bon_odori.py` | current-year rare signal promotion | A `confirm_current_year_date` 置換対象 | `legacy/apply/`へ移動 |
| `apply_sumibon_2026_rare_signal.py` | current-year rare signal promotion | A `confirm_current_year_date` 置換対象 | main未収録 |
| `apply_tokyofesta_2026_public_events_batch.py` | third-party current-year batch | A `confirm_current_year_date` 置換対象。batch2/harumiがimportするので移動順注意 | main未収録 |
| `apply_tokyofesta_2026_public_events_batch2.py` | wrapper one-off | base移動時に同時移動 | main未収録 |
| `apply_tokyofesta_harumi_2026_public_event.py` | wrapper one-off | base移動時に同時移動 | main未収録 |

## 保留: C完了まで残す公開JSONパッチ系

| file | 理由 |
|---|---|
| `apply_public_date_predictions.py` | CでRDB側へ統合予定。切替まで温存 |
| `apply_public_historical_references.py` | CでRDB側へ統合予定。切替まで温存 |
| `apply_public_season_hints.py` | CでRDB側へ統合予定。切替まで温存 |
| `apply_public_display_tiers.py` | Dの語彙整理まで温存 |
| `apply_public_event_name_cleanup.py` | 公開JSON整形系。Cの前に動かさない |
| `apply_public_official_source_urls.py` | 公開JSON/ソースURL整理系。Cの前に動かさない |

## 保留: B/Dまたは別移行まで残すレビュー・Notion・曲/用語系

| file | 理由 |
|---|---|
| `apply_event_occurrence_backfill_plan.py` | YouTube backfill判断系。Bの受信箱統合まで残す |
| `apply_glossary_review_decisions.py` | 用語系。別移行範囲 |
| `apply_missing_venue_review_decisions.py` | レビュー判断系。Bまで残す |
| `apply_notion_drift_public_intro.py` | Notion drift整理系。別移行範囲 |
| `apply_notion_drift_source_url_resolutions.py` | Notion drift整理系。別移行範囲 |
| `apply_official_source_review_decisions.py` | evergreen/local JSON系。B/C確認まで残す |
| `apply_predicted_occurrence_source_rechecks.py` | 予測日ソース再確認系。C/B境界のため残す |
| `apply_pre_cutover_p0_historical_references.py` | pre-cutover一括系。参照確認後に第2段で判断 |
| `apply_retrospective_existing_event_updates.py` | legacy Notion系。Notion残置整理で判断 |
| `apply_retrospective_ready_venue_events.py` | legacy Notion系。Notion残置整理で判断 |
| `apply_retrospective_song_candidates.py` | legacy Notion/song系。別移行範囲 |
| `apply_retrospective_venue_song_review_decisions.py` | song/venue review系。別移行範囲 |
| `apply_reviewed_historical_references.py` | A置換候補だが、既存レビュー入力との接続確認後 |
| `apply_reviewed_missing_date_start_promotions.py` | A置換候補だが、B/C前のレビュー入力接続あり |
| `apply_reviewed_missing_occurrence_venues.py` | venue review系。Bまで残す |
| `apply_reviewed_missing_source_urls.py` | source_url review系。B/Cまで残す |
| `apply_reviewed_official_wait_events.py` | A置換候補だが、既存公式待ちreview入力の接続確認後 |
| `apply_reviewed_public_event_candidates_20260701.py` | reviewed batch系。参照確認後 |
| `apply_reviewed_shinagawa_date_fills.py` | A置換候補だが、review入力接続確認後 |
| `apply_reviewed_venue_field_fixes.py` | A置換候補だが、review入力接続確認後 |
| `apply_series_source_url_inheritance.py` | shared maintenance系。残す |
| `apply_song_content_research_batch.py` | 曲コンテンツ系。別移行範囲 |
| `apply_song_ocr_review.py` | 曲証拠系。別移行範囲 |
| `apply_song_official_sources_batch.py` | 曲コンテンツ系。別移行範囲 |
| `apply_song_publication_review_decisions.py` | 曲公開系。別移行範囲 |
| `apply_weekly_harvest_human13_decisions.py` | X/用語系。別移行範囲 |
| `apply_weekly_song_final_corrections.py` | 曲系。別移行範囲 |
| `apply_weekly_song_review_decisions.py` | 曲系。別移行範囲 |
| `apply_youtube_2025_curated_official_candidates.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_2025_date_backfill.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_2025_koto_decisions.py` | review decision merge系。Bまで残す |
| `apply_youtube_2025_koto_ready_events.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_2025_official_candidate_existing_updates.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_active_existing_event_updates.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_blocked_new_events.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_existing_event_updates.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_official_confirmation.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_review_video_evidence.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_reviewed_new_events.py` | legacy Notion/YouTube系。Notion残置整理で判断 |
| `apply_youtube_year_backfill_review_decisions.py` | local evidence/review系。Bまで残す |

## 次のE手順

1. `rg 'apply_(gujo|irifune|july19|kameari|kyobashi5|marunouchi|ph2|satake|sumibon|tokyofesta)' .github docs tests *.py` で参照を確認する。
2. `legacy/apply/` を作り、移動候補だけを `git mv` する。
3. wrapper関係の `apply_tokyofesta_2026_public_events_batch*.py` は同時に移動する。
4. 移動後に `python3 -m unittest tests.test_apply_change_requests` と、参照が残る関連テストを回す。
5. workflow参照が残る場合は移動を保留し、分類表へ理由を追記する。
