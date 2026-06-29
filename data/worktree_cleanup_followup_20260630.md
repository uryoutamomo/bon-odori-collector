# Worktree cleanup follow-up

- generated_at: 2026-06-30
- generated_by: おと（Codex）
- scope: post-cleanup status after splitting URL, review console, operation-boundary, character-asset, and review-tooling commits
- deploy_performed: false
- push_performed: false

## Completed cleanup commits

| commit | summary | note |
| --- | --- | --- |
| `a542488` | Fill missing event source URLs | URL補完だけを切り出し済み。 |
| `9910a4b` | Add local review console | ローカル管理コンソールを別コミット化。 |
| `03ab05a` | Document worktree cleanup plan | 初回整理メモとローカル成果物 ignore。 |
| `996af49` | Document manual operation boundaries | 手動/自動運用境界、確認フレーズ、policy tests を切り出し済み。 |
| `468302c` | Document character asset handoff | キャラクター素材の正本を `bonsuke-manga` 側に寄せ、collector 側の generated コピーを ignore。 |
| `9bf00b6` | Add official social source registry | X/公式SNS情報源の登録・判定・レビュー候補を切り出し済み。 |
| `ac158ad` | Add X news digest tooling | X由来ニュース候補生成/昇格のコードとテストだけを切り出し済み。生成digest JSONは未コミット。 |
| `8a379e4` | Add rare signal backcheck tooling | rare signal 裏どり用コード、設計doc、テストを切り出し済み。生成キューJSONは未コミット。 |
| `4f25cc0` | Constrain source reviews to Tokyo wards | 東京23区スコープ補助と公式ソースレビューの除外条件を切り出し済み。 |
| `d36c83e` | Add post-batch operations reports | post-batch/ops metrics のコードとテストを切り出し済み。生成レポートは未コミット。 |
| `2604504` | Improve YouTube title song parsing | YouTube title/setlist解析、title helper、監査スクリプト、関連テストを切り出し済み。生成監査JSONは未コミット。 |
| `5924968` | Add historical reference quality review | historical reference quality review のコード、doc、テストを切り出し済み。生成レビューJSONは未コミット。 |
| `1a86a96` | Opt in glossary tests to Notion writes | 既存テストを Notion 書き込み opt-in 方針へ追随。 |
| `82385d1` | Accept approved X member rows | 承認済みXメンバー候補の扱いを小さく切り出し済み。 |

## Current remaining scale

| metric | value |
| --- | ---: |
| tracked changed files | 71 |
| untracked files | 68 |
| tracked diff size | +103,991 / -455,535 |

## Public JSON status

Do not deploy the remaining public JSON diff as-is.

Observed state:

- `data/public/events_public.js` has 3 official URL additions.
- `data/public/events_public.json` is not changed.
- `data/public/event_songs_public.json` and `data/public/event_song_occurrences_public.json` still contain generated song diffs.
- `python3 apply_public_official_source_urls.py --dry-run` reports 33 public events would be updated with 34 URLs if applied to the JSON source.

Risk:

- The current JS-only diff is not aligned with the JSON source.
- A deploy should first regenerate a clean public JSON/JS pair or explicitly choose a source-of-truth path.

Recommended next split:

1. Rebuild `data/public/events_public.json` and `.js` from the intended source.
2. Confirm whether the 33-event official-source URL update is desired.
3. Keep song export files in a separate song/public export review.

## Remaining groups

### A. Public/generated data

Files include:

- `data/public/events_public.js`
- `data/public/event_songs_public.json`
- `data/public/event_song_occurrences_public.json`
- `data/public_events_sync_guard.*`
- `data/public_historical_reference_dry_run.json`
- `data/public_season_hint_dry_run.json`

Action:

- Keep separate from deploy until regenerated and reviewed.

### B. YouTube/song generated data

Largest files/diffs include:

- `data/song_prediction_snapshots.json`
- `data/youtube_setlist_occurrences.json`
- `data/youtube_active_video_review.json`
- `data/youtube_active_video_review.md`
- `data/youtube_daily_backfill_report.*`
- `data/youtube_channels.json`

Action:

- Treat as a batch output. Commit only with the exact runner/test context, or regenerate cleanly before review.

### C. Review/research feature workstreams

Untracked groups remain for:

- July official source promotions
- event time / source / venue review batches
- generated X news / rare-signal / historical-reference review outputs
- one-off Notion append note scripts

Action:

- Commit each feature with its scripts, tests, docs, and generated review data as separate units.

### D. Existing code/test changes

Tracked code changes remain in:

- `export_public_glossary.py`
- `review_missing_occurrence_venues.py`
- `audit_master_rdb.py`
- associated tests

Action:

- Do not bundle them with generated data. Run targeted tests and commit by feature.

## Still not safe for whole-repo deploy

The repository is cleaner than before, but it still contains multiple independent workstreams and large generated diffs.

Current safe stance:

- Commit/deploy only intentionally isolated groups.
- Do not push/deploy the whole worktree.
- Treat remaining public JSON and song/YouTube outputs as review-required.
