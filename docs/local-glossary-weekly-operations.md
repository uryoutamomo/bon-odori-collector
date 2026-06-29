# Local Song/Glossary Harvest Fallback Operations

Updated: 2026-06-27 JST  
署名: おと（Codex）

## Position

Song/glossary harvesting is now part of the daily `collect.yml` flow.
The old weekly workflow and local runner are manual fallbacks only.

Automatic:

- GitHub Actions `collect.yml` daily collector.
- X/RSS event reading plus song/glossary/co-occurrence candidate extraction.
- Review queue generation and UI generation for daily X harvest.

Manual only:

- GitHub Actions `weekly_harvest.yml`, now workflow_dispatch only.
- Local `run_weekly_glossary_review.py`.
- Human review of generated song/glossary queues, whenever Uchida-san chooses.
- Applying reviewed song/glossary decisions.
- Writing weekly cost rows to Notion.

## Local Runner

The local runner now requires an explicit manual flag:

```bash
python3 run_weekly_glossary_review.py --manual --days 3
```

Without `--manual`, it exits before running the generation commands.

This protects the worktree from accidental LaunchAgent execution. The local
script writes review artifacts under `data/`, so running it in the background
can create unreviewed local diffs that GitHub Actions cannot see.

## LaunchAgent Template

The repo keeps a plist template for emergency local use:

```text
ops/com.ryotauchida.bon-odori.glossary-weekly.plist
```

It is deliberately not a schedule:

- `Disabled` is true.
- `StartCalendarInterval` is absent.
- Program arguments include `--manual`.

Do not copy it to `~/Library/LaunchAgents` as a recurring job.

## When To Use The Local Runner

Use it only when the daily collector is unavailable and Uchida-san wants a
local review UI immediately.

Normal manual check:

```bash
python3 run_weekly_glossary_review.py --manual --days 3
```

Outputs:

- `data/weekly_glossary_review_run.json`
- `data/weekly_glossary_review_run.md`
- `data/weekly_harvest_candidates.json`
- `data/weekly_harvest_review_candidates.json`
- `data/weekly_harvest_review_ui.html`
- `data/weekly_song_candidates_review.json`
- `data/weekly_song_candidates_review_ui.html`

## Apply Boundary

The daily collector and local fallback only prepare review artifacts.
It must not be extended to apply reviewed decisions automatically.
Review timing is intentionally manual and opportunistic; a generated queue can
wait until Uchida-san chooses to review it.

Use the manual fallback workflow inputs or local apply commands for apply flows:

- `apply_reviewed=true` for reviewed song/glossary decisions.
- `apply_dry_run=false` only after reviewing the generated apply result.
- `sync_weekly_costs_to_notion=true` only when intentionally writing cost rows.

## Re-enabling Rule

Do not add a separate weekly schedule unless all of these are true:

- Daily collector song/glossary harvest is intentionally disabled.
- The manual/auto inventory is updated first.
- The LaunchAgent has a clear owner and logging path.
- There is a reason local dirty data artifacts are acceptable.
