---
id: L2-review-inbox-adapter
layer: L2
title: レビュー受信箱アダプタの契約
owns: []
depends_on:
  - L1-review
  - L2-master-schema
invariants:
  - INV-ADP-001
  - INV-ADP-002
  - INV-ADP-003
  - INV-ADP-004
verified_by:
  - tests/test_review_inbox_source_adapter.py
  - tests/test_review_inbox_parity.py
updated_for: 83bf7d0
---

# レビュー受信箱アダプタの契約

> 上位は[人のレビュー運用](../L1/03-review.md)。ここは**アダプタが守るべきデータの形と禁止事項**だけを扱う。
> 実装は `review_inbox_adapters/source_adapter.py` にあり、ファイルの持ち主は L1-review である
> （`owns` は排他なので、この契約はファイルを持たない。逆引きから来た人はあちらの本文で案内される）。

## なぜこの契約が要るか

レビューへ積む入口は種類ごとに別のアダプタになっていて、`83bf7d0` 時点で
`review_inbox_adapters/` の22ファイルが `source_id` を持つ（アダプタ本体と、それを束ねる集約や書き出しを含む）。
X由来の穴、公式ソース、会場欠落、過去実績、YouTube、稀少シグナル……と増え続ける構造で、
[03-review](../L1/03-review.md) の「未解決」にも**共通の契約を切り出したい**と書かれたままになっていた。

数が増えること自体は問題ではない。問題は、**アダプタが1本ずつ勝手な形の行を積めてしまうと、
受信箱が「何でも入る箱」になる**ことである。とくに危ないのは、アダプタが決定そのものを書けてしまう場合で、
そうなると「人が裁定した」という状態を機械が自分で作れることになり、レビュー工程が意味を失う。

だからこの契約は、**アダプタにできることを意図的に狭くしてある。**
アダプタは「1つのJSONを読み、未決の項目の並びへ変換する」ことしかできない。
SQLiteへ書かない、決定を仮置きしない、ドメインの変更を適用しない。
実装の docstring がそう宣言していて、以下の不変条件がそれを機械的に守っている。

## 項目の形

アダプタが1件ずつ返す写像（マッピング）は、`normalize_adapter_item()` を通って次の形になる。

| 欄 | 誰が入れるか | 意味 |
|---|---|---|
| `kind` | **アダプタが必ず入れる** | 項目の種類。`current_year_confirmation`・`official_source`・`venue_review`・`rare_signal`・`historical_reference`・`youtube_evidence` など |
| `title` | **アダプタが必ず入れる** | 人が一覧で読む見出し |
| `source_key` | **アダプタが必ず入れる** | 元データの中でその項目を一意に指す鍵 |
| `source_id` | 契約側が入れる | どのアダプタが作ったか。アダプタが違う値を入れていたら失敗させる |
| `domain` | 省略可 | 省略時は `その他` |
| `time_scope` | 省略可 | 省略時は `kind` から推測。`future` / `historical` / `reference` のいずれかでなければ失敗 |
| `recommended_action` | 省略可 | 省略時は空文字 |
| `payload` | 省略可 | 種類ごとの中身。省略時は空の写像 |
| `inbox_id` | 契約側が入れる | `kind` + `source_id` + `source_key` から作る安定ID |

「安定ID」は、**同じ入力からは何度作っても同じIDになる**という意味である。
日次で作り直すたびに新しいIDが振られると、同じ項目が毎日新規として積まれ、
人が昨日裁定したものがまた出てくる。受信箱の重複はレビューの詰まりに直結するので、
IDの安定性はこの契約でいちばん基本的な性質になっている。

**書いてはいけない欄**（ライフサイクル欄）は次のとおりで、アダプタが1つでも含めると例外で止まる。

```
status  decision  decided_by  decided_at  closed_at  decision_route
source_payload_hash  last_seen_at  created_at  updated_at
```

## スナップショットの形

`load_adapted_source()` が返す（そして `write_adapted_snapshot()` が書く）まとまりは次のとおり。

| 欄 | 意味 |
|---|---|
| `source_id` | どのアダプタか |
| `input_path` | 読んだ入力ファイル |
| `input_sha256` | **入力の生バイト**のSHA-256 |
| `input_size_bytes` | 入力の大きさ |
| `item_count` / `items` | 変換した項目 |

`input_sha256` は、あとで受信箱の投影と突き合わせる（`review_inbox_adapters/parity.py`）ときに、
**「入力が違ったのか、アダプタの変換が違ったのか」を区別する**ためにある。
これが無いと、食い違いを見つけても原因がどちらにあるか永久に分からない。

書き込みは一時ファイルへ書いてから `os.replace()` で置き換える。
途中で落ちても、読み手が半分だけのJSONを読むことがないようにするためである。

## 不変条件

### INV-ADP-001 アダプタは決定のライフサイクル欄を書けない

- **内容**: `normalize_adapter_item()` は、上に挙げたライフサイクル欄がアダプタの出力に含まれていたら
  `ValueError` で止める。アダプタが作れるのは**未決の項目だけ**である。
- **なぜ**: 「レビュー済み」という印は、人が見たことの証明でなければ意味がない
  （[INV-RVW-004](../L1/03-review.md) と同じ考え方）。アダプタが `status` や `decision` を書けると、
  積む側が裁定済みの状態を自分で作れることになり、レビュー工程そのものが素通りされる。
  アダプタは種類ごとに増えていくので、**1本でも例外を許すと契約全体が崩れる。**
- **破れたときの症状**: 誰も見ていない項目が「裁定済み」として受信箱に現れ、そのまま下流へ流れる。
- **守っているコード**: `review_inbox_adapters/source_adapter.py` の `normalize_adapter_item()` と `LIFECYCLE_FIELDS`
- **守っているテスト**: `tests/test_review_inbox_source_adapter.py::ReviewInboxSourceAdapterTest::test_adapter_cannot_write_decision_lifecycle`

### INV-ADP-002 1回の変換で同じ安定IDを2つ出さない

- **内容**: `adapt_source_payload()` は、変換した項目の `inbox_id` に重複があれば `ValueError` で止める。
  必須欄（`kind` / `title` / `source_key`）が欠けている場合、`time_scope` が既知の3種でない場合も同様に止める。
- **なぜ**: 安定IDは `kind` + `source_id` + `source_key` から作るので、重複が出るということは
  **元データの中で項目を一意に指せていない**ということである。そのまま積むと、
  片方の裁定がもう片方を上書きする、あるいは同じ項目が二重に適用される。
  ここで止めておけば、原因は必ず「アダプタの `source_key` の選び方」に絞られる。
- **破れたときの症状**: 1回の裁定が別の項目にも当たる。受信箱の件数が元データの件数と合わない。
- **守っているコード**: `review_inbox_adapters/source_adapter.py` の `adapt_source_payload()`
- **守っているテスト**: `tests/test_review_inbox_source_adapter.py::ReviewInboxSourceAdapterTest::test_duplicate_stable_ids_are_rejected`、
  `tests/test_review_inbox_source_adapter.py::ReviewInboxSourceAdapterTest::test_adapter_rejects_unknown_time_scope`

### INV-ADP-003 入力の生バイトのハッシュを必ず残す

- **内容**: `load_adapted_source()` は読み込んだ**バイト列そのもの**のSHA-256を記録する。
  突き合わせ（`parity.py`）は、このハッシュが欠けているスナップショットを受け付けない。
- **なぜ**: 受信箱の投影と元データが食い違ったとき、原因は「入力が変わった」か「変換が変わった」の
  どちらかしかない。**入力の指紋が残っていれば機械的に切り分けられる**が、無ければ人が推測するしかない。
  JSONを読み直してから再シリアライズしたものではなく生バイトを使うのは、
  整形の違いで指紋が変わってしまうと、同じ入力を同じと言えなくなるためである。
- **破れたときの症状**: 突き合わせで差が出たときに、入力の違いかアダプタの違いか判別できない。
- **守っているコード**: `review_inbox_adapters/source_adapter.py` の `input_sha256()` と `load_adapted_source()`、
  `review_inbox_adapters/parity.py`
- **守っているテスト**: `tests/test_review_inbox_source_adapter.py::ReviewInboxSourceAdapterTest::test_loader_records_exact_input_file_hash`、
  `tests/test_review_inbox_parity.py::ReviewInboxParityTest::test_missing_input_hash_is_rejected`

### INV-ADP-004 アダプタは受け取った入力を書き換えない

- **内容**: `adapt_source_payload()` はアダプタへ渡す前に入力を複製し、
  返ってきた項目も複製したうえで正規化する。アダプタの実装が入力を破壊しても、
  呼び出し側が持っている元データは変わらない。
- **なぜ**: 同じ入力を複数のアダプタが読むことがあり、順番によって結果が変わる状態は再現性を壊す。
  アダプタは「純粋な変換」であるという前提が、突き合わせ（同じ入力から同じ出力が出るはず）の土台になっている。
- **破れたときの症状**: 実行順序によって受信箱の中身が変わる。同じ入力で再実行しても同じ結果にならない。
- **守っているコード**: `review_inbox_adapters/source_adapter.py` の `adapt_source_payload()`（`copy.deepcopy`）
- **守っているテスト**: `tests/test_review_inbox_source_adapter.py::ReviewInboxSourceAdapterTest::test_adapter_isolated_from_input_and_emits_stable_future_item`

## 突き合わせ（parity）で見るもの

`parity.py` は、アダプタが作ったスナップショットと、実際の受信箱の投影（`data/review_inbox.json`）を比べる。
比べる欄は `kind` / `time_scope` / `event_name` / `venue` / `event_year` / `source_url` / `recommended_action` で、
**決定のライフサイクル欄は意図的に無視する。**

無視するのは、比べたいのが「同じ入力から同じ項目が作られているか」だからである。
人が裁定した結果まで比較対象に入れると、裁定が進むたびに差分として現れ、
本当に見たい変換の食い違いが埋もれてしまう。

## 新しいアダプタを足すとき

1. `source_id` を決める（この値は項目の安定IDに入るので、あとから変えると全項目のIDが変わる）。
2. `adapt(payload)` を書く。**外部への書き込みを一切しない。**
3. `kind` / `title` / `source_key` を必ず入れる。`source_key` は元データの中で一意になるものを選ぶ。
4. `load_adapted_source()` と `write_adapted_snapshot()` を通して出力する。自前でJSONを書かない。
5. どのレーンから流すかを [03-review](../L1/03-review.md) の「日次で積んでいるのは、いくつの入口か」に足す。

**この5番目を忘れると、動いているのに仕様のどこにも書かれていないアダプタが増える。**
実際、日次で走っているのに未記述のスクリプトが23本たまっていたのは、この積み残しが原因だった。

---

こと（Claude Code）
