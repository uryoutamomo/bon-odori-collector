# X Candidate Workflows Operations

作成日: 2026-06-26 JST  
署名: おと（Codex）

## Purpose

X candidate / social graph workflows are manual discovery tools.

They are not part of the daily collector. They either spend X API quota or write
approved accounts into the legacy Notion X member list.

## Workflows

| Workflow | Mode | Writes | External cost | Confirmation |
| --- | --- | --- | --- | --- |
| `discover_x_social_graph.yml` | follow graph discovery | `data/x_social_graph.json`, `data/x_candidate_accounts.json` | X API | `DISCOVER X SOCIAL GRAPH` |
| `review_x_candidate_posts.yml` | recent post review | `data/x_candidate_post_review.json` | X API | `REVIEW X CANDIDATES` |
| `review_x_candidate_posts.yml` with `sync_only=true` | approved member sync | Notion X member list, `data/x_candidate_post_review.json` sync summary | no X API | `SYNC APPROVED X MEMBERS` |

## Decision

Keep these workflows manual.

Reasons:

- Follow graph and candidate post review can consume paid X API quota faster
  than the bounded daily collector.
- Social graph is a discovery hint only. Promotion still needs post-quality
  review.
- Notion member registration is a legacy write path and should remain
  operator-approved.
- Daily `collect.yml` already covers bounded X/RSS collection with budget
  controls.

## Flow

```mermaid
flowchart TD
  operator[Manual workflow_dispatch] --> choice{workflow}
  choice --> graph[discover_x_social_graph]
  graph --> xapi1[X API followings]
  xapi1 --> candidates[x_candidate_accounts.json]

  choice --> review[review_x_candidate_posts]
  review --> xapi2[X API recent posts]
  xapi2 --> review_json[x_candidate_post_review.json]
  review_json --> approval[Uchida-san chooses 情報源にする in review console]
  approval --> sync[sync_only=true]
  sync --> notion[legacy Notion X member list]
```

## Notion Boundary

`sync_only=true` is the only mode that writes to Notion.

It should be used only after `data/x_candidate_post_review.json` contains
explicit user approval on promote rows:

- `user_approved=true`, or
- `approved_by_user=true`, or
- `registration_decision` set to an approval word such as `登録` or `承認`.

The review console now writes `registration_decision` directly for X/RSS
candidate accounts:

- `情報源にする` -> `登録`
- `様子を見る` -> `監視`
- `対象外` -> `不採用`
- `後で見る` -> `保留`

X/RSS account decisions do not use the console export/stage path.

## Automation Boundary

Do not add `schedule` or `push` triggers to these workflows.

If a future change wants a scheduled X candidate discovery path, it must first:

- add a separate budget cap,
- keep Notion writes off by default,
- produce review-only artifacts,
- update `docs/manual-auto-operations-inventory.md`,
- add tests proving scheduled defaults do not spend unbounded quota or write to
  Notion.
