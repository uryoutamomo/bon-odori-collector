# Public JSON diff review

- generated_at: 2026-06-29
- generated_by: おと（Codex）
- scope: review current public JSON diffs before cleanup/deploy
- deploy_performed: false
- commit_performed_for_public_json: false

## Checks

| check | result |
| --- | --- |
| `python3 guard_public_events_sync.py` | pass |
| public event collector/site count | 183 / 183 |
| blocking public event diffs | 0 |

## Files currently changed

| file | status | review |
| --- | --- | --- |
| `data/public/events_public.js` | changed | Small event-source diff: 3 official URL additions. |
| `data/public/event_songs_public.json` | changed | Generated song/public data diff; not reviewed as part of URL cleanup. |
| `data/public/event_song_occurrences_public.json` | changed | Generated song occurrence diff; includes song/event row removals and timestamp change. |
| `data/public_events_sync_guard.json` | changed | Guard report refreshed. |
| `data/public_events_sync_guard.md` | changed | Guard report refreshed. |
| `apply_public_event_name_cleanup.py` | changed | Adds manual confirmation guard for public JSON one-off writes. |
| `apply_public_official_source_urls.py` | changed | Adds manual confirmation guard for public JSON one-off writes. |

## Observed `events_public.js` change

The direct event JSON diff appears limited to official source URL additions:

- `みたままつり 納涼民踊のつどい`: `https://www.yasukuni.or.jp/schedule/saiji.html#saiji03`
- `佐竹ゲバゲバ盆踊り`: `https://satakeshotengai.com/satakeodori/`
- `品川区民まつり 品川第二地区`: `https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html`

## Risk assessment

- Public event sync guard passes, so there is no known blocking event-list mismatch.
- However, public song files also changed:
  - `data/public/event_song_occurrences_public.json`: +296 / -255
  - `data/public/event_songs_public.json`: +43 / -37
- These song/public generated changes are not part of the URL-source cleanup and should not be bundled into a URL/public-source commit without a separate song export review.

## Recommendation

Do not deploy or commit the whole current public JSON diff as-is.

Safe next split:

1. If the goal is only official source URL additions, isolate `events_public.js` plus its true source JSON/postprocessor inputs and regenerate cleanly.
2. If the goal is to publish song export updates, review the song occurrence diff separately using the existing master RDB public song export reports.
3. Keep `apply_public_*` confirmation guard changes in an operations-safety commit, separate from generated public JSON.
