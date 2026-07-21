# Manual tools

workflow・現役コードから呼ばれないが、調査やローカルレビューで再利用可能な手動ツールを置く。
GitHub Actionsへは組み込まず、repo rootからmoduleとして実行する。

```bash
python3 -m scripts.manual.<module> --help
```

各ツールの既定出力先は従来どおりrepo root基準の `data/` である。
Notionや外部APIへ書く可能性があるツールは、実行前に引数とdry-run有無を個別確認する。
