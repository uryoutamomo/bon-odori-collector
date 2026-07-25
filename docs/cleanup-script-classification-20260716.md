# cleanup script classification for E pass 2

作成日: 2026-07-16 JST
署名: おと（Codex）
ステータス: 第2段の分類dry-run後、append系52本とbuild系低リスク/移行補助11本を実移動済み。

## 目的

E第1段で、mainに実在していた済みone-off `apply_*.py` 4本を `legacy/apply/` へ移動し、ルート直下の `apply_*.py` は50本になった。
第2段では、ルート直下に残る `append_*.py` と `build_*.py` のうち、現役運用に不要な単発スクリプトを分類してから移動する。

この文書は分類だけを行う。移動は、ことレビューと内田さんGO後に実施する。

## 現状

分類時点 main `ee9d02f`:

| pattern | count | 所見 |
|---|---:|---|
| root `*.py` | 317 | ルート直下がまだ多い |
| root `append_*.py` | 52 | ほぼNotionへの単発メモ追記 |
| root `build_*.py` | 54 | workflow現役・レビュー生成・RDB移行補助が混在 |
| root `apply_*.py` | 50 | E第1段後の目標値に到達 |
| `legacy/apply/*.py` | 4 | E第1段で移動済み |

append系実移動後:

| pattern | count | 所見 |
|---|---:|---|
| root `*.py` | 265 | append系52本を移動 |
| root `append_*.py` | 0 | ルートから撤去完了 |
| `legacy/notion-notes/append_*.py` | 52 | Notion単発メモ追記を集約 |

build系低リスク群 第1回実移動後:

| pattern | count | 所見 |
|---|---:|---|
| root `*.py` | 261 | build系4本を追加移動 |
| root `build_*.py` | 50 | workflow現役・RDB/レビュー基盤を温存 |
| `legacy/build-reports/build_*.py` | 4 | 単発レポート・旧候補生成を集約 |

build系低リスク群 第2回実移動後:

| pattern | count | 所見 |
|---|---:|---|
| root `*.py` | 259 | retrospective補助2本を追加移動 |
| root `build_*.py` | 48 | workflow現役・RDB/レビュー基盤を温存 |
| `legacy/build-reports/build_*.py` | 6 | 単発レポート・旧候補生成を集約 |

build系 Ph2/pre-cutover 移行補助クラスタ 実移動後:

| pattern | count | 所見 |
|---|---:|---|
| root `*.py` | 254 | Ph2/pre-cutover補助5本を追加移動 |
| root `build_*.py` | 43 | workflow現役・RDB/レビュー基盤を温存 |
| `legacy/build-reports/build_*.py` | 11 | 単発レポート・旧移行補助を集約 |

## 第2段の移動候補A: Notionメモ追記 append系

原則として `legacy/notion-notes/` へ移動候補。これらは「過去にNotionへ方針や作業記録を追記するための一回きりスクリプト」で、現在の正本はローカルMDまたはdocs側へ寄せる方針と整合する。

2026-07-16 の実移動で、下記52本はすべて `legacy/notion-notes/` へ移動済み。

移動時の注意:

- `append_youtube_task_list_to_notion.py` は `tests/test_notion_worklog_maintenance_policy.py` と `docs/notion-worklog-maintenance-operations.md` に参照があるため、移動時に参照更新が必要。
- `append_regional_seo_8ward_positioning_note.py` は自己参照のみ。
- ほかのappend系は、今回の `rg` ではworkflow/test/docsからの外部参照なし。

候補一覧:

```text
append_amplify_plan_note.py
append_bonsuke_kindle_manga_note.py
append_bonsuke_manga_generation_rule_note.py
append_bonsuke_opening_hook_note.py
append_bonsuke_web_serial_kindle_note.py
append_event_occurrence_model_note.py
append_event_time_research_note.py
append_fixed_date_ga4_report_note.py
append_historical_reference_review_flow_to_notion.py
append_keyboard_review_ui_note_to_notion.py
append_manual_auto_build_export_note.py
append_manual_auto_infra_note.py
append_manual_auto_legacy_notion_note.py
append_manual_auto_legacy_repair_note.py
append_manual_auto_legacy_youtube_notion_note.py
append_manual_auto_notion_queue_note.py
append_manual_auto_notion_worklog_note.py
append_manual_auto_public_json_note.py
append_manual_auto_x_candidate_note.py
append_public_event_count_note_to_notion.py
append_public_event_publication_flow_to_notion.py
append_public_recurrence_scoring_note.py
append_rdb_progress_to_current_work.py
append_rdb_roadmap_to_current_work.py
append_regional_seo_8ward_positioning_note.py
append_review_console_domain_difference_note_to_notion.py
append_review_console_export_stage_note_to_notion.py
append_review_console_flow_to_notion.py
append_review_console_keyboard_save_note_to_notion.py
append_review_console_note_to_notion.py
append_review_console_operations_manual_to_notion.py
append_review_console_stage_ack_note_to_notion.py
append_review_console_stage_reminder_note_to_notion.py
append_shibuya_public_ui_progress_note.py
append_shibuya_youtube_research_note.py
append_yearly_event_inheritance_policy_note.py
append_youtube_2025_backfill_policy_note.py
append_youtube_2025_backfill_progress_note.py
append_youtube_2025_curated_official_note.py
append_youtube_2025_date_backfill_note.py
append_youtube_2025_hold_note.py
append_youtube_2025_koto_decision_note.py
append_youtube_2025_manual_queue_note.py
append_youtube_2025_official_candidate_note.py
append_youtube_2025_second_pass_note.py
append_youtube_channel_registry_note.py
append_youtube_channel_review_note.py
append_youtube_channel_strategy_note_to_notion.py
append_youtube_next_tasks_note.py
append_youtube_public_export_note.py
append_youtube_task_list_to_notion.py
append_youtube_user_confirmation_note.py
```

実移動時の参照更新: `append_youtube_task_list_to_notion.py` は `tests/test_notion_worklog_maintenance_policy.py` と `docs/notion-worklog-maintenance-operations.md` の参照を `legacy/notion-notes/append_youtube_task_list_to_notion.py` へ更新済み。

## 第2段の移動候補B: 済みbuild/移行補助系

`build_*.py` は現役が多いので、第2段では「明確に古い移行補助・単発レビュー材料」だけを候補にする。実移動前に再度 `rg` でworkflow/test/docs参照を確認する。

| file | 分類 | 理由 |
|---|---|---|
| `build_blog_registration_candidates.py` | 移動候補 | 参照なし。過去のブログ登録候補作成 |
| `build_fallback_event_candidates.py` | 移動候補 | 参照なし。fallback候補の一回きり補助 |
| `build_july_official_url_gap_report.py` | 移動候補 | 自己参照のみ。7月公式URL gapレポート |
| `youtube_backfill/build_low_confidence_backfill_review.py` | package化済み | `run_daily_youtube_backfill.py` / docs参照を更新済み |
| `build_ph2_ebara_fifth_public_preview.py` | 移動候補 | 自己参照のみ。Ph2荏原第五の一回きりpreview |
| `build_ph2_ebara_fifth_venue_plan.py` | 移動候補 | docs参照あり。Ph2荏原第五の一回きりplan |
| `build_ph2_event_occurrence_apply_plan.py` | 移動候補 | Ph2移行補助。docs/他build参照あり |
| `build_ph2_review_packet.py` | 移動候補 | Ph2移行補助。他buildから参照あり |
| `build_pre_cutover_p0_apply_plan.py` | 移動候補 | pre-cutover一括補助。apply側参照あり |
| `build_retrospective_occurrences.py` | 移動候補 | 自己参照のみ。retrospective移行補助 |
| `build_retrospective_venue_song_associations.py` | 移動候補 | 自己参照のみ。retrospective song/venue補助 |

2026-07-16 の実移動で、参照なし・自己参照のみの低リスク4本を `legacy/build-reports/` へ移動済み。

```text
build_blog_registration_candidates.py
build_fallback_event_candidates.py
build_july_official_url_gap_report.py
build_ph2_ebara_fifth_public_preview.py
```

同日追加で、workflow/docs/scriptsからの実行参照がなく、テストだけが import していた retrospective 補助2本を
`legacy/build-reports/` へ移動済み。テストは移動先ファイルを明示ロードする形へ更新した。

```text
build_retrospective_occurrences.py
build_retrospective_venue_song_associations.py
```

同日追加で、workflowには入っていない Ph2/pre-cutover 移行補助クラスタ5本を `legacy/build-reports/` へ移動済み。
runbookの直接実行コマンドは `PYTHONPATH=. python3 legacy/build-reports/...` へ更新し、テストと
レビュー補助内の参照パスも移動先へ更新した。

## 2026-07-25 復帰: 東京盆踊りマップ取り込み4本

上記「参照なし」判定は当時は正しかったが、`build_blog_registration_candidates.py`（および
`legacy/venue_research/` へ同時に移動していた `extract_venues_blog.py` / `extract_blog_venue_rows.py` /
`triage_blog_venue_candidates.py`）は、盆助イシューリストP1「official_source 52件中43件がMaster RDB
にマッチせず新規登録候補の可能性」の調査で、実行済みone-offではなく本来は定期的に再実行すべき情報源
更新ツールだったことが判明した。移動時に潜んでいた2件のバグ（`extract_venues_blog.py`の出力先が
`os.path.dirname(__file__)`基準になっており移動後に誤ったディレクトリへ書いていた／
`build_blog_registration_candidates.py`の`triage_blog_venue_candidates`importが移動後に壊れていた）
も合わせて修正し、4本ともroot直下へ復帰。`.github/workflows/refresh_official_source_review.yml`
（毎週木曜15:30 JST）で自動実行する。

```text
build_ph2_cutover_readiness.py
build_ph2_ebara_fifth_venue_plan.py
build_ph2_event_occurrence_apply_plan.py
build_ph2_review_packet.py
build_pre_cutover_p0_apply_plan.py
```

`youtube_backfill/build_low_confidence_backfill_review.py` は `run_daily_youtube_backfill.py` からモジュール実行する。

推奨: build系はappend系と同じコミットで動かさない。append系移動後に、参照更新範囲を個別に見てから小さく移動する。

## 残す: workflow現役

以下は `.github/workflows/collect.yml` / `weekly_harvest.yml` から直接呼ばれる、または日次・週次運用の中核なので残す。

```text
build_event_poster_ocr_queue.py
build_event_song_candidates.py
build_glossary_runtime.py
collection_support/build_keyboard_review_ui.py
build_rare_signal_backcheck_queue.py
build_retrospective_harvest.py
build_song_occurrences.py
build_song_ocr_queue.py
build_weekly_harvest_candidates.py
build_x_news_digest_for_oto.py
```

## 残す: RDB/公開/レビュー基盤

以下は現役のRDB構築、公開投影、レビューキュー、YouTube/曲/用語の基盤として残す。B/C/Dや別移行が終わるまで動かさない。

```text
build_all_rdb.py
rdb_builders/build_bon_odori_rdb.py
youtube_backfill/build_event_date_predictions.py
youtube_backfill/build_event_occurrence_backfill_plan.py
youtube_backfill/build_event_occurrence_observations.py
youtube_backfill/build_event_schedule_rules.py
rdb_builders/build_evidence_rdb.py
build_glossary_review_ui.py
build_glossary_v2_seed_candidates.py
build_historical_promotion_candidates.py
build_historical_reference_quality_review.py
rdb_builders/build_master_rdb.py
build_missing_venue_review_from_song_associations.py
youtube_backfill/build_month_youtube_backfill_queue.py
rdb_builders/build_notion_rdb.py
build_notion_snapshot_drift_decisions.py
build_observed_promotion_candidates.py
build_official_social_source_review.py
build_official_source_review.py
build_predicted_occurrence_research_queue.py
build_publication_gap_review.py
build_registered_event_investigation_queue.py
build_youtube_active_video_review.py
build_youtube_channel_review.py
build_youtube_channels.py
youtube_backfill/build_youtube_event_review.py
build_youtube_event_song_candidates.py
build_youtube_nationwide_hold.py
rdb_builders/build_youtube_rdb.py
build_youtube_song_master.py
build_youtube_year_backfill_queue.py
build_youtube_year_backfill_review_queue.py
```

## 第2段の推奨手順

1. ことレビューで分類を確認する。
2. 内田さんGO後、まず append系52本だけを `legacy/notion-notes/` へ `git mv` する。
3. `append_youtube_task_list_to_notion.py` のテスト・docs参照を更新する。
4. `python3 -m unittest discover -s tests` を実行する。
5. append系移動がgreenなら、build系移動候補を別コミットで小さく移す。
