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

## Decision required before workflow cleanup

`daily_song` と `daily_term` は `weekly_harvest.yml` の手動fallbackから、legacy keyboard-review HTMLの再生成、parity input JSONのcommit、`apply_reviewed=true` 時のNotion直接applyを行える。これはB5の統合inbox経路とは別のlive writerである。

workflow変更対象を明示した内田さんのGO後に、次のいずれかを選ぶ。

1. 退役: legacy UI生成と直接applyを削除し、workflow自体を停止または削除する。
2. 縮小: parity inputを読むだけの手動fallbackにし、legacy UI・commit・直接applyを外す。
3. 維持: 明示的なescape hatchとして残し、B5の通常経路外であることと実行条件をrunbookへ固定する。

rollback snapshot 7件の最終更新は2026-06-22〜2026-07-19であり、reader切替時点の最新状態を保証しない。このためrollbackは「古いlegacy snapshotを読む入口」であって、最新状態への復帰手段とはみなさない。
