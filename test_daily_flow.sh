#!/usr/bin/env bash
#
# 盆踊り 1日フロー疎通テスト（収集 → 配信）を一発で回すスクリプト。
#
# 本番と同じ GitHub Actions（Secrets はサーバ側に設定済み）を workflow_dispatch で
# 叩くだけなので、手元にトークンを置く必要はない。gh CLI の認証だけ必要。
#
#   前提: `gh auth status` が通っていること（github.com / uryoutamomo）。
#
# 使い方:
#   ./test_daily_flow.sh            # 収集→配信を順に実行して完了まで見守る
#   ./test_daily_flow.sh mail-only  # 配信(send_mail.yml)だけ
#   ./test_daily_flow.sh collect-only # 収集(collect.yml)だけ
#
# ★配信を実際に届かせるには、Notion「📧 メール配信ドラフト」DB に
#   「ステータス=送信予約 / 配信日<=今日」のレコードが必要。
#   無ければ send_mail は「送信対象なし」で正常終了する（メールは飛ばない）。
#   テスト用ドラフトの投入は、こと（Claude Code）に「1日フローをテスト」と頼めば
#   自動で1件入れて配信まで通してくれる。
#
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-all}"

run_and_watch() {
  local wf="$1" label="$2"
  echo "▶ ${label}（${wf}）を起動..."
  gh workflow run "$wf"
  sleep 8
  local rid
  rid=$(gh run list --workflow="$wf" --limit 1 --json databaseId -q '.[0].databaseId')
  echo "  run=${rid}  https://github.com/uryoutamomo/bon-odori-collector/actions/runs/${rid}"
  gh run watch "$rid" --exit-status --interval 10 | tail -n 15
  echo "✓ ${label} 完了"
  echo
  printf '%s' "$rid"
}

case "$MODE" in
  collect-only)
    run_and_watch collect.yml "収集" >/dev/null
    ;;
  mail-only)
    rid=$(run_and_watch send_mail.yml "配信")
    echo "--- 送信ログ ---"
    gh run view "$rid" --log | grep -iE "\[mail\]" || true
    ;;
  all)
    run_and_watch collect.yml "収集" >/dev/null
    rid=$(run_and_watch send_mail.yml "配信")
    echo "--- 送信ログ ---"
    gh run view "$rid" --log | grep -iE "\[mail\]" || true
    ;;
  *)
    echo "不明なモード: $MODE （all / collect-only / mail-only）" >&2
    exit 1
    ;;
esac

echo
echo "完了。配信結果はメール受信トレイ / Notion「📧 メール配信ドラフト」DB のステータスで確認。"
