# Koto LaunchAgents Operations

Updated: 2026-06-26 JST  
署名: おと（Codex）

## Position

`com.koto.*` LaunchAgents are stopped and disabled.

Uchida-san confirmed on 2026-06-26 that `こと` should not be started now.
Therefore the local launchd files are kept only as historical/manual reference.

## Current Local State

All koto LaunchAgents in `~/Library/LaunchAgents` have been moved to
`.plist.disabled`:

```text
~/Library/LaunchAgents/com.koto.bon-odori-breaking-news.plist.disabled
~/Library/LaunchAgents/com.koto.bon-odori-calendar-sync.plist.disabled
~/Library/LaunchAgents/com.koto.bon-odori-evening-news.plist.disabled
~/Library/LaunchAgents/com.koto.bon-odori-home-venue-watch.plist.disabled
~/Library/LaunchAgents/com.koto.bon-odori-watchdog.plist.disabled
```

`launchctl list <label>` returned unloaded for the checked labels before
renaming.

## Why Disabled

These jobs can write or trigger writes outside the current GitHub Actions
control plane:

- `breaking-news`: can create `pending_mail.json`, push Git, and write Notion logs.
- `evening-news`: can create weekly mail, push Git, and write Notion logs.
- `home-venue-watch`: can inspect/update Notion event data.
- `calendar-sync`: can write Google Calendar and Notion sync metadata.
- `watchdog`: can trigger the mail workflow outside the GitHub scheduled watchdog.

The project now keeps scheduled automation in GitHub Actions wherever possible.
Local launchd jobs are not visible to Actions concurrency, summaries, or guards.

## Relationship To Current Automation

Use these current owners instead:

- Mail sending: `send_mail.yml` and `send_mail_watchdog.yml`.
- Google Calendar sync: manual `python3 sync_gcal.py --apply` only.
- Song/glossary review queue generation: daily `collect.yml`; `weekly_harvest.yml` is manual fallback only.
- YouTube daily backfill: `youtube_daily_backfill.yml`.
- Public site sync/deploy: `bon-odori-site` workflows.

## Re-enabling Rule

Do not rename any `.plist.disabled` file back to `.plist` unless all are true:

- Uchida-san explicitly asks to restart that local job.
- The manual/auto inventory is updated first.
- The replacement GitHub Actions path is either intentionally disabled or judged insufficient.
- The command's write targets are listed: repo, Notion, Google Calendar, mail, or workflow trigger.
- A rollback step is written down before bootstrap.

Prefer creating a manual runbook over re-enabling launchd.
