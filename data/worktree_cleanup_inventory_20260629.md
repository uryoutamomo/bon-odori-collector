# Worktree cleanup inventory

- generated_at: 2026-06-29
- generated_by: おと（Codex）
- scope: current dirty worktree triage; no destructive cleanup performed

## Summary

The repository is not in a bad state, but it is not a single deployable change. It contains several independent workstreams plus generated data.

## Progress on 2026-06-29

Completed non-destructive cleanup:

- Committed group A as `a542488 Fill missing event source URLs`.
- Reviewed group B in `data/public_json_diff_review_20260629.md`; public event URL additions look narrow, but song/public generated JSON churn is still mixed in, so it is not approved for broad deploy as-is.
- Committed group C as `9910a4b Add local review console` after unit, syntax, and browser GET smoke checks.
- Marked local operational artifacts as ignored:
  - `data/review_console/`
  - `data/automation/`
  - `assets/character/originals/`

No deploy or push was performed.

| metric | value |
| --- | ---: |
| `git status --short` entries | 315 |
| tracked changed files | 161 |
| untracked files | 323 |
| tracked diff size | +106,392 / -455,916 |
| `data/` size on disk | 3.0G |
| `assets/` size on disk | 32M |

## Current safety checks

| check | result | note |
| --- | --- | --- |
| `python3 guard_public_events_sync.py` | pass | No blocking public event sync diff. This is not a deploy approval. |
| `python3 audit_master_rdb.py` | medium issue: `source_snapshot_drift` | Source snapshot differs from the master DB build manifest. Not caused by the URL cleanup alone, but it means DB lineage should be handled carefully. |
| `event_occurrences.source_url` missing | 0 | Filled in prior URL cleanup. |
| `event_series.source_url` missing | 0 | Filled by series source URL inheritance. |

## Recommended commit groups

### A. URL source cleanup

Status: completed in commit `a542488 Fill missing event source URLs`.

Files:

- `review_missing_source_urls.py`
- `apply_series_source_url_inheritance.py`
- `data/missing_source_url_review.json`
- `data/missing_source_url_review.md`
- `data/reviewed_missing_source_urls_apply_report.json`
- `data/reviewed_missing_source_urls_apply_report.md`
- `data/series_source_url_inheritance_apply_report.json`
- `data/series_source_url_inheritance_apply_report.md`
- `data/additional_event_url_research_20260629.json`
- `data/additional_event_url_research_20260629.md`

Verification already run:

- `python3 -m py_compile review_missing_source_urls.py apply_reviewed_missing_source_urls.py`
- `python3 -m py_compile apply_series_source_url_inheritance.py`
- `python3 -m unittest tests.test_source_url_scope tests.test_apply_reviewed_missing_source_urls`

Risk:

- Low for local DB/source review workflow.
- Does not by itself publish the newly researched public URL candidates to the site.

### B. Public site generated data

Status: deploy-sensitive. Keep separate from all other work. Reviewed in `data/public_json_diff_review_20260629.md`.

Files currently changed:

- `data/public/events_public.js`
- `data/public/event_song_occurrences_public.json`
- `data/public/event_songs_public.json`
- `data/public_events_sync_guard.json`
- `data/public_events_sync_guard.md`
- plus related public postprocessor scripts:
  - `apply_public_event_name_cleanup.py`
  - `apply_public_official_source_urls.py`

Observed `events_public.js` changes:

- Adds official URL for `みたままつり 納涼民踊のつどい`.
- Adds official URL for `佐竹ゲバゲバ盆踊り`.
- Adds official URL for `品川区民まつり 品川第二地区`.

Risk:

- Medium. Guard passes, but public deploy should still be a separate approval.
- Do not mix with management console or generated YouTube/song data.

### C. Review/admin console

Status: completed in commit `9910a4b Add local review console`.

Files/directories:

- `review_console/`
- `run_review_console.py`
- `apply_review_console_decisions.py`
- `docs/review-console-operations.md`
- `docs/admin-console-design.md`
- tests such as `tests/test_review_console.py`

Risk:

- Medium. It is local tooling, not direct public deploy, but it writes decisions under `data/review_console/`.
- `data/review_console/decisions.json`, `decision_history.json`, and exported decisions are treated as local operational state and ignored.

Verification run:

- `python3 -m unittest tests.test_review_console`
- `python3 -m py_compile run_review_console.py apply_review_console_decisions.py review_console/data.py review_console/server.py`
- `node --check review_console/static/app.js`
- browser GET smoke test at `http://127.0.0.1:8751/`

### D. GitHub Actions and automation operations

Status: separate infra/ops change.

Examples:

- `.github/workflows/collect.yml`
- `.github/workflows/weekly_harvest.yml`
- `.github/workflows/youtube_daily_backfill.yml`
- `.github/workflows/bootstrap_master_rdb_s3.yml`
- `.github/workflows/verify_master_rdb_s3.yml`
- `ops/com.ryotauchida.bon-odori.youtube-daily.plist`
- `ops/com.ryotauchida.bon-odori.glossary-weekly.plist`

Risk:

- High compared with report/data changes. These can affect scheduled or CI behavior.
- Commit separately with workflow-focused tests/review.

### E. YouTube/song/glossary generated data

Status: large generated data churn. Keep out of broad commits unless the exact generation run is intended.

Largest tracked diffs:

| file | added | deleted |
| --- | ---: | ---: |
| `data/song_prediction_snapshots.json` | 56,470 | 56,489 |
| `data/youtube_setlist_occurrences.json` | 35,041 | 31,209 |
| `data/youtube_active_video_review.json` | 2,202 | 359,549 |
| `data/public_historical_reference_dry_run.json` | 3,016 | 248 |
| `data/public_season_hint_dry_run.json` | 1,742 | 552 |
| `data/voices.json` | 1,024 | 70 |
| `data/song_occurrences.json` | 887 | 733 |
| `data/youtube_channels.json` | 676 | 328 |

Risk:

- High review cost.
- Likely generated outputs from separate batch jobs. They should be regenerated, validated, and committed independently if they are intentional.

### F. Documentation and operations manuals

Status: likely coherent but spans many topics. Split by topic.

Examples:

- `docs/notion-usage-policy.md`
- `docs/youtube-daily-operations.md`
- `docs/public-json-postprocessor-operations.md`
- `docs/master-rdb-public-json-one-off-operations.md`
- `docs/manual-auto-operations-inventory.md`
- `append_manual_auto_*`

Risk:

- Low direct runtime risk, but high confusion if mixed with code/data deploy commits.

### G. Character/image assets

Status: split between curated generated assets and ignored raw browser exports.

Observed:

- `assets/character/generated/` has 5 files.
- `assets/character/originals/` has about 150 files, including a saved ChatGPT web page, CSS, HTML, and many thumbnails/webp files.

Risk:

- Medium. Generated images may be useful, but saved browser-page support files are usually not good repo artifacts.
- Keep curated final assets under `assets/character/generated/` visible as a future commit candidate.
- Ignore raw browser export files under `assets/character/originals/`.

### H. Local automation/log outputs

Status: likely local run artifacts. `data/automation/` is ignored.

Examples:

- `data/automation/*`
- `data/post_batch_maintenance_report.*`
- `data/pending_mail.json`
- various one-off review queues/reports

Risk:

- Usually not deployable source. Commit only if they are intended audit artifacts.

## Cleanup order

1. Done: commit group A URL source cleanup.
2. Done: review group B public JSON diff; do not deploy broad generated JSON yet.
3. Done: verify and commit group C local review/admin console.
4. Handle group D workflows separately with CI/ops review.
5. Decide policy for groups E, G, and H: commit as audit artifacts, regenerate, ignore, or move out of repo.

## Non-destructive next commands

These commands are safe to inspect staging groups, but do not run them blindly as final staging without review.

```sh
git status --short review_missing_source_urls.py apply_series_source_url_inheritance.py data/missing_source_url_review.json data/missing_source_url_review.md data/reviewed_missing_source_urls_apply_report.json data/reviewed_missing_source_urls_apply_report.md data/series_source_url_inheritance_apply_report.json data/series_source_url_inheritance_apply_report.md data/additional_event_url_research_20260629.json data/additional_event_url_research_20260629.md
git status --short data/public data/public_events_sync_guard.json data/public_events_sync_guard.md
git status --short review_console run_review_console.py apply_review_console_decisions.py data/review_console docs/review-console-operations.md docs/admin-console-design.md
```

## Open decisions

- Should large generated JSON snapshots under `data/` be committed, or regenerated in CI/batch jobs?
- Should public JSON official URL updates be deployed separately now, or wait until URL candidates from `additional_event_url_research_20260629` are reviewed and applied?
