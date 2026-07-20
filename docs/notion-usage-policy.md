# Notion Usage Policy

Updated: 2026-06-27 / おと（Codex）

## Current Position

Notion is no longer the operational source of truth for public event data.

The current primary path is:

1. Master RDB: `data/bon_odori_master.sqlite` fetched from the S3 artifact.
2. Public export: `export_public_events.py` writes `data/public/events_public.json`.
3. Public site sync: `bon-odori-site` pulls public JSON from collector and deploys when data changes.
4. Queue storage: DynamoDB tables hold verification and event-candidate queues.

## Allowed Notion Uses

Keep Notion usage only for these explicit cases:

- Legacy read-only reference while validating older migration decisions.
- Human-facing work logs or handoff notes when Uchida-san explicitly asks for them.
- Glossary/song/cost tooling that still has an intentional Notion-backed workflow.
- Manual review workflows that are opt-in and clearly labelled as Notion-backed.
- X/RSS daily collection may read Notion-backed X member/glossary data, but scheduled collection must not write back to Notion by default.
- Personal participation planning may read Notion `参加計画` for manual Google Calendar sync.

Cost tooling boundary:

- Manual fallback `weekly_harvest.yml` runs `sync_weekly_costs.py` in dry-run/report mode by default.
- Writing weekly cost records to Notion requires a manual `workflow_dispatch` run with `sync_weekly_costs_to_notion=true`.

X/RSS collection boundary:

- Scheduled `collect.yml` keeps RSS/X collection, repo JSON updates, and DynamoDB queue writes automatic.
- Legacy Notion log, queue, summary, glossary, and X member score writes require `COLLECT_ALLOW_NOTION_WRITES=true`.
- The workflow input for this is manual-only: `allow_notion_writes=true`.

Legacy Notion queue migration boundary:

- `migrate_notion_queue_to_dynamodb.yml` is manual-only and defaults to dry-run.
- DynamoDB writes require `apply=true` and `confirm=MIGRATE NOTION QUEUE TO DYNAMODB`.
- Do not use this one-off migration as a recurring Notion-to-DynamoDB sync.

Legacy Notion write-back boundary:

- Master RDB -> Notion write-back is frozen by default.
- `sync_master_to_notion.py --apply` requires both
  `--allow-frozen-notion-write` and `--confirm "APPLY RDB TO NOTION"`.
- Other legacy Notion apply scripts must require an explicit confirmation phrase.
- YouTube / retrospective direct Notion apply scripts must require
  `--confirm "APPLY LEGACY YOUTUBE NOTION UPDATES"` when `--apply` is used.
- Legacy Notion repair / registration scripts must require
  `--confirm "APPLY LEGACY NOTION REPAIR"` before Notion writes.
- Master RDB / public JSON one-off apply scripts must remain manual and require
  their explicit confirmation phrase before direct data writes.
- Notion work-log task/page maintenance scripts must require
  `--confirm "APPLY NOTION WORKLOG MAINTENANCE"` when they check todos, update existing blocks, create pages, or alter navigation.
- Do not schedule these write-back scripts.

Google Calendar boundary:

- `sync_gcal.py` is manual-only and defaults to dry-run.
- Google Calendar writes and Notion `GCal同期ID` / `日付` updates require `python3 sync_gcal.py --apply`.
- The local LaunchAgent is disabled and must not be re-enabled without updating the manual/auto inventory first.

Daily harvest review boundary:

- Scheduled song/glossary review queue generation belongs to GitHub Actions `collect.yml`.
- Uchida-san reviews generated queues only when they choose to; queue generation must not imply automatic apply.
- GitHub Actions `weekly_harvest.yml` is a manual fallback only.
- Local `run_manual_glossary_review.py` is a fallback only and requires `--manual`.
- The local glossary weekly plist template is disabled and has no schedule.

Local LaunchAgent boundary:

- `com.koto.*` LaunchAgents are disabled as `.plist.disabled` files.
- Do not use local `こと` jobs for Notion logs, event DB updates, pending mail, or workflow triggers.
- Re-enabling any `com.koto.*` job requires updating the manual/auto inventory first.

## Disallowed Default Uses

New code and scheduled workflows should not:

- Treat Notion event DBs as the source of truth for public events.
- Sync Master RDB changes back to Notion automatically.
- Use Notion queues as the default storage for verification or event candidates.
- Require `NOTION_PAGE_ID` for daily collection or public export.
- Let scheduled `collect.yml` write legacy Notion logs, queues, summaries, glossary entries, or X member score updates without explicit opt-in.
- Run Google Calendar sync as a background Notion write-back job.
- Add a local weekly glossary LaunchAgent schedule that duplicates `collect.yml`.
- Re-enable `com.koto.*` LaunchAgents as hidden Notion/GitHub write paths.
- Wrap legacy Notion write-back scripts in scheduled workflows.
- Schedule YouTube / retrospective direct Notion apply scripts.
- Schedule legacy Notion repair / registration scripts.
- Schedule Master RDB / public JSON one-off apply scripts.
- Schedule Notion work-log / task-page maintenance scripts.

## Environment Boundary

- `NOTION_API_TOKEN` may remain available for explicit legacy/glossary/cost flows.
- `NOTION_PAGE_ID` is not part of normal daily collection.
- `BON_ODORI_PUBLIC_SOURCE=notion` is a manual fallback only; default public export is `master_rdb`.
- `QUEUE_STORAGE_MODE` and `EVENT_QUEUE_STORAGE_MODE` default to `dynamodb`.
- `COLLECT_ALLOW_NOTION_WRITES` defaults to false; set true only for an explicit manual legacy Notion run.

## Cleanup Rule

When touching old scripts or docs, update wording from "Notion正本" to one of:

- "Master RDB primary"
- "legacy Notion snapshot"
- "manual Notion-backed review flow"

Do not delete old migration scripts solely because they mention Notion. First classify whether they are archived history, read-only reference, or an active opt-in workflow.
