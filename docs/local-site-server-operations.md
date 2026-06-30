# Local Site Server Operations

Updated: 2026-06-26 JST
署名: おと（Codex）

## Position

The local site server is a manual development convenience only.
It is not part of the production deploy path.

Do not run it as a login-time LaunchAgent.

## Current Local State

The installed LaunchAgent has been moved out of active launchd discovery:

```text
~/Library/LaunchAgents/com.oto.bon-odori-site.plist.disabled
```

Before disabling, the plist used:

```text
python3 -m http.server 8642 --bind 0.0.0.0
```

That is too broad for a convenience server because it can listen on non-local
interfaces. Manual local preview should bind to localhost instead.

## Manual Runbook

Start a local preview only when needed:

```bash
cd /Users/ryotauchida/bon-odori-site
python3 -m http.server 8642 --bind 127.0.0.1
```

Open:

```text
http://127.0.0.1:8642/
```

Stop it with `Ctrl-C` in the terminal that started it.

## Production Boundary

This local server does not publish production.

Production deploy remains:

1. collector exports public JSON,
2. `bon-odori-site` syncs public data,
3. GitHub Actions deploys to S3 / CloudFront.

Editing or serving local files from `bon-odori-site` does not by itself update
the public website.

## Re-enabling Rule

Do not rename `com.oto.bon-odori-site.plist.disabled` back to `.plist` unless:

- Uchida-san explicitly wants the local preview to start on login,
- the manual/auto inventory is updated first,
- the server binds to `127.0.0.1`, not `0.0.0.0`,
- the local preview is still clearly documented as separate from production deploy.
