# Review Inbox Decision Staging

作成日: 2026-07-17 JST
署名: おと（Codex）

レビューコンソールの `review_inbox` 判断は、ステージ適用時に次の有限routeへ分ける。

- `change_request`: `confirm_current_year_date` / `add_historical_reference` / `update_venue` の候補packet
- `domain_stage`: song / term / YouTube evidenceの既存domain staging候補
- `research_followup`: 根拠URL補完や追加調査
- `no_apply`: reject / hold

同時に `review_inbox_decision_updates.json` を作り、`inbox_id`、decision、reviewer、時刻、routeを
将来のCAS single writerへ渡せるようにする。

このステージ処理はMaster RDBを更新せず、change requestやdomain applyも実行しない。
acceptedでも安全な有限routeへ変換できない値は失敗させ、自由記述actionをapplyへ流さない。

既存どおり次で生成する。

```bash
python3 apply_review_console_decisions.py --write
```

出力先は `data/review_console/staged/`。正本decisionへの反映は、schema v2 migrationと
CAS single writerの明示ゲートが整った後の別工程とする。
