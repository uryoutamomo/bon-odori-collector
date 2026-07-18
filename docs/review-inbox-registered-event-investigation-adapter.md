# Registered Event Investigation Review Inbox Adapter

作成日: 2026-07-18 JST

署名: おと（Codex）

`review_inbox_registered_event_investigation_adapter.py` は、
`data/registered_event_investigation_queue.json` をreview inbox adapter snapshotへ変換する。

- `task_id`をstable `source_key`に使う。
- `needs_name_review` / `needs_occurrence_split` は `occurrence_creation`、会場欠落は
  `venue_review`、日付欠落は `current_year_confirmation` にする。
- `primary_unconfirmed` は元のevent yearにかかわらず、当年・次年の判断仕事として
  `time_scope=future`にする。
- legacy task全体をpayloadへ保持し、lifecycle fieldは設定しない。
- 元JSONの生bytes SHA-256とbyte数をsnapshotへ記録する。

通常snapshotは次で生成する。

```bash
python3 review_inbox_registered_event_investigation_adapter.py \
  --output /tmp/registered-investigation-adapted.json
```

白金deferredだけを最初のcanaryにする場合は `--canary` を付ける。full入力bytesのhashを維持したまま、
固定source key `evtinv_d7b5f534c8b3ddd8` の1件だけをsnapshotへ含める。

```bash
python3 review_inbox_registered_event_investigation_adapter.py \
  --canary \
  --output /tmp/shirokane-canary.json
```

出力は `write_mode=snapshot_only_default_off` であり、Master RDB、legacy JSON、workflow、公開JSON、
domain stagingへ書かない。B1-1のcanary DoDはstable ID、0差分parity、input/adapter/payload hash系譜の
固定までである。decision往復、再観測lifecycle保持、accept fail-closedはB1-3の別GOで実データ検証する。
`occurrence_creation` のaccept→domain applyはB1-1/B1-3に含めず、`create_occurrence`等の有限change typeを
A拡張の別課題として設計する。
