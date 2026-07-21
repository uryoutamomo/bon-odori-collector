# Legacy tools

ここには、通常運用から外れたone-off、移行補助、rollback用ツールを削除せず保管する。
GitHub Actionsからは呼ばず、必要時だけrepo rootから手動実行する。

Python packageになっているディレクトリは次の形で実行する。

```bash
python3 -m legacy.notion_writes.<module> --help
```

| directory | retained purpose |
| --- | --- |
| `apply/` | 完了済みイベント個別apply |
| `build-reports/` | 完了済み移行・レビュー材料生成 |
| `notion-notes/` | Notionへの単発メモ追記 |
| `notion_writes/` | manual-onlyの旧Notion書き込み・修復 |
| `retrospective_tools/` | 完了済みretrospective移行補助 |
| `migration_reports/` | Ph0–Ph2等の読み取り専用移行レポート |
| `youtube_2025/` | 完了済みYouTube 2025移行補助 |
| `site_sync/` | 日付固定の旧site同期 |
| `experiments/` | 完了済み使い捨て実験 |

削除・再利用・通常経路への復帰は、対応runbookと最新の
`docs/root-python-inventory-20260721.md` を確認してから行う。
