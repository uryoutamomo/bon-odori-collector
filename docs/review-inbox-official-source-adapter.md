# Official Source Review Inbox Adapter

作成日: 2026-07-17 JST
署名: おと（Codex）

`review_inbox_official_source_adapter.py` は、
`data/official_source_review_candidates.json` を統合受信箱のadapter snapshotへ変換する。

- legacy rowの `id` をstable `source_key`に使う。
- 2026年または年不明は `time_scope=future`、2025年以前は `historical` として分ける。
- legacyの既存decisionはsource payload内に残すが、inbox lifecycleへ自動昇格しない。
- 元JSONの生bytes SHA-256とbyte数をsnapshotへ記録する。

```bash
python3 review_inbox_official_source_adapter.py \
  --output /tmp/official-source-adapted.json
```

この段階ではsnapshot生成だけで、legacy writer停止、Master RDB upsert、workflow dual-write、
正本migrationは行わない。次工程でparity reportとCAS writerのゲートを通してから接続する。
