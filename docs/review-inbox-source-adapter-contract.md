# Review Inbox Source Adapter Contract

作成日: 2026-07-17 JST
署名: おと（Codex）

`review_inbox_adapters/source_adapter.py` は、既存のreview JSONを統合受信箱へ移す際の共通境界である。
各adapterはdecoded JSONを受け取り、安定した `source_key` を持つpending itemを返す純粋変換として実装する。

## Adapterが行うこと

- `source_id` を固定する。
- 各itemへ `kind`、`title`、`source_key` を必ず付ける。
- source固有の根拠情報は `payload` に保持する。
- `time_scope` を明示するか、kindから `future` / `historical` / `reference` へ派生させる。

## Adapterが行わないこと

- SQLite、公開JSON、domain stagingへの書き込み。
- `decision`、`status`、`decided_at` などlifecycleの設定。
- console decisionからの直接apply。

共通runnerは入力payloadをdeep copyしてadapterへ渡す。同じ `kind + source_id + source_key` は同じ
`inbox_id` になり、1回の変換で重複IDが出た場合は失敗する。

## Parity用の入力系譜

`load_adapted_source()` はJSONファイルの生bytesからSHA-256とbyte数を記録する。後続parity reportは
legacyとinboxのitem差分だけでなく、この入力hashも並べる。曲・用語系JSONが別run由来の場合に、
入力差とadapter差を混同しないためである。

この段階では実source adapter、RDB upsert、workflow dual-writeは追加しない。それらはsource単位の
後続PRで、legacy writerを維持したまま導入する。
