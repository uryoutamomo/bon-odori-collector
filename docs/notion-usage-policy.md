# Notion Usage Policy

Updated: 2026-06-23 / おと（Codex）

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

## Disallowed Default Uses

New code and scheduled workflows should not:

- Treat Notion event DBs as the source of truth for public events.
- Sync Master RDB changes back to Notion automatically.
- Use Notion queues as the default storage for verification or event candidates.
- Require `NOTION_PAGE_ID` for daily collection or public export.

## Environment Boundary

- `NOTION_API_TOKEN` may remain available for explicit legacy/glossary/cost flows.
- `NOTION_PAGE_ID` is not part of normal daily collection.
- `BON_ODORI_PUBLIC_SOURCE=notion` is a manual fallback only; default public export is `master_rdb`.
- `QUEUE_STORAGE_MODE` and `EVENT_QUEUE_STORAGE_MODE` default to `dynamodb`.

## Cleanup Rule

When touching old scripts or docs, update wording from "Notion正本" to one of:

- "Master RDB primary"
- "legacy Notion snapshot"
- "manual Notion-backed review flow"

Do not delete old migration scripts solely because they mention Notion. First classify whether they are archived history, read-only reference, or an active opt-in workflow.
