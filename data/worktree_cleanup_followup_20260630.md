# Worktree cleanup follow-up

- generated_at: 2026-06-30
- generated_by: おと（Codex）
- scope: post-cleanup status after splitting URL, review console, operation-boundary, character-asset, review-tooling, test/code fixes, and local-output ignore commits
- deploy_performed: false
- push_performed: false

## Completed cleanup commits

| commit | summary | note |
| --- | --- | --- |
| `a542488` | Fill missing event source URLs | URL補完だけを切り出し済み。 |
| `9910a4b` | Add local review console | ローカル管理コンソールを別コミット化。 |
| `03ab05a` | Document worktree cleanup plan | 初回整理メモとローカル成果物 ignore。 |
| `9081112` | Update worktree cleanup follow-up | 初回整理後の残状況を記録。 |
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
| `baf1878` | Refresh cleanup follow-up status | レビュー系コード切り出し後の残状況を更新。 |
| `3318687` | Align operations tests with dry-run behavior | ops/dry-run まわりのテスト期待値を現行挙動へ追随。 |
| `f02ada1` | Allow reviewed missing venues to create venues | レビュー済み missing venue から会場を作成できるようにし、テストを追加。 |
| `b83262c` | Improve public glossary song descriptions | 公開 glossary の曲説明生成を改善し、テストを追加。 |
| `d2cd290` | Pass JST date to historical references | daily backfill から historical reference へ JST 日付を渡すテスト付き修正。 |
| `51ed25d` | Rename harvest wording to daily X | weekly harvest 表現を daily X 向けへ整理。 |
| `ad62501` | Point Bonsuke notes to manga assets | Bonsuke 画像メモの参照先を `bonsuke-manga` 側へ更新。 |
| `9b6b8a0` | Ignore local review outputs | ローカル生成レビュー出力と pending mail を ignore。 |

## Current remaining scale

| metric | value |
| --- | ---: |
| tracked changed files | 56 |
| untracked files | 40 |
| tracked diff size | +103,512 / -455,476 |

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
- generated July source URL gap reports
- one-off Notion append note scripts
- review console operation docs
- YouTube morning review launchd/runner files

Action:

- Commit each feature with its scripts, tests, docs, and generated review data as separate units.

### D. Local-only generated outputs

Now ignored by `.gitignore`:

- X news digest review outputs
- rare-signal backcheck outputs
- historical-reference quality review outputs
- YouTube song clip fragment audit outputs
- post-batch maintenance reports
- manual X review outputs
- local pending mail queue

Action:

- Keep these out of normal commits. If one is intentionally needed later, add it explicitly with `git add -f` and document why.

### E. Small tracked doc change

Tracked doc diff remains in:

- `docs/master-rdb-migration-ph0-design.md`

Action:

- This appears to update the workflow concurrency name for `weekly_harvest.yml`. It can be committed separately after confirming the workflow rename is intentional.

## Still not safe for whole-repo deploy

The repository is cleaner than before, but it still contains multiple independent workstreams and large generated diffs.

Current safe stance:

- Commit/deploy only intentionally isolated groups.
- Do not push/deploy the whole worktree.
- Treat remaining public JSON and song/YouTube outputs as review-required.
