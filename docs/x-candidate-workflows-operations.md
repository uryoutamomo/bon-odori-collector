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

## Decision (2026-06-26, superseded 2026-07-26)

元の判断: Keep these workflows manual.

Reasons:

- Follow graph and candidate post review can consume paid X API quota faster
  than the bounded daily collector.
- Social graph is a discovery hint only. Promotion still needs post-quality
  review.
- Notion member registration is a legacy write path and should remain
  operator-approved.
- Daily `collect.yml` already covers bounded X/RSS collection with budget
  controls.

## Decision (2026-07-26)

週次スケジュールを追加する。手動 `workflow_dispatch` は確認文字列つきのまま残す。

理由と経緯:

- 手動専用のまま誰も起動せず、`discover_x_social_graph` は 2026-06-06、
  `review_x_candidate_posts` は 2026-06-09 を最後に止まっていた。その結果、収集対象の
  名簿が6月上旬の69アカウントで固定され、新しい盆踊ラーを発見できなくなっていた
  （2026-07-26 内田さん指摘「そもそもXでの重要盆オドラーが把握できていない」）。
- 上の「Automation Boundary」が定めた昇格条件を満たしたうえで移行する:
  - 予算上限: `collection_support/x_budget_guard.py` を両スクリプトに追加。日次収集と
    同じ `data/x_budget.json` を見て上限で停止し、使った分も同じ帳簿へ記録する。
    「日次収集と違って止まらない」という手動維持の主因を解消した。
  - Notion書き込みは既定オフ: sync ステップは `inputs.sync_only` が真のときだけ動く。
    `inputs` の無いスケジュール実行では動かない。
  - レビュー専用の成果物のみ生成する（この点は元から変わらない）。
  - `docs/manual-auto-operations-inventory.md` を更新。
  - `tests/test_x_candidate_workflows_policy.py` に予算ガードとNotion非同期のテストを追加。
- 昇格（Notionメンバーリストへの登録）は引き続き内田さんの承認が要る。スケジュール実行が
  増やすのは「候補と評価」だけで、収集対象そのものは
  `x_queries.json` の `auto_trusted_roster`（スコア基準・上限つき）が決める。

| Workflow | Schedule |
| --- | --- |
| `discover_x_social_graph.yml` | 毎週火曜 6:00 JST (`0 21 * * 1`) |
| `review_x_candidate_posts.yml` | 毎週火曜 6:30 JST (`30 21 * * 1`) |

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

Do not add `push` triggers to these workflows.

`schedule` は 2026-07-26 に、下の条件を全て満たしたうえで追加した（上の Decision 参照）。
条件は今後も維持する。スケジュール実行の内容を広げるときは、同じ条件を再確認すること:

- a separate budget cap（`collection_support/x_budget_guard.py`）,
- keep Notion writes off by default,
- produce review-only artifacts,
- update `docs/manual-auto-operations-inventory.md`,
- add tests proving scheduled defaults do not spend unbounded quota or write to
  Notion.
