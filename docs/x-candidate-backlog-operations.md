# X候補バックログと日次レビュー運用

作成日: 2026-08-18 JST
署名: おと（Codex）

## 目的

Xで取得済みの新規イベント・日付更新候補を、日次上限の外側で失わず、開催日が近い順に
Review Inboxへ運ぶ。内田さんがイベント名を思い出して質問したときだけ候補が発見される状態をなくす。

## 日次の流れ

```text
voices.json
  → build_x_gap_candidates.py（当日の表示用30件＋上限超過）
  → x_candidate_backlog.py merge（全件を永続台帳へ合流）
  → x_gap_adapter.py --backlog ... --daily-limit 5（部分コホート）
  → run_review_inbox_x_gap_scheduled.py（CASでReview Inboxへ）
  → 成功した5件だけ「処理中」
```

正本は `data/x_candidate_backlog.json`。`data/x_gap_candidates.json` は当日の機械抽出結果であり、
候補のライフサイクルを持たない。Review Inboxの書き込みが失敗した場合、台帳は `未処理` のままなので
翌日に再選出される。

投稿本文に区名がなくても、`data/blog_venue_rows.json` の既知会場名と一致し、同じ行の住所が
東京23区を示す場合は地域根拠として使う。これにより京華スクエアのような告知も候補になる。
同じ既知会場・初日の複数投稿は一候補へ束ね、ポスターURLと全投稿URLを残す。

状態は4つだけにする。

| 状態 | 意味 |
|---|---|
| `unprocessed` / 未処理 | Review Inboxへまだ正常投入されていない |
| `in_progress` / 処理中 | CAS済みのReview Inbox項目としてレビュー中 |
| `registered` / 登録済み | 根拠つきの明示transitionで正本反映を確認した |
| `rejected` / 却下 | 根拠つきの明示transitionで対象外と確定した |

terminal状態を再開するときは `--reopen` と新しい根拠を必須にする。日次生成が勝手に状態を戻さない。

## 信頼度別の目標動作

台帳は各候補に `confidence.target_action` を記録する。

| 条件 | 目標動作 |
|---|---|
| 既存開催回＋登録済み公式X | 既存開催回の自動更新候補 |
| 新規イベント＋登録済み公式X | 重複検査後の自動登録候補 |
| 主催者入りポスター＋独立2根拠以上 | 重複検査後の自動登録候補 |
| 個人投稿1件だけ | 根拠待ち |
| 日付衝突・中止変更・同名近隣候補 | 内田さん確認 |

最初の5件/日は精度測定用canaryなので、全候補に
`execution_mode=daily_canary_review_only` / `automatic_publication_enabled=false` を付ける。
Review Inbox投入だけではMaster RDBや公開JSONを変更しない。重複率・誤分類率を確認してから、
目標動作ごとの自動反映を別gateで有効にする。

## 日次アラート

`x_candidate_backlog.py merge` はJSONとMarkdownのアラートを作り、GitHub Actions summaryへ追記する。

- 開催7日以内なのに `未処理` / `処理中`
- 高信頼候補が初回検出から24時間以上 `未処理` / `処理中`
- 当日の `archived_candidates` が永続台帳へ持ち越されていない

3つ目は台帳の取りこぼしなのでworkflowを失敗させる。前2つは運用上の滞留であり、候補を消さず警告として残す。

## GitHub Actions gate

workflow配線はdefault offで、次のrepository variableを `true` にしたときだけS3上のMaster RDBへ
Review Inbox行をCAS追加する。

```text
REVIEW_INBOX_X_GAP_DUAL_WRITE_ENABLED=true
```

runner内部では `REVIEW_INBOX_DUAL_WRITE_MODE=cohort`、reader `inbox`、legacy writer `false` の
組を要求する。5件は完全スナップショットではないため、`bulk/all` へ変更しない。

## 定期実行するおとのプロンプト

ChatGPT desktopのScheduled taskはローカルプロジェクトまたは隔離worktreeで動かせる。
ローカルファイルが必要な実行ではMacを起動し、ChatGPTアプリを動かしておく必要がある。
管理画面はCLIではなくChatGPT desktopまたはWebのScheduledを使う。

公式手順: https://learn.chatgpt.com/docs/automations

日次タスクはリポジトリを更新した後、次の指示で動かす。X投稿の定常読解はプロジェクト方針に従い
Terraを使い、判断結果とdry-run証跡だけを残す。本番反映・workflow変更・PR mergeは行わない。

```text
あなたは盆踊りプロジェクトの「X候補 日次レビュー」を担当するおとです。
/Users/ryotauchida/bon-odori-collector/AGENTS.md と
docs/x-candidate-backlog-operations.md を最初に読み、隔離worktreeで作業してください。

1. origin/mainを取得し、data/x_candidate_backlog.json と
   data/review_inbox_adapted/x_gap.json の selection.mode=cohort / 最大5件を確認する。
2. 5件それぞれについて、投稿本文、data/event_poster_ocr_queue.json の同一URL・tweet_id、
   matched_occurrence、data/public/events_public.json、Master RDBの候補を横断確認する。
3. ポスター画像があればOCRする。ローカル根拠だけで同一性・日時・会場を決められない場合だけWeb確認する。
4. 「既存更新」「新規公式」「ポスター＋独立補強」「個人1件保留」「同名・近隣衝突」へ分類し、
   重複候補、使った根拠URL、未確定事項を記録する。推測で日付・会場・正式名を補わない。
5. 変更候補は既存のE0→J0→E2またはapply_change_requests経路のdry-runまでに止める。
   Master RDB、本番S3、公開JSON、workflow、PR状態は変更しない。
6. data/x_candidate_daily_reviews/YYYY-MM-DD.json と同名.mdへ、5件全件の結果、
   重複率、誤分類率、保留理由、dry-run結果、次アクションを書く。
7. 開催7日以内未解決、高信頼24時間超、持ち越し欠落があれば先頭に警告する。

結果が0件でも「0件」と理由を残し、候補の状態を勝手に登録済み・却下へ変えないでください。
```

最初の数回は結果を人が確認し、対象地域外率、重複率、誤分類率を測る。5件canaryを増やす判断は、
数日分の証跡が揃ってから行う。
