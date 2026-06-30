# Worktree cleanup follow-up

- generated_at: 2026-06-30
- generated_by: おと（Codex）
- scope: post-cleanup status after splitting URL, review console, operation-boundary, character-asset, review-tooling, test/code fixes, and local-output ignore commits
- deploy_performed: false
- push_performed: false

## Completed cleanup commits

### 2026-06-30 deploy cleanup continuation

| repo | commit | summary | note |
| --- | --- | --- | --- |
| `bon-odori-site` | `6d7ccf0` | Ignore local public deploy guard reports | site local was fast-forwarded to `origin/main` first; no push/deploy performed. |
| `bon-odori-collector` | `8922222` | Ignore one-off YouTube morning review artifacts | 2026-06-29専用の朝レビュー起動ファイルをローカル生成物として扱う。 |
| `bon-odori-collector` | `f12b824` | Add review console batch decision helpers | レビューコンソール用の一括一次判断helperを追加。既定URLは `http://127.0.0.1:8751` に修正し、`--base-url` で上書き可能。 |
| `bon-odori-collector` | `b671fec` | Add publication gap review builder | 採用済みデータと公開siteデータのズレを `data/publication_gap_review.json` に出すローカル分析ツール。出力JSONはignore済み。 |
| `bon-odori-collector` | `3bab84c` | Add manual Notion maintenance helpers | 未追跡のNotion追記/手動メンテ系スクリプトを保存。DB更新/ページ作成系2本には確認文字列を追加。 |
| `bon-odori-collector` | `c2f3f26` | Update glossary review wording for daily X flow | 生成データと独立した文言修正を切り出し。 |
| `bon-odori-collector` | `b3d4ab4` | Refresh missing venue review dry-run | missing occurrence venue review と dry-run apply report を再生成・保存。production apply は未実行。 |
| `bon-odori-collector` | `10d46be` | Refresh evidence RDB summary | evidence RDB summary を現行入力から再生成。SQLite本体はignore対象のローカル成果物。 |

Additional checks:

- `bon-odori-site`: `python3 -m pytest -q tests/test_guard_public_deploy.py tests/test_public_sync_deploy_policy.py` -> 6 passed.
- `bon-odori-collector`: `python3 -m py_compile review_current_date_batch.py review_source_url_batch.py review_venue_batch.py` -> OK.
- `bon-odori-collector`: `python3 build_publication_gap_review.py` -> rows=152.
- `bon-odori-collector`: Notion append / planning scripts were syntax-checked and committed, but not run. `fill_glossary_readings.py --apply` and `create_regional_seo_illustrated_list_plan_notion.py --apply` now require explicit `--confirm`.
- `bon-odori-collector`: `python3 -m unittest tests.test_apply_reviewed_missing_occurrence_venues` -> OK.
- `bon-odori-collector`: `python3 -m unittest tests.test_build_evidence_rdb` -> OK.

Current safe stance remains unchanged:

- Do not push/deploy the whole collector worktree.
- Public deploy remains already handled by `bon-odori-site` Actions; local collector dirty state is not automatically part of production.
- Remaining generated data diffs need review or regeneration from approved paths before commit.
- Timestamp-only diffs in event occurrence derived JSON/MD were removed from the dirty set as cleanup noise.

### Earlier cleanup commits

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
| `fe40ca4` | Refresh cleanup follow-up after ignores | ignore 整理後の残状況を記録。 |
| `2b7adda` | Update master RDB workflow reference | 設計docの workflow 名を現行 `weekly_harvest.yml` に合わせて更新。 |
| `5b059f4` | Refresh cleanup follow-up after doc split | doc切り出し後の残状況を記録。 |
| `ef5434c` | Document review console and X collection operations | レビューコンソール次アクション設計と X/RSS 収集運用境界を追加。 |
| `30b5a10` | Add public official source URLs | `events_public.json` と `.js` を揃え、34件の公開ソースURLを反映。 |
| `c7cafb4` | Add July official source promotion reports | July公式URL昇格スクリプト、dry-run現状レポート、ギャップレポートを追加。 |
| `7f63f18` | Refresh cleanup follow-up after URL splits | URL切り出し後の残状況を更新。 |
| `b3cf298` | Switch public song occurrences to master RDB export | 公開曲 occurrence を SQLite/Master RDB 由来に切替え、表記ゆれ重複2件を折り畳み。 |
| `a2e1475` | Update freeze release wording | freeze解除提案docの weekly 表現をレビューキュー一般へ更新。 |
| `0870464` | Refresh cleanup follow-up after song split | 公開曲 occurrence 切り出し後の残状況を更新。 |
| `1415da5` | Refresh public events sync guard | 公開イベント同期guardを再実行し、pass状態を保存。 |
| `f0ec170` | Add public glossary supplement notes | 公開glossary補足語42件と曲本文メモ51件を追加。 |
| `df740b3` | Align harvest review labels with daily X flow | 週次収穫レビュー生成物の表示文言を日次X収穫へ統一。 |
| `7eae4b9` | Record X candidate review decisions | X候補30件の内田さんレビュー判断を保存。 |
| `feffed0` | Preserve official source review decisions | 公式ソース候補の再生成時に既存レビュー判定を保持し、51件保持・新規pending 1件の状態へ修復。 |
| `a196275` | Record YouTube backfill evidence batch | YouTube evidence/active review/RDB summary/backfill report を切り出し、active review の既定出力を全件側へ修正。 |

## Current remaining scale

| metric | value |
| --- | ---: |
| tracked changed files | 10 |
| untracked files | 0 |
| tracked diff size | +62,226 / -58,105 |

## Public JSON status

The event URL mismatch, public song-occurrence switch, and public event sync guard are resolved, but do not deploy the remaining generated data diff as-is.

Observed state:

- `data/public/events_public.json` and `data/public/events_public.js` are aligned after `30b5a10`.
- `python3 apply_public_official_source_urls.py --dry-run` now reports `updated: 0` and `added_urls: 0`.
- The URL-only public event update added 34 source URLs across 33 public events.
- `data/public/event_song_occurrences_public.json` is now generated by `export_master_rdb_song_occurrences.py` after `b3cf298`.
- `data/public/event_songs_public.json` has no remaining diff.
- `data/public/event_song_occurrences_public.json` now has 1856 occurrences and 28105 song rows, matching the existing production preview except for `generated_at`.
- `data/public_events_sync_guard.json` / `.md` now report `status=pass` after `1415da5`.
- `data/public_glossary_supplements.json` and `data/public_song_content_notes.json` are saved after `f0ec170`.

Risk:

- The former JS-only URL mismatch is gone.
- The former public song occurrence blocker is gone.
- The former public event sync guard blocker is gone.
- The remaining deploy blockers are now non-song public dry-run files plus broader YouTube/ops generated outputs.

Recommended next split:

1. Review non-song public dry-run files (historical reference dry-run, season hint dry-run).
2. Keep old song generation files frozen unless explicitly regenerated from the approved path.
3. Keep YouTube-derived ops metrics separate from frozen song/public dry-run state.

## Remaining groups

### A. Public/generated data

Files include:

- `data/public_historical_reference_dry_run.json`
- `data/public_season_hint_dry_run.json`

Action:

- Keep separate from deploy until regenerated and reviewed.
- `data/public_events_sync_guard.*` has already been split and is no longer part of this remaining group.

### B. Song/ops generated data

Largest files/diffs still include:

- `data/song_occurrences.json`
- `data/song_prediction_snapshots.json`
- `data/ops_metrics_*`

Action:

- Treat as a batch output. `legacy_song_occurrence_generation` is still frozen, so do not commit `data/song_occurrences.json` or `data/song_prediction_snapshots.json` from the old generation path.
- YouTube evidence/backfill outputs were split in `a196275`.
- `data/evidence_rdb_summary.json` was refreshed and split in `10d46be`.
- Keep ops metrics out until the remaining frozen song/public dry-run state is either reverted, regenerated from approved paths, or explicitly accepted.

2026-06-30 status:

- `data/song_occurrences.json` and `data/song_prediction_snapshots.json` still account for most of the remaining diff and remain non-committable under the freeze policy.
- `data/ops_metrics_*` reflects local generated state and should wait until the frozen song/public dry-run state is resolved.
- `data/evidence_rdb_summary.json` is no longer part of the dirty set.

### E. Remaining generated-data groups after Notion cleanup

| group | files | current action |
| --- | --- | --- |
| Master RDB lineage/audit | `data/bon_odori_master_manifest.json`, `data/master_rdb_audit.json`, `data/master_rdb_audit.md` | Hold. These refer to local DB/source checksum drift and should not be pushed without the matching RDB artifact/cutover decision. |
| Public postprocessor dry-runs | `data/public_historical_reference_dry_run.json`, `data/public_season_hint_dry_run.json` | Hold pending public data review. Do not treat as deploy approval. |
| Ops metrics | `data/ops_metrics_dashboard.html`, `data/ops_metrics_history.jsonl`, `data/ops_metrics_latest.md` | Hold until upstream generated state is accepted or reset. |
| Frozen legacy song outputs | `data/song_occurrences.json`, `data/song_prediction_snapshots.json` | Do not commit unless Ph2/Ph3 explicitly reopens the legacy path. |

Resolved in this continuation:

- `data/missing_occurrence_venue_review.*` and `data/reviewed_missing_occurrence_venues_apply_report.*` were split in `b3d4ab4`; this is still dry-run evidence only.
- `data/evidence_rdb_summary.json` was split in `10d46be` after `tests.test_build_evidence_rdb` passed.

### C. Review/research feature workstreams

Untracked groups are now cleared.

Recent resolution:

- Event time / source / venue review batch helpers are committed in `f12b824`.
- One-off Notion append / manual maintenance helpers are committed in `3bab84c`.
- YouTube morning review launchd/runner files are ignored as one-off local artifacts by `8922222`.

Tracked review state also remains for:

- `data/ops_metrics_*` (current numbers depend on uncommitted YouTube outputs)
- Master RDB audit/manifest outputs (current numbers depend on local DB state and frozen song inputs)

Resolved tracked review state:

- `data/official_source_review_candidates.*` was repaired in `feffed0`; regenerated rows now preserve existing decisions by id/key and leave only the new 自由が丘 candidate as `pending`.

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

## Still not safe for whole-repo deploy

The repository is cleaner than before, but it still contains multiple independent workstreams and large generated diffs.

Current safe stance:

- Commit/deploy only intentionally isolated groups.
- Do not push/deploy the whole worktree.
- Treat remaining generated public guard files and YouTube/ops outputs as review-required.
