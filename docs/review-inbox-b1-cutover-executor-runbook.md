# B1 review console reader cutover executor runbook

Updated: 2026-07-18 JST

署名: おと（Codex）

## Scope

`run_review_console_cutover.py`はローカルreview consoleのB1入力だけを`canary`または`inbox`へ
切り替える。Master DB、review inbox lifecycle、decision/stage、domain table、公開JSON、workflowを
変更しない。writer側の`REVIEW_INBOX_READER_MODE=legacy`も維持する。

このPRはexecutor実装とテストだけで、本番readerをactivateしない。実行はPR merge後、ことの
独立レビューと内田さんのB1-cutover-b実行GOを受けた別工程で行う。

## Prepared input lineage

repo内の古い`data/review_inbox.json`を暗黙使用しない。実行ごとに次を新しい作業pathへ準備する。

1. S3 statusでRstart checksum / snapshot IDを固定する。
2. latest Master DBとmanifestを別pathへfetchする。
3. fetch DBから`review_inbox.py`で`data/review_inbox.json`をexportする。
4. 同じRstartに対応する7 legacy inputと7 adapter snapshotを配置する。
5. 未使用のevidence pathを指定する。

executorはactivate前に次をコードで再検証する。

- fetch DB bytes SHA = manifest checksum = operator固定Rstart
- manifest snapshot ID = operator固定snapshot ID
- integrity ok / FK 0 / decision系non-NULL 0
- DBのpending 170件 = source別`52/79/8/12/0/3/16`
- `review_inbox.json`全row = fetch DBのpending row
- 7 legacy input SHA = 対応adapter snapshotの`input_sha256`
- 7 adapter snapshotとfetch DBのparityがmissing/extra/mismatch `0/0/0`
- reader previewがcanary/full exact replacement、non-B1不変、新規重複0
- public projection SHA = operator固定SHA

いずれか1つでも不一致ならconsole serverを開始しない。

## Explicit gates

共通の4環境変数をすべて明示する。

```sh
export REVIEW_INBOX_DUAL_WRITE_MODE=bulk
export REVIEW_INBOX_CAS_PUBLISH_ENABLED=true
export REVIEW_INBOX_READER_MODE=legacy
export REVIEW_INBOX_LEGACY_WRITER_ENABLED=true
```

canaryではさらに次を明示する。

```sh
export REVIEW_CONSOLE_READER_MODE=canary
```

実行時は`--execute`、mode別exact confirm、Rstart、snapshot ID、公開digest、固定JST日付、7つの
`--adapted-snapshot`、未使用`--evidence-out`を必須にする。`17:20-18:00 JST`は停止する。

canary confirm:

```text
ACTIVATE B1 REVIEW CONSOLE CANARY READER
```

full inbox confirm:

```text
ACTIVATE B1 REVIEW CONSOLE INBOX READER
```

## Staged execution

1. canaryを起動し、`missing_occurrence_venue` legacy 3件だけが`missing_venue` v2 3件へ置換され、
   近接sourceと非B1 sourceが不変であることをことが独立確認する。
2. canaryを終了する。rollbackは`REVIEW_CONSOLE_READER_MODE=legacy`で再起動するだけである。
3. こと合格後かつ内田さんGO範囲内でのみ、最新Rstartを取り直して`inbox`を同じ手順で起動する。
4. fullで7 source 170件、二重表示0、非B1不変、decision/stage/domain/public write 0を独立確認する。

canary合格をfullのGO代用にしない。本PRの作成・レビュー自体も本番activateのGO代用にしない。
