# Review Inbox Parity Operations

作成日: 2026-07-17 JST
署名: おと（Codex）

`review_inbox_adapters/parity.py` は、legacy JSONをsource adapterで変換したsnapshotと、
`review_inbox.json` の同一 `source_id` 部分を比較するread-onlyの検証入口である。

比較するもの:

- item件数とstable `inbox_id` 集合
- kind、時間軸、event/year/source URL/recommended action
- source payload hash
- 元入力JSONのpath、SHA-256、byte数
- adapter snapshot自体のpathとSHA-256

decision、reviewer、statusなどのlifecycleは内容parityから除外する。人が判断した後でもsource内容の
一致を検証できるようにするためである。

```bash
python3 -m review_inbox_adapters.parity \
  --adapted-snapshot /tmp/official-source-adapted.json \
  --inbox data/review_inbox.json \
  --out-json /tmp/review-inbox-parity.json \
  --out-md /tmp/review-inbox-parity.md \
  --require-parity
```

`--adapted-snapshot` は複数指定できる。`--require-parity` を付けた場合、missing / extra /
content mismatchのいずれかがあればexit 1になる。

この段階ではreport生成だけを追加し、workflow gateや実source dual-writeにはまだ接続しない。
