# Root Python inventory

基準日: 2026-07-21 JST

この台帳は参照シグナルの棚卸しであり、`review_candidate` を自動削除・自動移動しない。
移動前に用途・生成物・git履歴を個別確認する。

## Summary

| metric | count |
| --- | ---: |
| root `*.py` | 211 |
| `legacy/**/*.py` | 153 |
| `documented_manual` | 10 |
| `retained_legacy_dependency` | 6 |
| `source_dependency` | 87 |
| `test_supported_manual` | 66 |
| `workflow_entrypoint` | 42 |

## Review candidates

workflow・現役Python・tests・docsから参照されない候補。名前だけで退役判断しない。

- なし

## Regenerate

```bash
python3 scripts/build_root_python_inventory.py --as-of 2026-07-21
```

署名: おと（Codex）
