# Review inbox legacy cleanup inventory

この棚卸しはread-onlyであり、削除・移動・workflow変更を行わない。

| source | path | category | exists | references | alternate writer |
| --- | --- | --- | --- | ---: | --- |
| rare_signal_backcheck | `data/rare_signal_backcheck_queue.json` | parity_input | false | 3 | — |
| youtube_active | `data/youtube_active_video_review.json` | parity_input | true | 3 | — |
| youtube_year_backfill | `data/youtube_year_backfill_review_queue.json` | parity_input | true | 3 | — |
| youtube_user_confirmation | `data/youtube_user_confirmation_queue.json` | parity_input | true | 3 | — |
| daily_song | `data/weekly_song_candidates_review.json` | parity_input | true | 4 | .github/workflows/weekly_harvest.yml |
| daily_term | `data/weekly_harvest_review_candidates.json` | parity_input | true | 4 | .github/workflows/weekly_harvest.yml |
| accepted_venue_song_missing_venue | `data/accepted_venue_song_missing_venue_review.json` | parity_input | true | 3 | — |
| historical_reference_quality | `data/historical_reference_quality_review.json` | parity_input | true | 3 | — |
| publication_gap | `data/publication_gap_review.json` | parity_input | true | 3 | — |
| legacy_official_source | `data/official_source_review_candidates.json` | rollback_snapshot | true | 2 | — |
| legacy_registered_investigation | `data/registered_event_investigation_queue.json` | rollback_snapshot | true | 2 | — |
| legacy_predicted_research | `data/predicted_occurrence_research_queue.json` | rollback_snapshot | true | 2 | — |
| legacy_predicted_date_review | `data/predicted_occurrence_date_review.json` | rollback_snapshot | true | 2 | — |
| legacy_missing_source_url | `data/missing_source_url_review.json` | rollback_snapshot | true | 2 | — |
| legacy_missing_venue | `data/missing_occurrence_venue_review.json` | rollback_snapshot | true | 2 | — |
| legacy_historical_promotion | `data/historical_promotion_candidate_review.json` | rollback_snapshot | true | 1 | — |

## Rules

- `parity_input` は対応するscheduled adapterとparity検証が残る間、削除・移動しない。
- `alternate_live_writer` がある入力は、手動workflowがlegacy UI再生成・commit・直接applyを行える。writerを退役・縮小・維持のいずれにするか、別レビューで明示決定するまで削除候補にしない。
- `rollback_snapshot` はconsoleの既定入力に戻さず、rollback手順に従ってのみ参照する。JSONの `snapshot_provenance` は最終commitと時刻を記録する。
- manifest外のlegacy候補は、このinventoryへ追加してから別レビューで扱う。

## Out of scope

- `x_news_digest_for_oto / rare_signal_candidates`: machine discovery pipeline inputs, not review-inbox reader snapshots
- `weekly_harvest_candidates`: upstream collection material; the review-inbox input is weekly_harvest_review_candidates
- `x_candidate_post_review`: separate X account/member-list workflow
