---
id: L1-platform
layer: L1
title: 実行基盤・安全弁
owns:
  - operation_safety/**
  - guard_git_large_files.py
  - infra/**
depends_on: []
invariants:
  - INV-PLT-001
  - INV-PLT-002
verified_by:
  - tests/test_guard_git_large_files.py
  - tests/test_manual_infra_workflows_policy.py
updated_for: 6537e7f
---

# 実行基盤・安全弁

> 上位は[全体地図](../README.md)。基盤はデータを判断しないが、誤った経路での実行を止める。

## この工程は何のためにあるか

GitHub Actions、インフラ定義、手動実行の確認句、リポジトリの容量ガードを通じて、日次処理が再現可能な経路で動き、危険な変更を静かに通さないようにする。

## 入力と出力

入力はworkflowイベント、環境変数、手動コマンドの `--apply` と確認句、ステージ済みファイル。出力は実行結果、失敗理由、またはブロックである。

## 不変条件

### INV-PLT-001 手動の実変更には操作ごとの確認句が必要である

- **内容**: `require_confirmation()` は `--apply` が指定されたときだけ、操作に対応する完全一致の確認句を要求する。
- **なぜ**: dry-run と実反映を同じ見た目で実行すると、コピーペーストや引数漏れで本番データを変える危険があるから。
- **破れたときの症状**: 調査のつもりのコマンドが実データや外部サービスを書き換える。
- **守っているコード**: `operation_safety/manual_apply_guards.py` の `require_confirmation()`
- **守っているテスト**: **なし（要追加）**

### INV-PLT-002 GitHubの上限に近い大容量ファイルをコミットしない

- **内容**: `guard_git_large_files.py` は追跡対象を検査し、95MiB以上をブロック、50MiB以上を警告する。
- **なぜ**: GitHubの上限を越えるコミットはpush時に失敗し、日次workflowの成果物更新全体を止めるから。
- **破れたときの症状**: 更新が最後のpushで失敗し、次回以降の差分も積み残される。
- **守っているコード**: `guard_git_large_files.py` の `classify_files()` と `run()`
- **守っているテスト**: `tests/test_guard_git_large_files.py::test_classifies_warn_and_block_files`

## 主要な流れ

1. workflowがイベントに応じて検証・収集・成果物更新を実行する。
2. 手動実反映は確認句を通す。
3. コミット前に容量ガードが追跡ファイルを検査する。

## 依存と影響

すべてのL1は実行基盤に依存する。基盤が止まると収集や公開は古い状態のままになり、基盤が緩むと安全弁を迂回した変更が残る。

## 壊れたときの症状

Actionsが失敗したら該当workflowのログ、手動処理が拒否されたら確認句、push失敗なら大容量ガードの出力をまず確認する。

## 未解決・注意点

workflowの環境変数・秘密情報の契約は散在している。実行条件と所有者をL2として整理する余地がある。

---

おと（Codex）
